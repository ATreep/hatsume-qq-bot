"""Unified memory engine: SQLite persistence, BM25 indexing, and hybrid retrieval."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------
import json
import sqlite3
import time
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Third-party
# ---------------------------------------------------------------------------
import numpy as np
from nonebot import require
import nonebot_plugin_localstore as store
from apscheduler.triggers.cron import CronTrigger
from rank_bm25 import BM25Okapi

# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------
from .. import config as _config
from ..config import MEMORY_EXPIRY_DAYS
from .tokenizer import tokenize_with_pos

# noinspection PyNoneFunctionAssignment
scheduler = require("nonebot_plugin_apscheduler").scheduler
require("nonebot_plugin_localstore")


# =============================================================================
# ---- Database Layer (db.py) ----
# =============================================================================


def init_db(conn_or_path):
    """Open (or create) the SQLite database and ensure schema exists.

    Accepts either an existing sqlite3.Connection or a path string.
    Returns the connection.
    """
    if isinstance(conn_or_path, sqlite3.Connection):
        conn = conn_or_path
    else:
        conn = sqlite3.connect(str(conn_or_path), check_same_thread=False)
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


def insert_memory(conn, content, mem_time, people, tokens, embedding):
    """Insert a memory row. Returns the new row id."""
    people_json = json.dumps(people, ensure_ascii=False)
    tokens_json = json.dumps(tokens, ensure_ascii=False)
    embedding_blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
    now = int(time.time())
    cursor = conn.execute(
        "INSERT INTO memories (content, time, people, tokens, embedding, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (content, mem_time, people_json, tokens_json, embedding_blob, now),
    )
    conn.commit()
    return cursor.lastrowid


def delete_expired_memories(conn, retention_seconds):
    """Delete memories older than retention_seconds. Returns count deleted."""
    cutoff = int(time.time()) - retention_seconds
    cursor = conn.execute("DELETE FROM memories WHERE time < ?", (cutoff,))
    conn.commit()
    return cursor.rowcount


def load_all_memories(conn):
    """Load all memories from SQLite and reconstruct in-memory structures."""
    all_mem_list = []
    tokenized_corpus = []
    tokenized_corpus_pos = []
    vectors = []
    cursor = conn.execute(
        "SELECT id, content, time, people, tokens, embedding FROM memories ORDER BY id"
    )
    for row in cursor:
        _, content, mem_time, people_json, tokens_json, embedding_blob = row
        people = json.loads(people_json)
        tokens = [tuple(t) for t in json.loads(tokens_json)]
        all_mem_list.append({"content": content, "time": mem_time, "people": people})
        tokenized_corpus.append([w for w, _ in tokens])
        tokenized_corpus_pos.append(tokens)
        if embedding_blob is not None:
            vectors.append(np.frombuffer(embedding_blob, dtype=np.float32))
    if vectors:
        embedding_vectors = np.stack(vectors, axis=0)
    else:
        embedding_vectors = None
    return all_mem_list, tokenized_corpus, tokenized_corpus_pos, embedding_vectors


def query_by_user_ids(conn, user_ids, since_time, exclude_ids):
    """Query memories whose people JSON contains any of the given user_ids."""
    if not user_ids:
        return []
    placeholders = ",".join("?" * len(user_ids))
    exclude_placeholders = ",".join("?" * len(exclude_ids)) if exclude_ids else ""
    conditions = [
        f"id IN ("
        f"  SELECT DISTINCT m.id FROM memories m, json_each(m.people) AS p "
        f"  WHERE json_extract(p.value, '$.user_id') IN ({placeholders})"
        f")"
    ]
    params = list(user_ids)
    if since_time is not None:
        conditions.append("time > ?")
        params.append(int(since_time))
    if exclude_ids:
        conditions.append(f"id NOT IN ({exclude_placeholders})")
        params.extend(exclude_ids)
    query = f"SELECT id, content, time, people FROM memories WHERE {' AND '.join(conditions)} ORDER BY time DESC"
    cursor = conn.execute(query, params)
    results = []
    for row in cursor:
        mem_id, content, mem_time, people_json = row
        results.append({"id": mem_id, "content": content, "time": mem_time, "people": json.loads(people_json)})
    return results


def query_all_except(conn, exclude_ids, limit):
    """Query all memories except those in exclude_ids, ordered by time DESC."""
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        query = f"SELECT id, content, time, people FROM memories WHERE id NOT IN ({placeholders}) ORDER BY time DESC LIMIT ?"
        params = list(exclude_ids) + [limit]
    else:
        query = "SELECT id, content, time, people FROM memories ORDER BY time DESC LIMIT ?"
        params = [limit]
    cursor = conn.execute(query, params)
    results = []
    for row in cursor:
        mem_id, content, mem_time, people_json = row
        results.append({"id": mem_id, "content": content, "time": mem_time, "people": json.loads(people_json)})
    return results


def migrate_from_json(conn, json_path, embedding_model):
    """One-time migration from memory.json to SQLite."""
    json_path = Path(json_path)
    if not json_path.exists():
        return 0

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return 0

    count = 0
    for raw_obj in raw:
        obj, _ = normalize_memory_object(raw_obj)
        if obj is None:
            continue
        tokens = tokenize_with_pos(obj["content"])
        embedding = None
        if embedding_model is not None:
            try:
                truncated = obj["content"][:300]
                vec = np.asarray(
                    embedding_model.embed_documents([truncated])[0],
                    dtype=np.float32,
                )
                embedding = vec
            except Exception:
                pass
        insert_memory(conn, obj["content"], obj["time"], obj["people"], tokens, embedding)
        count += 1
    return count


# =============================================================================
# ---- Storage & Indexing (store.py) ----
# =============================================================================

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
tokenized_corpus: list[list[str]] = []
tokenized_corpus_pos: list[list[tuple[str, str]]] = []
all_mem_list: list[dict] = []
bm25_dirty: bool = False
_db_conn = None


def _get_db():
    """Lazy-init SQLite connection for this process."""
    global _db_conn
    if _db_conn is None:
        db_path = str(store.get_plugin_data_file("memory.db"))
        _db_conn = init_db(db_path)
    return _db_conn


def get_mem_list() -> list[dict]:
    return all_mem_list


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def normalize_people(people: list[dict[str, Any]] | None) -> list[dict[str, int | str]]:
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
    if not isinstance(content, str) or content.strip() == "":
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


# ---------------------------------------------------------------------------
# Add memory
# ---------------------------------------------------------------------------
def add_mem(value: str, people: list[dict[str, Any]] | None = None) -> None:
    global bm25_dirty

    normalized_people = normalize_people(people)

    now = int(time.time())

    print("add memory:", value)
    print("relative people: ", ", ".join([str(p["user_name"]) for p in normalized_people]))

    all_mem_list.append({"content": value, "time": now, "people": normalized_people})

    tokens_pos = tokenize_with_pos(value)
    tokenized_corpus_pos.append(tokens_pos)
    tokenized_corpus.append([w for w, _ in tokens_pos])

    bm25_dirty = True

    # Compute embedding for DB persistence and in-memory index
    new_vector: np.ndarray | None = None
    try:
        model = ensure_embedding_model()

        truncated = value[:300]
        new_vector = np.asarray(
            model.embed_documents([truncated])[0], dtype=np.float32
        )  # shape (1024,)

        # Update in-memory embedding_vectors
        expected_existing_count = len(all_mem_list) - 1
        e_vectors = get_embedding_vectors()

        if (
            e_vectors is not None
            and len(e_vectors) == expected_existing_count
        ):
            new_vector_2d = new_vector[np.newaxis, :]
            if expected_existing_count == 0:
                set_embedding_vectors(new_vector_2d)
            else:
                set_embedding_vectors(
                    np.concatenate([e_vectors, new_vector_2d], axis=0)
                )
        else:
            rebuild_embedding_vectors()
    except Exception as e:
        print(f"Error building embeddings: {e}")
        traceback.print_exc()
        new_vector = None

    # Persist to SQLite
    try:
        conn = _get_db()
        mem_id = insert_memory(conn, value, now, normalized_people, tokens_pos, new_vector)
        print(f"Memory inserted to SQLite: id={mem_id}, content=\"{value[:60]}\"")
    except Exception as e:
        print(f"Error persisting to SQLite: {e}")


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------
def init_memory_system() -> None:
    """Call on plugin startup: init DB, migrate JSON if needed, load into memory."""
    conn = _get_db()

    # Check for JSON → SQLite migration
    json_path_obj = store.get_plugin_data_file("memory.json")
    json_path = str(json_path_obj)
    if Path(json_path).exists():
        cursor = conn.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]
        if count == 0:
            print("Migrating memory.json → SQLite...")
            model = ensure_embedding_model()
            migrated = migrate_from_json(conn, json_path, model)
            print(f"Migrated {migrated} memories to SQLite")
            # Rename JSON file as backup
            bak_path = json_path + ".bak"
            Path(json_path).rename(bak_path)
            print("Renamed memory.json → memory.json.bak")

    # Load into memory
    global all_mem_list, tokenized_corpus, tokenized_corpus_pos
    all_mem_list, tokenized_corpus, tokenized_corpus_pos, _embedding_vectors = (
        load_all_memories(conn)
    )
    set_embedding_vectors(_embedding_vectors)
    rebuild_bm25(index_b=0.3)
    print(f"Loaded {len(all_mem_list)} memories from SQLite")


# ---------------------------------------------------------------------------
# Daily maintenance (APScheduler job)
# ---------------------------------------------------------------------------
@scheduler.scheduled_job(
    CronTrigger(hour=4, minute=30, second=0, timezone="Asia/Shanghai"),
    id="daily_memory_manage",
    name="每日整理记忆",
    misfire_grace_time=300,
)
def init_tokenized_corpus() -> None:
    """Daily maintenance: expire old memories, reload all indices from SQLite."""
    global tokenized_corpus, tokenized_corpus_pos, all_mem_list, bm25_dirty

    print("Updating tokenized corpus...")
    t_start = time.time()

    try:
        conn = _get_db()
        delete_expired_memories(conn, 60 * 60 * 24 * MEMORY_EXPIRY_DAYS)
        all_mem_list, tokenized_corpus, tokenized_corpus_pos, _embedding_vectors = (
            load_all_memories(conn)
        )
        set_embedding_vectors(_embedding_vectors)
    except Exception as e:
        print(f"Error in daily maintenance: {e}")
        traceback.print_exc()
        all_mem_list = []
        tokenized_corpus = []
        tokenized_corpus_pos = []
        set_embedding_vectors(None)

    rebuild_bm25(index_b=0)

    bm25_dirty = False

    print(f"Updated finished, t={time.time() - t_start}s")


# =============================================================================
# ---- Hybrid Retrieval (retrieval.py) ----
# =============================================================================

_EMBEDDING_MAX_CHARS = 300

# Index state
bm25: BM25Okapi | None = None
embedding_vectors: np.ndarray | None = None
embedding_model = None


def _truncate_for_embedding(text: str) -> str:
    return text[:_EMBEDDING_MAX_CHARS]


def ensure_embedding_model():
    global embedding_model
    if embedding_model is None:
        from ..models import get_embedding_model
        embedding_model = get_embedding_model()
    return embedding_model


def rebuild_bm25(index_b: float = 0.3) -> None:
    global bm25
    bm25 = BM25Okapi(tokenized_corpus, b=index_b) if tokenized_corpus else None


def rebuild_embedding_vectors() -> None:
    global embedding_vectors
    if not all_mem_list:
        embedding_vectors = None
        return
    model = ensure_embedding_model()
    texts = [_truncate_for_embedding(mem["content"]) for mem in all_mem_list]
    embedding_vectors = np.asarray(model.embed_documents(texts), dtype=np.float32)


def get_embedding_vectors() -> np.ndarray | None:
    return embedding_vectors


def set_embedding_vectors(vectors: np.ndarray | None) -> None:
    global embedding_vectors
    embedding_vectors = vectors


def query_mems(
    user_query: str,
    user_ids: list[int] | None = None,
    max_limit: int | None = None,
    time_window: int = 24 * 3600,
) -> list[tuple[str, int]]:
    """Search memories with two-phase retrieval.

    Phase 1: User-specific — memories involving user_ids within the configured window,
             scored by hybrid BM25+embedding relevance.
    Phase 2: Supplemental — if Phase 1 < max_limit, fill with any
             sentence-relevant memories (no time filter).

    Returns list of (content, timestamp) tuples.
    """
    global bm25

    if not all_mem_list or not user_query:
        return []

    if bm25_dirty:
        rebuild_bm25(index_b=0.3)

    import time as _time
    now = _time.time()

    limit = max_limit if max_limit is not None else _config.MAX_MEMORY_LIMIT

    # --- Phase 1: User-specific (24h default window) ---
    phase1_results: dict[int, float] = {}
    excluded_ids: set[int] = set()

    if user_ids:
        try:
            conn = _get_db()
            since_time = now - time_window
            db_rows = query_by_user_ids(conn, list(user_ids), since_time, [])
            if db_rows:
                phase1_results, excluded_ids = _score_memory_rows(db_rows, user_query)
        except Exception as e:
            print(f"Error in Phase 1 retrieval: {e}")
            traceback.print_exc()

    # --- Phase 2: Supplemental (if needed) ---
    remaining = limit - len(phase1_results)
    if remaining > 0:
        try:
            conn = _get_db()
            fetch_limit = remaining * 3  # Fetch more than needed for better scoring
            db_rows = query_all_except(conn, list(excluded_ids), limit=fetch_limit)
            if db_rows:
                phase2_results, _ = _score_memory_rows(db_rows, user_query)
                for idx, score in phase2_results.items():
                    if idx not in phase1_results:
                        phase1_results[idx] = score
        except Exception as e:
            print(f"Error in Phase 2 retrieval: {e}")
            traceback.print_exc()

    # --- Final ranking ---
    if not phase1_results:
        return []

    sorted_results = sorted(phase1_results.items(), key=lambda x: x[1], reverse=True)
    sorted_results = sorted_results[:limit]

    return [
        (all_mem_list[idx]["content"], all_mem_list[idx]["time"])
        for idx, _ in sorted_results
    ]


def _score_memory_rows(
    db_rows: list[dict], user_query: str
) -> tuple[dict[int, float], set[int]]:
    """Score db rows via hybrid BM25+embedding against user_query.

    Returns (scored_indices: dict[index -> score], excluded_indices: set[index]).
    Indices are into all_mem_list.
    """
    global bm25, embedding_vectors

    # Build an index map from all_mem_list content -> position
    content_to_idx: dict[str, int] = {}
    for i, mem in enumerate(all_mem_list):
        content_to_idx[mem["content"]] = i

    row_indices: dict[int, dict] = {}  # idx_in_all_mem_list -> row dict
    for row in db_rows:
        idx = content_to_idx.get(row["content"])
        if idx is not None:
            row_indices[idx] = row

    results: dict[int, float] = {}
    excluded: set[int] = set(idx for idx in row_indices)

    # BM25 keyword matching
    if tokenized_corpus and bm25 is not None:
        query_tokens_pos = tokenize_with_pos(user_query)
        if query_tokens_pos:
            query_tokens = [w for w, _ in query_tokens_pos]
            scores = bm25.get_scores(query_tokens)
            max_score = max(scores) if len(scores) > 0 else 1.0
            if max_score > 0:
                for idx in row_indices:
                    if idx < len(scores):
                        normalized_score = scores[idx] / max_score
                        if normalized_score > _config.SCORE_THRESHOLD:
                            results[idx] = (1 - _config.EMBEDDING_WEIGHT) * normalized_score

    # Embedding semantic similarity
    try:
        if embedding_vectors is not None:
            model = ensure_embedding_model()
            query_vec = np.asarray(
                model.embed_query(_truncate_for_embedding(user_query)), dtype=np.float32
            )
            query_norm = np.linalg.norm(query_vec)

            if query_norm > 0:
                for idx in row_indices:
                    if idx < len(embedding_vectors):
                        mem_vec = embedding_vectors[idx]
                        mem_norm = np.linalg.norm(mem_vec)
                        if mem_norm > 0:
                            cosine_sim = np.dot(query_vec, mem_vec) / (query_norm * mem_norm)
                            cosine_sim_norm = (cosine_sim + 1) / 2
                            if cosine_sim_norm >= _config.EMBEDDING_SIMILARITY_THRESHOLD:
                                embedding_component = _config.EMBEDDING_WEIGHT * cosine_sim_norm
                                if idx in results:
                                    results[idx] += embedding_component
                                else:
                                    results[idx] = embedding_component
    except Exception as e:
        print(f"Error in embedding search: {e}")
        traceback.print_exc()

    return results, excluded
