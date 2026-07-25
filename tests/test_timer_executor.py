"""Tests for timer-v2 native APScheduler execution and recovery."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
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
    utils.get_group_member_name = AsyncMock(return_value="user")
    sys.modules[utils.__name__] = utils

    scheduler = MagicMock()
    apscheduler_plugin = types.ModuleType("nonebot_plugin_apscheduler")
    apscheduler_plugin.scheduler = scheduler
    sys.modules[apscheduler_plugin.__name__] = apscheduler_plugin

    nonebot = types.ModuleType("nonebot")
    nonebot.require = lambda name: apscheduler_plugin
    nonebot.get_bot = lambda: object()
    sys.modules[nonebot.__name__] = nonebot

    schedule = _load_file(
        f"{BASE_NAME}.timer.schedule", PLUGIN_DIR / "timer/schedule.py"
    )
    store = _load_file(f"{BASE_NAME}.timer.store", PLUGIN_DIR / "timer/store.py")
    executor = _load_file(
        f"{BASE_NAME}.timer.executor", PLUGIN_DIR / "timer/executor.py"
    )
    executor.scheduler = scheduler
    return schedule, store, executor, scheduler


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
    _, store_module, _, _ = modules
    instance = store_module.TimerStore(str(tmp_path / "timer.db"))
    instance.init_db()
    yield instance
    instance.close()


def _plans(schedule):
    return {
        "daily": schedule.build_daily_plan(
            "2026-08-01T00:00:00+08:00",
            "2026-08-05T23:59:59+08:00",
            ["09:00:00"],
            2,
            now=0,
        ),
        "weekly": schedule.build_weekly_plan(
            "2026-08-01T00:00:00+08:00",
            "2026-09-30T23:59:59+08:00",
            [{"weekday": 1, "time": "09:00:00"}],
            2,
            now=0,
        ),
        "monthly": schedule.build_monthly_plan(
            "2026-08-01T00:00:00+08:00",
            "2027-03-31T23:59:59+08:00",
            [{"day": 15, "time": "09:00:00"}],
            2,
            now=0,
        ),
        "at": schedule.build_at_plan(["2026-08-01T09:00:00+08:00"], now=0),
    }


@pytest.mark.parametrize(
    ("mode", "trigger_type_name"),
    [
        ("daily", "IntervalTrigger"),
        ("weekly", "IntervalTrigger"),
        ("monthly", "CalendarIntervalTrigger"),
        ("at", "DateTrigger"),
    ],
)
def test_build_trigger_uses_native_schedule_type(
    modules, store, mode, trigger_type_name
):
    schedule, _, executor, _ = modules
    plan = _plans(schedule)[mode]
    task_id = store.create_task(1, 2, "prompt", plan)
    task = store.get_task(task_id)
    point = store.get_points_for_task(task_id)[0]

    trigger = executor.build_trigger(task, point)

    assert isinstance(trigger, getattr(executor, trigger_type_name))
    if mode == "daily":
        assert trigger.interval == timedelta(days=2)
    elif mode == "weekly":
        assert trigger.interval == timedelta(weeks=2)
    elif mode == "monthly":
        assert trigger.months == 2


def test_monthly_trigger_iterates_calendar_dates_and_skips_missing_days(
    modules, store
):
    schedule, _, executor, _ = modules
    plan = schedule.build_monthly_plan(
        "2026-01-01T00:00:00+08:00",
        "2026-05-31T23:59:59+08:00",
        [{"day": 31, "time": "09:00:00"}],
        1,
        now=0,
    )
    task_id = store.create_task(1, 2, "prompt", plan)
    task = store.get_task(task_id)
    point = store.get_points_for_task(task_id)[0]
    trigger = executor.build_trigger(task, point)

    fire_times = []
    previous = None
    now = datetime(2026, 1, 1, tzinfo=SHANGHAI)
    for _ in range(3):
        previous = trigger.get_next_fire_time(previous, now)
        fire_times.append(previous)
        assert previous is not None
        now = previous

    assert fire_times == [
        datetime(2026, 1, 31, 9, tzinfo=SHANGHAI),
        datetime(2026, 3, 31, 9, tzinfo=SHANGHAI),
        datetime(2026, 5, 31, 9, tzinfo=SHANGHAI),
    ]


@pytest.mark.parametrize("mode", ["daily", "weekly", "monthly", "at"])
def test_native_trigger_fire_times_match_retained_plan(modules, store, mode):
    schedule, _, executor, _ = modules
    plan = _plans(schedule)[mode]
    task_id = store.create_task(1, 2, "prompt", plan)
    task = store.get_task(task_id)
    point = store.get_points_for_task(task_id)[0]
    trigger = executor.build_trigger(task, point)
    expected = [
        schedule.occurrence_at_index(task, point, index)
        for index in range(point["planned_occurrences"])
    ]

    actual = []
    previous = None
    now = datetime.fromtimestamp(point["first_fire_at"], tz=SHANGHAI)
    for _ in expected:
        next_fire = trigger.get_next_fire_time(previous, now)
        assert next_fire is not None
        actual.append(next_fire.timestamp())
        previous = next_fire
        now = next_fire

    assert actual == expected
    assert trigger.get_next_fire_time(previous, now) is None


@pytest.mark.parametrize(
    ("builder_name", "time_points"),
    [
        ("build_daily_plan", ["09:00:00"]),
        ("build_weekly_plan", [{"weekday": 1, "time": "09:00:00"}]),
        ("build_monthly_plan", [{"day": 3, "time": "09:00:00"}]),
    ],
)
def test_single_retained_frequency_occurrence_uses_native_date_trigger(
    modules, store, builder_name, time_points
):
    schedule, _, executor, _ = modules
    plan = getattr(schedule, builder_name)(
        "2026-08-03T00:00:00+08:00",
        "2026-08-03T23:59:59+08:00",
        time_points,
        10**9,
        now=0,
    )
    task_id = store.create_task(1, 2, "prompt", plan)
    task = store.get_task(task_id)
    point = store.get_points_for_task(task_id)[0]

    trigger = executor.build_trigger(task, point)

    assert isinstance(trigger, executor.DateTrigger)
    first = datetime.fromtimestamp(point["first_fire_at"], tz=SHANGHAI)
    assert trigger.get_next_fire_time(None, first) == first
    assert trigger.get_next_fire_time(first, first) is None


def test_frequency_point_uses_date_trigger_for_final_remaining_occurrence(
    modules, store
):
    schedule, _, executor, _ = modules
    plan = schedule.build_daily_plan(
        "2026-08-01T00:00:00+08:00",
        "2026-08-05T23:59:59+08:00",
        ["09:00:00"],
        2,
        now=0,
    )
    task_id = store.create_task(1, 2, "prompt", plan)
    task = store.get_task(task_id)
    point = store.get_points_for_task(task_id)[0]
    store.mark_occurrence_processed(
        point["id"], schedule.occurrence_at_index(task, point, 0)
    )
    store.mark_occurrence_processed(
        point["id"], schedule.occurrence_at_index(task, point, 1)
    )
    point = store.get_point(point["id"])
    assert point is not None

    trigger = executor.build_trigger(task, point)
    final = datetime.fromtimestamp(
        schedule.occurrence_at_index(task, point, 2), tz=SHANGHAI
    )

    assert isinstance(trigger, executor.DateTrigger)
    assert trigger.get_next_fire_time(None, final) == final


def test_register_point_uses_stable_job_contract(modules, store):
    schedule, _, executor, scheduler = modules
    task_id = store.create_task(1, 2, "prompt", _plans(schedule)["daily"])
    point = store.get_points_for_task(task_id)[0]

    assert executor.register_point(point, store) == point["job_id"]

    call = scheduler.add_job.call_args
    assert call.args[0] is executor._execute_wrapper
    assert isinstance(call.args[1], executor.IntervalTrigger)
    assert call.kwargs["id"] == point["job_id"]
    assert call.kwargs["args"] == [point["id"], store]
    assert call.kwargs["next_run_time"] == datetime.fromtimestamp(
        point["first_fire_at"], tz=SHANGHAI
    )
    assert call.kwargs["replace_existing"] is True
    assert call.kwargs["coalesce"] is False


def test_register_point_clears_runtime_state_when_add_job_fails(modules, store):
    schedule, _, executor, scheduler = modules
    task_id = store.create_task(1, 2, "prompt", _plans(schedule)["daily"])
    point = store.get_points_for_task(task_id)[0]
    scheduler.add_job.side_effect = RuntimeError("registration failed")

    with pytest.raises(RuntimeError, match="registration failed"):
        executor.register_point(point, store)

    assert point["id"] not in executor._point_stores
    assert point["id"] not in executor._pending_run_times


def test_cancel_task_jobs_removes_every_incomplete_point(modules, store):
    schedule, _, executor, scheduler = modules
    task_id = store.create_task(
        1,
        2,
        "prompt",
        schedule.build_daily_plan(
            "2026-08-01T00:00:00+08:00",
            "2026-08-03T23:59:59+08:00",
            ["09:00:00", "18:00:00"],
            1,
            now=0,
        ),
    )

    executor.cancel_task_jobs(task_id, store)

    assert {call.args[0] for call in scheduler.remove_job.call_args_list} == {
        point["job_id"] for point in store.get_points_for_task(task_id)
    }


@pytest.mark.asyncio
async def test_execute_point_injects_then_marks_progress(modules, store, monkeypatch):
    schedule, _, executor, _ = modules
    task_id = store.create_task(1, 2, "prompt", _plans(schedule)["at"])
    point = store.get_points_for_task(task_id)[0]
    inject = AsyncMock()
    monkeypatch.setattr(executor, "_inject_timer_to_graph", inject)

    await executor._execute_point(point["id"], store, scheduled_at=point["exact_at"])

    inject.assert_awaited_once_with(2, 1, "prompt", user_name="user")
    assert store.get_point(point["id"])["processed_occurrences"] == 1
    assert store.get_task(task_id)["processed_occurrences"] == 1


@pytest.mark.asyncio
async def test_execute_point_marks_progress_after_injection_failure(
    modules, store, monkeypatch
):
    schedule, _, executor, _ = modules
    task_id = store.create_task(1, 2, "prompt", _plans(schedule)["at"])
    point = store.get_points_for_task(task_id)[0]
    monkeypatch.setattr(
        executor,
        "_inject_timer_to_graph",
        AsyncMock(side_effect=RuntimeError("delivery failed")),
    )

    await executor._execute_point(point["id"], store, scheduled_at=point["exact_at"])

    assert store.get_point(point["id"])["processed_occurrences"] == 1


@pytest.mark.asyncio
async def test_recovery_expires_old_compensates_recent_and_registers_future(
    modules, store, monkeypatch
):
    schedule, _, executor, _ = modules
    now = datetime(2026, 8, 1, 12, 0, tzinfo=SHANGHAI).timestamp()
    plan = schedule._plan_from_epoch_times(
        [now - 600, now - 60, now + 600]
    )
    task_id = store.create_task(1, 2, "prompt", plan)
    points = store.get_points_for_task(task_id)
    inject = AsyncMock()
    register = MagicMock()
    monkeypatch.setattr(executor, "_inject_timer_to_graph", inject)
    monkeypatch.setattr(executor, "register_point", register)

    await executor.reload_all_schedules(store, now=now)

    assert store.get_point(points[0]["id"])["processed_occurrences"] == 1
    assert store.get_point(points[1]["id"])["processed_occurrences"] == 1
    assert store.get_point(points[2]["id"])["processed_occurrences"] == 0
    inject.assert_awaited_once()
    assert register.call_args.args[0]["id"] == points[2]["id"]


@pytest.mark.asyncio
async def test_repeated_recovery_does_not_reinject_processed_occurrence(
    modules, store, monkeypatch
):
    schedule, _, executor, _ = modules
    now = datetime(2026, 8, 1, 12, 0, tzinfo=SHANGHAI).timestamp()
    task_id = store.create_task(
        1, 2, "prompt", schedule._plan_from_epoch_times([now - 60])
    )
    inject = AsyncMock()
    monkeypatch.setattr(executor, "_inject_timer_to_graph", inject)

    await executor.reload_all_schedules(store, now=now)
    await executor.reload_all_schedules(store, now=now)

    inject.assert_awaited_once()
    assert store.get_task(task_id)["processed_occurrences"] == 1


@pytest.mark.asyncio
async def test_live_misfire_expires_old_run_and_executes_recent_run(
    modules, store, monkeypatch
):
    from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    schedule, _, executor, _ = modules
    recent = datetime.now(SHANGHAI).replace(microsecond=0) - timedelta(minutes=1)
    old = recent - timedelta(days=1)
    plan = schedule.build_daily_plan(
        old.isoformat(),
        recent.isoformat(),
        [recent.strftime("%H:%M:%S")],
        now=0,
    )
    task_id = store.create_task(1, 2, "prompt", plan)
    point = store.get_points_for_task(task_id)[0]
    inject = AsyncMock()
    monkeypatch.setattr(executor, "_inject_timer_to_graph", inject)

    live_scheduler = AsyncIOScheduler(timezone=SHANGHAI)
    observed_codes: set[int] = set()
    observed_both = asyncio.Event()

    def observe(event):
        observed_codes.add(event.code)
        if {EVENT_JOB_EXECUTED, EVENT_JOB_MISSED} <= observed_codes:
            observed_both.set()

    live_scheduler.add_listener(observe, EVENT_JOB_EXECUTED | EVENT_JOB_MISSED)
    live_scheduler.start(paused=True)
    monkeypatch.setattr(executor, "scheduler", live_scheduler)
    try:
        executor.register_point(point, store)
        live_scheduler.modify_job(point["job_id"], next_run_time=old)
        live_scheduler.resume()
        await asyncio.wait_for(observed_both.wait(), timeout=3)
    finally:
        live_scheduler.shutdown(wait=False)

    inject.assert_awaited_once()
    updated = store.get_point(point["id"])
    assert updated is not None
    assert updated["processed_occurrences"] == 2
    assert updated["last_processed_at"] == recent.timestamp()


@pytest.mark.asyncio
async def test_live_all_missed_batch_advances_progress_without_injection(
    modules, store, monkeypatch
):
    from apscheduler.events import EVENT_JOB_MISSED
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    schedule, _, executor, _ = modules
    old = datetime.now(SHANGHAI).replace(microsecond=0) - timedelta(minutes=10)
    plan = schedule.build_at_plan([old.isoformat()], now=0)
    task_id = store.create_task(1, 2, "prompt", plan)
    point = store.get_points_for_task(task_id)[0]
    inject = AsyncMock()
    monkeypatch.setattr(executor, "_inject_timer_to_graph", inject)

    live_scheduler = AsyncIOScheduler(timezone=SHANGHAI)
    observed_miss = asyncio.Event()
    live_scheduler.add_listener(
        lambda event: observed_miss.set(),
        EVENT_JOB_MISSED,
    )
    live_scheduler.start(paused=True)
    monkeypatch.setattr(executor, "scheduler", live_scheduler)
    try:
        executor.register_point(point, store)
        live_scheduler.modify_job(point["job_id"], next_run_time=old)
        live_scheduler.resume()
        await asyncio.wait_for(observed_miss.wait(), timeout=3)
    finally:
        live_scheduler.shutdown(wait=False)

    inject.assert_not_awaited()
    updated = store.get_point(point["id"])
    assert updated is not None
    assert updated["processed_occurrences"] == 1
    assert updated["last_processed_at"] == old.timestamp()


def test_cleanup_job_runs_daily_at_three(modules, store):
    _, _, executor, scheduler = modules

    executor.register_cleanup_job(store)

    call = scheduler.add_job.call_args
    assert call.args[0] is executor.cleanup_finished_tasks
    assert isinstance(call.args[1], executor.CronTrigger)
    assert call.kwargs["id"] == "timer_v2_cleanup"
    assert call.kwargs["args"] == [store]
    assert call.kwargs["replace_existing"] is True
    assert call.args[1].fields[5].expressions[0].first == 3


@pytest.mark.asyncio
async def test_cleanup_cancels_and_deletes_only_finished_tasks(
    modules, store, monkeypatch
):
    schedule, _, executor, _ = modules
    finished_id = store.create_task(1, 2, "done", _plans(schedule)["at"])
    active_id = store.create_task(1, 3, "active", _plans(schedule)["at"])
    point = store.get_points_for_task(finished_id)[0]
    store.mark_occurrence_processed(point["id"], point["exact_at"])
    cancel = MagicMock()
    monkeypatch.setattr(executor, "cancel_task_jobs", cancel)

    assert inspect.iscoroutinefunction(executor.cleanup_finished_tasks)
    await executor.cleanup_finished_tasks(store)

    cancel.assert_called_once_with(finished_id, store)
    assert store.get_task(finished_id) is None
    assert store.get_task(active_id) is not None
