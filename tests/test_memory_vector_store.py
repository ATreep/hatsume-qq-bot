"""Milvus Lite vector storage and migration tests."""

from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
GROUP_ID = 101
OTHER_GROUP_ID = 202
VECTOR_STORE_PATH = (
    ROOT / "hatsume/plugins/hatsume-plugin/memory/vector_store.py"
)


def _load_vector_store_module():
    module_name = "hatsume_memory_vector_store"
    spec = importlib.util.spec_from_file_location(
        module_name,
        VECTOR_STORE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_milvus_vector_store_upserts_searches_and_deletes(tmp_path: Path):
    vector_store = _load_vector_store_module()
    store = vector_store.MilvusVectorStore(tmp_path / "vectors.db", dimension=3)

    try:
        store.upsert(
            [
                (7, GROUP_ID, [1.0, 0.0, 0.0]),
                (8, OTHER_GROUP_ID, [0.0, 1.0, 0.0]),
            ]
        )

        assert store.existing_ids([7, 8, 9], group_id=GROUP_ID) == {7}
        assert store.existing_ids([7, 8, 9], group_id=OTHER_GROUP_ID) == {8}
        results = store.search(
            [1.0, 0.0, 0.0], group_id=GROUP_ID, limit=2
        )
        assert results[0].memory_id == 7
        assert results[0].score == pytest.approx(1.0)

        store.delete([7, 8], group_id=GROUP_ID)
        assert store.existing_ids([7, 8], group_id=GROUP_ID) == set()
        assert store.existing_ids([7, 8], group_id=OTHER_GROUP_ID) == {8}
    finally:
        store.close()


def test_milvus_vector_store_rejects_wrong_vector_dimension(tmp_path: Path):
    vector_store = _load_vector_store_module()
    store = vector_store.MilvusVectorStore(tmp_path / "vectors.db", dimension=3)

    try:
        with pytest.raises(ValueError, match="dimension"):
            store.upsert([(7, GROUP_ID, [1.0, 0.0])])

        with pytest.raises(ValueError, match="dimension"):
            store.search([1.0, 0.0], group_id=GROUP_ID, limit=1)
    finally:
        store.close()


def test_milvus_vector_store_loads_existing_collection_on_reopen(tmp_path: Path):
    vector_store = _load_vector_store_module()
    db_path = tmp_path / "vectors.db"
    store = vector_store.MilvusVectorStore(db_path, dimension=3)
    store.upsert([(7, GROUP_ID, [1.0, 0.0, 0.0])])
    store._client.release_collection(vector_store.COLLECTION_NAME)
    store.close()

    reopened = vector_store.MilvusVectorStore(db_path, dimension=3)
    try:
        assert reopened.existing_ids([7], group_id=GROUP_ID) == {7}
    finally:
        reopened.close()


def test_milvus_vector_store_close_releases_data_directory_lock(tmp_path: Path):
    vector_store = _load_vector_store_module()
    db_path = tmp_path / "vectors.db"
    store = vector_store.MilvusVectorStore(db_path, dimension=3)
    store.upsert([(7, GROUP_ID, [1.0, 0.0, 0.0])])
    store.close()

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pymilvus import MilvusClient; "
                f"client = MilvusClient(uri={str(db_path)!r}); "
                "client.close()"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert probe.returncode == 0, probe.stderr


def _create_legacy_memory_db(path: Path, rows: list[tuple[int, str, bytes | None]]):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            embedding BLOB
        )"""
    )
    conn.executemany(
        "INSERT INTO memories (id, content, embedding) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_migrate_sqlite_vectors_is_read_only_and_idempotent(tmp_path: Path):
    vector_store = _load_vector_store_module()
    sqlite_path = tmp_path / "memory.db"
    _create_legacy_memory_db(
        sqlite_path,
        [
            (1, "copied", np.asarray([1.0, 0.0, 0.0], dtype=np.float32).tobytes()),
            (2, "generated", None),
            (3, "invalid", np.asarray([9.0], dtype=np.float32).tobytes()),
        ],
    )
    before_hash = _sha256(sqlite_path)
    store = vector_store.MilvusVectorStore(tmp_path / "vectors.db", dimension=3)
    generated = {
        "generated": [0.0, 1.0, 0.0],
        "invalid": [0.0, 0.0, 1.0],
    }

    try:
        first = vector_store.migrate_sqlite_vectors(
            sqlite_path,
            store,
            lambda texts: [generated[text] for text in texts],
            batch_size=2,
            legacy_group_id=GROUP_ID,
        )
        second = vector_store.migrate_sqlite_vectors(
            sqlite_path,
            store,
            lambda _texts: pytest.fail("idempotent migration re-embedded rows"),
            batch_size=2,
            legacy_group_id=GROUP_ID,
        )

        assert first == vector_store.MigrationReport(
            total=3,
            copied=1,
            generated=2,
            already_present=0,
            invalid=1,
            failed=0,
            verified=3,
        )
        assert second == vector_store.MigrationReport(
            total=3,
            copied=0,
            generated=0,
            already_present=3,
            invalid=0,
            failed=0,
            verified=3,
        )
        assert store.existing_ids([1, 2, 3], group_id=GROUP_ID) == {1, 2, 3}
        assert _sha256(sqlite_path) == before_hash
    finally:
        store.close()


def test_migrate_sqlite_vectors_reports_wrong_generated_dimension(tmp_path: Path):
    vector_store = _load_vector_store_module()
    sqlite_path = tmp_path / "memory.db"
    _create_legacy_memory_db(sqlite_path, [(5, "missing", None)])
    before_hash = _sha256(sqlite_path)
    store = vector_store.MilvusVectorStore(tmp_path / "vectors.db", dimension=3)

    try:
        report = vector_store.migrate_sqlite_vectors(
            sqlite_path,
            store,
            lambda _texts: [[1.0, 0.0]],
            legacy_group_id=GROUP_ID,
        )

        assert report.failed == 1
        assert report.verified == 0
        assert store.existing_ids([5], group_id=GROUP_ID) == set()
        assert _sha256(sqlite_path) == before_hash
    finally:
        store.close()


def test_migrate_sqlite_vectors_reports_missing_generated_vector(tmp_path: Path):
    vector_store = _load_vector_store_module()
    sqlite_path = tmp_path / "memory.db"
    _create_legacy_memory_db(sqlite_path, [(9, "missing", None)])
    store = vector_store.MilvusVectorStore(tmp_path / "vectors.db", dimension=3)

    try:
        report = vector_store.migrate_sqlite_vectors(
            sqlite_path,
            store,
            lambda _texts: [],
            legacy_group_id=GROUP_ID,
        )

        assert report.failed == 1
        assert report.verified == 0
    finally:
        store.close()
