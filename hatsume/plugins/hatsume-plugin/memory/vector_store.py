"""Milvus Lite storage for long-term memory vectors."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
from milvus_lite import server_manager_instance
from numpy.typing import NDArray
from pymilvus import MilvusClient


COLLECTION_NAME = "memory_embeddings"
PRIMARY_FIELD = "memory_id"
VECTOR_FIELD = "embedding"


@dataclass(frozen=True)
class VectorSearchResult:
    memory_id: int
    score: float


@dataclass(frozen=True)
class MigrationReport:
    total: int
    copied: int
    generated: int
    already_present: int
    invalid: int
    failed: int
    verified: int


class MilvusVectorStore:
    """Small ID-based wrapper around a local Milvus Lite database."""

    def __init__(self, db_path: str | Path, *, dimension: int = 1024):
        if dimension <= 0:
            raise ValueError("vector dimension must be positive")

        self.dimension = dimension
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = MilvusClient(uri=str(self.db_path))
        self._closed = False

        try:
            if not self._client.has_collection(COLLECTION_NAME):
                self._client.create_collection(
                    collection_name=COLLECTION_NAME,
                    dimension=dimension,
                    primary_field_name=PRIMARY_FIELD,
                    id_type="int",
                    vector_field_name=VECTOR_FIELD,
                    metric_type="COSINE",
                    auto_id=False,
                    consistency_level="Strong",
                )
            else:
                description = self._client.describe_collection(COLLECTION_NAME)
                existing_dimension = _collection_vector_dimension(description)
                if existing_dimension is not None and existing_dimension != dimension:
                    raise ValueError(
                        "Milvus vector dimension mismatch: "
                        f"expected {dimension}, found {existing_dimension}"
                    )
            self._client.load_collection(COLLECTION_NAME)
        except Exception:
            self.close()
            raise

    def upsert(
        self,
        items: Iterable[tuple[int, Sequence[float]]],
    ) -> None:
        rows = []
        for memory_id, vector in items:
            values = self._validate_vector(vector)
            rows.append({PRIMARY_FIELD: int(memory_id), VECTOR_FIELD: values})
        if rows:
            self._client.upsert(collection_name=COLLECTION_NAME, data=rows)

    def search(
        self,
        vector: Sequence[float],
        *,
        limit: int,
    ) -> list[VectorSearchResult]:
        if limit <= 0:
            return []
        values = self._validate_vector(vector)
        raw_results = self._client.search(
            collection_name=COLLECTION_NAME,
            data=[values],
            anns_field=VECTOR_FIELD,
            limit=limit,
            output_fields=[PRIMARY_FIELD],
            search_params={"metric_type": "COSINE"},
        )
        if not raw_results:
            return []

        results = []
        for hit in raw_results[0]:
            entity = hit.get("entity") or {}
            memory_id = entity.get(PRIMARY_FIELD, hit.get("id"))
            if memory_id is None:
                continue
            results.append(
                VectorSearchResult(
                    memory_id=int(memory_id),
                    score=float(hit.get("distance", 0.0)),
                )
            )
        return results

    def existing_ids(self, memory_ids: Sequence[int]) -> set[int]:
        ids = [int(memory_id) for memory_id in memory_ids]
        if not ids:
            return set()
        rows = self._client.query(
            collection_name=COLLECTION_NAME,
            ids=ids,
            output_fields=[PRIMARY_FIELD],
        )
        return {int(row[PRIMARY_FIELD]) for row in rows}

    def delete(self, memory_ids: Sequence[int]) -> None:
        ids = [int(memory_id) for memory_id in memory_ids]
        if ids:
            self._client.delete(collection_name=COLLECTION_NAME, ids=ids)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._client.close()
        finally:
            server_manager_instance.release_server(str(self.db_path))

    def _validate_vector(self, vector: Sequence[float]) -> list[float]:
        values = [float(value) for value in vector]
        if len(values) != self.dimension:
            raise ValueError(
                f"vector dimension must be {self.dimension}, got {len(values)}"
            )
        return values


def _collection_vector_dimension(description: dict) -> int | None:
    for field in description.get("fields", []):
        if field.get("name") != VECTOR_FIELD:
            continue
        params = field.get("params") or {}
        dimension = params.get("dim")
        return int(dimension) if dimension is not None else None
    return None


def migrate_sqlite_vectors(
    sqlite_path: str | Path,
    vector_store: MilvusVectorStore,
    embed_documents: Callable[[list[str]], list[list[float]]],
    *,
    batch_size: int = 100,
) -> MigrationReport:
    """Copy legacy SQLite vectors into Milvus without opening SQLite writable."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    path = Path(sqlite_path).resolve()
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    copied = 0
    generated = 0
    already_present = 0
    invalid = 0
    failed = 0
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(memories)")
        }
        if not {"id", "content"}.issubset(columns):
            raise ValueError("SQLite memories table must contain id and content")
        embedding_expression = "embedding" if "embedding" in columns else "NULL"
        total = int(
            connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        )

        last_id = -1
        while True:
            rows = connection.execute(
                "SELECT id, content, "
                + embedding_expression
                + " AS embedding FROM memories "
                "WHERE id > ? ORDER BY id LIMIT ?",
                (last_id, batch_size),
            ).fetchall()
            if not rows:
                break
            last_id = int(rows[-1][0])
            ids = [int(row[0]) for row in rows]
            existing = vector_store.existing_ids(ids)
            already_present += len(existing)

            pending: list[tuple[int, list[float], str]] = []
            generate_rows: list[tuple[int, str]] = []
            for raw_id, raw_content, raw_blob in rows:
                memory_id = int(raw_id)
                if memory_id in existing:
                    continue
                vector = _decode_legacy_vector(
                    raw_blob,
                    dimension=vector_store.dimension,
                )
                if vector is not None:
                    pending.append((memory_id, vector, "copied"))
                    continue
                if raw_blob is not None:
                    invalid += 1
                generate_rows.append((memory_id, str(raw_content)[:300]))

            if generate_rows:
                try:
                    generated_vectors = embed_documents(
                        [content for _, content in generate_rows]
                    )
                except Exception:
                    failed += len(generate_rows)
                    generated_vectors = None
                if generated_vectors is not None:
                    for index, (memory_id, _content) in enumerate(generate_rows):
                        if index >= len(generated_vectors):
                            failed += 1
                            continue
                        vector = _coerce_vector(
                            generated_vectors[index],
                            dimension=vector_store.dimension,
                        )
                        if vector is None:
                            failed += 1
                            continue
                        pending.append((memory_id, vector, "generated"))

            if pending:
                try:
                    vector_store.upsert(
                        (memory_id, vector)
                        for memory_id, vector, _source in pending
                    )
                except Exception:
                    failed += len(pending)
                else:
                    copied += sum(source == "copied" for _, _, source in pending)
                    generated += sum(
                        source == "generated" for _, _, source in pending
                    )

        verified = _verified_sqlite_ids(
            connection,
            vector_store,
            batch_size=batch_size,
        )
    finally:
        connection.close()

    return MigrationReport(
        total=total,
        copied=copied,
        generated=generated,
        already_present=already_present,
        invalid=invalid,
        failed=failed,
        verified=verified,
    )


def _decode_legacy_vector(blob: bytes | None, *, dimension: int) -> list[float] | None:
    if blob is None or len(blob) % np.dtype(np.float32).itemsize != 0:
        return None
    vector = np.frombuffer(blob, dtype=np.float32)
    return _coerce_vector(vector, dimension=dimension)


def _coerce_vector(
    vector: Sequence[float] | NDArray[np.float32],
    *,
    dimension: int,
) -> list[float] | None:
    values = np.asarray(vector, dtype=np.float32)
    if values.ndim != 1 or len(values) != dimension or not np.all(np.isfinite(values)):
        return None
    return values.astype(float).tolist()


def _verified_sqlite_ids(
    connection: sqlite3.Connection,
    vector_store: MilvusVectorStore,
    *,
    batch_size: int,
) -> int:
    verified = 0
    last_id = -1
    while True:
        rows = connection.execute(
            "SELECT id FROM memories WHERE id > ? ORDER BY id LIMIT ?",
            (last_id, batch_size),
        ).fetchall()
        if not rows:
            return verified
        ids = [int(row[0]) for row in rows]
        verified += len(vector_store.existing_ids(ids))
        last_id = ids[-1]
