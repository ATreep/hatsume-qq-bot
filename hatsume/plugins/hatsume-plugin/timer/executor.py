"""APScheduler job management and graph injection for timer-v2."""

from __future__ import annotations

import random
import time
import traceback
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Iterable

from apscheduler.events import EVENT_JOB_MISSED, EVENT_JOB_SUBMITTED
from apscheduler.triggers.calendarinterval import CalendarIntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from nonebot import require

from ..config import (
    AUTO_RESPONSE_MAX_INTERVAL_MINUTES,
    AUTO_RESPONSE_MIN_INTERVAL_MINUTES,
    AUTO_RESPONSE_QUIET_END_HOUR,
    AUTO_RESPONSE_QUIET_START_HOUR,
    TIMER_TOLERANCE_MINUTES,
)
from .schedule import SHANGHAI, occurrence_at_index
from .store import TimerStore

scheduler = require("nonebot_plugin_apscheduler").scheduler

_POINT_JOB_PREFIX = "timer_v2_point_"
_pending_run_times: dict[int, deque[float]] = {}
_point_stores: dict[int, TimerStore] = {}
_listener_scheduler: Any = None


def _point_id_from_job_id(job_id: str) -> int | None:
    if not job_id.startswith(_POINT_JOB_PREFIX):
        return None
    try:
        return int(job_id.removeprefix(_POINT_JOB_PREFIX))
    except ValueError:
        return None


def _clear_point_runtime(point_id: int) -> None:
    _pending_run_times.pop(point_id, None)
    _point_stores.pop(point_id, None)


def _clear_point_runtime_if_complete(point_id: int, store: TimerStore) -> None:
    point = store.get_point(point_id)
    if point is None or point["processed_occurrences"] >= point["planned_occurrences"]:
        _clear_point_runtime(point_id)


def _handle_scheduler_event(event: Any) -> None:
    point_id = _point_id_from_job_id(str(event.job_id))
    if point_id is None:
        return
    if event.code == EVENT_JOB_SUBMITTED:
        pending = _pending_run_times.setdefault(point_id, deque())
        pending.extend(run_time.timestamp() for run_time in event.scheduled_run_times)
        return
    if event.code != EVENT_JOB_MISSED:
        return

    scheduled_at = event.scheduled_run_time.timestamp()
    pending = _pending_run_times.get(point_id)
    if pending is not None:
        try:
            pending.remove(scheduled_at)
        except ValueError:
            pass
    store = _point_stores.get(point_id)
    if store is not None:
        store.mark_occurrence_processed(point_id, scheduled_at)
        _clear_point_runtime_if_complete(point_id, store)


def _ensure_scheduler_listener() -> None:
    global _listener_scheduler
    if _listener_scheduler is scheduler:
        return
    scheduler.add_listener(
        _handle_scheduler_event,
        EVENT_JOB_SUBMITTED | EVENT_JOB_MISSED,
    )
    _listener_scheduler = scheduler


def build_trigger(
    task: dict[str, Any],
    point: dict[str, Any],
    *,
    start_at: float | None = None,
) -> DateTrigger | IntervalTrigger | CalendarIntervalTrigger:
    """Build the native trigger for the point's next retained occurrence."""
    if start_at is None:
        start_at = occurrence_at_index(
            task, point, int(point["processed_occurrences"])
        )
    start_date = datetime.fromtimestamp(start_at, tz=SHANGHAI)
    end_date = datetime.fromtimestamp(point["last_fire_at"], tz=SHANGHAI)
    mode = task["schedule_type"]
    remaining = int(point["planned_occurrences"]) - int(
        point["processed_occurrences"]
    )

    if mode == "at" or remaining == 1:
        return DateTrigger(run_date=start_date, timezone=SHANGHAI)
    if mode == "daily":
        return IntervalTrigger(
            days=int(task["step"]),
            start_date=start_date,
            end_date=end_date,
            timezone=SHANGHAI,
        )
    if mode == "weekly":
        return IntervalTrigger(
            weeks=int(task["step"]),
            start_date=start_date,
            end_date=end_date,
            timezone=SHANGHAI,
        )
    if mode == "monthly":
        return CalendarIntervalTrigger(
            months=int(task["step"]),
            hour=start_date.hour,
            minute=start_date.minute,
            second=start_date.second,
            start_date=start_date.date(),
            end_date=end_date.date(),
            timezone=SHANGHAI,
        )
    raise ValueError(f"unsupported schedule type: {mode}")


def register_point(point: dict[str, Any], store: TimerStore) -> str:
    """Register one native APScheduler job for an incomplete schedule point."""
    task = store.get_task(int(point["task_id"]))
    if task is None:
        raise KeyError(point["task_id"])
    point_id = int(point["id"])
    _clear_point_runtime(point_id)
    _point_stores[point_id] = store
    try:
        _ensure_scheduler_listener()
        next_at = occurrence_at_index(
            task, point, int(point["processed_occurrences"])
        )
        trigger = build_trigger(task, point, start_at=next_at)
        job_id = str(point["job_id"])
        scheduler.add_job(
            _execute_wrapper,
            trigger,
            id=job_id,
            args=[int(point["id"]), store],
            next_run_time=datetime.fromtimestamp(next_at, tz=SHANGHAI),
            misfire_grace_time=TIMER_TOLERANCE_MINUTES * 60,
            coalesce=False,
            replace_existing=True,
        )
    except BaseException:
        _clear_point_runtime(point_id)
        raise
    return job_id


def cancel_point_job(point_id: int) -> None:
    """Cancel one point job, tolerating an already-absent scheduler entry."""
    _clear_point_runtime(point_id)
    try:
        scheduler.remove_job(f"{_POINT_JOB_PREFIX}{point_id}")
    except Exception:
        pass


def cancel_task_jobs(task_id: int, store: TimerStore) -> None:
    """Cancel every scheduler job owned by a task."""
    for point in store.get_points_for_task(task_id):
        cancel_point_job(int(point["id"]))


def add_jobs_for_task(task_id: int, store: TimerStore) -> None:
    """Register native jobs for all incomplete points owned by a task."""
    for point in store.get_points_for_task(task_id):
        if point["processed_occurrences"] < point["planned_occurrences"]:
            register_point(point, store)


def _random_response_trigger() -> float:
    """Return a random timestamp within the configured interval from now."""
    delay_minutes = random.uniform(
        AUTO_RESPONSE_MIN_INTERVAL_MINUTES,
        AUTO_RESPONSE_MAX_INTERVAL_MINUTES,
    )
    return (datetime.now(SHANGHAI) + timedelta(minutes=delay_minutes)).timestamp()


def _is_auto_response_quiet_time(triggered_at: float) -> bool:
    """Return whether a scheduled trigger falls within Shanghai quiet hours."""
    trigger_hour = datetime.fromtimestamp(triggered_at, SHANGHAI).hour
    return AUTO_RESPONSE_QUIET_START_HOUR <= trigger_hour < AUTO_RESPONSE_QUIET_END_HOUR


async def _execute_auto_response(
    task: dict[str, Any], store: TimerStore, *, triggered_at: float
) -> None:
    """Inject an internal auto-response and immediately schedule its successor."""
    group_id = int(task["group_id"])
    if group_id <= 0:
        print(f"[auto_response] Skipped invalid group_id={group_id}")
        return

    try:
        if _is_auto_response_quiet_time(triggered_at):
            print("[auto_response] Skipped: scheduled during quiet hours")
            return

        from ..graph.nodes import inject_timer

        inject_timer(
            user_id=0,
            group_id=group_id,
            timer_prompt=task["prompt"],
            start_conversation_cb=_timer_start_conv_cb,
        )
    finally:
        reschedule_auto_response(store, group_id)


def reschedule_auto_response(
    store: TimerStore, group_id: int, *, register_job: bool = True
) -> None:
    """Replace one group's internal task with a random future exact-time point."""
    task_id = store.upsert_auto_response(group_id, _random_response_trigger())
    if register_job:
        add_jobs_for_task(task_id, store)


def ensure_auto_response_for_group(store: TimerStore, group_id: int) -> None:
    """Ensure one group owns exactly one future auto-response point."""
    point = store.get_auto_response_point(group_id)
    if point is not None and float(point["exact_at"]) > time.time():
        if scheduler.get_job(str(point["job_id"])) is None:
            register_point(point, store)
        return
    if point is not None:
        cancel_point_job(int(point["id"]))
    store.delete_auto_response_tasks(group_id)
    reschedule_auto_response(store, group_id)


def _normalize_group_ids(group_ids: Iterable[int]) -> set[int]:
    normalized: set[int] = set()
    for group_id in group_ids:
        if (
            isinstance(group_id, bool)
            or not isinstance(group_id, int)
            or group_id <= 0
        ):
            raise ValueError("group_id must be a positive integer")
        normalized.add(group_id)
    return normalized


def remove_ineligible_auto_response_groups(
    store: TimerStore, group_ids: Iterable[int]
) -> None:
    """Delete auto-response tasks whose groups no longer own memory."""
    eligible_group_ids = _normalize_group_ids(group_ids)
    stored_group_ids = set(store.list_auto_response_group_ids())
    for group_id in sorted(stored_group_ids - eligible_group_ids):
        if group_id > 0:
            point = store.get_auto_response_point(group_id)
            if point is not None:
                cancel_point_job(int(point["id"]))
        store.delete_auto_response_tasks(group_id)


async def refresh_auto_responses(
    store: TimerStore,
    group_ids: Iterable[int],
    *,
    routable_group_ids: Iterable[int] | None = None,
) -> None:
    """Synchronize per-group auto-response points with memory-owned groups."""
    eligible_group_ids = _normalize_group_ids(group_ids)
    routable = (
        eligible_group_ids
        if routable_group_ids is None
        else _normalize_group_ids(routable_group_ids)
    )
    remove_ineligible_auto_response_groups(store, eligible_group_ids)

    now = time.time()
    for group_id in sorted(eligible_group_ids):
        point = store.get_auto_response_point(group_id)
        if point is not None and float(point["exact_at"]) > now:
            if group_id in routable:
                register_point(point, store)
            continue
        if point is not None:
            cancel_point_job(int(point["id"]))
        store.delete_auto_response_tasks(group_id)
        reschedule_auto_response(
            store,
            group_id,
            register_job=group_id in routable,
        )


async def reload_all_schedules(
    store: TimerStore,
    *,
    now: float | None = None,
    group_ids: Iterable[int] | None = None,
) -> None:
    """Recover incomplete points, compensating only the latest recent fire."""
    current = time.time() if now is None else now
    tolerance = TIMER_TOLERANCE_MINUTES * 60
    routable_group_ids = (
        None if group_ids is None else _normalize_group_ids(group_ids)
    )

    for stored_point in store.list_incomplete_points():
        point_id = int(stored_point["id"])
        task = store.get_task(int(stored_point["task_id"]))
        if task is None:
            continue
        if (
            routable_group_ids is not None
            and int(task["group_id"]) not in routable_group_ids
        ):
            continue

        due: list[float] = []
        index = int(stored_point["processed_occurrences"])
        planned = int(stored_point["planned_occurrences"])
        while index < planned:
            scheduled_at = occurrence_at_index(task, stored_point, index)
            if scheduled_at > current:
                break
            due.append(scheduled_at)
            index += 1

        compensate_at: float | None = None
        if due and current - due[-1] <= tolerance:
            compensate_at = due.pop()
        for scheduled_at in due:
            store.mark_occurrence_processed(point_id, scheduled_at)
        if compensate_at is not None:
            await _execute_point(point_id, store, scheduled_at=compensate_at)

        point = store.get_point(point_id)
        if (
            point is not None
            and point["processed_occurrences"] < point["planned_occurrences"]
        ):
            next_at = occurrence_at_index(
                task, point, int(point["processed_occurrences"])
            )
            if next_at > current:
                register_point(point, store)


async def cleanup_finished_tasks(store: TimerStore) -> None:
    """Cancel and delete completed normal tasks."""
    for task_id in store.list_finished_task_ids():
        cancel_task_jobs(task_id, store)
    store.delete_finished_tasks()


def register_cleanup_job(store: TimerStore) -> None:
    """Register the daily 03:00:00 China Standard Time cleanup job."""
    scheduler.add_job(
        cleanup_finished_tasks,
        CronTrigger(hour=3, minute=0, second=0, timezone=SHANGHAI),
        id="timer_v2_cleanup",
        args=[store],
        replace_existing=True,
    )


async def _execute_wrapper(point_id: int, store: TimerStore) -> None:
    """APScheduler entry point that reconciles submitted run timestamps."""
    point = store.get_point(point_id)
    if point is None or point["processed_occurrences"] >= point["planned_occurrences"]:
        _clear_point_runtime(point_id)
        return
    task = store.get_task(int(point["task_id"]))
    if task is None:
        _clear_point_runtime(point_id)
        return

    pending = _pending_run_times.get(point_id)
    if pending is not None:
        cutoff = time.time() - TIMER_TOLERANCE_MINUTES * 60
        while pending and pending[0] < cutoff:
            store.mark_occurrence_processed(point_id, pending.popleft())
        if not pending:
            _clear_point_runtime_if_complete(point_id, store)
            return
        scheduled_at = pending.popleft()
    else:
        scheduled_at = occurrence_at_index(
            task, point, int(point["processed_occurrences"])
        )

    try:
        await _execute_point(point_id, store, scheduled_at=scheduled_at)
    finally:
        _clear_point_runtime_if_complete(point_id, store)


async def _execute_point(
    point_id: int,
    store: TimerStore,
    *,
    scheduled_at: float | None = None,
) -> None:
    """Execute one retained occurrence and advance durable progress."""
    point = store.get_point(point_id)
    if point is None or point["processed_occurrences"] >= point["planned_occurrences"]:
        return
    task = store.get_task(int(point["task_id"]))
    if task is None:
        return
    if scheduled_at is None:
        scheduled_at = occurrence_at_index(
            task, point, int(point["processed_occurrences"])
        )

    if task["task_type"] == "auto_response":
        if store.mark_occurrence_processed(point_id, scheduled_at):
            await _execute_auto_response(task, store, triggered_at=scheduled_at)
        return

    user_id = int(task["user_id"])
    group_id = int(task["group_id"])
    user_name: str | None = None
    try:
        from ..group_runtime import group_runtime_registry
        from ..utils import get_group_member_name

        if user_id != 0:
            user_name = await get_group_member_name(
                group_runtime_registry.get_bot(group_id),
                group_id,
                user_id,
            )
    except Exception:
        print(
            f"[timer-v2] Cannot resolve user {user_id} in group {group_id}; "
            "injecting without a display name"
        )

    try:
        await _inject_timer_to_graph(
            user_id, group_id, str(task["prompt"]), user_name=user_name
        )
    except Exception:
        print(f"[timer-v2] Timer injection failed for task {task['id']}")
        traceback.print_exc()
    finally:
        store.mark_occurrence_processed(point_id, scheduled_at)


_timer_start_conv_cb: Any = None


def set_timer_conv_callback(cb: Any) -> None:
    """Set the callback used when a timer starts an inactive conversation."""
    global _timer_start_conv_cb
    _timer_start_conv_cb = cb


async def _inject_timer_to_graph(
    user_id: int,
    group_id: int,
    task_prompt: str,
    user_name: str | None = None,
) -> None:
    """Inject a normal timer occurrence into the shared conversation graph."""
    from ..graph.nodes import inject_timer

    inject_timer(
        user_id=user_id,
        group_id=group_id,
        timer_prompt=task_prompt,
        start_conversation_cb=_timer_start_conv_cb,
        notified_user_name=user_name,
    )
