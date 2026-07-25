"""Tests for timer-v2 auto-response scheduling and execution."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
BASE_NAME = "hatsume.plugins.hatsume-plugin"
SHANGHAI = timezone(timedelta(hours=8))


def _is_stubbed_namespace(name: str) -> bool:
    return name == "hatsume" or name.startswith("hatsume.") or name in {
        "nonebot",
        "nonebot_plugin_apscheduler",
    } or name.startswith(("nonebot.", "apscheduler.")) or name == "apscheduler"


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_modules():
    for name in list(sys.modules):
        if name == "apscheduler" or name.startswith("apscheduler."):
            del sys.modules[name]

    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        (BASE_NAME, PLUGIN_DIR),
        (f"{BASE_NAME}.timer", PLUGIN_DIR / "timer"),
        (f"{BASE_NAME}.graph", PLUGIN_DIR / "graph"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    config = types.ModuleType(f"{BASE_NAME}.config")
    config.TIMER_MAX_FREQUENCY_POINTS = 5
    config.TIMER_MAX_EXACT_POINTS = 10
    config.TIMER_TOLERANCE_MINUTES = 5
    config.AUTO_RESPONSE_GROUP_ID = 123
    sys.modules[config.__name__] = config

    prompts = types.ModuleType(f"{BASE_NAME}.prompts")
    prompts.get_auto_response_prompt = lambda: "auto response prompt"
    sys.modules[prompts.__name__] = prompts

    nodes = types.ModuleType(f"{BASE_NAME}.graph.nodes")
    nodes.inject_timer = MagicMock()
    sys.modules[nodes.__name__] = nodes

    utils = types.ModuleType(f"{BASE_NAME}.utils")
    utils.get_group_member_name = AsyncMock(return_value=None)
    sys.modules[utils.__name__] = utils

    scheduler = MagicMock()
    apscheduler_plugin = types.ModuleType("nonebot_plugin_apscheduler")
    apscheduler_plugin.scheduler = scheduler
    sys.modules[apscheduler_plugin.__name__] = apscheduler_plugin

    nonebot = types.ModuleType("nonebot")
    nonebot.require = lambda name: apscheduler_plugin
    nonebot.get_bot = lambda: object()
    sys.modules[nonebot.__name__] = nonebot

    _load_file(
        f"{BASE_NAME}.timer.schedule", PLUGIN_DIR / "timer/schedule.py"
    )
    store = _load_file(f"{BASE_NAME}.timer.store", PLUGIN_DIR / "timer/store.py")
    executor = _load_file(
        f"{BASE_NAME}.timer.executor", PLUGIN_DIR / "timer/executor.py"
    )
    executor.scheduler = scheduler
    return store, executor, scheduler, nodes


@pytest.fixture
def modules():
    previous = {
        name: module
        for name, module in sys.modules.items()
        if _is_stubbed_namespace(name)
    }
    try:
        yield _load_modules()
    finally:
        for name in list(sys.modules):
            if _is_stubbed_namespace(name):
                del sys.modules[name]
        sys.modules.update(previous)


@pytest.fixture
def store(tmp_path, modules):
    store_module, _, _, _ = modules
    instance = store_module.TimerStore(str(tmp_path / "timer.db"))
    instance.init_db()
    yield instance
    instance.close()


def test_random_response_trigger_is_between_one_and_three_hours(modules):
    _, executor, _, _ = modules
    before = datetime.now(SHANGHAI)

    result = datetime.fromtimestamp(executor._random_response_trigger(), SHANGHAI)

    assert timedelta(hours=1) <= result - before <= timedelta(hours=3)


@pytest.mark.asyncio
async def test_refresh_removes_internal_task_when_group_is_disabled(
    modules, store, monkeypatch
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    store.upsert_auto_response(point_time)
    point = store.get_auto_response_point()
    assert point is not None
    monkeypatch.setattr(executor, "AUTO_RESPONSE_GROUP_ID", 0)

    await executor.refresh_auto_response(store)

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point() is None


@pytest.mark.asyncio
async def test_refresh_retains_and_registers_one_future_internal_point(
    modules, store
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    task_id = store.upsert_auto_response(point_time)

    await executor.refresh_auto_response(store)

    point = store.get_auto_response_point()
    assert point is not None
    assert point["task_id"] == task_id
    assert point["exact_at"] == point_time
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["id"] == point["job_id"]


@pytest.mark.asyncio
async def test_refresh_creates_one_future_internal_point_when_missing(
    modules, store, monkeypatch
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: point_time)

    await executor.refresh_auto_response(store)

    point = store.get_auto_response_point()
    assert point is not None
    assert point["exact_at"] == point_time
    assert scheduler.add_job.call_count == 1


@pytest.mark.asyncio
async def test_auto_response_marks_before_injection_and_registers_successor(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    trigger_at = datetime.now(SHANGHAI).timestamp() + 60
    successor_at = trigger_at + 3600
    store.upsert_auto_response(trigger_at, "participate in chat")
    point = store.get_auto_response_point()
    assert point is not None
    progress_marked = False
    original_mark = store.mark_occurrence_processed

    def mark_processed(point_id, scheduled_at):
        nonlocal progress_marked
        progress_marked = original_mark(point_id, scheduled_at)
        return progress_marked

    def inject_timer(**kwargs):
        assert progress_marked is True
        assert kwargs["group_id"] == 123
        assert kwargs["timer_prompt"] == "participate in chat"

    monkeypatch.setattr(store, "mark_occurrence_processed", mark_processed)
    monkeypatch.setattr(nodes, "inject_timer", inject_timer)
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: successor_at)
    scheduler.reset_mock()

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    successor = store.get_auto_response_point()
    assert successor is not None
    assert successor["exact_at"] == successor_at
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["id"] == successor["job_id"]


@pytest.mark.asyncio
async def test_auto_response_registers_successor_when_injection_fails(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    trigger_at = datetime.now(SHANGHAI).timestamp() + 60
    successor_at = trigger_at + 3600
    store.upsert_auto_response(trigger_at, "participate in chat")
    point = store.get_auto_response_point()
    assert point is not None
    monkeypatch.setattr(
        nodes,
        "inject_timer",
        MagicMock(side_effect=RuntimeError("injection failed")),
    )
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: successor_at)
    scheduler.reset_mock()

    with pytest.raises(RuntimeError, match="injection failed"):
        await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    successor = store.get_auto_response_point()
    assert successor is not None
    assert successor["exact_at"] == successor_at
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["id"] == successor["job_id"]


@pytest.mark.asyncio
async def test_auto_response_never_injects_or_reschedules_when_disabled(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    trigger_at = datetime.now(SHANGHAI).timestamp() + 60
    store.upsert_auto_response(trigger_at)
    point = store.get_auto_response_point()
    assert point is not None
    monkeypatch.setattr(executor, "AUTO_RESPONSE_GROUP_ID", 0)

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    nodes.inject_timer.assert_not_called()
    scheduler.add_job.assert_not_called()
