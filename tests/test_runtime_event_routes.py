"""Exercise production event entrypoints without starting NoneBot or paid models."""

import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from langchain_core.messages import (
    AIMessage,
    ToolMessage,
    HumanMessage,
    SystemMessage,
    RemoveMessage,
)
from langgraph.graph.message import add_messages

ROOT = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"
spec = importlib.util.spec_from_file_location(
    "route_runtime_events", ROOT / "runtime_events.py"
)
events = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = events
spec.loader.exec_module(events)


def functions(file, names, namespace):
    tree = ast.parse((ROOT / file).read_text())
    body = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(ROOT / file), "exec"),
        namespace,
    )
    return namespace


@pytest.fixture
def env():
    state = SimpleNamespace(
        group_id=123,
        is_chatting=False,
        is_graph_running=False,
        human_queue=[],
        human_source_queue=[],
        end_requested=False,
        checked_agent_ids=set(),
    )
    runtime = SimpleNamespace(
        conversation=state,
        current_input_messages=[],
        auxiliary_messages_queue=[],
        last_was_system_trigger=False,
        last_was_auxiliary_only=False,
    )
    ns = {
        "offload_event_output": lambda content: content,
        "tool_origin": events.tool_origin,
        "time": time,
        "asyncio": asyncio,
        "get_date": lambda: "now",
        "_get_ai_answer": lambda: None,
        "_set_current_query_user_id": Mock(),
        "Any": Any,
        "MessagesState": dict,
        "RuntimeEvent": events.RuntimeEvent,
        "enqueue_runtime_event": events.enqueue_runtime_event,
        "stable_event_key": events.stable_event_key,
        "consume_inputs": events.consume_inputs,
        "is_event_message": events.is_event_message,
        "safe_cutoff": events.safe_cutoff,
        "eviction_cutoff": events.eviction_cutoff,
        "group_runtime_registry": SimpleNamespace(get_or_create=lambda gid: runtime),
        "_register_injected_chat_peers": lambda gid, users: [
            user for user in users if type(user) is int and user > 0
        ],
        "_runtime": lambda: runtime,
        "HumanMessage": HumanMessage,
        "SystemMessage": SystemMessage,
        "RemoveMessage": RemoveMessage,
        "_get_human_queue": lambda: state.human_queue,
        "_clear_human_queue": lambda: (
            state.human_queue.clear(),
            state.human_source_queue.clear(),
        ),
        "_set_graph_running": lambda flag: setattr(state, "is_graph_running", flag),
    }
    functions(
        "graph/nodes.py",
        {
            "_build_notified_user_prompt",
            "inject_timer",
            "inject_hook",
            "inject_agent_notification",
            "_deliver_runtime_event",
            "human_node",
            "finish_conversation_node",
        },
        ns,
    )
    ns["_start_direct_conv"] = Mock()
    return state, runtime, ns


@pytest.mark.parametrize("kind", ["timer", "hook", "agent"])
@pytest.mark.parametrize("mode", ["active", "draining", "idle", "callback_failure"])
def test_injectors_preserve_typed_event_across_routes(env, kind, mode):
    state, runtime, ns = env
    state.is_chatting = mode == "active"
    state.is_graph_running = mode == "draining"
    callback = (
        Mock(side_effect=RuntimeError("offline"))
        if mode == "callback_failure"
        else Mock()
    )
    if kind == "timer":
        ns["inject_timer"](
            0,
            123,
            "task",
            start_conversation_cb=callback,
            event_key="occurrence",
            event_data={"source": "auto_response", "task_id": 4},
        )
    elif kind == "hook":
        ns["inject_hook"](
            group_id=123,
            hook_name="watch",
            prompt="notify",
            event_text="changed",
            start_conversation_cb=callback,
            event_key="occurrence",
            event_data={"trigger_type": "heartbeat", "hook_id": 4},
        )
    else:
        ns["inject_agent_notification"](
            0,
            123,
            "coding_agent",
            "done",
            "task",
            start_conversation_cb=callback,
            event_key="occurrence",
        )
    event = callback.call_args.args[2] if mode == "idle" else state.human_queue[0]
    assert isinstance(event, events.RuntimeEvent)
    assert event.event_type == kind
    assert event.occurrence_key == "occurrence"
    if mode in {"active", "draining"}:
        callback.assert_not_called()
    if mode == "callback_failure":
        assert len(state.human_queue) == 1


@pytest.mark.asyncio
async def test_actual_human_node_preserves_batch_and_reducer_ids(env):
    state, runtime, ns = env
    state.human_queue.extend(
        [
            {"type": "text", "text": "A"},
            events.RuntimeEvent("timer", 123, "tick", "timer"),
            {"type": "text", "text": "B"},
        ]
    )
    update = await ns["human_node"]({"messages": []})
    messages = add_messages([], update["messages"])
    assert [m.type for m in messages] == ["human", "ai", "tool", "human"]
    assert {m.id for m in messages} == {m.id for m in runtime.current_input_messages}
    assert not state.human_queue
    assert runtime.last_was_system_trigger
    assert events.assemble_input([], runtime.current_input_messages, [], []) == messages


@pytest.mark.asyncio
async def test_finish_keeps_events_arriving_during_final_turn(env):
    state, runtime, ns = env
    event = events.RuntimeEvent("timer", 123, "late", "timer")
    state.human_queue.extend([{"type": "text", "text": "old"}, event])
    await ns["finish_conversation_node"]({"messages": []})
    assert state.human_queue == [event]


def test_removed_generic_startup_parameters():
    tree = ast.parse((ROOT / "handlers/dialogue.py").read_text())
    start = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "start_new_conversation"
    )
    names = {arg.arg for arg in start.args.kwonlyargs}
    assert "runtime_event" in names
    assert not {"system_task_text", "system_trigger_type"} & names


def test_real_call_provenance_is_optional_and_group_scoped():
    token = events.bind_tool_origin(
        {"name": "create_at_timer", "id": "real_call", "args": {"prompt": "hello"}}
    )
    try:
        events.remember_tool_origin(123, "timer", 42)
    finally:
        events.reset_tool_origin(token)
    origin = events.tool_origin(123, "timer", 42)
    assert origin["original_tool_call_id"] == "real_call"
    assert events.tool_origin(456, "timer", 42) == {}
    assert events.tool_origin(123, "hook", 42) == {}
    events.remember_tool_origin(123, "timer", 43)
    assert events.tool_origin(123, "timer", 43) == {}
    pair = events.event_messages(
        events.RuntimeEvent("timer", 123, "tick", "timer", **origin)
    )
    assert pair[0].tool_calls[0]["args"]["original_tool_call_id"] == "real_call"
    assert pair[0].tool_calls[0]["id"] != "real_call"


@pytest.mark.asyncio
async def test_parallel_origin_context_is_isolated():
    async def register(call_id, task_id):
        token = events.bind_tool_origin(
            {"name": "agent_dispatch", "id": call_id, "args": {}}
        )
        try:
            await asyncio.sleep(0)
            events.remember_tool_origin(123, "agent", task_id)
        finally:
            events.reset_tool_origin(token)

    await asyncio.gather(register("call_a", "agent_a"), register("call_b", "agent_b"))
    assert (
        events.tool_origin(123, "agent", "agent_a")["original_tool_call_id"] == "call_a"
    )
    assert (
        events.tool_origin(123, "agent", "agent_b")["original_tool_call_id"] == "call_b"
    )


def test_eviction_advances_past_multi_tool_exchange():
    messages = [
        AIMessage(
            "",
            tool_calls=[
                {"name": "tool", "args": {}, "id": name}
                for name in ("one", "two", "three")
            ],
        ),
        *[ToolMessage("result", tool_call_id=name) for name in ("one", "two", "three")],
        HumanMessage("next"),
    ]
    assert events.safe_cutoff(messages, 2) == 0
    assert events.eviction_cutoff(messages, 2) == 4


@pytest.mark.asyncio
async def test_finish_preserves_event_body_beyond_old_three_thousand_limit(env):
    state, runtime, ns = env
    event = events.RuntimeEvent("timer", 123, "x" * 5000 + "IMPORTANT_TAIL", "timer")
    from unittest.mock import AsyncMock

    archived = AsyncMock()
    ns["append_auxiliary_message_async"] = archived
    ns["json"] = __import__("json")
    ns["mask_secret_keys"] = lambda value: value
    await ns["finish_conversation_node"]({"messages": events.event_messages(event)})
    assert "IMPORTANT_TAIL" in str(archived.call_args.args[0])


@pytest.mark.asyncio
async def test_consumption_restores_event_notification_peers(env):
    state, runtime, ns = env
    register = Mock(return_value=[456])
    ns["_register_injected_chat_peers"] = register
    state.human_queue.append(
        events.RuntimeEvent("timer", 123, "tick", "timer", notified_user_ids=(456,))
    )
    await ns["human_node"]({"messages": []})
    register.assert_called_once_with(123, [456])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "cancelled", "stopping"])
async def test_startup_replay_occurs_only_after_normal_completion(mode):
    import contextlib
    from unittest.mock import AsyncMock

    state = SimpleNamespace(
        group_id=123,
        end_requested=False,
        human_queue=[],
        human_source_queue=[],
        _graph_task=None,
        checked_agent_ids=set(),
        is_graph_running=False,
        is_generate_image_rate_limited=lambda: False,
        update_generate_image_time=lambda: None,
        request_end_conversation=lambda: None,
    )
    runtime = SimpleNamespace(
        group_id=123,
        stopping=mode == "stopping",
        conversation=state,
        graph_start_lock=asyncio.Lock(),
    )
    event = events.RuntimeEvent("timer", 123, "late", "timer", notified_user_ids=(456,))
    entered = asyncio.Event()

    async def invoke(*args):
        entered.set()
        if mode == "cancelled":
            await asyncio.Event().wait()
        state.human_queue.append(event)

    tree = ast.parse((ROOT / "handlers/dialogue.py").read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "start_new_conversation"
    )

    class DependencyImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            return None

    node = DependencyImports().visit(node)
    ast.fix_missing_locations(node)
    replay = Mock()
    ns = {
        "GroupRuntime": Any,
        "RuntimeEvent": events.RuntimeEvent,
        "asyncio": asyncio,
        "bind_group_runtime": lambda runtime: contextlib.nullcontext(),
        "SystemMessage": SystemMessage,
        "enqueue_runtime_event": events.enqueue_runtime_event,
        "get_role_sys_prompt": lambda: "role",
        "graph": SimpleNamespace(ainvoke=invoke),
        "get_mcp_manager": lambda: SimpleNamespace(close_conversation=AsyncMock()),
        "set_current_query_user_id": Mock(),
        "_start_conv_for_trigger": replay,
    }
    exec(
        compile(
            ast.Module(body=[node], type_ignores=[]), "dialogue-startup-test", "exec"
        ),
        ns,
    )
    task = asyncio.create_task(
        ns["start_new_conversation"](
            runtime, None, Mock(), runtime_event=event if mode == "stopping" else None
        )
    )
    if mode == "cancelled":
        await entered.wait()
        state.human_queue.append(event)
        state._graph_task.cancel()
    await task
    if mode == "normal":
        replay.assert_called_once_with(456, 123, event)
    else:
        replay.assert_not_called()
    if mode == "stopping":
        assert state.human_queue == [event]
        assert not entered.is_set()
