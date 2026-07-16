# Memory System Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace JSON-based memory storage with SQLite, inline memory recording via `[memoryrecord: ...]` tags, and two-phase retrieval with 6-hour user window.

**Architecture:** SQLite database (`memory/db.py`) becomes the authoritative persistence layer storing content, tokens, and embedding vectors. `store.py` keeps in-memory indices but loads from SQLite on startup without rebuilding. `ai_node` parses inline `[memoryrecord: {...}]` JSON tags from chat_agent output instead of a separate LLM call in `finish.py`. Retrieval uses a two-phase algorithm: user-specific memories (6h window) first, then supplemental.

**Tech Stack:** Python 3.12+, sqlite3 (stdlib), numpy, rank_bm25, jieba

## Global Constraints

- `MAX_MEMORY_LIMIT: int = 50` added to config.py (replaces `MEMORY_TOP_K`)
- 6-hour window applies only to user-specific prioritization phase
- `[memoryrecord: {"content": "...", "people": [...]}]` JSON format, parsed via regex
- Embedding vectors stored as float32 BLOBs in SQLite — no rebuild on startup
- Tokenized corpus stored as JSON in SQLite — no re-tokenization on startup
- One-time JSON→SQLite migration on first deploy (memory.json renamed to .bak)
- `find_memory` tool unchanged; `write_memory` tool removed entirely
- All existing tests must continue to pass after refactor

---

### Task 1: Config Changes

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py:119-127`

**Interfaces:**
- Produces: `MAX_MEMORY_LIMIT: int = 50`
- Removes: `MEMORY_TOP_K: int = 25`, `BM25_RECALL_K: int = 50`

- [ ] **Step 1: Replace memory constants in config.py**

Replace the memory constants block (lines 119-127):
```python
# ---------------------------------------------------------------------------
# Memory constants
# ---------------------------------------------------------------------------
MAX_MEMORY_LIMIT: int = 50
SCORE_THRESHOLD: float = 0.1
EMBEDDING_SIMILARITY_THRESHOLD: float = 0.4
EMBEDDING_WEIGHT: float = 0.5
PEOPLE_PRIORITY_RATIO: float = 0.3
MEMORY_EXPIRY_DAYS: int = 150
MEMORY_SIX_HOUR_WINDOW: int = 6 * 3600  # 21600 seconds
```

- [ ] **Step 2: Run existing tests to verify no import breakage**

```bash
python -m pytest tests/test_memory_utils.py -xvs
```

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/config.py
git commit -m "feat: add MAX_MEMORY_LIMIT and MEMORY_SIX_HOUR_WINDOW, remove MEMORY_TOP_K

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: SQLite Database Layer (db.py)

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/memory/db.py`
- Test: `tests/test_memory_db.py` (create new)

**Interfaces:**
- Produces:
  - `init_db(db_path: str) -> sqlite3.Connection`
  - `insert_memory(conn, content: str, time: int, people: list[dict], tokens: list[tuple[str, str]], embedding: np.ndarray | None) -> int`
  - `delete_expired_memories(conn, retention_seconds: int) -> int`
  - `load_all_memories(conn) -> tuple[list[dict], list[list[str]], list[list[tuple[str, str]]], np.ndarray | None]`
  - `query_by_user_ids(conn, user_ids: list[int], since_time: float | None, exclude_ids: list[int]) -> list[dict]`
  - `query_all_except(conn, exclude_ids: list[int], limit: int) -> list[dict]`
  - `migrate_from_json(conn, json_path: str, embedding_model) -> int`

- [ ] **Step 1: Write failing tests for db.py**

Create `tests/test_memory_db.py`:
```python
"""Tests for memory/db.py — SQLite storage layer."""
from __future__ import annotations

import json
import sqlite3
import sys
import types
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _load_db_module():
    base = ROOT / "hatsume/plugins/hatsume-plugin"
    for pfx in ("hatsume", "hatsume.plugins", "hatsume.plugins.hatsume-plugin",
                "hatsume.plugins.hatsume-plugin.memory"):
        if pfx in sys.modules:
            del sys.modules[pfx]
    hatsume = types.ModuleType("hatsume")
    hatsume.__path__ = [str(ROOT / "hatsume")]
    sys.modules["hatsume"] = hatsume
    plugins = types.ModuleType("hatsume.plugins")
    plugins.__path__ = [str(ROOT / "hatsume/plugins")]
    sys.modules["hatsume.plugins"] = plugins
    plugin = types.ModuleType("hatsume.plugins.hatsume-plugin")
    plugin.__path__ = [str(base)]
    sys.modules["hatsume.plugins.hatsume-plugin"] = plugin
    memory = types.ModuleType("hatsume.plugins.hatsume-plugin.memory")
    memory.__path__ = [str(base / "memory")]
    sys.modules["hatsume.plugins.hatsume-plugin.memory"] = memory
    spec = __import__("importlib.util").util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.memory.db", base / "memory" / "db.py"
    )
    mod = __import__("importlib.util").util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.memory.db"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_init_db_creates_tables():
    """init_db creates the memories table with correct schema."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
    assert cursor.fetchone() is not None
    # Check columns
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    assert cols >= {"id", "content", "time", "people", "tokens", "embedding", "created_at"}


def test_insert_and_load_roundtrip():
    """Insert a memory, then load_all — data survives roundtrip."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)

    now = int(time.time())
    people = [{"user_id": 123, "user_name": "测试用户"}]
    tokens = [("测试", "n"), ("用户", "n")]
    embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    row_id = db.insert_memory(conn, "测试用户喜欢芒果", now, people, tokens, embedding)
    assert row_id == 1

    mem_list, tok_corpus, tok_corpus_pos, emb_vectors = db.load_all_memories(conn)
    assert len(mem_list) == 1
    assert mem_list[0]["content"] == "测试用户喜欢芒果"
    assert mem_list[0]["time"] == now
    assert mem_list[0]["people"] == people
    assert tok_corpus == [["测试", "用户"]]
    assert tok_corpus_pos == [[("测试", "n"), ("用户", "n")]]
    np.testing.assert_array_equal(emb_vectors, np.array([[0.1, 0.2, 0.3]], dtype=np.float32))


def test_delete_expired_memories():
    """delete_expired_memories removes rows older than retention_seconds."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)

    old_time = int(time.time()) - 100000
    db.insert_memory(conn, "old", old_time, [], [], None)
    db.insert_memory(conn, "new", int(time.time()), [], [], None)

    deleted = db.delete_expired_memories(conn, retention_seconds=50000)
    assert deleted == 1
    mem_list, _, _, _ = db.load_all_memories(conn)
    assert len(mem_list) == 1
    assert mem_list[0]["content"] == "new"


def test_query_by_user_ids_with_time_window():
    """query_by_user_ids filters by user_ids and optional since_time."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)

    now = int(time.time())
    db.insert_memory(conn, "mem-a", now - 10000, [{"user_id": 1, "user_name": "A"}], [], None)
    db.insert_memory(conn, "mem-b", now - 1000, [{"user_id": 2, "user_name": "B"}], [], None)
    db.insert_memory(conn, "mem-c", now - 100, [{"user_id": 1, "user_name": "A"}], [], None)

    # Query with 1-hour window for user 1
    results = db.query_by_user_ids(conn, [1], since_time=now - 3600, exclude_ids=[])
    assert len(results) == 1
    assert results[0]["content"] == "mem-c"

    # Query without time window
    results = db.query_by_user_ids(conn, [1], since_time=None, exclude_ids=[])
    assert len(results) == 2

    # Query with exclude
    results = db.query_by_user_ids(conn, [1], since_time=None, exclude_ids=[1])
    assert len(results) == 1


def test_query_all_except():
    """query_all_except returns rows not in exclude_ids, limited."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)

    ids = []
    for i in range(10):
        rid = db.insert_memory(conn, f"mem-{i}", int(time.time()), [], [], None)
        ids.append(rid)

    results = db.query_all_except(conn, exclude_ids=ids[:3], limit=5)
    assert len(results) == 5
    for r in results:
        assert r["id"] not in ids[:3]


def test_migrate_from_json():
    """migrate_from_json reads memory.json and inserts into empty SQLite DB."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)

    # Write a temporary memory.json
    recent = int(time.time())
    json_data = json.dumps([
        {"content": "old-mem-1", "time": recent, "people": []},
        {"content": "old-mem-2", "time": recent - 1000, "people": [{"user_id": 1, "user_name": "X"}]},
    ], ensure_ascii=False)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(json_data)
        json_path = f.name

    class StubEmbedder:
        def embed_documents(self, texts):
            return [[float(i + 1)] * 3 for i in range(len(texts))]

    try:
        count = db.migrate_from_json(conn, json_path, StubEmbedder())
        assert count == 2
        mem_list, tok_corpus, _, emb_vectors = db.load_all_memories(conn)
        assert len(mem_list) == 2
        assert len(tok_corpus) == 2
        assert emb_vectors.shape == (2, 3)
    finally:
        Path(json_path).unlink(missing_ok=True)


def test_load_all_returns_none_embedding_when_empty():
    """load_all_memories returns None embedding_vectors for empty DB."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    mem_list, tok_corpus, tok_corpus_pos, emb_vectors = db.load_all_memories(conn)
    assert mem_list == []
    assert emb_vectors is None
```

- [ ] **Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_memory_db.py -xvs
```
Expected: FAIL — module not yet created

- [ ] **Step 3: Implement db.py**

Create `hatsume/plugins/hatsume-plugin/memory/db.py`:
```python
"""SQLite persistence layer for long-term memories."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import numpy as np


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure schema exists."""
    conn = sqlite3.connect(str(db_path))
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_time ON memories(time)"
    )
    conn.commit()
    return conn


def insert_memory(
    conn: sqlite3.Connection,
    content: str,
    mem_time: int,
    people: list[dict],
    tokens: list[tuple[str, str]],
    embedding: np.ndarray | None,
) -> int:
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


def delete_expired_memories(
    conn: sqlite3.Connection, retention_seconds: int
) -> int:
    """Delete memories older than retention_seconds. Returns count deleted."""
    cutoff = int(time.time()) - retention_seconds
    cursor = conn.execute("DELETE FROM memories WHERE time < ?", (cutoff,))
    conn.commit()
    return cursor.rowcount


def load_all_memories(
    conn: sqlite3.Connection,
) -> tuple[list[dict], list[list[str]], list[list[tuple[str, str]]], np.ndarray | None]:
    """Load all memories from SQLite and reconstruct in-memory structures.

    Returns:
        (all_mem_list, tokenized_corpus, tokenized_corpus_pos, embedding_vectors)
        embedding_vectors is None if there are no rows or no embeddings.
    """
    all_mem_list: list[dict] = []
    tokenized_corpus: list[list[str]] = []
    tokenized_corpus_pos: list[list[tuple[str, str]]] = []
    vectors: list[np.ndarray] = []

    cursor = conn.execute("SELECT id, content, time, people, tokens, embedding FROM memories ORDER BY id")
    for row in cursor:
        mem_id, content, mem_time, people_json, tokens_json, embedding_blob = row
        people = json.loads(people_json)
        tokens = [tuple(t) for t in json.loads(tokens_json)]  # JSON arrays → tuples
        all_mem_list.append({
            "content": content,
            "time": mem_time,
            "people": people,
        })
        tokenized_corpus.append([w for w, _ in tokens])
        tokenized_corpus_pos.append(tokens)
        if embedding_blob is not None:
            vectors.append(np.frombuffer(embedding_blob, dtype=np.float32))

    if vectors:
        embedding_vectors = np.stack(vectors, axis=0)
    else:
        embedding_vectors = None

    return all_mem_list, tokenized_corpus, tokenized_corpus_pos, embedding_vectors


def query_by_user_ids(
    conn: sqlite3.Connection,
    user_ids: list[int],
    since_time: float | None,
    exclude_ids: list[int],
) -> list[dict]:
    """Query memories whose people JSON contains any of the given user_ids.

    Optionally filtered by since_time (unix timestamp) and excluding
    specific memory ids. Returns list of memory dicts with 'id' included.
    """
    if not user_ids:
        return []

    # Build a query that checks json_each on the people array
    # JSON format: [{"user_id": 1, "user_name": "A"}, ...]
    placeholders = ",".join("?" * len(user_ids))
    exclude_placeholders = ",".join("?" * len(exclude_ids)) if exclude_ids else ""

    conditions = [
        f"id IN ("
        f"  SELECT DISTINCT m.id FROM memories m, json_each(m.people) AS p "
        f"  WHERE json_extract(p.value, '$.user_id') IN ({placeholders})"
        f")"
    ]
    params: list = list(user_ids)

    if since_time is not None:
        conditions.append("time > ?")
        params.append(int(since_time))

    if exclude_ids:
        conditions.append(f"id NOT IN ({exclude_placeholders})")
        params.extend(exclude_ids)

    query = f"SELECT id, content, time, people FROM memories WHERE {' AND '.join(conditions)} ORDER BY time DESC"

    cursor = conn.execute(query, params)
    results: list[dict] = []
    for row in cursor:
        mem_id, content, mem_time, people_json = row
        results.append({
            "id": mem_id,
            "content": content,
            "time": mem_time,
            "people": json.loads(people_json),
        })
    return results


def query_all_except(
    conn: sqlite3.Connection,
    exclude_ids: list[int],
    limit: int,
) -> list[dict]:
    """Query all memories except those in exclude_ids, ordered by time DESC."""
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        query = f"SELECT id, content, time, people FROM memories WHERE id NOT IN ({placeholders}) ORDER BY time DESC LIMIT ?"
        params = list(exclude_ids) + [limit]
    else:
        query = "SELECT id, content, time, people FROM memories ORDER BY time DESC LIMIT ?"
        params = [limit]

    cursor = conn.execute(query, params)
    results: list[dict] = []
    for row in cursor:
        mem_id, content, mem_time, people_json = row
        results.append({
            "id": mem_id,
            "content": content,
            "time": mem_time,
            "people": json.loads(people_json),
        })
    return results


def migrate_from_json(
    conn: sqlite3.Connection,
    json_path: str | Path,
    embedding_model,
) -> int:
    """One-time migration from memory.json to SQLite.

    Reads existing JSON file, re-tokenizes and re-embeds each entry,
    inserts into SQLite. Returns count of migrated memories.
    Caller should rename/delete the JSON file after success.
    """
    import json as _json
    from .tokenizer import tokenize_with_pos

    json_path = Path(json_path)
    if not json_path.exists():
        return 0

    raw = _json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return 0

    from .store import normalize_memory_object

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
```

- [ ] **Step 4: Run tests to verify**

```bash
python -m pytest tests/test_memory_db.py -xvs
```
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/memory/db.py tests/test_memory_db.py
git commit -m "feat: add SQLite memory database layer with migration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Refactor store.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/store.py`

**Interfaces:**
- Consumes: `db.init_db()`, `db.insert_memory()`, `db.load_all_memories()`, `db.delete_expired_memories()`
- Produces: `get_mem_list()`, `add_mem()`, `init_tokenized_corpus()`, `normalize_people()`, `normalize_memory_object()`, `memory_has_user()`
- Removes: `save_mem_list()`, `_get_memory_data_file()`, `set_active_memory_sources()`, `clear_active_memory_sources()`, `resolve_active_memory_people()`, `active_memory_sources`

- [ ] **Step 1: Update test mocks in test_memory_utils.py**

The `load_memory_modules` helper needs a mock for `db` module so store.py can import it:
```python
# Add before loading store module in load_memory_modules():
db_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.db")
db_mod.init_db = lambda path: sqlite3.connect(str(path) if not isinstance(path, str) else path)
db_mod.insert_memory = lambda conn, content, mem_time, people, tokens, embedding: 1
db_mod.delete_expired_memories = lambda conn, retention: 0
db_mod.load_all_memories = lambda conn: ([], [], [], None)
sys.modules["hatsume.plugins.hatsume-plugin.memory.db"] = db_mod
```

And store.py needs a way to get the DB path. Add to config mock:
```python
config_mod.MEMORY_DB_PATH = str(tmp_path / "memory.db")
```

- [ ] **Step 2: Run tests to confirm current failures**

```bash
python -m pytest tests/test_memory_utils.py -xvs
```
Expected: some tests FAIL because store.py still imports from old code (save_mem_list, etc.)

- [ ] **Step 3: Rewrite store.py**

```python
"""Persistent storage for long-term memory records (SQLite-backed)."""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

from nonebot import require
import nonebot_plugin_localstore as store
from apscheduler.triggers.cron import CronTrigger

from ..config import MEMORY_EXPIRY_DAYS
from .tokenizer import tokenize_with_pos
from . import db as _db

scheduler = require("nonebot_plugin_apscheduler").scheduler
require("nonebot_plugin_localstore")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
tokenized_corpus: list[list[str]] = []
tokenized_corpus_pos: list[list[tuple[str, str]]] = []
all_mem_list: list[dict] = []
bm25_dirty: bool = False

_db_conn = None


def _get_db() -> Any:
    """Lazy-init the SQLite connection."""
    global _db_conn
    if _db_conn is None:
        db_path = store.get_plugin_data_file("memory.db")
        _db_conn = _db.init_db(str(db_path))
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
            user_id = int(person.get("user_id"))
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
        mem_time = int(obj.get("time"))
    except (TypeError, ValueError):
        return None, True

    normalized_obj = {
        "content": content,
        "time": mem_time,
        "people": normalize_people(obj.get("people")),
    }

    return normalized_obj, normalized_obj != obj


def memory_has_user(mem: dict[str, Any], user_id: int) -> bool:
    return any(
        int(person.get("user_id", -1)) == user_id
        for person in mem.get("people", [])
        if isinstance(person, dict)
    )


# ---------------------------------------------------------------------------
# Add memory
# ---------------------------------------------------------------------------
def add_mem(value: str, people: list[dict[str, Any]] | None = None) -> None:
    global bm25_dirty

    from . import retrieval  # deferred to avoid circular import

    normalized_people = normalize_people(people)
    now = int(time.time())

    print("add memory:", value)
    print("relative people: ", ", ".join([str(p["user_name"]) for p in normalized_people]))

    # Persist to SQLite
    tokens_pos = tokenize_with_pos(value)
    all_tokens = [w for w, _ in tokens_pos]

    try:
        model = retrieval.ensure_embedding_model()
        import numpy as np
        truncated = value[:300]
        new_vector = np.asarray(
            model.embed_documents([truncated])[0], dtype=np.float32
        )
    except Exception as e:
        print(f"Error building embedding for new memory: {e}")
        traceback.print_exc()
        new_vector = None

    conn = _get_db()
    _db.insert_memory(conn, value, now, normalized_people, tokens_pos, new_vector)

    # Update in-memory structures
    obj = {
        "content": value,
        "time": now,
        "people": normalized_people,
    }
    all_mem_list.append(obj)
    tokenized_corpus_pos.append(tokens_pos)
    tokenized_corpus.append(all_tokens)
    bm25_dirty = True

    # Update in-memory embedding vectors
    try:
        embedding_vectors = retrieval.get_embedding_vectors()
        if new_vector is not None:
            if embedding_vectors is None or len(embedding_vectors) == 0:
                retrieval.set_embedding_vectors(new_vector[np.newaxis, :])
            else:
                retrieval.set_embedding_vectors(
                    np.concatenate([embedding_vectors, new_vector[np.newaxis, :]], axis=0)
                )
    except Exception as e:
        print(f"Error updating in-memory embeddings: {e}")
        traceback.print_exc()


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
    """Expire old records in SQLite and reload in-memory indices."""
    from . import retrieval

    global tokenized_corpus, tokenized_corpus_pos, all_mem_list, bm25_dirty

    print("Running daily memory maintenance...")
    t_start = time.time()

    conn = _get_db()

    # Delete expired rows from SQLite
    outdate_seconds = 60 * 60 * 24 * MEMORY_EXPIRY_DAYS
    deleted = _db.delete_expired_memories(conn, outdate_seconds)
    if deleted > 0:
        print(f"Deleted {deleted} expired memories")

    # Reload all in-memory structures from SQLite (authoritative source)
    all_mem_list, tokenized_corpus, tokenized_corpus_pos, embedding_vectors = (
        _db.load_all_memories(conn)
    )

    retrieval.set_embedding_vectors(embedding_vectors)
    retrieval.rebuild_bm25(index_b=0.3)
    bm25_dirty = False

    print(f"Daily maintenance finished, t={time.time() - t_start:.1f}s")


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------
def init_memory_system() -> None:
    """Call on plugin startup: init DB, migrate JSON if needed, load into memory."""
    from . import retrieval

    conn = _get_db()

    # Check for JSON → SQLite migration
    json_path = store.get_plugin_data_file("memory.json")
    if Path(str(json_path)).exists():
        cursor = conn.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]
        if count == 0:
            print("Migrating memory.json → SQLite...")
            model = retrieval.ensure_embedding_model()
            migrated = _db.migrate_from_json(conn, str(json_path), model)
            print(f"Migrated {migrated} memories to SQLite")
            # Rename JSON file as backup
            bak_path = Path(str(json_path) + ".bak")
            Path(str(json_path)).rename(bak_path)
            print(f"Renamed memory.json → memory.json.bak")

    # Load into memory
    global all_mem_list, tokenized_corpus, tokenized_corpus_pos
    all_mem_list, tokenized_corpus, tokenized_corpus_pos, embedding_vectors = (
        _db.load_all_memories(conn)
    )
    retrieval.set_embedding_vectors(embedding_vectors)
    retrieval.rebuild_bm25(index_b=0.3)
    print(f"Loaded {len(all_mem_list)} memories from SQLite")
```

- [ ] **Step 4: Run memory tests**

```bash
python -m pytest tests/test_memory_utils.py -xvs
```
Expected: all tests PASS (after updating mocks). Tests using `set_active_memory_sources` / `resolve_active_memory_people` will need to be removed or updated.

Remove these test functions from test_memory_utils.py since the functions they test are removed:
- `test_resolve_active_memory_people_merges_source_people_without_guessing` — REMOVE (function removed)

Update tests that reference `memory_file` / JSON to work with SQLite-backed store:
- `test_init_tokenized_corpus_migrates_old_memory_records_with_empty_people` — UPDATE to use DB instead of JSON
- `test_add_mem_*` tests — these test in-memory behavior and should pass with SQLite delegation

- [ ] **Step 5: Update test_memory_utils.py**

For `test_init_tokenized_corpus_migrates_old_memory_records_with_empty_people`, populate the DB instead of JSON:
```python
def test_init_tokenized_corpus_expires_old_memories_from_db(tmp_path: Path):
    embedding_model = EmbeddingModelStub({"recent-memory": [0.2, 0.8]})
    _tok, store, retrieval, cfg, _ = load_memory_modules(tmp_path, embedding_model)

    retrieval.embedding_model = embedding_model

    # Insert via db directly (bypass add_mem which needs embedding model)
    conn = sqlite3.connect(str(tmp_path / "memory.db"))
    _db_mod = sys.modules["hatsume.plugins.hatsume-plugin.memory.db"]
    _db_mod.init_db(conn)
    recent = int(time.time())
    _db_mod.insert_memory(conn, "recent-memory", recent, [], [("recent", "n")], None)
    old = recent - 86400 * 200  # 200 days ago, well past 30-day expiry
    _db_mod.insert_memory(conn, "old-memory", old, [], [("old", "n")], None)
    conn.close()

    store.init_tokenized_corpus()

    assert len(store.all_mem_list) == 1
    assert store.all_mem_list[0]["content"] == "recent-memory"
```

Remove:
```python
# DELETE this test function:
def test_resolve_active_memory_people_merges_source_people_without_guessing(...):
    ...
```

- [ ] **Step 6: Run all memory tests to verify**

```bash
python -m pytest tests/test_memory_utils.py tests/test_memory_db.py -xvs
```
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/memory/store.py tests/test_memory_utils.py
git commit -m "refactor: migrate store.py to SQLite backend, remove active_memory_sources

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Update retrieval.py — Two-Phase Query

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/retrieval.py`

**Interfaces:**
- Consumes: `db.query_by_user_ids()`, `db.query_all_except()`, `store.get_mem_list()`
- Produces: updated `query_mems(user_ids, query_text, max_limit, six_hour_window)` with new signature
- Removes: old `preferred_user_id` parameter pattern

- [ ] **Step 1: Update retrieval.py — new query_mems signature and two-phase logic**

Replace the `query_mems` function:

```python
def query_mems(
    user_query: str,
    user_ids: list[int] | None = None,
    max_limit: int | None = None,
    six_hour_window: int = 6 * 3600,
) -> list[tuple[str, int]]:
    """Search memories with two-phase retrieval.

    Phase 1: User-specific — memories involving user_ids within 6h window,
             scored by hybrid BM25+embedding relevance.
    Phase 2: Supplemental — if Phase 1 < max_limit, fill with any
             sentence-relevant memories (no time filter).

    Returns list of (content, timestamp) tuples.
    """
    global bm25

    if not _store.all_mem_list or not user_query:
        return []

    if _store.bm25_dirty:
        rebuild_bm25(index_b=0.3)

    import time as _time
    now = _time.time()

    limit = max_limit if max_limit is not None else _config.MAX_MEMORY_LIMIT

    # ── Phase 1: User-specific (6h window) ──
    phase1_results: dict[int, float] = {}
    excluded_ids: set[int] = set()

    if user_ids:
        conn = _store._get_db()
        since_time = now - six_hour_window
        db_rows = _db.query_by_user_ids(conn, list(user_ids), since_time, [])

        if db_rows:
            # Score db_rows via BM25 + embedding
            phase1_results, excluded_ids = _score_memory_rows(
                db_rows, user_query
            )

    # ── Phase 2: Supplemental (if needed) ──
    remaining = limit - len(phase1_results)
    if remaining > 0:
        conn = _store._get_db()
        db_rows = _db.query_all_except(conn, list(excluded_ids), limit=remaining * 3)
        if db_rows:
            phase2_results, _ = _score_memory_rows(db_rows, user_query)
            # Merge, keeping phase1 results first
            for idx, score in phase2_results.items():
                if idx not in phase1_results:
                    phase1_results[idx] = score

    # ── Final ranking ──
    if not phase1_results:
        return []

    sorted_results = sorted(phase1_results.items(), key=lambda x: x[1], reverse=True)
    sorted_results = sorted_results[:limit]

    return [
        (_store.all_mem_list[idx]["content"], _store.all_mem_list[idx]["time"])
        for idx, _ in sorted_results
    ]


def _score_memory_rows(
    db_rows: list[dict], user_query: str
) -> tuple[dict[int, float], set[int]]:
    """Score db rows via hybrid BM25+embedding against user_query.

    Returns (scored_indices: dict[index → score], excluded_indices: set[index]).
    Indices are into _store.all_mem_list.
    """
    global bm25, embedding_vectors

    # Build an index map from all_mem_list content → position
    # (db rows may not be contiguous in all_mem_list)
    content_to_idx: dict[str, int] = {}
    for i, mem in enumerate(_store.all_mem_list):
        content_to_idx[mem["content"]] = i

    row_indices: dict[int, dict] = {}  # idx_in_all_mem_list → row dict
    for row in db_rows:
        idx = content_to_idx.get(row["content"])
        if idx is not None:
            row_indices[idx] = row

    results: dict[int, float] = {}
    excluded: set[int] = set(idx for idx in row_indices)

    # BM25 keyword matching
    if _store.tokenized_corpus and bm25 is not None:
        query_tokens_pos = _tokenizer.tokenize_with_pos(user_query)
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
```

Add the import at top of retrieval.py:
```python
from . import db as _db
```

- [ ] **Step 2: Update test_memory_utils.py for new query_mems signature**

The existing `test_query_mems_prioritizes_sender_related_memories_up_to_thirty_percent` uses `preferred_user_id`. Update it to use `user_ids`:

```python
def test_query_mems_prioritizes_user_specific_within_six_hours(tmp_path: Path):
    embedding_model = EmbeddingModelStub({"query": [1.0, 0.0]})
    _tok, store, retrieval, cfg, _ = load_memory_modules(tmp_path, embedding_model)

    cfg.MAX_MEMORY_LIMIT = 10
    cfg.SCORE_THRESHOLD = 0
    retrieval.embedding_model = embedding_model
    retrieval.set_embedding_vectors(None)
    store.bm25_dirty = False
    _tok.tokenize_with_pos = lambda text: [(text, "n")]

    # Stub bm25
    retrieval.bm25 = types.SimpleNamespace(
        get_scores=lambda _query_tokens: np.array(
            [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55]
        )
    )
    store.tokenized_corpus.clear()
    store.tokenized_corpus.extend([["query"]] * 10)
    store.all_mem_list.clear()
    store.all_mem_list.extend(
        [{"content": f"memory-{idx}", "time": idx, "people": []} for idx in range(7)]
        + [
            {"content": "memory-7", "time": int(time.time()), "people": [{"user_id": 42, "user_name": "目标"}]},
            {"content": "memory-8", "time": int(time.time()), "people": [{"user_id": 42, "user_name": "目标"}]},
            {"content": "memory-9", "time": int(time.time()), "people": [{"user_id": 42, "user_name": "目标"}]},
        ]
    )

    # Stub _get_db to return an in-memory DB with matching rows
    import sqlite3 as _sqlite3
    _conn = _sqlite3.connect(":memory:")
    _db_mod = sys.modules["hatsume.plugins.hatsume-plugin.memory.db"]
    _db_mod.init_db(_conn)
    now = int(time.time())
    for i in range(7, 10):
        _db_mod.insert_memory(_conn, f"memory-{i}", now, store.all_mem_list[i]["people"], store.tokenized_corpus[i], None)
    store._get_db = lambda: _conn

    memories = retrieval.query_mems("query", user_ids=[42])

    # User-specific results (memories 7-9) should come first
    user_results = [m for m in memories if m[0] in ("memory-7", "memory-8", "memory-9")]
    assert len(user_results) == 3
```

- [ ] **Step 3: Run retrieval tests**

```bash
python -m pytest tests/test_memory_utils.py -xvs -k "query_mems"
```

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/memory/retrieval.py tests/test_memory_utils.py
git commit -m "feat: two-phase memory retrieval with 6h user window

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Update prompts.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py`

**Interfaces:**
- Adds: `# 记忆记录` section to `role_sys_prompt`
- Removes: `MEMORY_RECORDING_PROMPT`

- [ ] **Step 1: Add memory recording instruction to role_sys_prompt**

In `role_sys_prompt`, after the existing `# 记忆` section (around line 91-92), add:

```python
# 记忆记录
当对话中出现值得长期记住的重要事件时（用户兴趣爱好、性格特点、重要经历、
观点偏好、人际关系、关键事件、用户明确要求记住的内容），在回复的最后添加：

[memoryrecord: {"content": "简要描述（50字内），用户名用引号包围", "people": [{"user_id": QQ号, "user_name": "昵称"}]}]

可以记录多条，每条一个 [memoryrecord: ...]。
不记录问候告别、无实质闲聊、日常寒暄。
历史聊天记录中的事件也可以记录。
```

- [ ] **Step 2: Remove MEMORY_RECORDING_PROMPT**

Delete lines 231-240:
```python
# REMOVE this entire block:
MEMORY_RECORDING_PROMPT = (
    "你是机器人的长期记忆记录器。从对话中提取有价值的用户信息。\n\n"
    "规则：\n"
    "1. 使用 `write_memory` 工具记录，每条必须提供 `content` 与 `source_ids`。\n"
    "2. `source_ids` 只填对话中方括号里的消息编号（如 m3、m8），来源多条则列出多个。\n"
    "3. 只记录：用户兴趣爱好、性格特点、重要经历、观点偏好、人际关系、关键事件、"
    "用户明确要求记住的内容。\n"
    "4. 不记录：问候告别、无实质闲聊、日常寒暄、临时话题。\n"
    "5. 无值得记忆的内容则不调用任何工具。"
)
```

- [ ] **Step 3: Update test mocks**

In `tests/test_graph_nodes.py`, remove the `MEMORY_RECORDING_PROMPT` mock (line 247):
```python
# REMOVE this line:
prompts_pkg.MEMORY_RECORDING_PROMPT = "Record the following memory."
```

- [ ] **Step 4: Run graph node tests to verify no breakage**

```bash
python -m pytest tests/test_graph_nodes.py -xvs -k "not recording"
```

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py tests/test_graph_nodes.py
git commit -m "feat: add inline memory recording prompt, remove MEMORY_RECORDING_PROMPT

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Update tools.py — Remove write_memory, Update query_memory

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

**Interfaces:**
- Consumes: `query_mems()` with new `user_ids` parameter
- Removes: `write_memory` tool (entire function)
- Updates: `query_memory()` to accept and pass `user_ids`

- [ ] **Step 1: Remove write_memory tool**

Delete lines 169-210:
```python
# REMOVE:
@tool(return_direct=True)
async def write_memory(values: list[dict[str, Any]]) -> None:
    ...
    (entire function body)
```

Also remove the import at top (line 23):
```python
# REMOVE:
from ..memory.store import get_mem_list, add_mem, resolve_active_memory_people
```
Replace with:
```python
from ..memory.store import get_mem_list, add_mem
```

- [ ] **Step 2: Update query_memory() signature**

Change `query_memory()` to accept `user_ids`:
```python
def query_memory(query: str, user_ids: list[int] | None = None, max_results: int | None = None) -> str:
    """Shared memory query logic."""
    from datetime import datetime

    all_mem_keys = get_mem_list()
    memory_summary = ""

    if len(all_mem_keys) > 0:
        results = query_mems(
            str(query), user_ids=user_ids, max_limit=max_results
        )
        results = [(c, t) for c, t in results if c not in _retrieved_mem_keys]
        _retrieved_mem_keys.update(c for c, _ in results)

        if len(results) > 0:
            formatted = []
            for content, ts in results:
                dt = datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M:%S")
                formatted.append(f"- ({dt}) {content}")
            memory_summary = "\n".join(formatted)

    if memory_summary != "":
        print("Memory search results: \n" + memory_summary)

    return memory_summary
```

- [ ] **Step 3: Remove write_memory from tools.py imports in ai.py**

No change needed yet — this will be done in Task 7.

- [ ] **Step 4: Run tool tests**

```bash
python -m pytest tests/test_tools.py -xvs
```
Expected: tests that reference `write_memory` fail. Update those tests.

Update `tests/test_tools.py` — find and remove any `write_memory` references in the mock setup and tests. Search for `write_memory` in the test file and remove those lines.

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py tests/test_tools.py
git commit -m "refactor: remove write_memory tool, update query_memory signature

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Refactor ai_node — Inline Memory Recording

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Consumes: `add_mem()` from store, prompts changes from Task 5
- Produces: `MEMORY_RECORD_PATTERN` regex, `extract_user_ids()`
- Removes: `_memory_record_transcript`, `_memory_record_source_map`, `append_memory_record_sources()`, `reset_memory_record_context()`

- [ ] **Step 1: Add memory recording regex and extractor**

Add after the existing `FACE_TAG_PATTERN` (line 57):
```python
MEMORY_RECORD_PATTERN = re.compile(r"\[memoryrecord:\s*(\{.*?\})\]")
```

Add user ID extraction function:
```python
def extract_user_ids_from_content(content: Any) -> list[int]:
    """Extract user IDs from message content structure.
    
    Handles both string content and list-of-dict content formats.
    Looks for user.id fields in the message JSON structure.
    """
    user_ids: list[int] = []
    seen: set[int] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "user" in obj and isinstance(obj["user"], dict):
                uid = obj["user"].get("id")
                if uid is not None:
                    try:
                        uid_int = int(uid)
                        if uid_int not in seen and uid_int != 0:
                            seen.add(uid_int)
                            user_ids.append(uid_int)
                    except (TypeError, ValueError):
                        pass
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(content)
    return user_ids
```

- [ ] **Step 2: Update ai_node to parse memory records and extract user IDs**

In `ai_node()`, after the face tag extraction block (after line 488, the `if match:` block for face_emotion):

```python
    # ── Extract memory records from ai_text ──
    mem_records: list[dict] = []
    for mem_match in MEMORY_RECORD_PATTERN.finditer(ai_text):
        try:
            record = json.loads(mem_match.group(1))
            if "content" in record and str(record.get("content", "")).strip():
                mem_records.append(record)
        except json.JSONDecodeError:
            pass

    # Strip memoryrecord tags from visible output
    ai_text_clean = MEMORY_RECORD_PATTERN.sub("", ai_text_clean).strip()
```

Add `import json` to imports if not already present.

Update the memory retrieval section (lines 344-367) to use user_ids:
```python
    _MEMORY_TOTAL_LIMIT = 50  # was 15, now matches MAX_MEMORY_LIMIT
    chatting_user_ids = extract_user_ids_from_content(last_content)

    last_content = state["messages"][-1].content
    if isinstance(last_content, list) and len(last_content) > 0:
        text_parts: list[str] = []
        for part in last_content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = str(part.get("text", "")).strip()
                if t:
                    text_parts.append(t)
            elif isinstance(part, str) and part.strip():
                text_parts.append(part.strip())
        if text_parts:
            per_item = _MEMORY_TOTAL_LIMIT // len(text_parts)
            mem_parts: list[str] = []
            for text in reversed(text_parts):
                mem = query_memory(text, user_ids=chatting_user_ids, max_results=per_item)
                if mem:
                    mem_parts.append(mem)
            memory_summary = "\n".join(mem_parts)
        else:
            memory_summary = ""
    else:
        memory_summary = query_memory(str(last_content), user_ids=chatting_user_ids)
```

- [ ] **Step 3: Add memory saving after sending reply**

After the `await _ai_answer(ai_msg)` block (line 504), add:
```python
    # ── Save parsed memory records ──
    for record in mem_records:
        content = str(record.get("content", "")).strip()
        people = record.get("people", [])
        if content:
            add_mem(content, people=people)
```

Add `add_mem` to imports from memory.store:
```python
from ...memory.store import add_mem
```
(Remove the old `add_mem` import from `...memory.store` if it exists — actually, check existing imports. Currently ai.py doesn't import from memory.store directly. Add the import.)

- [ ] **Step 4: Remove recording transcript variables and functions**

Remove these module-level variables:
```python
# REMOVE:
_memory_record_transcript: list[dict] = []
_memory_record_source_map: dict[str, list[dict]] = {}
```

Remove these functions:
```python
# REMOVE:
def reset_memory_record_context() -> None:
    ...

def append_memory_record_sources(source_entries: list[dict] | None) -> None:
    ...
```

Remove the `append_memory_record_sources(aux_sources)` call in the aux queue section (line 434).

Remove the `_memory_record_transcript.append(...)` calls (lines 506-512):
```python
# REMOVE:
_memory_record_transcript.append({"type": "text", "text": "你: " + ai_text})

from ..tools import _last_capture_html_demand, _capture_html_shot_used
if _capture_html_shot_used and _last_capture_html_demand:
    _memory_record_transcript.append(
        {"type": "text", "text": "你发送了一张关于以下内容的富文本渲染图片:\n" + _last_capture_html_demand}
    )
```

- [ ] **Step 5: Run graph node tests**

```bash
python -m pytest tests/test_graph_nodes.py -xvs
```
Expected: some tests fail due to removed variables. Update affected tests.

Update `test_capture_html_transcript_recorded_in_ai_node` — this test checks `_memory_record_transcript` which no longer exists. Remove this test (HTML capture transcript is no longer needed since memory recording is inline).

Remove:
```python
# DELETE:
def test_capture_html_transcript_recorded_in_ai_node():
    ...
```

Update the `_load_nodes_module` helper in test_graph_nodes.py — add stubs for new functions:
```python
# Add to the mock setup:
nodes._ai.query_memory = lambda text, user_ids=None, max_results=None: ""
nodes.extract_user_ids_from_content = lambda content: []
nodes.MEMORY_RECORD_PATTERN = __import__("re").compile(r"\[memoryrecord:\s*(\{.*?\})\]")
```

- [ ] **Step 6: Run all tests to verify**

```bash
python -m pytest tests/test_graph_nodes.py -xvs
```
Expected: all remaining tests PASS

- [ ] **Step 7: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py tests/test_graph_nodes.py
git commit -m "feat: parse [memoryrecord:...] tags inline, remove recording transcript

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Simplify finish.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py`

**Interfaces:**
- Consumes: none (all memory recording logic removed)
- Produces: simplified `finish_conversation_node()`

- [ ] **Step 1: Rewrite finish_conversation_node**

Replace the entire function:
```python
"""Finish node: clean up after conversation ends."""

from __future__ import annotations

from langgraph.graph import MessagesState

from ...skills import get_skill_manager
from .ai import (
    _set_graph_running,
    _clear_human_queue,
    _clear_auxiliary_archive,
    _retrieved_mem_keys,
    _get_ai_answer,
    _set_current_query_user_id,
)


async def finish_conversation_node(state: MessagesState) -> dict:
    print("Enter finish_conversation_node")

    _set_graph_running(False)
    _clear_human_queue()
    _clear_auxiliary_archive()
    _retrieved_mem_keys.clear()

    from ...infra import cleanup_persistent_container
    # cleanup_persistent_container()

    # Reset skill dedup for next conversation
    get_skill_manager().reset_conversation()

    _ai_answer = _get_ai_answer()
    if _ai_answer:
        await _ai_answer("[CONVERSATION END]")

    _set_current_query_user_id(None)

    print("⚒️ Conversation end.")
    return {}
```

- [ ] **Step 2: Update test_graph_nodes.py finish tests**

Update `test_finish_conversation_node_calls_cleanup_persistent_container`:
```python
def test_finish_conversation_node_calls_cleanup_persistent_container():
    """Verify finish_conversation_node runs without error after memory refactor."""
    nodes = _load_nodes_module()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    messages = [
        MockMessage("hello", "human"),
        MockMessage("hi", "ai"),
    ]

    # No mem_record_agent to stub — should just run cleanly
    asyncio.run(nodes.finish_conversation_node({"messages": messages}))
    assert mock_state.is_graph_running is False
```

Update `test_finish_conversation_node_clears_auxiliary_archive`:
```python
def test_finish_conversation_node_clears_auxiliary_archive():
    """finish_conversation_node must clear the archived auxiliary_queue on
    ConversationState so it doesn't accumulate across conversations."""
    nodes = _load_nodes_module()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[{"type": "text", "text": "leftover aux"}],
        auxiliary_source_queue=[{"source_id": "s1", "text": "t", "people": []}],
    )
    nodes.bind_state(mock_state)

    messages = [
        MockMessage("hello", "human"),
        MockMessage("hi", "ai"),
    ]

    # No mem_record_agent stubbing needed
    asyncio.run(nodes.finish_conversation_node({"messages": messages}))
    assert mock_state.auxiliary_queue == []
    assert mock_state.auxiliary_source_queue == []
```

- [ ] **Step 3: Run finish tests**

```bash
python -m pytest tests/test_graph_nodes.py -xvs -k "finish"
```
Expected: both finish tests PASS

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/finish.py tests/test_graph_nodes.py
git commit -m "refactor: simplify finish node, remove separate mem_record_agent

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Integration & Cleanup

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py` (call `init_memory_system()`)
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py` (clean up imports)
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` (clean up imports)

**Interfaces:**
- Produces: `init_memory_system()` called on plugin startup
- Removes: All stale import references

- [ ] **Step 1: Update memory/__init__.py**

```python
"""Memory package: storage (SQLite), retrieval, and tokenization."""

from .store import (
    get_mem_list,
    add_mem,
    init_tokenized_corpus,
    init_memory_system,
    normalize_people,
    normalize_memory_object,
    memory_has_user,
)
from .retrieval import query_mems, ensure_embedding_model, rebuild_bm25, rebuild_embedding_vectors
from .tokenizer import tokenize_with_pos
```

- [ ] **Step 2: Call init_memory_system() on plugin startup**

In `hatsume/plugins/hatsume-plugin/__init__.py`, add:
```python
from .memory.store import init_memory_system

# Call during plugin init
init_memory_system()
```

Find the appropriate place in `__init__.py` to add this — after imports, before matcher registration.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -xvs --ignore=tests/test_agent_allocate.py --ignore=tests/test_agent_monitor.py --ignore=tests/test_background_shell_agent.py --ignore=tests/test_background_shell_infra.py --ignore=tests/test_background_shell_prompts.py --ignore=tests/test_background_shell_stdin.py --ignore=tests/test_background_shell_stdin_integration.py --ignore=tests/test_container_lifecycle.py --ignore=tests/test_deepseek_provider.py --ignore=tests/test_models_mimo.py --ignore=tests/test_reasoning_content.py --ignore=tests/test_omni_model.py
```

Expected: all tested modules PASS

- [ ] **Step 4: Fix any remaining issues**

Check for any remaining references to removed functions:
```bash
grep -r "write_memory\|MEMORY_RECORDING_PROMPT\|save_mem_list\|active_memory_sources\|_memory_record_transcript\|resolve_active_memory_people\|MEMORY_TOP_K" hatsume/ --include="*.py" | grep -v __pycache__ | grep -v ".bak"
```

If any references found (outside of migration code), fix them.

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/memory/__init__.py hatsume/plugins/hatsume-plugin/__init__.py
git commit -m "feat: add init_memory_system startup hook, update memory exports

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 6: Final test run**

```bash
python -m pytest tests/test_memory_utils.py tests/test_memory_db.py tests/test_graph_nodes.py tests/test_tools.py -xvs
```
Expected: ALL tests PASS
