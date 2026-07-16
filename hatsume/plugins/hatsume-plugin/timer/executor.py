"""Timer executor: APScheduler job management + graph injection for timer delivery."""

from __future__ import annotations

import asyncio
import random
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any

from nonebot import require

from ..config import AUTO_CREATE_GROUP_ID, TIMER_TOLERANCE_MINUTES
from .store import TimerStore

scheduler = require("nonebot_plugin_apscheduler").scheduler


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------
def _make_job_id(trigger_id: int) -> str:
    return f"timer_{trigger_id}"


def register_job(trigger: dict, store: TimerStore) -> str:
    """Register an APScheduler date job for a trigger."""
    from apscheduler.triggers.date import DateTrigger
    from datetime import datetime, timezone, timedelta

    trigger_at = trigger["trigger_at"]
    trigger_id = trigger["id"]
    job_id = _make_job_id(trigger_id)
    run_dt = datetime.fromtimestamp(trigger_at, tz=timezone(timedelta(hours=8)))
    ts_str = run_dt.strftime("%Y-%m-%d %H:%M:%S")

    scheduler.add_job(
        _execute_wrapper,
        DateTrigger(run_date=run_dt),
        id=job_id,
        args=[trigger, store],
        misfire_grace_time=300,
        replace_existing=True,
    )
    print(f"⏰ [timer] Job registered: {job_id} at {ts_str}")
    return job_id


def cancel_job(trigger_id: int) -> None:
    """Cancel an APScheduler job by trigger ID."""
    job_id = _make_job_id(trigger_id)
    try:
        scheduler.remove_job(job_id)
        print(f"⏰ [timer] Job cancelled: {job_id}")
    except Exception:
        pass


def cancel_task_jobs(task_id: int, store: TimerStore) -> None:
    """Cancel all APScheduler jobs for a task's pending triggers."""
    triggers = store.get_triggers_for_task(task_id)
    count = 0
    for t in triggers:
        if not t["fired"]:
            cancel_job(t["id"])
            count += 1
    print(f"⏰ [timer] Cancelled {count} jobs for task {task_id}")


def add_jobs_for_task(task_id: int, store: TimerStore) -> None:
    """Register APScheduler jobs for all pending triggers of a task."""
    triggers = store.get_triggers_for_task(task_id)
    now = time.time()
    count = 0
    for t in triggers:
        if not t["fired"] and t["trigger_at"] > now:
            register_job(t, store)
            count += 1
    print(f"⏰ [timer] Added {count} jobs for task {task_id}")


# ---------------------------------------------------------------------------
# Auto Create — random trigger time
# ---------------------------------------------------------------------------

def _random_next_trigger() -> float:
    """Generate a random trigger time in [now+4h, now+6h].

    Returns a Unix timestamp (float).
    """
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    delta_seconds = random.uniform(4 * 3600, 6 * 3600)
    t = now + timedelta(seconds=delta_seconds)
    return t.timestamp()


def _random_response_trigger() -> float:
    """Generate a random trigger time in [now+1h, now+3h].

    No time-window restriction — auto_response runs 24h.
    Returns a Unix timestamp (float).
    """
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    delta_seconds = random.uniform(1 * 3600, 3 * 3600)
    t = now + timedelta(seconds=delta_seconds)
    return t.timestamp()


# ---------------------------------------------------------------------------
# Auto Create — execution and lifecycle
# ---------------------------------------------------------------------------

async def _execute_auto_create(task: dict, store: TimerStore) -> None:
    """Execute an auto_create timer: inject into graph, then reschedule.

    The auto_create task produces creative output visible in the group
    but does NOT @-mention any user (user_id=0).
    Rescheduling happens immediately after injection — we don't wait
    for the LLM to finish processing.
    """
    from ..prompts import get_auto_create_prompt
    from ..graph.nodes import inject_timer

    prompt = task.get("prompt") or get_auto_create_prompt()

    print("🎨 [auto_create] Executing...")
    inject_timer(
        user_id=0,
        group_id=AUTO_CREATE_GROUP_ID,
        timer_prompt=prompt,
        start_conversation_cb=_timer_start_conv_cb,
        is_auto_create=True,
    )

    # Reschedule immediately — fire-and-forget pattern
    reschedule_auto_create(store)


def reschedule_auto_create(store: TimerStore) -> None:
    """Delete the old auto_create task and create a new one with a random
    trigger time in [now+4h, now+6h].

    Registers the new APScheduler job for the random trigger time.
    """
    next_trigger = _random_next_trigger()
    task_id = store.upsert_auto_create(next_trigger)

    triggers = store.get_triggers_for_task(task_id)
    for t in triggers:
        if not t["fired"]:
            register_job(t, store)

    run_dt = datetime.fromtimestamp(next_trigger, tz=timezone(timedelta(hours=8)))
    print(
        f"🎨 [auto_create] Rescheduled: task={task_id} "
        f"next={run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ---------------------------------------------------------------------------
# Auto Response — execution and lifecycle
# ---------------------------------------------------------------------------

async def _execute_auto_response(task: dict, store: TimerStore) -> None:
    """Execute an auto_response timer: inject into graph, then reschedule.

    Mirror of _execute_auto_create — injects the prompt with user_id=0
    (no @-mention) and reschedules immediately (fire-and-forget).
    """
    from ..prompts import get_auto_response_prompt
    from ..graph.nodes import inject_timer
    from ..config import AUTO_RESPONSE_GROUP_ID

    prompt = task.get("prompt") or get_auto_response_prompt()

    print("💬 [auto_response] Executing...")
    inject_timer(
        user_id=0,
        group_id=AUTO_RESPONSE_GROUP_ID,
        timer_prompt=prompt,
        start_conversation_cb=_timer_start_conv_cb,
        is_auto_create=False,
    )

    # Reschedule immediately — fire-and-forget pattern
    reschedule_auto_response(store)


def reschedule_auto_response(store: TimerStore) -> None:
    """Delete the old auto_response task and create a new one with a random
    trigger time in [now+1h, now+3h].

    Registers the new APScheduler job for the random trigger time.
    """
    next_trigger = _random_response_trigger()
    task_id = store.upsert_auto_response(next_trigger)

    triggers = store.get_triggers_for_task(task_id)
    for t in triggers:
        if not t["fired"]:
            register_job(t, store)

    run_dt = datetime.fromtimestamp(next_trigger, tz=timezone(timedelta(hours=8)))
    print(
        f"💬 [auto_response] Rescheduled: task={task_id} "
        f"next={run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def refresh_auto_response(store: TimerStore) -> None:
    """Called on startup: ensure one auto_response task exists with a registered job.

    If a pending auto_response task already exists (not yet triggered), re-register
    its APScheduler job without changing the trigger time.
    Otherwise, create a fresh one via reschedule_auto_response.
    """
    import time as time_mod

    now = time_mod.time()

    # Check for existing pending auto_response trigger
    pending = store.list_auto_response_triggers()
    future_pending = [t for t in pending if t["trigger_at"] > now]

    if future_pending:
        # Re-register jobs for existing pending triggers (lost on restart)
        for t in future_pending:
            register_job(t, store)
        run_dt = datetime.fromtimestamp(
            future_pending[0]["trigger_at"], tz=timezone(timedelta(hours=8))
        )
        print(
            f"💬 [auto_response] Startup: existing task retained, "
            f"next={run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        # No pending trigger — create fresh one
        assert store._conn is not None, "TimerStore not initialized"
        store._conn.execute(
            "DELETE FROM timer_tasks WHERE task_type = 'auto_response'"
        )
        store._conn.commit()
        reschedule_auto_response(store)
        print("💬 [auto_response] Startup refresh complete (new task created)")




# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------
async def reload_all_triggers(store: TimerStore) -> None:
    """Load all pending triggers from DB. Register future ones, compensate
    missed ones within tolerance, expire old ones."""
    now = time.time()
    tolerance = TIMER_TOLERANCE_MINUTES * 60
    assert store._conn is not None, "TimerStore not initialized"
    rows = store._conn.execute(
        "SELECT * FROM timer_triggers WHERE fired = 0 ORDER BY trigger_at"
    ).fetchall()

    print(f"⏰ [timer] Recovery: found {len(rows)} unfired triggers in DB")

    registered = 0
    compensated = 0
    expired = 0
    for row in rows:
        trigger = dict(row)
        trigger_id = trigger["id"]
        trigger_at = trigger["trigger_at"]

        if trigger_at > now:
            job_id = register_job(trigger, store)
            store._conn.execute(
                "UPDATE timer_triggers SET job_id = ? WHERE id = ?",
                (job_id, trigger_id),
            )
            registered += 1
        elif now - trigger_at <= tolerance:
            asyncio.ensure_future(_execute_timer(trigger, store))
            compensated += 1
        else:
            store.mark_trigger_fired(trigger_id)
            expired += 1
    store._conn.commit()
    print(
        f"⏰ [timer] Recovery done: {registered} registered, "
        f"{compensated} compensated, {expired} expired"
    )


# ---------------------------------------------------------------------------
# Timer execution
# ---------------------------------------------------------------------------
async def _execute_wrapper(trigger: dict, store: TimerStore) -> None:
    """APScheduler job entry point."""
    print(f"⏰ [timer] Job triggered: timer_{trigger['id']}")
    await _execute_timer(trigger, store)


async def _execute_timer(trigger: dict, store: TimerStore) -> None:
    """Execute a timer trigger: lookup user, build context, run chat_agent,
    deliver result."""
    trigger_id = trigger["id"]
    task_id = trigger["task_id"]

    print(f"⏰ [timer] Executing trigger {trigger_id} (task {task_id})")

    task = store.get_task(task_id)
    if task is None:
        print(f"⏰ [timer] Task {task_id} not found, skipping")
        return

    # Auto-create tasks take a separate execution path
    if task.get("task_type") == "auto_create":
        # Mark fired before executing (fire-and-forget)
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_create(task, store)
        return

    # Auto-response tasks take a separate execution path
    if task.get("task_type") == "auto_response":
        # Mark fired before executing (fire-and-forget)
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_response(task, store)
        return

    group_id = task["group_id"]
    user_id = task["user_id"]
    prompt = task["prompt"]

    # 1. Look up username — continue even if not found (send without @mention)
    try:
        print(f"⏰ [timer] User lookup OK: {user_id} in group {group_id}")
    except Exception:
        print(f"⏰ [timer] Cannot get user info for {user_id} in group {group_id}, will send without @mention")

    # 2. Inject into the conversation graph (replaces standalone _run_timer_agent)
    t_start = time.time()
    try:
        await _inject_timer_to_graph(
            user_id, group_id, prompt
        )
        elapsed = time.time() - t_start
        print(
            f"⏰ [timer] Timer injected into graph OK: task={task_id} "
            f"elapsed={elapsed:.1f}s"
        )
    except Exception:
        elapsed = time.time() - t_start
        print(f"❌ [timer] Timer injection FAILED: task={task_id} elapsed={elapsed:.1f}s")
        traceback.print_exc()

    # 4. Mark fired (delivery is handled by the graph's ai_node)
    store.mark_trigger_fired(trigger_id)


# Lazy reference to the timer start-conversation callback (set by chat.py)
_timer_start_conv_cb: Any = None


def set_timer_conv_callback(cb: Any) -> None:
    """Set the callback used to start a conversation when a timer fires
    and no conversation is active. Called by handlers/chat.py at import time."""
    global _timer_start_conv_cb
    _timer_start_conv_cb = cb


async def _inject_timer_to_graph(
    user_id: int,
    group_id: int,
    task_prompt: str,
    is_auto_create: bool = False,
) -> None:
    """Inject a timer prompt into the conversation graph.

    Mirrors the agent_dispatch -> inject_agent_notification pattern.
    Builds a __timer__:{user_id} marked message and injects it via
    inject_timer() in graph/nodes.py. The existing LangGraph handles
    everything: human_node picks it up, detect_node routes to continue,
    ai_node @mentions the timer creator.
    """
    from ..graph.nodes import inject_timer

    inject_timer(
        user_id=user_id,
        group_id=group_id,
        timer_prompt=task_prompt,
        start_conversation_cb=_timer_start_conv_cb,
        is_auto_create=is_auto_create,
    )
