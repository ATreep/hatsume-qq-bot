"""Tests for per-group todo SQLite persistence."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
TEST_PACKAGE = "_hatsume_todo_store_test"
NOW = 2_000_000_000.0


def _load_store_module():
    package = types.ModuleType(TEST_PACKAGE)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[TEST_PACKAGE] = package

    todo_package = types.ModuleType(f"{TEST_PACKAGE}.todo")
    todo_package.__path__ = [str(PLUGIN_DIR / "todo")]
    sys.modules[todo_package.__name__] = todo_package

    config = types.ModuleType(f"{TEST_PACKAGE}.config")
    config.TODO_MAX_ITEMS = 15
    config.TODO_EXPIRY_SECONDS = 48 * 60 * 60
    sys.modules[config.__name__] = config

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = (
        lambda filename: ROOT / "data" / "hatsume-plugin" / filename
    )
    previous_localstore = sys.modules.get("nonebot_plugin_localstore")
    sys.modules["nonebot_plugin_localstore"] = localstore
    try:
        name = f"{TEST_PACKAGE}.todo.store"
        spec = importlib.util.spec_from_file_location(
            name, PLUGIN_DIR / "todo/store.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        if previous_localstore is None:
            del sys.modules["nonebot_plugin_localstore"]
        else:
            sys.modules["nonebot_plugin_localstore"] = previous_localstore
    return module


@pytest.fixture
def store_module():
    return _load_store_module()


@pytest.fixture
def store(tmp_path, store_module):
    instance = store_module.TodoStore(str(tmp_path / "todo.db"))
    instance.init_db()
    yield instance
    instance.close()


def _create(
    store,
    *,
    group_id: int = 100,
    user_id: int = 200,
    content: str = "tell the user the result",
    now: float = NOW,
):
    return store.create_item(
        group_id,
        user_id,
        "Initiator",
        content,
        "the initiator only",
        "the initiator says the qualifying event happened",
        now=now,
    )


def test_default_path_uses_todo_directory(store_module):
    assert Path(store_module._get_default_db_path()).parts[-4:] == (
        "data",
        "hatsume-plugin",
        "todo-db",
        "todo.db",
    )


def test_schema_indexes_and_pragmas(store):
    assert store._conn is not None
    tables = {
        row["name"]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert tables - {"sqlite_sequence"} == {"todo_items"}
    columns = {
        row["name"]
        for row in store._conn.execute("PRAGMA table_info('todo_items')")
    }
    assert columns == {
        "id",
        "group_id",
        "initiator_qq_id",
        "initiator_group_name",
        "content",
        "finish_condition",
        "created_at",
    }
    indexes = {
        row["name"]
        for row in store._conn.execute("PRAGMA index_list('todo_items')")
    }
    assert "idx_todo_active_duplicate" in indexes
    assert "idx_todo_group_created" in indexes
    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_reopen_existing_database_is_idempotent(tmp_path, store_module):
    path = str(tmp_path / "todo.db")
    first = store_module.TodoStore(path)
    first.init_db()
    created = _create(first)
    first.close()

    reopened = store_module.TodoStore(path)
    reopened.init_db()
    reopened.init_db()
    try:
        assert reopened.list_items(100) == [created.item]
    finally:
        reopened.close()


def test_incompatible_existing_schema_is_rejected(tmp_path, store_module):
    path = tmp_path / "todo.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE todo_items (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    instance = store_module.TodoStore(str(path))
    with pytest.raises(RuntimeError, match="incompatible todo database schema"):
        instance.init_db()
    assert instance._conn is None


def test_group_isolation_and_creation_order(store):
    later = _create(store, content="later", now=NOW + 1)
    earlier = _create(store, content="earlier", now=NOW)
    other = _create(store, group_id=101, content="other group", now=NOW - 1)

    assert [item["id"] for item in store.list_items(100)] == [
        earlier.item["id"],
        later.item["id"],
    ]
    assert store.list_items(101) == [other.item]


def test_exact_duplicate_returns_existing_item(store):
    first = _create(store)
    duplicate = _create(store)

    assert first.status == "created"
    assert duplicate.status == "duplicate"
    assert duplicate.item == first.item
    assert len(store.list_items(100)) == 1


def test_capacity_is_per_group_and_never_evicts(store):
    for index in range(15):
        assert _create(store, content=f"item {index}").status == "created"

    full = _create(store, content="sixteenth")
    other_group = _create(store, group_id=101, content="independent")

    assert full.status == "full"
    assert full.item is None
    assert len(store.list_items(100)) == 15
    assert other_group.status == "created"


def test_expiry_boundary_is_inclusive_and_frees_capacity(store, store_module):
    for index in range(14):
        _create(store, content=f"active {index}", now=NOW)
    boundary = _create(
        store,
        content="boundary",
        now=NOW - store_module.TODO_EXPIRY_SECONDS,
    )
    recent = _create(
        store,
        content="just recent",
        now=NOW - store_module.TODO_EXPIRY_SECONDS + 0.001,
    )
    assert boundary.status == "created"
    assert recent.status == "full"

    assert store.delete_expired(now=NOW) == 1
    replacement = _create(store, content="replacement", now=NOW)

    assert replacement.status == "created"
    assert all(item["content"] != "boundary" for item in store.list_items(100))


def test_mark_is_group_scoped_and_hard_deletes_without_history(store):
    created = _create(store)
    assert created.item is not None

    assert store.mark_item(101, created.item["id"], now=NOW) is None
    assert store.list_items(100) == [created.item]
    assert store.mark_item(100, created.item["id"], now=NOW) == created.item
    assert store.list_items(100) == []
    assert store._conn is not None
    tables = {
        row["name"]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == {"todo_items"}


def test_expired_item_cannot_be_marked(store, store_module):
    created = _create(
        store,
        now=NOW - store_module.TODO_EXPIRY_SECONDS,
    )
    assert created.item is not None

    assert store.mark_item(100, created.item["id"], now=NOW) is None
    assert store.list_items(100) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content", ""),
        ("content", "x" * 501),
        ("permitted_finisher", " "),
        ("completion_event", "x" * 501),
    ],
)
def test_field_validation_is_non_destructive(store, field, value):
    arguments = {
        "group_id": 100,
        "initiator_qq_id": 200,
        "initiator_group_name": "Initiator",
        "content": "content",
        "permitted_finisher": "initiator",
        "completion_event": "event",
        "now": NOW,
    }
    arguments[field] = value

    with pytest.raises(ValueError, match="错误"):
        store.create_item(**arguments)
    assert store.list_items(100) == []


def test_concurrent_exact_duplicate_creates_one_row(tmp_path, store_module):
    path = str(tmp_path / "todo.db")
    stores = [store_module.TodoStore(path), store_module.TodoStore(path)]
    for instance in stores:
        instance.init_db()
    barrier = threading.Barrier(2)

    def create(instance):
        barrier.wait()
        return _create(instance).status

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(create, stores))
        assert sorted(statuses) == ["created", "duplicate"]
        assert len(stores[0].list_items(100)) == 1
    finally:
        for instance in stores:
            instance.close()


def test_concurrent_capacity_never_creates_sixteenth(tmp_path, store_module):
    path = str(tmp_path / "todo.db")
    seed = store_module.TodoStore(path)
    seed.init_db()
    for index in range(14):
        _create(seed, content=f"seed {index}")
    contenders = [store_module.TodoStore(path), store_module.TodoStore(path)]
    for instance in contenders:
        instance.init_db()
    barrier = threading.Barrier(2)

    def create(arguments):
        instance, content = arguments
        barrier.wait()
        return _create(instance, content=content).status

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(
                executor.map(create, zip(contenders, ("candidate 1", "candidate 2")))
            )
        assert sorted(statuses) == ["created", "full"]
        assert len(seed.list_items(100)) == 15
    finally:
        seed.close()
        for instance in contenders:
            instance.close()
