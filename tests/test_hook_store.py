"""Focused tests for persistent per-group Hook metadata."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
BASE_NAME = "hatsume.plugins.hatsume-plugin"
MODULE_NAME = f"{BASE_NAME}.hooks.store"


def _load_store_module(tmp_path: Path):
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        (BASE_NAME, PLUGIN_DIR),
        (f"{BASE_NAME}.hooks", PLUGIN_DIR / "hooks"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = lambda _name: tmp_path / "hooks.db"
    sys.modules[localstore.__name__] = localstore

    config = types.ModuleType(f"{BASE_NAME}.config")
    config.HOOK_MAX_ACTIVE_PER_GROUP = 5
    config.HOOK_MIN_INTERVAL_SECONDS = 300
    config.HOOK_DEFAULT_INTERVAL_SECONDS = 900
    config.HOOK_DEFAULT_TIMEOUT_SECONDS = 15
    config.HOOK_MAX_TIMEOUT_SECONDS = 60
    sys.modules[config.__name__] = config

    sys.modules.pop(MODULE_NAME, None)
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        PLUGIN_DIR / "hooks/store.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def store_module(tmp_path):
    return _load_store_module(tmp_path)


@pytest.fixture
def hook_store(tmp_path, store_module):
    instance = store_module.HookStore(str(tmp_path / "hooks.db"))
    instance.init_db()
    yield instance
    instance.close()


def _create(store, *, group_id=100, name="mail", enabled=True):
    record = store.create_hook(
        group_id=group_id,
        name=name,
        script_path=f"/hooks/{group_id}/{name}.py",
        prompt="Handle newly received mail",
        interval_seconds=300,
        timeout_seconds=15,
        created_by=123,
        enabled=enabled,
    )
    return record


def test_schema_is_idempotent_and_reopens_existing_database(tmp_path, store_module):
    db_path = tmp_path / "hooks.db"
    first = store_module.HookStore(str(db_path))
    first.init_db()
    _create(first)
    first.close()

    second = store_module.HookStore(str(db_path))
    second.init_db()
    assert second.get_hook_by_name(100, "mail")["prompt"] == "Handle newly received mail"
    second.close()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(hooks)")}
    assert columns == store_module.EXPECTED_COLUMNS


def test_crud_is_filtered_by_group(hook_store):
    first = _create(hook_store, group_id=100, name="mail")
    _create(hook_store, group_id=200, name="mail")

    assert [row["group_id"] for row in hook_store.list_hooks(100)] == [100]
    assert hook_store.get_hook_by_name(200, "mail")["group_id"] == 200

    updated = hook_store.update_hook(
        100,
        "mail",
        prompt="New prompt",
        interval_seconds=600,
        timeout_seconds=30,
        enabled=False,
    )
    assert updated["id"] == first["id"]
    assert updated["prompt"] == "New prompt"
    assert updated["interval_seconds"] == 600
    assert updated["timeout_seconds"] == 30
    assert updated["enabled"] is False
    assert hook_store.get_hook_by_name(200, "mail")["enabled"] is True

    assert hook_store.delete_hook(100, "mail")["group_id"] == 100
    assert hook_store.get_hook_by_name(100, "mail") is None
    assert hook_store.get_hook_by_name(200, "mail") is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("group_id", 0),
        ("group_id", True),
        ("created_by", 0),
        ("name", ""),
        ("name", "x" * 65),
        ("prompt", ""),
        ("prompt", "x" * 2001),
        ("interval_seconds", 299),
        ("interval_seconds", True),
        ("timeout_seconds", 0),
        ("timeout_seconds", 61),
        ("timeout_seconds", True),
    ],
)
def test_create_rejects_invalid_values(hook_store, field, value):
    values = {
        "group_id": 100,
        "name": "mail",
        "script_path": "/hooks/100/mail.py",
        "prompt": "prompt",
        "interval_seconds": 300,
        "timeout_seconds": 15,
        "created_by": 123,
        "enabled": True,
    }
    values[field] = value
    with pytest.raises(ValueError):
        hook_store.create_hook(**values)


def test_name_is_unique_within_group(hook_store):
    _create(hook_store, group_id=100, name="mail")
    with pytest.raises(ValueError, match="already exists"):
        _create(hook_store, group_id=100, name="mail")
    _create(hook_store, group_id=200, name="mail")


def test_disabled_hooks_do_not_consume_active_limit(hook_store, store_module):
    for index in range(5):
        _create(hook_store, name=f"hook-{index}")
    disabled = _create(hook_store, name="disabled", enabled=False)

    with pytest.raises(store_module.HookLimitError, match="at most 5"):
        _create(hook_store, name="sixth")
    with pytest.raises(store_module.HookLimitError, match="at most 5"):
        hook_store.update_hook(100, "disabled", enabled=True)

    hook_store.update_hook(100, "hook-0", enabled=False)
    enabled = hook_store.update_hook(100, "disabled", enabled=True)
    assert enabled["id"] == disabled["id"]
    assert len(hook_store.list_enabled_hooks([100])) == 5


def test_concurrent_creates_cannot_exceed_active_limit(hook_store, store_module):
    def create(index: int) -> bool:
        try:
            _create(hook_store, name=f"concurrent-{index}")
        except store_module.HookLimitError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(create, range(6)))

    assert results.count(True) == 5
    assert results.count(False) == 1
    assert len(hook_store.list_enabled_hooks([100])) == 5


def test_run_state_updates_and_redacts_error_length(hook_store):
    record = _create(hook_store)
    hook_store.record_failure(record["id"], 3, "x" * 3000, run_at=10.0)
    failed = hook_store.get_hook(record["id"])
    assert failed["last_exit_code"] == 3
    assert len(failed["last_error"]) == 2000
    assert failed["consecutive_failures"] == 1

    hook_store.record_success(record["id"], 0, run_at=20.0)
    succeeded = hook_store.get_hook(record["id"])
    assert succeeded["last_run_at"] == 20.0
    assert succeeded["last_error"] is None
    assert succeeded["consecutive_failures"] == 0
