"""SQLite-backed memory metadata with bounded BM25 and Milvus retrieval."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from apscheduler.triggers.cron import CronTrigger
from nonebot import require
import nonebot_plugin_localstore as store
from rank_bm25 import BM25Okapi

from .. import config as _config
from ..config import MEMORY_EXPIRY_DAYS
from .tokenizer import tokenize_with_pos
from .vector_store import MilvusVectorStore, VectorSearchResult


scheduler = require("nonebot_plugin_apscheduler").scheduler
require("nonebot_plugin_localstore")

_EMBEDDING_MAX_CHARS = 300
_VECTOR_DIMENSION = 1024
_VECTOR_CANDIDATE_MULTIPLIER = 3
_MEMORY_DB_FILE = "memory-db/memory.db"
_MEMORY_VECTOR_DB_FILE = "memory-db/memory_vectors.db"

_db_conn: sqlite3.Connection | None = None
_vector_store_lock = threading.RLock()
embedding_model = None


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------


def init_db(conn_or_path: sqlite3.Connection | str | Path) -> sqlite3.Connection:
    """Open the memory database and retain the legacy vector column for rollback."""
    if isinstance(conn_or_path, sqlite3.Connection):
        conn = conn_or_path
    else:
        path = Path(conn_or_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT NOT NULL,
            time        INTEGER NOT NULL,
            people      TEXT NOT NULL DEFAULT '[]',
            tokens      TEXT NOT NULL DEFAULT '[]',
            embedding   BLOB,
            created_at  INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_time ON memories(time)")
    conn.commit()
    return conn


def insert_memory(
    conn: sqlite3.Connection,
    content: str,
    mem_time: int,
    people: list[dict[str, Any]],
    tokens: list[tuple[str, str]],
) -> int:
    """Insert metadata only; new vectors belong exclusively to Milvus."""
    people_json = json.dumps(people, ensure_ascii=False)
    tokens_json = json.dumps(tokens, ensure_ascii=False)
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO memories (content, time, people, tokens, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (content, int(mem_time), people_json, tokens_json, now),
    )
    conn.commit()
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return a memory ID")
    return int(cursor.lastrowid)


def delete_expired_memories(conn: sqlite3.Connection, retention_seconds: int) -> int:
    cutoff = int(time.time()) - retention_seconds
    cursor = conn.execute("DELETE FROM memories WHERE time < ?", (cutoff,))
    conn.commit()
    return int(cursor.rowcount)


def _expired_memory_ids(
    conn: sqlite3.Connection,
    retention_seconds: int,
) -> list[int]:
    cutoff = int(time.time()) - retention_seconds
    return [
        int(row[0])
        for row in conn.execute("SELECT id FROM memories WHERE time < ?", (cutoff,))
    ]


def _canonical_user_id_pattern(user_id: int) -> str:
    return f'%"user_id": {int(user_id)},%'


def query_by_user_ids(
    conn: sqlite3.Connection,
    user_ids: list[int],
    since_time: float | None,
    exclude_ids: list[int],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query user-linked rows using raw JSON text instead of SQLite JSON APIs."""
    normalized_ids = list(dict.fromkeys(int(user_id) for user_id in user_ids))
    if not normalized_ids:
        return []

    user_conditions = " OR ".join("people LIKE ?" for _ in normalized_ids)
    conditions = [f"({user_conditions})"]
    params: list[Any] = [
        _canonical_user_id_pattern(user_id) for user_id in normalized_ids
    ]
    if since_time is not None:
        conditions.append("time > ?")
        params.append(int(since_time))
    if exclude_ids:
        placeholders = ",".join("?" for _ in exclude_ids)
        conditions.append(f"id NOT IN ({placeholders})")
        params.extend(int(memory_id) for memory_id in exclude_ids)

    query = (
        "SELECT id, content, time FROM memories WHERE "
        + " AND ".join(conditions)
        + " ORDER BY time DESC, id DESC"
    )
    if limit is not None:
        query += " LIMIT ?"
        params.append(max(0, int(limit)))
    return _row_dicts(conn.execute(query, params))


def query_all_except(
    conn: sqlite3.Connection,
    exclude_ids: list[int],
    limit: int,
) -> list[dict[str, Any]]:
    conditions = ""
    params: list[Any] = []
    if exclude_ids:
        placeholders = ",".join("?" for _ in exclude_ids)
        conditions = f" WHERE id NOT IN ({placeholders})"
        params.extend(int(memory_id) for memory_id in exclude_ids)
    params.append(max(0, int(limit)))
    cursor = conn.execute(
        "SELECT id, content, time FROM memories"
        + conditions
        + " ORDER BY time DESC, id DESC LIMIT ?",
        params,
    )
    return _row_dicts(cursor)


def _fetch_memories_by_ids(
    conn: sqlite3.Connection,
    memory_ids: list[int],
) -> dict[int, dict[str, Any]]:
    ids = list(dict.fromkeys(int(memory_id) for memory_id in memory_ids))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = _row_dicts(
        conn.execute(
            f"SELECT id, content, time FROM memories WHERE id IN ({placeholders})",
            ids,
        )
    )
    return {int(row["id"]): row for row in rows}


def _row_dicts(cursor) -> list[dict[str, Any]]:
    return [
        {"id": int(memory_id), "content": content, "time": int(memory_time)}
        for memory_id, content, memory_time in cursor
    ]


# ---------------------------------------------------------------------------
# Exact keyword retrieval
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExactKeyword:
    value: str
    numeric_user_id: bool


def _is_cjk_ideograph(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
    )


def _eligible_exact_keywords(query: str) -> list[ExactKeyword]:
    keywords: list[ExactKeyword] = []
    seen: set[str] = set()
    for raw_keyword in str(query).split():
        normalized = raw_keyword.casefold()
        if normalized in seen:
            continue
        numeric_user_id = raw_keyword.isascii() and raw_keyword.isdigit()
        weighted_length = sum(
            2 if _is_cjk_ideograph(character) else 1
            for character in raw_keyword
            if _is_cjk_ideograph(character)
            or (character.isascii() and character.isalpha())
        )
        if not numeric_user_id and weighted_length < 5:
            continue
        seen.add(normalized)
        keywords.append(ExactKeyword(raw_keyword, numeric_user_id))
    return keywords


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def query_exact_memories(
    conn: sqlite3.Connection,
    query: str,
) -> list[dict[str, Any]]:
    keywords = _eligible_exact_keywords(query)
    if not keywords:
        return []

    score_terms: list[str] = []
    match_terms: list[str] = []
    params: dict[str, str] = {}
    for index, keyword in enumerate(keywords):
        parameter = f"keyword_{index}"
        if keyword.numeric_user_id:
            condition = f"people LIKE :{parameter} ESCAPE '\\'"
            params[parameter] = _canonical_user_id_pattern(int(keyword.value))
        else:
            condition = (
                f"(content LIKE :{parameter} ESCAPE '\\' COLLATE NOCASE "
                f"OR people LIKE :{parameter} ESCAPE '\\' COLLATE NOCASE)"
            )
            params[parameter] = f"%{_escape_like(keyword.value)}%"
        score_terms.append(f"CASE WHEN {condition} THEN 1 ELSE 0 END")
        match_terms.append(condition)

    cursor = conn.execute(
        "SELECT id, content, time, ("
        + " + ".join(score_terms)
        + ") AS keyword_hits FROM memories WHERE "
        + " OR ".join(match_terms)
        + " ORDER BY keyword_hits DESC, time DESC, id DESC",
        params,
    )
    return [
        {
            "id": int(memory_id),
            "content": content,
            "time": int(memory_time),
            "keyword_hits": int(keyword_hits),
        }
        for memory_id, content, memory_time, keyword_hits in cursor
    ]


# ---------------------------------------------------------------------------
# Normalization and lifecycle
# ---------------------------------------------------------------------------


def _get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = init_db(store.get_plugin_data_file(_MEMORY_DB_FILE))
    return _db_conn


def _get_vector_store() -> MilvusVectorStore:
    return MilvusVectorStore(
        store.get_plugin_data_file(_MEMORY_VECTOR_DB_FILE),
        dimension=_VECTOR_DIMENSION,
    )


@contextmanager
def _vector_store_session() -> Iterator[MilvusVectorStore]:
    """Serialize embedded Milvus use and stop its gRPC server afterward."""
    with _vector_store_lock:
        vector_store = _get_vector_store()
        try:
            yield vector_store
        finally:
            vector_store.close()


def _truncate_for_embedding(text: str) -> str:
    return text[:_EMBEDDING_MAX_CHARS]


def ensure_embedding_model():
    global embedding_model
    if embedding_model is None:
        from ..models import get_embedding_model

        embedding_model = get_embedding_model()
    return embedding_model


def normalize_people(
    people: list[dict[str, Any]] | None,
) -> list[dict[str, int | str]]:
    normalized: list[dict[str, int | str]] = []
    seen_ids: set[int] = set()
    for person in people or []:
        if not isinstance(person, dict):
            continue
        try:
            user_id = int(person.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if user_id in seen_ids:
            continue
        user_name = str(person.get("user_name") or user_id)
        seen_ids.add(user_id)
        normalized.append({"user_id": user_id, "user_name": user_name})
    return normalized


def normalize_memory_object(obj: Any) -> tuple[dict[str, Any] | None, bool]:
    if not isinstance(obj, dict):
        return None, True
    content = obj.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, True
    try:
        raw_time = obj.get("time")
        if raw_time is None:
            return None, True
        mem_time = int(raw_time)
    except (TypeError, ValueError):
        return None, True
    normalized_obj = {
        "content": content,
        "time": mem_time,
        "people": normalize_people(obj.get("people")),
    }
    return normalized_obj, normalized_obj != obj


def get_recent_user_memories(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    bounded_limit = max(0, min(int(limit), 100))
    if bounded_limit == 0:
        return []
    cursor = _get_db().execute(
        "SELECT content, time FROM memories "
        "WHERE people LIKE ? ORDER BY time DESC, id DESC LIMIT ?",
        (_canonical_user_id_pattern(int(user_id)), bounded_limit),
    )
    return [
        {"content": content, "time": int(memory_time)}
        for content, memory_time in cursor
    ]


def add_mem(value: str, people: list[dict[str, Any]] | None = None) -> None:
    normalized_people = normalize_people(people)
    now = int(time.time())
    tokens = tokenize_with_pos(value)

    print("add memory:", value)
    print(
        "relative people: ",
        ", ".join(str(person["user_name"]) for person in normalized_people),
    )
    try:
        memory_id = insert_memory(
            _get_db(),
            value,
            now,
            normalized_people,
            tokens,
        )
    except Exception as exc:
        print(f"Error persisting memory to SQLite: {exc}")
        traceback.print_exc()
        return

    try:
        vector = ensure_embedding_model().embed_documents(
            [_truncate_for_embedding(value)]
        )[0]
        with _vector_store_session() as vector_store:
            vector_store.upsert([(memory_id, vector)])
        print(f'Memory inserted: id={memory_id}, content="{value[:60]}"')
    except Exception as exc:
        print(f"Error persisting memory vector to Milvus: {exc}")
        traceback.print_exc()


def migrate_from_json(
    conn: sqlite3.Connection,
    json_path: str | Path,
    model,
) -> int:
    path = Path(json_path)
    if not path.exists():
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return 0

    vector_store = None
    if model is not None:
        try:
            _vector_store_lock.acquire()
            vector_store = _get_vector_store()
        except Exception as exc:
            _vector_store_lock.release()
            print(f"Error opening Milvus for JSON migration: {exc}")
            traceback.print_exc()

    count = 0
    try:
        for raw_obj in raw:
            obj, _ = normalize_memory_object(raw_obj)
            if obj is None:
                continue
            tokens = tokenize_with_pos(obj["content"])
            memory_id = insert_memory(
                conn,
                obj["content"],
                obj["time"],
                obj["people"],
                tokens,
            )
            count += 1
            if model is None or vector_store is None:
                continue
            try:
                vector = model.embed_documents(
                    [_truncate_for_embedding(obj["content"])]
                )[0]
                vector_store.upsert([(memory_id, vector)])
            except Exception as exc:
                print(f"Error migrating memory {memory_id} vector: {exc}")
                traceback.print_exc()
    finally:
        if vector_store is not None:
            try:
                vector_store.close()
            finally:
                _vector_store_lock.release()
    return count


def init_memory_system() -> None:
    conn = _get_db()
    json_path = Path(store.get_plugin_data_file("memory.json"))
    if json_path.exists():
        count = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        if count == 0:
            print("Migrating memory.json to SQLite and Milvus...")
            migrated = migrate_from_json(conn, json_path, ensure_embedding_model())
            print(f"Migrated {migrated} memories")
            json_path.rename(Path(str(json_path) + ".bak"))
    try:
        with _vector_store_session():
            pass
    except Exception as exc:
        print(f"Error opening Milvus memory vectors: {exc}")
        traceback.print_exc()
    count = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
    print(f"Initialized SQLite memory store with {count} memories")


@scheduler.scheduled_job(
    CronTrigger(hour=4, minute=30, second=0, timezone="Asia/Shanghai"),
    id="daily_memory_manage",
    name="每日整理记忆",
    misfire_grace_time=300,
)
def init_tokenized_corpus() -> None:
    """Delete expired metadata and best-effort remove matching Milvus vectors."""
    retention_seconds = 60 * 60 * 24 * MEMORY_EXPIRY_DAYS
    try:
        conn = _get_db()
        expired_ids = _expired_memory_ids(conn, retention_seconds)
        deleted = delete_expired_memories(conn, retention_seconds)
        if expired_ids:
            try:
                with _vector_store_session() as vector_store:
                    vector_store.delete(expired_ids)
            except Exception as exc:
                print(f"Error deleting expired Milvus vectors: {exc}")
                traceback.print_exc()
        print(f"Expired {deleted} memories")
    except Exception as exc:
        print(f"Error in daily memory maintenance: {exc}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Bounded hybrid retrieval
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredMemory:
    memory_id: int
    content: str
    timestamp: int
    score: float


def _bm25_candidates(
    conn: sqlite3.Connection,
    user_query: str,
    user_ids: list[int] | None,
    exclude_ids: set[int],
    remaining: int,
    time_window: int,
) -> dict[int, ScoredMemory]:
    candidate_limit = remaining * _VECTOR_CANDIDATE_MULTIPLIER
    if candidate_limit <= 0:
        return {}

    rows: list[dict[str, Any]] = []
    selected_ids = set(exclude_ids)
    if user_ids:
        user_rows = query_by_user_ids(
            conn,
            user_ids,
            time.time() - time_window,
            list(selected_ids),
            limit=candidate_limit,
        )
        rows.extend(user_rows)
        selected_ids.update(int(row["id"]) for row in user_rows)
    rows.extend(query_all_except(conn, list(selected_ids), candidate_limit))
    if not rows:
        return {}

    query_tokens = [word for word, _ in tokenize_with_pos(user_query)]
    corpus = [
        [word for word, _ in tokenize_with_pos(str(row["content"]))]
        for row in rows
    ]
    if not query_tokens or not any(corpus):
        return {}

    scores = BM25Okapi(corpus, b=0.3).get_scores(query_tokens)
    max_score = max(scores) if len(scores) else 0.0
    if max_score <= 0:
        return {}

    results: dict[int, ScoredMemory] = {}
    for row, raw_score in zip(rows, scores, strict=True):
        normalized_score = float(raw_score) / float(max_score)
        if normalized_score <= _config.SCORE_THRESHOLD:
            continue
        memory_id = int(row["id"])
        results[memory_id] = ScoredMemory(
            memory_id=memory_id,
            content=str(row["content"]),
            timestamp=int(row["time"]),
            score=(1 - _config.EMBEDDING_WEIGHT) * normalized_score,
        )
    return results


def _vector_candidates(
    conn: sqlite3.Connection,
    user_query: str,
    exclude_ids: set[int],
    remaining: int,
) -> dict[int, ScoredMemory]:
    search_limit = remaining * _VECTOR_CANDIDATE_MULTIPLIER
    if search_limit <= 0:
        return {}
    try:
        query_vector = ensure_embedding_model().embed_query(
            _truncate_for_embedding(user_query)
        )
        with _vector_store_session() as vector_store:
            hits: list[VectorSearchResult] = vector_store.search(
                query_vector,
                limit=search_limit,
            )
    except Exception as exc:
        print(f"Error searching Milvus memory vectors: {exc}")
        traceback.print_exc()
        return {}

    eligible_hits = [hit for hit in hits if int(hit.memory_id) not in exclude_ids]
    rows_by_id = _fetch_memories_by_ids(
        conn,
        [int(hit.memory_id) for hit in eligible_hits],
    )
    results: dict[int, ScoredMemory] = {}
    for hit in eligible_hits:
        memory_id = int(hit.memory_id)
        row = rows_by_id.get(memory_id)
        if row is None:
            continue
        normalized_score = (float(hit.score) + 1.0) / 2.0
        if normalized_score < _config.EMBEDDING_SIMILARITY_THRESHOLD:
            continue
        results[memory_id] = ScoredMemory(
            memory_id=memory_id,
            content=str(row["content"]),
            timestamp=int(row["time"]),
            score=_config.EMBEDDING_WEIGHT * normalized_score,
        )
    return results


def query_mems(
    user_query: str,
    user_ids: list[int] | None = None,
    max_limit: int | None = None,
    time_window: int = 24 * 3600,
) -> list[tuple[str, int]]:
    """Return unlimited exact matches, then bounded BM25/Milvus supplements."""
    if not str(user_query).strip():
        return []

    conn = _get_db()
    exact_rows = query_exact_memories(conn, str(user_query))
    results = [
        (str(row["content"]), int(row["time"]))
        for row in exact_rows
    ]
    limit = max(0, int(max_limit if max_limit is not None else _config.MAX_MEMORY_LIMIT))
    if len(exact_rows) >= limit:
        return results

    remaining = limit - len(exact_rows)
    exact_ids = {int(row["id"]) for row in exact_rows}
    bm25_results = _bm25_candidates(
        conn,
        str(user_query),
        user_ids,
        exact_ids,
        remaining,
        time_window,
    )
    vector_results = _vector_candidates(
        conn,
        str(user_query),
        exact_ids,
        remaining,
    )

    fused = dict(bm25_results)
    for memory_id, vector_result in vector_results.items():
        existing = fused.get(memory_id)
        if existing is None:
            fused[memory_id] = vector_result
        else:
            fused[memory_id] = ScoredMemory(
                memory_id=memory_id,
                content=existing.content,
                timestamp=existing.timestamp,
                score=existing.score + vector_result.score,
            )
    ranked = sorted(
        fused.values(),
        key=lambda item: (item.score, item.timestamp, item.memory_id),
        reverse=True,
    )
    results.extend(
        (item.content, item.timestamp)
        for item in ranked[:remaining]
    )
    return results
