"""Tests for memory/engine.py — SQLite storage layer."""
from __future__ import annotations

import json
import sqlite3
import sys
import types
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]


def _load_db_module():
    """Load the db module with stubbed package hierarchy."""
    base = ROOT / "hatsume/plugins/hatsume-plugin"
    # Clean up — include external packages that may have stale stubs from other tests
    for pfx in ("hatsume", "hatsume.plugins", "hatsume.plugins.hatsume-plugin",
                "hatsume.plugins.hatsume-plugin.memory",
                "hatsume.plugins.hatsume-plugin.config",
                "nonebot", "nonebot_plugin", "apscheduler", "rank_bm25"):
        for name in list(sys.modules):
            if name == pfx or name.startswith(pfx + ".") or name.startswith(pfx + "_"):
                del sys.modules[name]
    # Build package hierarchy
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

    # Stub tokenizer (imported by engine.py)
    tokenizer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.tokenizer")
    tokenizer_mod.tokenize_with_pos = lambda text: [(w, "n") for w in text if len(w.strip()) > 1]
    sys.modules["hatsume.plugins.hatsume-plugin.memory.tokenizer"] = tokenizer_mod

    # Stub nonebot and its plugins (imported by engine.py)
    nonebot_mod = types.ModuleType("nonebot")
    apscheduler_mod = types.ModuleType("nonebot_plugin_apscheduler")
    apscheduler_mod.scheduler = MagicMock()
    nonebot_mod.require = lambda name: apscheduler_mod if name == "nonebot_plugin_apscheduler" else MagicMock()
    sys.modules["nonebot"] = nonebot_mod

    store_mod = types.ModuleType("nonebot_plugin_localstore")
    store_mod.get_data_file = MagicMock(return_value=Path("/tmp/test_memory.db"))
    sys.modules["nonebot_plugin_localstore"] = store_mod

    # Provide normalize_memory_object stub (was in store, now merged into engine)
    store_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.engine")

    def normalize_memory_object(obj):
        if not isinstance(obj, dict):
            return None, True
        content = obj.get("content", "")
        if not isinstance(content, str) or content.strip() == "":
            return None, True
        try:
            t = int(obj.get("time"))
        except (TypeError, ValueError):
            return None, True
        return {"content": content, "time": t, "people": obj.get("people", [])}, obj.get("people") is None

    store_mod.normalize_memory_object = normalize_memory_object
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = store_mod

    import importlib.util
    db_path = base / "memory" / "engine.py"
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.memory.engine", db_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_init_db_creates_tables():
    """init_db creates the memories table with correct schema."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
    assert cursor.fetchone() is not None
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    assert cols >= {"id", "content", "time", "people", "tokens", "embedding", "created_at"}


def test_insert_memory_persists_metadata_without_sqlite_embedding():
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    now = int(time.time())
    people = [{"user_id": 123, "user_name": "测试用户"}]
    tokens = [("测试", "n"), ("用户", "n")]
    row_id = db.insert_memory(conn, "测试用户喜欢芒果", now, people, tokens)
    assert row_id == 1
    row = conn.execute(
        "SELECT content, time, people, tokens, embedding FROM memories WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "测试用户喜欢芒果"
    assert row[1] == now
    assert json.loads(row[2]) == people
    assert json.loads(row[3]) == [["测试", "n"], ["用户", "n"]]
    assert row[4] is None


def test_get_recent_user_memories_queries_sqlite_newest_first():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    memory.insert_memory(conn, "old", 1, [{"user_id": 7, "user_name": "A"}], [])
    memory.insert_memory(conn, "other", 3, [{"user_id": 8, "user_name": "B"}], [])
    memory.insert_memory(conn, "new", 2, [{"user_id": 7, "user_name": "A"}], [])
    memory._get_db = lambda: conn

    result = memory.get_recent_user_memories(7, limit=100)

    assert [item["content"] for item in result] == ["new", "old"]


def test_delete_expired_memories():
    """delete_expired_memories removes rows older than retention_seconds."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    old_time = int(time.time()) - 100000
    db.insert_memory(conn, "old", old_time, [], [])
    db.insert_memory(conn, "new", int(time.time()), [], [])
    deleted = db.delete_expired_memories(conn, retention_seconds=50000)
    assert deleted == 1
    rows = conn.execute("SELECT content FROM memories ORDER BY id").fetchall()
    assert rows == [("new",)]


def test_query_by_user_ids_with_time_window():
    """query_by_user_ids filters by user_ids and optional since_time."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    now = int(time.time())
    db.insert_memory(conn, "mem-a", now - 10000, [{"user_id": 1, "user_name": "A"}], [])
    db.insert_memory(conn, "mem-b", now - 1000, [{"user_id": 2, "user_name": "B"}], [])
    db.insert_memory(conn, "mem-c", now - 100, [{"user_id": 1, "user_name": "A"}], [])
    results = db.query_by_user_ids(conn, [1], since_time=now - 3600, exclude_ids=[])
    assert len(results) == 1
    assert results[0]["content"] == "mem-c"
    results = db.query_by_user_ids(conn, [1], since_time=None, exclude_ids=[])
    assert len(results) == 2
    results = db.query_by_user_ids(conn, [1], since_time=None, exclude_ids=[1])
    assert len(results) == 1


def test_query_all_except():
    """query_all_except returns rows not in exclude_ids, limited."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    ids = []
    for i in range(10):
        rid = db.insert_memory(conn, f"mem-{i}", int(time.time()), [], [])
        ids.append(rid)
    results = db.query_all_except(conn, exclude_ids=ids[:3], limit=5)
    assert len(results) == 5
    for r in results:
        assert r["id"] not in ids[:3]


def test_eligible_exact_keywords_apply_weighted_length_and_deduplicate():
    memory = _load_db_module()

    result = memory._eligible_exact_keywords(
        "苹果手机 abcde ABCDE 123 你好 ab_cd 中文ab"
    )

    assert [(item.value, item.numeric_user_id) for item in result] == [
        ("苹果手机", False),
        ("abcde", False),
        ("123", True),
        ("中文ab", False),
    ]


def test_query_exact_memories_matches_content_raw_people_and_exact_user_id():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    first_id = memory.insert_memory(
        conn,
        "Alice 使用苹果手机",
        10,
        [{"user_id": 123, "user_name": "小明同学"}],
        [],
    )
    second_id = memory.insert_memory(
        conn,
        "只提到苹果手机",
        20,
        [{"user_id": 1234, "user_name": "其他成员"}],
        [],
    )
    third_id = memory.insert_memory(
        conn,
        "abcde",
        30,
        [{"user_id": 99, "user_name": "小明同学"}],
        [],
    )

    results = memory.query_exact_memories(conn, "苹果手机 小明同学 123")

    assert [(row["id"], row["keyword_hits"]) for row in results] == [
        (first_id, 3),
        (third_id, 1),
        (second_id, 1),
    ]
    retrieval_sql = "\n".join(statements).casefold()
    assert "json_each" not in retrieval_sql
    assert "json_extract" not in retrieval_sql


def test_query_exact_memories_escapes_like_metacharacters():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    expected_id = memory.insert_memory(
        conn,
        r"literal 100%_done\path",
        1,
        [],
        [],
    )
    memory.insert_memory(conn, "literal 100XdoneXpath", 2, [], [])

    results = memory.query_exact_memories(conn, r"100%_done\path")

    assert [row["id"] for row in results] == [expected_id]


def test_query_exact_memories_does_not_apply_result_limit():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    for index in range(55):
        memory.insert_memory(conn, f"共同关键词-{index}", index, [], [])

    results = memory.query_exact_memories(conn, "共同关键词")

    assert len(results) == 55
    assert [row["time"] for row in results[:2]] == [54, 53]


class _QueryEmbeddingStub:
    def __init__(self, vector: list[float]):
        self.vector = vector
        self.queries: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return self.vector


class _VectorSearchStub:
    def __init__(self, results: list[tuple[int, float]]):
        self.results = results
        self.search_limits: list[int] = []
        self.close_calls = 0

    def search(self, _vector, *, limit: int):
        self.search_limits.append(limit)
        return [
            SimpleNamespace(memory_id=memory_id, score=score)
            for memory_id, score in self.results[:limit]
        ]

    def close(self):
        self.close_calls += 1


class _VectorWriteStub:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.rows: list[tuple[int, list[float]]] = []
        self.close_calls = 0

    def upsert(self, rows):
        materialized = list(rows)
        if self.fail:
            raise RuntimeError("milvus unavailable")
        self.rows.extend(materialized)

    def close(self):
        self.close_calls += 1


class _DocumentEmbeddingStub:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_query_mems_keeps_exact_matches_then_supplements_from_milvus():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    exact_id = memory.insert_memory(conn, "正在使用苹果手机", 10, [], [])
    vector_id = memory.insert_memory(conn, "完全不同的往事", 20, [], [])
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    embedding = _QueryEmbeddingStub([1.0, 0.0, 0.0])
    vectors = _VectorSearchStub([(vector_id, 0.9), (exact_id, 0.8)])
    memory._get_db = lambda: conn
    memory.ensure_embedding_model = lambda: embedding
    memory._get_vector_store = lambda: vectors
    memory.tokenize_with_pos = lambda text: [(word, "n") for word in text.split()]

    results = memory.query_mems("苹果手机", max_limit=3)

    assert results == [("正在使用苹果手机", 10), ("完全不同的往事", 20)]
    assert vectors.search_limits == [6]
    assert vectors.close_calls == 1
    select_sql = "\n".join(
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ).casefold()
    assert "embedding" not in select_sql


def test_query_mems_returns_all_exact_matches_and_skips_supplements_at_limit():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    for index in range(4):
        memory.insert_memory(conn, f"共同关键词-{index}", index, [], [])
    vectors = _VectorSearchStub([])
    memory._get_db = lambda: conn
    memory._get_vector_store = lambda: vectors

    results = memory.query_mems("共同关键词", max_limit=2)

    assert len(results) == 4
    assert vectors.search_limits == []


def test_query_mems_builds_bm25_only_from_bounded_sqlite_candidates():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    memory.insert_memory(conn, "cat target", 10, [], [])
    memory.insert_memory(conn, "unrelated words", 20, [], [])
    memory.insert_memory(conn, "another memory", 30, [], [])
    vectors = _VectorSearchStub([])
    memory._get_db = lambda: conn
    memory._get_vector_store = lambda: vectors
    memory.ensure_embedding_model = lambda: _QueryEmbeddingStub([1.0, 0.0, 0.0])
    memory.tokenize_with_pos = lambda text: [(word, "n") for word in text.split()]

    results = memory.query_mems("cat", max_limit=2)

    assert results[0] == ("cat target", 10)
    assert len(results) <= 2
    assert vectors.search_limits == [6]


def test_add_mem_writes_sqlite_first_and_vector_to_milvus():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    vectors = _VectorWriteStub()
    memory._get_db = lambda: conn
    memory._get_vector_store = lambda: vectors
    memory.ensure_embedding_model = lambda: _DocumentEmbeddingStub()
    memory.tokenize_with_pos = lambda _text: [("苹果", "n")]

    memory.add_mem(
        "喜欢苹果",
        people=[{"user_id": 7, "user_name": "小明"}],
    )

    row = conn.execute(
        "SELECT id, content, people, tokens, embedding FROM memories"
    ).fetchone()
    assert row is not None
    assert row[1] == "喜欢苹果"
    assert json.loads(row[2]) == [{"user_id": 7, "user_name": "小明"}]
    assert json.loads(row[3]) == [["苹果", "n"]]
    assert row[4] is None
    assert vectors.rows == [(row[0], [1.0, 0.0, 0.0])]
    assert vectors.close_calls == 1


def test_add_mem_keeps_sqlite_row_when_milvus_write_fails():
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    memory._get_db = lambda: conn
    memory._get_vector_store = lambda: _VectorWriteStub(fail=True)
    memory.ensure_embedding_model = lambda: _DocumentEmbeddingStub()

    memory.add_mem("仍然保留")

    assert conn.execute("SELECT content, embedding FROM memories").fetchall() == [
        ("仍然保留", None)
    ]


def test_init_memory_system_does_not_load_full_memory_table(tmp_path: Path):
    memory = _load_db_module()
    conn = memory.init_db(sqlite3.connect(":memory:"))
    memory.insert_memory(conn, "existing", 1, [], [])
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    vectors = _VectorWriteStub()
    memory._get_db = lambda: conn
    memory._get_vector_store = lambda: vectors
    memory.store.get_plugin_data_file = lambda name: tmp_path / name

    memory.init_memory_system()

    selects = [
        statement.casefold()
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]
    assert selects == ["select count(*) from memories"]
    assert vectors.close_calls == 1


def test_engine_exposes_no_full_memory_loader_or_resident_indexes():
    memory = _load_db_module()

    for name in (
        "load_all_memories",
        "all_mem_list",
        "tokenized_corpus",
        "tokenized_corpus_pos",
        "embedding_vectors",
        "bm25_dirty",
    ):
        assert not hasattr(memory, name)


def test_migrate_from_json():
    """migrate_from_json reads memory.json-style data and inserts into SQLite."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
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
    class StubVectors:
        def __init__(self):
            self.rows = []
            self.close_calls = 0
        def upsert(self, rows):
            self.rows.extend(rows)
        def close(self):
            self.close_calls += 1
    vectors = StubVectors()
    db._get_vector_store = lambda: vectors
    try:
        count = db.migrate_from_json(conn, json_path, StubEmbedder())
        assert count == 2
        rows = conn.execute(
            "SELECT id, content, embedding FROM memories ORDER BY id"
        ).fetchall()
        assert rows == [(1, "old-mem-1", None), (2, "old-mem-2", None)]
        assert vectors.rows == [(1, [1.0, 1.0, 1.0]), (2, [1.0, 1.0, 1.0])]
        assert vectors.close_calls == 1
    finally:
        Path(json_path).unlink(missing_ok=True)


def test_migration_empty_json():
    """migrate_from_json handles empty JSON array."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write("[]")
        json_path = f.name
    try:
        count = db.migrate_from_json(conn, json_path, None)
        assert count == 0
    finally:
        Path(json_path).unlink(missing_ok=True)
