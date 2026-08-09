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


def _future_non_quiet_timestamp() -> float:
    """Return a future Shanghai-noon timestamp for non-quiet execution tests."""
    return (
        datetime.now(SHANGHAI) + timedelta(days=1)
    ).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()


def _is_stubbed_namespace(name: str) -> bool:
    return name == "hatsume" or name.startswith("hatsume.") or name in {
        "nonebot",
        "nonebot_plugin_apscheduler",
        "nonebot_plugin_localstore",
    } or name.startswith(("nonebot.", "apscheduler.")) or name == "apscheduler"


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_auto_response_blacklist_defaults():
    module_name = "hatsume_test_config"
    try:
        config = _load_file(module_name, PLUGIN_DIR / "config.py")
        assert config.AUTO_RESPONSE_GROUP_BLACKLIST == frozenset(
            {376347217, 579996918}
        )
        assert not hasattr(config, "AUTO_RESPONSE" "_GROUP_ID")
    finally:
        sys.modules.pop(module_name, None)


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
    config.AUTO_RESPONSE_GROUP_BLACKLIST = frozenset({376347217, 579996918})
    config.AUTO_RESPONSE_MIN_INTERVAL_MINUTES = 30
    config.AUTO_RESPONSE_MAX_INTERVAL_MINUTES = 120
    config.AUTO_RESPONSE_QUIET_START_HOUR = 2
    config.AUTO_RESPONSE_QUIET_END_HOUR = 6
    sys.modules[config.__name__] = config

    prompts = types.ModuleType(f"{BASE_NAME}.prompts")
    prompts.get_auto_response_prompt = lambda: "auto response prompt"
    sys.modules[prompts.__name__] = prompts

    nodes = types.ModuleType(f"{BASE_NAME}.graph.nodes")
    nodes.inject_timer = MagicMock()
    sys.modules[nodes.__name__] = nodes

    memory = types.ModuleType(f"{BASE_NAME}.memory")
    memory.is_group_activated = lambda _group_id: True
    memory.synchronize_activated_group = (
        lambda group_id, callback: callback(group_id, True)
    )
    sys.modules[memory.__name__] = memory

    group_runtime = types.ModuleType(f"{BASE_NAME}.group_runtime")
    group_runtime.group_runtime_registry = types.SimpleNamespace(
        get_bot=lambda _group_id: object(),
        get_existing=lambda _group_id: None,
    )
    sys.modules[group_runtime.__name__] = group_runtime

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

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = lambda filename: ROOT / "data" / filename
    sys.modules[localstore.__name__] = localstore

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


def test_random_response_trigger_is_between_thirty_minutes_and_two_hours(
    modules, monkeypatch
):
    _, executor, _, _ = modules
    uniform = MagicMock(return_value=75)
    monkeypatch.setattr(executor.random, "uniform", uniform)
    before = datetime.now(SHANGHAI)

    result = datetime.fromtimestamp(executor._random_response_trigger(), SHANGHAI)

    after = datetime.now(SHANGHAI)
    uniform.assert_called_once_with(30, 120)
    assert before + timedelta(minutes=75) <= result <= after + timedelta(minutes=75)


@pytest.mark.asyncio
async def test_refresh_removes_internal_task_for_group_without_memories(modules, store):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    store.upsert_auto_response(123, point_time)
    point = store.get_auto_response_point(123)
    assert point is not None

    await executor.refresh_auto_responses(store, ())

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point(123) is None


@pytest.mark.asyncio
async def test_refresh_removes_blacklisted_group_even_when_it_owns_memory(
    modules, store
):
    _, executor, scheduler, _ = modules
    group_id = 376347217
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    store.upsert_auto_response(group_id, point_time)
    point = store.get_auto_response_point(group_id)
    assert point is not None

    await executor.refresh_auto_responses(store, (group_id,))

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point(group_id) is None


@pytest.mark.asyncio
async def test_refresh_retains_future_internal_points_for_each_memory_group(modules, store):
    _, executor, scheduler, _ = modules
    first_time = datetime.now(SHANGHAI).timestamp() + 3600
    second_time = first_time + 600
    first_task_id = store.upsert_auto_response(123, first_time)
    second_task_id = store.upsert_auto_response(456, second_time)

    await executor.refresh_auto_responses(store, (123, 456))

    first_point = store.get_auto_response_point(123)
    second_point = store.get_auto_response_point(456)
    assert first_point["task_id"] == first_task_id
    assert first_point["exact_at"] == first_time
    assert second_point["task_id"] == second_task_id
    assert second_point["exact_at"] == second_time
    assert {call.kwargs["id"] for call in scheduler.add_job.call_args_list} == {
        first_point["job_id"],
        second_point["job_id"],
    }


@pytest.mark.asyncio
async def test_refresh_cancels_registered_job_for_unroutable_active_group(
    modules, store
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    task_id = store.upsert_auto_response(456, point_time)
    point = store.get_auto_response_point(456)
    executor.register_point(point, store)
    scheduler.reset_mock()

    await executor.refresh_auto_responses(
        store,
        (456,),
        routable_group_ids=(),
    )

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    assert store.get_auto_response_point(456)["task_id"] == task_id


@pytest.mark.asyncio
async def test_refresh_creates_one_future_internal_point_for_each_missing_group(
    modules, store, monkeypatch
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: point_time)

    await executor.refresh_auto_responses(store, (123, 456))

    first_point = store.get_auto_response_point(123)
    second_point = store.get_auto_response_point(456)
    assert first_point["exact_at"] == point_time
    assert second_point["exact_at"] == point_time
    assert scheduler.add_job.call_count == 2


def test_sync_auto_response_for_active_group_is_idempotent(
    modules, store, monkeypatch
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: point_time)

    executor.sync_auto_response_for_group(store, 456, True)
    first = store.get_auto_response_point(456)
    executor.sync_auto_response_for_group(store, 456, True)

    assert store.get_auto_response_point(456)["task_id"] == first["task_id"]
    assert scheduler.add_job.call_count == 1


def test_sync_active_unroutable_group_persists_without_registering_job(
    modules, store, monkeypatch
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: point_time)

    executor.sync_auto_response_for_group(
        store,
        456,
        True,
        register_job=False,
    )

    assert store.get_auto_response_point(456)["exact_at"] == point_time
    scheduler.add_job.assert_not_called()


def test_sync_unroutable_group_cancels_job_without_deleting_point(
    modules, store
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    task_id = store.upsert_auto_response(456, point_time)
    point = store.get_auto_response_point(456)
    executor.register_point(point, store)
    scheduler.reset_mock()

    executor.sync_auto_response_for_group(
        store,
        456,
        True,
        register_job=False,
    )

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    assert store.get_auto_response_point(456)["task_id"] == task_id


def test_sync_auto_response_removes_blacklisted_group_task(modules, store):
    _, executor, scheduler, _ = modules
    group_id = 579996918
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    store.upsert_auto_response(group_id, point_time)
    point = store.get_auto_response_point(group_id)
    assert point is not None

    executor.sync_auto_response_for_group(store, group_id, True)

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point(group_id) is None


def test_sync_auto_response_removes_inactive_group_task(modules, store):
    _, executor, scheduler, _ = modules
    group_id = 456
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    store.upsert_auto_response(group_id, point_time)
    point = store.get_auto_response_point(group_id)
    assert point is not None

    executor.sync_auto_response_for_group(store, group_id, False)

    scheduler.remove_job.assert_called_once_with(point["job_id"])
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point(group_id) is None


def test_sync_auto_response_repairs_orphaned_future_point(
    modules, store, monkeypatch
):
    _, executor, scheduler, _ = modules
    point_time = datetime.now(SHANGHAI).timestamp() + 3600
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: point_time)
    scheduler.add_job.side_effect = RuntimeError("scheduler unavailable")

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        executor.sync_auto_response_for_group(store, 456, True)

    orphaned = store.get_auto_response_point(456)
    assert orphaned is not None
    scheduler.add_job.side_effect = None
    scheduler.get_job.return_value = None

    executor.sync_auto_response_for_group(store, 456, True)

    repaired = store.get_auto_response_point(456)
    assert repaired["task_id"] == orphaned["task_id"]
    assert scheduler.add_job.call_count == 2
    scheduler.get_job.assert_called_once_with(orphaned["job_id"])


@pytest.mark.asyncio
async def test_recovery_skips_groups_without_registered_bot_routes(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    current = _future_non_quiet_timestamp()
    trigger_at = current - 60
    successor_at = current + 3600
    store.upsert_auto_response(123, trigger_at, "routable")
    store.upsert_auto_response(456, trigger_at, "unroutable")
    unroutable_point = store.get_auto_response_point(456)
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: successor_at)
    scheduler.reset_mock()

    await executor.reload_all_schedules(store, now=current, group_ids=(123,))

    nodes.inject_timer.assert_called_once()
    assert nodes.inject_timer.call_args.kwargs["group_id"] == 123
    assert store.get_point(unroutable_point["id"])["processed_occurrences"] == 0


@pytest.mark.asyncio
async def test_route_loss_before_execution_preserves_unconsumed_point(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    trigger_at = datetime.now(SHANGHAI).timestamp()
    task_id = store.upsert_auto_response(456, trigger_at, "participate in chat")
    point = store.get_auto_response_point(456)
    monkeypatch.setattr(
        executor,
        "_get_auto_response_state",
        lambda _group_id: (True, False),
    )
    scheduler.reset_mock()

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    retained = store.get_auto_response_point(456)
    assert retained["task_id"] == task_id
    assert retained["id"] == point["id"]
    assert retained["processed_occurrences"] == 0
    nodes.inject_timer.assert_not_called()
    scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_ineligible_due_auto_response_is_removed_before_recovery(modules, store):
    _, executor, _, nodes = modules
    current = datetime.now(SHANGHAI).timestamp()
    task_id = store.upsert_auto_response(456, current - 60, "stale")

    executor.remove_ineligible_auto_response_groups(store, (123,))
    await executor.reload_all_schedules(store, now=current, group_ids=(123, 456))

    assert store.get_task(task_id) is None
    nodes.inject_timer.assert_not_called()


@pytest.mark.asyncio
async def test_auto_response_marks_before_injection_and_registers_successor(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    trigger_at = _future_non_quiet_timestamp()
    successor_at = trigger_at + 3600
    store.upsert_auto_response(456, trigger_at, "participate in chat")
    point = store.get_auto_response_point(456)
    assert point is not None
    progress_marked = False
    original_mark = store.mark_occurrence_processed

    def mark_processed(point_id, scheduled_at):
        nonlocal progress_marked
        progress_marked = original_mark(point_id, scheduled_at)
        return progress_marked

    def inject_timer(**kwargs):
        assert progress_marked is True
        assert kwargs["group_id"] == 456
        assert kwargs["timer_prompt"] == "participate in chat"

    monkeypatch.setattr(store, "mark_occurrence_processed", mark_processed)
    monkeypatch.setattr(nodes, "inject_timer", inject_timer)
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: successor_at)
    scheduler.reset_mock()

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    successor = store.get_auto_response_point(456)
    assert successor is not None
    assert successor["exact_at"] == successor_at
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["id"] == successor["job_id"]


@pytest.mark.asyncio
async def test_auto_response_skips_active_conversation_and_registers_successor(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    group_id = 456
    trigger_at = _future_non_quiet_timestamp()
    successor_at = trigger_at + 3600
    store.upsert_auto_response(group_id, trigger_at, "participate in chat")
    point = store.get_auto_response_point(group_id)
    assert point is not None
    group_runtime = sys.modules[f"{BASE_NAME}.group_runtime"]
    group_runtime.group_runtime_registry.get_existing = MagicMock(
        return_value=types.SimpleNamespace(
            conversation=types.SimpleNamespace(is_chatting=True)
        )
    )
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: successor_at)
    scheduler.reset_mock()

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    nodes.inject_timer.assert_not_called()
    successor = store.get_auto_response_point(group_id)
    assert successor is not None
    assert successor["exact_at"] == successor_at
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["id"] == successor["job_id"]


@pytest.mark.asyncio
async def test_auto_response_registers_successor_when_injection_fails(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    trigger_at = _future_non_quiet_timestamp()
    successor_at = trigger_at + 3600
    store.upsert_auto_response(456, trigger_at, "participate in chat")
    point = store.get_auto_response_point(456)
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

    successor = store.get_auto_response_point(456)
    assert successor is not None
    assert successor["exact_at"] == successor_at
    assert scheduler.add_job.call_count == 1
    assert scheduler.add_job.call_args.kwargs["id"] == successor["job_id"]


@pytest.mark.asyncio
async def test_inflight_auto_response_does_not_resurrect_deactivated_group(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    group_id = 456
    trigger_at = _future_non_quiet_timestamp()
    store.upsert_auto_response(group_id, trigger_at, "participate in chat")
    point = store.get_auto_response_point(group_id)
    task = store.get_task(point["task_id"])
    monkeypatch.setattr(
        executor,
        "_get_auto_response_state",
        lambda _group_id: (True, True),
    )
    memory = sys.modules[f"{BASE_NAME}.memory"]
    memory.synchronize_activated_group = (
        lambda resolved_group_id, callback: callback(resolved_group_id, False)
    )
    nodes.inject_timer.side_effect = lambda **_kwargs: store.delete_auto_response_tasks(
        group_id
    )

    await executor._execute_auto_response(task, store, triggered_at=trigger_at)

    nodes.inject_timer.assert_called_once()
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point(group_id) is None


@pytest.mark.asyncio
async def test_successor_sync_uses_memory_owned_current_activation(
    modules, store, monkeypatch
):
    _, executor, scheduler, nodes = modules
    group_id = 456
    trigger_at = _future_non_quiet_timestamp()
    store.upsert_auto_response(group_id, trigger_at, "participate in chat")
    point = store.get_auto_response_point(group_id)
    memory = sys.modules[f"{BASE_NAME}.memory"]
    memory.synchronize_activated_group = MagicMock(
        side_effect=lambda resolved_group_id, callback: callback(
            resolved_group_id, False
        )
    )
    monkeypatch.setattr(
        executor,
        "_get_auto_response_state",
        lambda _group_id: (True, True),
    )
    scheduler.reset_mock()

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    nodes.inject_timer.assert_called_once()
    memory.synchronize_activated_group.assert_called_once()
    scheduler.add_job.assert_not_called()
    assert store.get_auto_response_point(group_id) is None


@pytest.mark.parametrize(
    ("hour", "minute", "should_inject"),
    [
        (1, 59, True),
        (2, 0, False),
        (5, 59, False),
        (6, 0, True),
    ],
)
@pytest.mark.asyncio
async def test_auto_response_skips_quiet_hours_and_registers_successor(
    modules, store, monkeypatch, hour, minute, should_inject
):
    _, executor, scheduler, nodes = modules
    trigger_at = datetime(2026, 1, 2, hour, minute, tzinfo=SHANGHAI).timestamp()
    successor_at = trigger_at + 3600
    store.upsert_auto_response(456, trigger_at, "participate in chat")
    point = store.get_auto_response_point(456)
    assert point is not None
    monkeypatch.setattr(executor, "_random_response_trigger", lambda: successor_at)
    scheduler.reset_mock()

    await executor._execute_point(point["id"], store, scheduled_at=trigger_at)

    if should_inject:
        nodes.inject_timer.assert_called_once()
    else:
        nodes.inject_timer.assert_not_called()
    successor = store.get_auto_response_point(456)
    assert successor is not None
    assert successor["exact_at"] == successor_at
    assert scheduler.add_job.call_count == 1
