"""Tests for memory/engine.py — SQLite storage layer."""
from __future__ import annotations

import json
import sqlite3
import sys
import types
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_db_module():
    """Load the db module with stubbed package hierarchy."""
    base = ROOT / "hatsume/plugins/hatsume-plugin"
    # Clean up — include external packages that may have stale stubs from other tests
    for pfx in ("hatsume", "hatsume.plugins", "hatsume.plugins.hatsume-plugin",
                "hatsume.plugins.hatsume-plugin.memory",
                "hatsume.plugins.hatsume-plugin.config",
                "nonebot", "nonebot_plugin", "apscheduler"):
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


def test_insert_and_load_roundtrip():
    """Insert a memory, then load_all — data survives roundtrip."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
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
    conn = db.init_db(conn)
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
    conn = db.init_db(conn)
    now = int(time.time())
    db.insert_memory(conn, "mem-a", now - 10000, [{"user_id": 1, "user_name": "A"}], [], None)
    db.insert_memory(conn, "mem-b", now - 1000, [{"user_id": 2, "user_name": "B"}], [], None)
    db.insert_memory(conn, "mem-c", now - 100, [{"user_id": 1, "user_name": "A"}], [], None)
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
        rid = db.insert_memory(conn, f"mem-{i}", int(time.time()), [], [], None)
        ids.append(rid)
    results = db.query_all_except(conn, exclude_ids=ids[:3], limit=5)
    assert len(results) == 5
    for r in results:
        assert r["id"] not in ids[:3]


def test_load_all_returns_none_embedding_when_empty():
    """load_all_memories returns None embedding_vectors for empty DB."""
    db = _load_db_module()
    conn = sqlite3.connect(":memory:")
    conn = db.init_db(conn)
    mem_list, tok_corpus, tok_corpus_pos, emb_vectors = db.load_all_memories(conn)
    assert mem_list == []
    assert emb_vectors is None


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
    try:
        count = db.migrate_from_json(conn, json_path, StubEmbedder())
        assert count == 2
        mem_list, tok_corpus, _, emb_vectors = db.load_all_memories(conn)
        assert len(mem_list) == 2
        assert len(tok_corpus) == 2
        assert emb_vectors.shape == (2, 3)
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
