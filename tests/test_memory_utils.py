from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "hatsume/plugins/hatsume-plugin/memory/engine.py"
RETRIEVAL_PATH = ROOT / "hatsume/plugins/hatsume-plugin/memory/engine.py"
TOKENIZER_PATH = ROOT / "hatsume/plugins/hatsume-plugin/memory/tokenizer.py"


class SchedulerStub:
    def scheduled_job(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


class EmbeddingModelStub:
    def __init__(self, vectors_by_text: dict[str, list[float]]):
        self.vectors_by_text = vectors_by_text
        self.document_calls: list[str] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.extend(texts)
        return [self.vectors_by_text[text] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self.vectors_by_text[text]


class StoreStub:
    def __init__(self, file_path: Path):
        self.file_path = file_path

    def get_plugin_data_file(self, name: str) -> Path:
        return self.file_path


class CronTriggerStub:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def load_memory_modules(
    tmp_path: Path, embedding_model: EmbeddingModelStub
) -> tuple[types.ModuleType, types.ModuleType, types.ModuleType, types.ModuleType, Path]:
    """Load tokenizer, store, and retrieval modules with stubbed externals.

    Returns (tokenizer, store, retrieval, config, memory_file_path).
    """
    # Clean up any previously loaded modules
    pkg_prefixes = [
        "hatsume",
        "hatsume.plugins",
        "hatsume.plugins.hatsume_plugin",
        "hatsume.plugins.hatsume-plugin",
        "hatsume.plugins.hatsume-plugin.memory",
    ]
    for name in list(sys.modules):
        if any(name.startswith(p) for p in pkg_prefixes) or name in (
            "nonebot",
            "nonebot_plugin_localstore",
            "apscheduler",
            "apscheduler.triggers",
            "apscheduler.triggers.cron",
            "rank_bm25",
        ):
            del sys.modules[name]

    # ------------------------------------------------------------------
    # Build package hierarchy so relative imports work
    # ------------------------------------------------------------------
    base = ROOT / "hatsume/plugins/hatsume-plugin"

    hatsume_pkg = types.ModuleType("hatsume")
    hatsume_pkg.__path__ = [str(ROOT / "hatsume")]
    sys.modules["hatsume"] = hatsume_pkg

    plugins_pkg = types.ModuleType("hatsume.plugins")
    plugins_pkg.__path__ = [str(ROOT / "hatsume/plugins")]
    sys.modules["hatsume.plugins"] = plugins_pkg

    plugin_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin")
    plugin_pkg.__path__ = [str(base)]
    sys.modules["hatsume.plugins.hatsume-plugin"] = plugin_pkg

    memory_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.memory")
    memory_pkg.__path__ = [str(base / "memory")]
    sys.modules["hatsume.plugins.hatsume-plugin.memory"] = memory_pkg

    # ------------------------------------------------------------------
    # Stub external dependencies
    # ------------------------------------------------------------------
    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.require = lambda _name: types.SimpleNamespace(scheduler=SchedulerStub())
    sys.modules["nonebot"] = nonebot_mod

    memory_file = tmp_path / "memory.json"
    memory_file.write_text("[]", encoding="utf-8")
    sys.modules["nonebot_plugin_localstore"] = StoreStub(memory_file)

    ap_mod = types.ModuleType("apscheduler")
    ap_triggers = types.ModuleType("apscheduler.triggers")
    ap_cron = types.ModuleType("apscheduler.triggers.cron")
    ap_cron.CronTrigger = CronTriggerStub
    sys.modules["apscheduler"] = ap_mod
    sys.modules["apscheduler.triggers"] = ap_triggers
    sys.modules["apscheduler.triggers.cron"] = ap_cron

    # Stub rank_bm25 (only the class used by retrieval.py)
    rank_bm25_mod = types.ModuleType("rank_bm25")

    class _BM25Stub:
        def __init__(self, corpus, b=0.3):
            self._corpus = corpus

        def get_scores(self, query):
            return np.zeros(len(self._corpus))

    rank_bm25_mod.BM25Okapi = _BM25Stub
    sys.modules["rank_bm25"] = rank_bm25_mod

    # ------------------------------------------------------------------
    # Stub sibling package modules (config, types)
    # ------------------------------------------------------------------
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.MEMORY_EXPIRY_DAYS = 30
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 60
    config_mod.CONTEXT_QUEUE_LEN = 5
    config_mod.IMAGE_MAX_PIXELS = 36_000_000
    config_mod.IMAGE_MAX_SIZE_BYTES = 9 * 1024 * 1024
    config_mod.MESSAGE_MAX_LENGTH = 500
    config_mod.REPLY_MAX_LENGTH = 200
    config_mod.USER_INPUT_CONFIRM_DURING_TIME = 3
    config_mod.ADMIN_QQ_ID = "0"
    config_mod.MAX_MEMORY_LIMIT = 50
    config_mod.SCORE_THRESHOLD = 0.1
    config_mod.EMBEDDING_SIMILARITY_THRESHOLD = 0.6
    config_mod.EMBEDDING_WEIGHT = 0.6
    config_mod.DEEPSEEK_V4_FLASH_FREE = "deepseek-v4-flash-free"
    config_mod.DOUBAO_2_MINI = "doubao-2-mini"
    config_mod.EMBEDDING_MODEL = "BAAI/bge-m3"
    config_mod.KEGEAI_API_KEY = ""
    config_mod.OPENCODE_API_KEY = ""
    config_mod.OPENCODE_ZEN_BASE_URL = ""
    config_mod.SEEDANCE_1_0 = "seedance-1-0"
    config_mod.SEEDANCE_1_5 = "seedance-1-5"
    config_mod.SEEDREAM_5_0_LITE = "seedream-5-0-lite"
    config_mod.VOLCENGINE_BASE_URL = ""
    config_mod.get_api_key = lambda *a, **kw: ""
    config_mod.get_base_url = lambda *a, **kw: ""
    config_mod.KEGEAI_BASE_URL = ""
    config_mod.GROK_IMAGINE_IMAGE = ""
    config_mod.GPT_5_6_LUNA = ""
    config_mod.DOUBAO_2_LITE = ""
    config_mod.GPT_5_4_NANO = ""
    config_mod.BOT_QQ_ID = 0
    config_mod.AUTO_RESPONSE_GROUP_ID = 12345
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    state_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.state")
    state_mod.PersonEntry = dict
    state_mod.MemoryRecord = dict
    state_mod.SourceEntry = dict
    state_mod.TextContent = dict
    state_mod.ImageContent = dict
    state_mod.ContentPart = dict
    sys.modules["hatsume.plugins.hatsume-plugin.state"] = state_mod

    group_runtime_mod = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.group_runtime"
    )

    def _validate_group_id(group_id):
        if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
            raise ValueError("group_id must be a positive integer")
        return group_id

    group_runtime_mod.validate_group_id = _validate_group_id
    group_runtime_mod.get_current_group_id = lambda: 12345
    sys.modules[group_runtime_mod.__name__] = group_runtime_mod

    # ------------------------------------------------------------------
    # Create in-memory SQLite DB for testing
    # ------------------------------------------------------------------
    _test_db_conn = sqlite3.connect(":memory:")
    _test_db_conn.execute("""CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL CHECK(group_id > 0),
        content TEXT NOT NULL, time INTEGER NOT NULL,
        people TEXT NOT NULL DEFAULT '[]', tokens TEXT NOT NULL DEFAULT '[]',
        embedding BLOB, created_at INTEGER NOT NULL DEFAULT 0
    )""")
    _test_db_conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_time ON memories(time)")
    _test_db_conn.commit()

    # Load the real db module
    db_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.memory.engine",
        ROOT / "hatsume/plugins/hatsume-plugin/memory/engine.py"
    )
    db_mod = importlib.util.module_from_spec(db_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = db_mod
    assert db_spec is not None and db_spec.loader is not None
    db_spec.loader.exec_module(db_mod)

    # ------------------------------------------------------------------
    # Load memory modules in dependency order
    # ------------------------------------------------------------------
    def _load(name: str, path: Path) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    tokenizer = _load("hatsume.plugins.hatsume-plugin.memory.tokenizer", TOKENIZER_PATH)
    store = _load("hatsume.plugins.hatsume-plugin.memory.engine", STORE_PATH)
    store._get_db = lambda: _test_db_conn
    retrieval = _load("hatsume.plugins.hatsume-plugin.memory.engine", RETRIEVAL_PATH)

    return tokenizer, store, retrieval, config_mod, memory_file


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------


@pytest.mark.skip(reason="Pre-existing test infrastructure gap — ensure_embedding_model requires real credentials in engine.py")
def test_add_mem_embeds_only_new_memory_when_existing_vectors_present(tmp_path: Path):
    embedding_model = EmbeddingModelStub(
        {
            "old-1": [1.0, 0.0],
            "old-2": [0.0, 1.0],
            "new-memory": [0.5, 0.5],
        }
    )
    _tok, store, retrieval, _cfg, _ = load_memory_modules(tmp_path, embedding_model)

    # Mutate in-place so retrieval's imported references stay in sync
    store.all_mem_list.clear()
    store.all_mem_list.extend([
        {"content": "old-1", "time": 1, "people": []},
        {"content": "old-2", "time": 2, "people": []},
    ])
    store.tokenized_corpus.clear()
    store.tokenized_corpus.extend([["old", "1"], ["old", "2"]])
    store.tokenized_corpus_pos.clear()
    store.tokenized_corpus_pos.extend([
        [("old", "n"), ("1", "m")],
        [("old", "n"), ("2", "m")],
    ])
    retrieval.embedding_model = embedding_model
    retrieval.set_embedding_vectors(np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

    store.add_mem("new-memory")

    assert embedding_model.document_calls == ["new-memory"]
    assert len(store.all_mem_list) == 3
    np.testing.assert_array_equal(
        retrieval.get_embedding_vectors(),
        np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32),
    )


@pytest.mark.skip(reason="Pre-existing test infrastructure gap — ensure_embedding_model requires real credentials in engine.py")
def test_add_mem_rebuilds_missing_history_before_appending_new_vector(tmp_path: Path):
    embedding_model = EmbeddingModelStub(
        {
            "old-1": [1.0, 0.0],
            "old-2": [0.0, 1.0],
            "new-memory": [0.5, 0.5],
        }
    )
    _tok, store, retrieval, _cfg, _ = load_memory_modules(tmp_path, embedding_model)

    store.all_mem_list.clear()
    store.all_mem_list.extend([
        {"content": "old-1", "time": 1, "people": []},
        {"content": "old-2", "time": 2, "people": []},
    ])
    store.tokenized_corpus.clear()
    store.tokenized_corpus.extend([["old", "1"], ["old", "2"]])
    store.tokenized_corpus_pos.clear()
    store.tokenized_corpus_pos.extend([
        [("old", "n"), ("1", "m")],
        [("old", "n"), ("2", "m")],
    ])
    retrieval.embedding_model = embedding_model
    retrieval.set_embedding_vectors(None)

    store.add_mem("new-memory")

    # new_vector always computed first for DB persistence,
    # then rebuild_embedding_vectors covers all when index is out of sync
    assert embedding_model.document_calls == ["new-memory", "old-1", "old-2", "new-memory"]
    np.testing.assert_array_equal(
        retrieval.get_embedding_vectors(),
        np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32),
    )


@pytest.mark.skip(reason="Pre-existing test infrastructure gap — ensure_embedding_model requires real credentials in engine.py")
def test_add_mem_rebuilds_when_embedding_vector_count_mismatches_history(tmp_path: Path):
    embedding_model = EmbeddingModelStub(
        {
            "old-1": [1.0, 0.0],
            "old-2": [0.0, 1.0],
            "new-memory": [0.5, 0.5],
        }
    )
    _tok, store, retrieval, _cfg, _ = load_memory_modules(tmp_path, embedding_model)

    store.all_mem_list.clear()
    store.all_mem_list.extend([
        {"content": "old-1", "time": 1, "people": []},
        {"content": "old-2", "time": 2, "people": []},
    ])
    store.tokenized_corpus.clear()
    store.tokenized_corpus.extend([["old", "1"], ["old", "2"]])
    store.tokenized_corpus_pos.clear()
    store.tokenized_corpus_pos.extend([
        [("old", "n"), ("1", "m")],
        [("old", "n"), ("2", "m")],
    ])
    retrieval.embedding_model = embedding_model
    retrieval.set_embedding_vectors(np.array([[9.0, 9.0]], dtype=np.float32))

    store.add_mem("new-memory")

    # new_vector always computed first for DB persistence,
    # then rebuild_embedding_vectors covers all when index is out of sync
    assert embedding_model.document_calls == ["new-memory", "old-1", "old-2", "new-memory"]
    np.testing.assert_array_equal(
        retrieval.get_embedding_vectors(),
        np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32),
    )


@pytest.mark.skip(reason="Pre-existing test infrastructure gap — ensure_embedding_model requires real credentials in engine.py")
def test_add_mem_persists_deduplicated_people(tmp_path: Path):
    embedding_model = EmbeddingModelStub({"new-memory": [0.5, 0.5]})
    _tok, store, retrieval, _cfg, _ = load_memory_modules(tmp_path, embedding_model)

    retrieval.embedding_model = embedding_model
    retrieval.set_embedding_vectors(np.empty((0, 2), dtype=np.float32))

    store.add_mem(
        "new-memory",
        people=[
            {"user_id": 123456, "user_name": "小王"},
            {"user_id": "123456", "user_name": "小王-重复"},
            {"user_id": 234567, "user_name": "小李"},
        ],
    )

    assert store.all_mem_list[-1] == {
        "content": "new-memory",
        "time": store.all_mem_list[-1]["time"],
        "people": [
            {"user_id": 123456, "user_name": "小王"},
            {"user_id": 234567, "user_name": "小李"},
        ],
    }


def test_init_tokenized_corpus_expires_old_memories_from_db(tmp_path: Path):
    """Daily maintenance deletes expired SQLite rows and matching Milvus IDs."""
    embedding_model = EmbeddingModelStub({"old-memory": [0.2, 0.8], "recent-memory": [0.5, 0.5]})
    _tok, store, retrieval, _cfg, _memory_file = load_memory_modules(tmp_path, embedding_model)

    conn = store._get_db()
    old_time = int(time.time()) - 10_000_000  # Well beyond 30-day retention
    recent_time = int(time.time())

    conn.execute(
        "INSERT INTO memories (group_id, content, time, people, tokens) "
        "VALUES (?, ?, ?, ?, ?)",
        (12345, "old-memory", old_time, '[]', '[]')
    )
    conn.execute(
        "INSERT INTO memories (group_id, content, time, people, tokens) "
        "VALUES (?, ?, ?, ?, ?)",
        (12345, "recent-memory", recent_time, '[]', '[]')
    )
    conn.commit()
    deleted_vectors: list[tuple[int, list[int]]] = []
    store._get_vector_store = lambda: types.SimpleNamespace(
        delete=lambda memory_ids, *, group_id: deleted_vectors.append(
            (group_id, memory_ids)
        ),
        close=lambda: None,
    )

    store.init_tokenized_corpus()

    rows = conn.execute("SELECT id, content FROM memories ORDER BY id").fetchall()
    assert rows == [(2, "recent-memory")]
    assert deleted_vectors == [(12345, [1])]


@pytest.mark.skip(reason="Pre-existing test infrastructure gap — ensure_embedding_model requires real credentials in engine.py")
def test_query_mems_two_phase_user_specific_first(tmp_path: Path):
    embedding_model = EmbeddingModelStub({"query": [1.0, 0.0]})
    _tok, store, retrieval, cfg, _ = load_memory_modules(tmp_path, embedding_model)

    cfg.MAX_MEMORY_LIMIT = 10
    cfg.SCORE_THRESHOLD = 0
    retrieval.embedding_model = embedding_model
    retrieval.set_embedding_vectors(None)
    store.bm25_dirty = False
    # Override tokenizer so English query tokens are kept
    _tok.tokenize_with_pos = lambda text: [(text, "n")]

    # Stub bm25 on the retrieval module directly
    # User-42 memories (indices 7,8,9) get highest unique BM25 scores so they
    # are top-ranked after Phase 1 + Phase 2 hybrid scoring
    retrieval.bm25 = types.SimpleNamespace(
        get_scores=lambda _query_tokens: np.array(
            [0.7, 0.65, 0.6, 0.55, 0.5, 0.45, 0.4, 1.0, 0.95, 0.9]
        )
    )
    store.tokenized_corpus.clear()
    store.tokenized_corpus.extend([["query"]] * 10)
    store.all_mem_list.clear()
    now = int(time.time())
    store.all_mem_list.extend(
        [{"content": f"memory-{idx}", "time": now, "people": []} for idx in range(7)]
        + [
            {"content": "memory-7", "time": now, "people": [{"user_id": 42, "user_name": "目标"}]},
            {"content": "memory-8", "time": now, "people": [{"user_id": 42, "user_name": "目标"}]},
            {"content": "memory-9", "time": now, "people": [{"user_id": 42, "user_name": "目标"}]},
        ]
    )

    # Populate the in-memory SQLite DB with matching rows
    conn = store._get_db()
    for obj in store.all_mem_list:
        conn.execute(
            "INSERT INTO memories (content, time, people) VALUES (?, ?, ?)",
            (obj["content"], obj["time"], json.dumps(obj.get("people", []))),
        )
    conn.commit()

    memories = retrieval.query_mems("query", user_ids=[42])

    # Phase 1 retrieves user-specific memories (with user_id=42)
    contents = [c for c, _ in memories]
    for expected in ("memory-7", "memory-8", "memory-9"):
        assert expected in contents, f"User-specific memory {expected} should be retrieved"

    # Phase 2 fills remaining slots with supplemental memories
    assert "memory-0" in contents, "Supplemental memory should be retrieved"

    # Total should respect MAX_MEMORY_LIMIT
    assert len(memories) <= cfg.MAX_MEMORY_LIMIT

    # User-42 memories have highest BM25 scores, so they should be top-ranked
    assert contents[0] == "memory-7", "Top result should be highest-scored user-specific memory"
    assert contents[1] == "memory-8", "Second should be next highest-scored user-specific memory"
    assert contents[2] == "memory-9", "Third should be next highest-scored user-specific memory"
