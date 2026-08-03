"""Tests for timer-v2 startup initialization and scheduler ordering."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TIMER_DIR = ROOT / "hatsume/plugins/hatsume-plugin/timer"
BASE_NAME = "hatsume.plugins.hatsume-plugin"


def _load_timer_init(store_type):
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        (BASE_NAME, ROOT / "hatsume/plugins/hatsume-plugin"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    store_module = types.ModuleType(f"{BASE_NAME}.timer.store")
    store_module.TimerStore = store_type
    sys.modules[store_module.__name__] = store_module

    name = f"{BASE_NAME}.timer"
    spec = importlib.util.spec_from_file_location(
        name,
        TIMER_DIR / "__init__.py",
        submodule_search_locations=[str(TIMER_DIR)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_get_store_initializes_only_v2_storage():
    calls = []

    class Store:
        _db_path = "v2.db"

        def __init__(self):
            calls.append("construct")

        def init_db(self):
            calls.append("init")

    timer = _load_timer_init(Store)

    first = timer.get_store()
    second = timer.get_store()

    assert first is second
    assert calls == ["construct", "init"]


def test_get_store_closes_failed_v2_initialization_and_retries(capsys):
    stores = []
    attempts = 0

    class Store:
        _db_path = "/private/timer-v2-db/timer.db"

        def __init__(self):
            stores.append(self)
            self.closed = False

        def init_db(self):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("v2 initialization failed")

        def close(self):
            self.closed = True

    timer = _load_timer_init(Store)

    with pytest.raises(RuntimeError, match="v2 initialization failed"):
        timer.get_store()
    output = capsys.readouterr().out
    recovered = timer.get_store()

    assert attempts == 2
    assert stores == [stores[0], recovered]
    assert stores[0].closed is True
    assert "/private/timer-v2-db/timer.db" in output


@pytest.mark.asyncio
async def test_init_scheduler_orders_recovery_memory_group_auto_response_and_cleanup():
    timer = _load_timer_init(type("Store", (), {}))
    store = object()
    timer._store = store
    calls = []
    executor = types.ModuleType(f"{BASE_NAME}.timer.executor")

    def sync(received, group_ids):
        assert received is store
        assert tuple(group_ids) == (101, 202)
        calls.append("sync")

    async def recover(received, *, group_ids):
        assert received is store
        assert tuple(group_ids) == (101,)
        calls.append("recover")

    async def auto(received, group_ids, *, routable_group_ids):
        assert received is store
        assert tuple(group_ids) == (101, 202)
        assert tuple(routable_group_ids) == (101,)
        calls.append("auto")

    def cleanup(received):
        assert received is store
        calls.append("cleanup")

    executor.remove_ineligible_auto_response_groups = sync
    executor.reload_all_schedules = recover
    executor.refresh_auto_responses = auto
    executor.register_cleanup_job = cleanup
    sys.modules[executor.__name__] = executor

    await timer.init_scheduler((101, 202), (101,))

    assert calls == ["sync", "recover", "auto", "cleanup"]
