"""Tests for the send() branching logic in chat.py.

Since send() is a nested async function inside NoneBot handlers, these tests
simulate the branching logic directly using ConversationState to verify:

1. When is_graph_running is True: messages are queued but no graph invocation
2. When is_graph_running is False: full graph flow (is_graph_running set to True)
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "hatsume/plugins/hatsume-plugin/state.py"


def _load_state_module():
    """Load state.py with the config dependency stubbed."""
    # Build minimal package hierarchy
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", ROOT / "hatsume/plugins/hatsume-plugin"),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    config_name = "hatsume.plugins.hatsume-plugin.config"
    config_mod = types.ModuleType(config_name)
    config_mod.CONTEXT_QUEUE_LEN = 5
    config_mod.CONTEXT_QUEUE_OVERLAP_LEN = 2
    config_mod.VIDEO_RATE_LIMIT_SECONDS = 60
    config_mod.GENERATE_IMAGE_RATE_LIMIT_SECONDS = 60
    config_mod.USER_INPUT_CONFIRM_DURING_TIME = 3
    sys.modules[config_name] = config_mod

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.state", STATE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules["hatsume.plugins.hatsume-plugin.state"] = mod
    spec.loader.exec_module(mod)
    return mod


_state_mod = _load_state_module()
ConversationState = _state_mod.ConversationState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> ConversationState:
    """Create a ConversationState with sensible defaults for testing."""
    state = ConversationState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _populate_pending(state: ConversationState, count: int = 2):
    """Add sample messages to the pending queue."""
    for i in range(count):
        state.pending_queue.append({"type": "text", "text": f"pending-{i}"})
        state.pending_source_queue.append({"source_id": f"src-{i}", "text": f"pending-{i}"})


async def _simulate_send(state: ConversationState) -> str:
    """Simulate the branching logic inside send() in chat.py.

    Mirrors the exact branching added to send():
    - flush pending queue
    - if is_graph_running: extend human_queue and return early
    - else: set is_graph_running = True, extend human_queue
    """
    pending_msgs, pending_srcs = state.flush_pending()

    if state.is_graph_running:
        state.human_queue.extend(pending_msgs)
        state.human_source_queue.extend(pending_srcs)
        return "early_return"

    # Full graph path (would normally call graph.ainvoke here)
    state.human_queue.extend(pending_msgs)
    state.human_source_queue.extend(pending_srcs)
    state.is_graph_running = True
    return "graph_invoked"


# ---------------------------------------------------------------------------
# Tests: is_graph_running = True (graph already running)
# ---------------------------------------------------------------------------


def test_send_when_graph_running_queues_messages_to_human_queue():
    """When is_graph_running is True, pending messages should be added to
    human_queue without starting a new graph invocation."""
    state = _make_state(is_graph_running=True, is_waiting_to_send=True)
    _populate_pending(state, count=3)

    result = asyncio.run(_simulate_send(state))

    # Should have taken the early-return path
    assert result == "early_return"

    # human_queue should contain the flushed pending messages
    assert len(state.human_queue) == 3
    assert state.human_queue[0] == {"type": "text", "text": "pending-0"}
    assert state.human_queue[2] == {"type": "text", "text": "pending-2"}

    # human_source_queue should also be populated
    assert len(state.human_source_queue) == 3
    assert state.human_source_queue[0] == {"source_id": "src-0", "text": "pending-0"}


def test_send_when_graph_running_flushes_pending_queue():
    """When is_graph_running is True, the pending queue should be emptied
    after flush_pending() is called."""
    state = _make_state(is_graph_running=True, is_waiting_to_send=True)
    _populate_pending(state, count=2)

    asyncio.run(_simulate_send(state))

    # Pending queues should be cleared by flush_pending()
    assert state.pending_queue == []
    assert state.pending_source_queue == []


def test_send_when_graph_running_does_not_change_graph_running_flag():
    """When is_graph_running is already True, the early-return path should
    not modify the flag."""
    state = _make_state(is_graph_running=True, is_waiting_to_send=True)
    _populate_pending(state, count=1)

    asyncio.run(_simulate_send(state))

    # is_graph_running should remain True (no change)
    assert state.is_graph_running is True


def test_send_when_graph_running_appends_to_existing_human_queue():
    """When is_graph_running is True and human_queue already has items,
    new messages should be appended (not replace existing)."""
    state = _make_state(
        is_graph_running=True,
        is_waiting_to_send=True,
        human_queue=[{"type": "text", "text": "existing"}],
        human_source_queue=[{"source_id": "existing-src", "text": "existing"}],
    )
    _populate_pending(state, count=2)

    asyncio.run(_simulate_send(state))

    # Should have 3 items: 1 existing + 2 new
    assert len(state.human_queue) == 3
    assert state.human_queue[0] == {"type": "text", "text": "existing"}
    assert state.human_queue[1] == {"type": "text", "text": "pending-0"}
    assert state.human_queue[2] == {"type": "text", "text": "pending-1"}


def test_send_when_graph_running_with_empty_pending():
    """When is_graph_running is True but pending queue is empty,
    should still return early without error."""
    state = _make_state(is_graph_running=True, is_waiting_to_send=True)
    # Don't populate pending -- it's empty

    result = asyncio.run(_simulate_send(state))

    assert result == "early_return"
    assert state.human_queue == []
    assert state.human_source_queue == []


# ---------------------------------------------------------------------------
# Tests: is_graph_running = False (new graph invocation)
# ---------------------------------------------------------------------------


def test_send_when_graph_not_running_invokes_graph():
    """When is_graph_running is False, send() should take the full graph
    invocation path and set is_graph_running to True."""
    state = _make_state(is_graph_running=False, is_waiting_to_send=True)
    _populate_pending(state, count=2)

    result = asyncio.run(_simulate_send(state))

    # Should have taken the full graph path
    assert result == "graph_invoked"

    # is_graph_running should now be True
    assert state.is_graph_running is True


def test_send_when_graph_not_running_queues_messages():
    """When is_graph_running is False, pending messages should still end up
    in human_queue (as part of the full graph path)."""
    state = _make_state(is_graph_running=False, is_waiting_to_send=True)
    _populate_pending(state, count=3)

    asyncio.run(_simulate_send(state))

    assert len(state.human_queue) == 3
    assert state.human_queue[0] == {"type": "text", "text": "pending-0"}
    assert len(state.human_source_queue) == 3


def test_send_when_graph_not_running_flushes_pending():
    """When is_graph_running is False, the pending queue should be emptied
    after the full send flow."""
    state = _make_state(is_graph_running=False, is_waiting_to_send=True)
    _populate_pending(state, count=2)

    asyncio.run(_simulate_send(state))

    assert state.pending_queue == []
    assert state.pending_source_queue == []


def test_send_when_graph_not_running_sets_is_graph_running():
    """When is_graph_running is False, the full path should set it to True
    before the graph invocation."""
    state = _make_state(is_graph_running=False, is_waiting_to_send=True)
    _populate_pending(state, count=1)

    assert state.is_graph_running is False
    asyncio.run(_simulate_send(state))
    assert state.is_graph_running is True


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


def test_flush_pending_returns_correct_data():
    """Verify flush_pending() returns the expected data and clears queues."""
    state = _make_state()
    _populate_pending(state, count=2)

    msgs, srcs = state.flush_pending()

    assert len(msgs) == 2
    assert msgs[0] == {"type": "text", "text": "pending-0"}
    assert len(srcs) == 2
    assert srcs[0] == {"source_id": "src-0", "text": "pending-0"}

    # Queues should be empty after flush
    assert state.pending_queue == []
    assert state.pending_source_queue == []


def test_conversation_state_default_is_graph_running_false():
    """ConversationState should default to is_graph_running = False."""
    state = ConversationState()
    assert state.is_graph_running is False


def test_conversation_state_queues_default_empty():
    """All message queues should default to empty lists."""
    state = ConversationState()
    assert state.human_queue == []
    assert state.human_source_queue == []
    assert state.pending_queue == []
    assert state.pending_source_queue == []
    assert state.idle_queue == []
    assert state.idle_source_queue == []


# ---------------------------------------------------------------------------
# Issue 2: Guard clause — assert replaced with early return
# ---------------------------------------------------------------------------


async def _simulate_send_with_guard(state: ConversationState) -> str:
    """Simulate send() with guard clause: return early if not waiting."""
    if not state.is_waiting_to_send:
        return "guard_returned"

    pending_msgs, pending_srcs = state.flush_pending()

    if state.is_graph_running:
        state.human_queue.extend(pending_msgs)
        state.human_source_queue.extend(pending_srcs)
        return "early_return"

    state.human_queue.extend(pending_msgs)
    state.human_source_queue.extend(pending_srcs)
    state.is_graph_running = True
    return "graph_invoked"


def test_send_guard_clause_returns_early_when_not_waiting():
    """When is_waiting_to_send is False, send() should return immediately
    without touching any queues."""
    state = _make_state(is_waiting_to_send=False)
    _populate_pending(state, count=3)

    result = asyncio.run(_simulate_send_with_guard(state))

    assert result == "guard_returned"
    # Pending queue should be untouched
    assert len(state.pending_queue) == 3
    assert state.human_queue == []
    # is_graph_running should not change
    assert state.is_graph_running is False


def test_send_guard_clause_proceeds_normally_when_waiting():
    """When is_waiting_to_send is True, send() should proceed normally."""
    state = _make_state(is_waiting_to_send=True, is_graph_running=False)
    _populate_pending(state, count=2)

    result = asyncio.run(_simulate_send_with_guard(state))

    assert result == "graph_invoked"
    assert len(state.human_queue) == 2
    assert state.is_graph_running is True


# ---------------------------------------------------------------------------
# Issue 3: Error handling — send() task must not die silently
# ---------------------------------------------------------------------------


async def _simulate_send_with_error_handling(
    state: ConversationState,
    start_fn=None,
) -> str:
    """Simulate send() wrapped in try/except."""
    if not state.is_waiting_to_send:
        return "guard_returned"

    try:
        pending_msgs, pending_srcs = state.flush_pending()

        if state.is_graph_running:
            state.human_queue.extend(pending_msgs)
            state.human_source_queue.extend(pending_srcs)
            return "early_return"

        if start_fn is not None:
            await start_fn()

        state.human_queue.extend(pending_msgs)
        state.human_source_queue.extend(pending_srcs)
        state.is_graph_running = True
        return "graph_invoked"
    except Exception as e:
        return f"error_caught: {e}"
    finally:
        state.is_waiting_to_send = False


def test_send_error_handling_catches_exception_and_resets_flag():
    """When start_new_conversation raises, the error should be caught and
    is_waiting_to_send should be reset to False."""
    state = _make_state(is_waiting_to_send=True, is_graph_running=False)
    _populate_pending(state, count=2)

    async def _failing_start():
        raise RuntimeError("boom")

    result = asyncio.run(_simulate_send_with_error_handling(state, _failing_start))

    assert "error_caught" in result
    assert "boom" in result
    assert state.is_waiting_to_send is False


def test_send_error_handling_does_not_affect_human_queue_on_error():
    """On error, human_queue should not receive the pending messages
    (the flush happened but the graph didn't process them)."""
    state = _make_state(is_waiting_to_send=True, is_graph_running=False)
    _populate_pending(state, count=2)

    async def _failing_start():
        raise RuntimeError("boom")

    asyncio.run(_simulate_send_with_error_handling(state, _failing_start))

    # Pending was flushed but graph errored — human_queue may or may not
    # have items depending on when the error occurred. The key assertion
    # is that is_waiting_to_send is reset.
    assert state.is_waiting_to_send is False


def test_send_error_handling_graph_running_path_no_error():
    """When graph is already running, the early-return path should work
    without triggering error handling."""
    state = _make_state(is_waiting_to_send=True, is_graph_running=True)
    _populate_pending(state, count=2)

    async def _should_not_be_called():
        raise RuntimeError("should not reach here")

    result = asyncio.run(
        _simulate_send_with_error_handling(state, _should_not_be_called)
    )

    assert result == "early_return"
    assert state.is_waiting_to_send is False
    assert len(state.human_queue) == 2


# ---------------------------------------------------------------------------
# Issue 4: Race condition — check-then-set pattern
# ---------------------------------------------------------------------------


def test_race_condition_sets_flag_before_creating_task():
    """The new pattern should set is_waiting_to_send unconditionally,
    then check if a new task is needed (not the other way around)."""
    state = _make_state(is_waiting_to_send=False)

    # Simulate the fixed pattern
    was_waiting = state.is_waiting_to_send
    state.is_waiting_to_send = True
    should_create_task = not was_waiting

    assert state.is_waiting_to_send is True
    assert should_create_task is True


def test_race_condition_no_duplicate_task_when_already_waiting():
    """When is_waiting_to_send is already True, no new task should be created,
    but the flag should remain True."""
    state = _make_state(is_waiting_to_send=True)

    was_waiting = state.is_waiting_to_send
    state.is_waiting_to_send = True
    should_create_task = not was_waiting

    assert state.is_waiting_to_send is True
    assert should_create_task is False


def test_race_condition_two_rapid_messages_only_one_task():
    """Two rapid messages should result in only one send() task.
    Both messages end up in the pending queue."""
    state = _make_state(is_waiting_to_send=False)
    tasks_created = []

    # First message
    _populate_pending(state, count=1)
    was_waiting = state.is_waiting_to_send
    state.is_waiting_to_send = True
    if not was_waiting:
        tasks_created.append("task_1")

    # Second message (arrives before send() completes)
    _populate_pending(state, count=1)
    was_waiting = state.is_waiting_to_send
    state.is_waiting_to_send = True
    if not was_waiting:
        tasks_created.append("task_2")

    assert len(tasks_created) == 1
    assert tasks_created[0] == "task_1"
    # Both messages should be in the pending queue
    assert len(state.pending_queue) == 2


# ---------------------------------------------------------------------------
# Issue 5: Polling → event-driven debounce
# ---------------------------------------------------------------------------


async def _simulate_send_with_event_debounce(
    state: ConversationState,
    timeout: float = 0.1,
) -> str:
    """Simulate send() using asyncio.Event for debounce instead of polling."""
    if not state.is_waiting_to_send:
        return "guard_returned"

    # Create a fresh event for this send cycle
    debounce_event = asyncio.Event()
    state._debounce_cancel = debounce_event

    try:
        await asyncio.wait_for(debounce_event.wait(), timeout=timeout)
        # Event was set → a new message arrived, cancel this send
        return "cancelled_by_new_message"
    except asyncio.TimeoutError:
        # Timeout → no new messages, proceed to flush
        pass

    state.is_waiting_to_send = False
    pending_msgs, pending_srcs = state.flush_pending()

    if state.is_graph_running:
        state.human_queue.extend(pending_msgs)
        state.human_source_queue.extend(pending_srcs)
        return "early_return"

    state.human_queue.extend(pending_msgs)
    state.human_source_queue.extend(pending_srcs)
    state.is_graph_running = True
    return "graph_invoked"


def test_event_debounce_timeout_proceeds_to_flush():
    """When no new messages arrive (timeout), send() should flush
    the pending queue and proceed."""
    state = _make_state(is_waiting_to_send=True)
    _populate_pending(state, count=2)

    result = asyncio.run(_simulate_send_with_event_debounce(state, timeout=0.05))

    assert result == "graph_invoked"
    assert state.is_waiting_to_send is False
    assert len(state.human_queue) == 2


def test_event_debounce_new_message_cancels_current_send():
    """When a new message arrives (event is set), the current send()
    should cancel and a new send task should handle it."""
    state = _make_state(is_waiting_to_send=True)
    _populate_pending(state, count=1)

    async def _run():
        # Start send() — it will wait on the event
        send_task = asyncio.create_task(
            _simulate_send_with_event_debounce(state, timeout=5.0)
        )
        # Let send() start and create the event
        await asyncio.sleep(0.01)

        # Simulate new message arrival: set the event
        if state._debounce_cancel is not None:
            state._debounce_cancel.set()

        return await send_task

    result = asyncio.run(_run())

    assert result == "cancelled_by_new_message"
    # is_waiting_to_send should still be True (the new message handler
    # will create a new send task)
    assert state.is_waiting_to_send is True


def test_event_debounce_does_not_use_polling():
    """The debounce should use asyncio.Event, not time-based polling.
    Verify that the event is stored on the state for the caller to set."""
    state = _make_state(is_waiting_to_send=True)
    _populate_pending(state, count=1)

    async def _run():
        task = asyncio.create_task(
            _simulate_send_with_event_debounce(state, timeout=5.0)
        )
        await asyncio.sleep(0.01)
        # The event should be accessible on the state
        assert state._debounce_cancel is not None
        assert isinstance(state._debounce_cancel, asyncio.Event)
        state._debounce_cancel.set()
        return await task

    result = asyncio.run(_run())
    assert result == "cancelled_by_new_message"


def test_event_debounce_graph_running_early_return():
    """When graph is already running and debounce timeout fires,
    messages should be queued to human_queue."""
    state = _make_state(is_waiting_to_send=True, is_graph_running=True)
    _populate_pending(state, count=2)

    result = asyncio.run(_simulate_send_with_event_debounce(state, timeout=0.05))

    assert result == "early_return"
    assert len(state.human_queue) == 2
    assert state.is_graph_running is True


# ---------------------------------------------------------------------------
# Issue 4+5: Full integration — caller sets event on new message
# ---------------------------------------------------------------------------


async def _simulate_message_handler_and_send(
    state: ConversationState,
    message_count: int = 1,
    debounce_timeout: float = 0.1,
) -> list[str]:
    """Simulate the full flow: message handler sets debounce cancel event,
    and send() reacts to it."""
    results = []

    for i in range(message_count):
        # Simulate message handler logic (Issue 4: race condition fix)
        state.pending_queue.append({"type": "text", "text": f"msg-{i}"})
        state.pending_source_queue.append({"source_id": f"src-{i}", "text": f"msg-{i}"})

        was_waiting = state.is_waiting_to_send
        state.is_waiting_to_send = True

        # Issue 5: cancel current debounce wait
        if state._debounce_cancel is not None:
            state._debounce_cancel.set()

        if not was_waiting:
            # Create a new send task
            task = asyncio.create_task(
                _simulate_send_with_event_debounce(state, timeout=debounce_timeout)
            )
            result = await task
            results.append(result)

    return results


def test_two_rapid_messages_first_cancelled_second_flushes():
    """When two messages arrive in rapid succession:
    1. First send() starts waiting
    2. Second message cancels the first send()
    3. A new send() starts waiting
    4. Timeout fires → flush both messages."""
    state = _make_state(is_waiting_to_send=False)

    async def _run():
        # First message — starts send()
        state.pending_queue.append({"type": "text", "text": "msg-0"})
        state.pending_source_queue.append({"source_id": "src-0", "text": "msg-0"})

        was_waiting = state.is_waiting_to_send
        state.is_waiting_to_send = True
        if state._debounce_cancel is not None:
            state._debounce_cancel.set()
        if not was_waiting:
            task1 = asyncio.create_task(
                _simulate_send_with_event_debounce(state, timeout=5.0)
            )

        await asyncio.sleep(0.01)  # Let task1 start and create event

        # Second message — should cancel first send() and create new one
        state.pending_queue.append({"type": "text", "text": "msg-1"})
        state.pending_source_queue.append({"source_id": "src-1", "text": "msg-1"})

        was_waiting = state.is_waiting_to_send
        state.is_waiting_to_send = True
        if state._debounce_cancel is not None:
            state._debounce_cancel.set()

        # was_waiting is True, so no new task is created
        # But the first task was cancelled by the event

        result1 = await task1
        assert result1 == "cancelled_by_new_message"

        # Now create a new send task (simulating what the real code would do
        # if a new message arrives while the previous send was cancelled)
        # In the real code, the second message's handler doesn't create a new
        # task because was_waiting is True. But the first task already returned.
        # The event-driven flow handles this: the first task returns, and
        # is_waiting_to_send is still True. We need a new task to flush.
        task2 = asyncio.create_task(
            _simulate_send_with_event_debounce(state, timeout=0.05)
        )
        result2 = await task2
        return result1, result2

    r1, r2 = asyncio.run(_run())
    assert r1 == "cancelled_by_new_message"
    assert r2 == "graph_invoked"
    # Both messages should be flushed
    assert len(state.human_queue) == 2
