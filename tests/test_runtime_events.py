"""Runtime event contracts using real LangChain messages, without plugin startup."""

import asyncio
from dataclasses import replace
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import PrivateAttr


ROOT = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"
PACKAGE = "_hatsume_runtime_event_tests"
EVENT_TYPES = ("agent", "timer", "hook", "sandbox_channel", "group_increase")


@pytest.fixture
def modules(monkeypatch):
    # Real package paths let relative imports work, but never execute __init__.py.
    # Remove imported children too, so no stub package leaks into other tests.
    with monkeypatch.context() as isolated:
        for name, path in ((PACKAGE, ROOT), (f"{PACKAGE}.graph", ROOT / "graph")):
            package = ModuleType(name)
            package.__path__ = [str(path)]
            isolated.setitem(sys.modules, name, package)
        try:
            yield SimpleNamespace(
                events=importlib.import_module(f"{PACKAGE}.runtime_events"),
                loop=importlib.import_module(f"{PACKAGE}.graph.chat_loop"),
                context=importlib.import_module(f"{PACKAGE}.graph.context"),
            )
        finally:
            for name in list(sys.modules):
                if name.startswith(PACKAGE + "."):
                    sys.modules.pop(name, None)


def event(module, event_type="timer", **overrides):
    fields = dict(
        event_type=event_type,
        group_id=123,
        source="fixture",
        text='初芽：任务完成\n下一行 "内容" 🐾',
        payload={"消息": ["你好", {"路径": "/tmp/中文.txt"}], "done": True},
        notified_user_ids=(456, 789),
        correlation_id="任务-123",
        original_tool_name="agent_dispatch",
        original_tool_call_id="original-call",
        original_args={"task": "检查中文"},
        occurrence_key="occurrence-1",
        created_at=1234.5,
    )
    fields.update(overrides)
    return module.RuntimeEvent(**fields)


def assert_pairs(module, messages):
    calls = []
    outputs = []
    for index, message in enumerate(messages):
        if not module.is_event_message(message):
            continue
        if isinstance(message, AIMessage):
            assert len(message.tool_calls) == 1
            call = message.tool_calls[0]
            result = messages[index + 1]
            assert isinstance(result, ToolMessage)
            assert module.is_event_message(result)
            assert call["name"] == result.name == module.INJECTED_EVENT_TOOL
            assert call["id"] == result.tool_call_id
            assert message.additional_kwargs == result.additional_kwargs
            calls.append(call["id"])
        else:
            assert isinstance(message, ToolMessage)
            assert isinstance(messages[index - 1], AIMessage)
            outputs.append(message.tool_call_id)
    assert calls == outputs
    assert len(calls) == len(set(calls))


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_all_event_types_preserve_unicode_provenance_and_call_ids(modules, event_type):
    import json

    module = modules.events
    original = event(module, event_type)
    messages = module.event_messages(original)
    assert_pairs(module, messages)
    call, result = messages
    assert call.content == ""
    assert call.tool_calls[0]["id"] == f"evt_{original.event_id}"
    assert call.tool_calls[0]["args"] == {
        "event_id": original.event_id,
        "event_type": event_type,
        "source": original.source,
        "correlation_id": original.correlation_id,
        "original_tool_name": original.original_tool_name,
        "original_tool_call_id": original.original_tool_call_id,
        "original_args": original.original_args,
    }
    assert json.loads(result.content) == {
        "event_id": original.event_id,
        "event_type": event_type,
        "source": original.source,
        "group_id": 123,
        "created_at": 1234.5,
        "text": original.text,
        "payload": original.payload,
        "notified_user_ids": [456, 789],
        "correlation_id": original.correlation_id,
        "occurrence_key": original.occurrence_key,
    }
    assert "初芽" in result.content and "你好" in result.content
    assert call.id != result.id
    assert module.event_messages(original) == messages
    assert call.additional_kwargs == {
        module.EVENT_MARKER: original.event_id,
        "event_type": event_type,
    }


@pytest.mark.parametrize(
    "event_type", ["system_task", "human", "heartbeat", "message_match", "", None]
)
def test_unclassified_or_non_event_types_are_rejected(modules, event_type):
    assert modules.events.EVENT_TYPES == set(EVENT_TYPES)
    with pytest.raises(ValueError, match="Unsupported runtime event type"):
        event(modules.events, event_type)


@pytest.mark.parametrize("group_id", [0, -1, True, False, "123", None])
def test_group_id_must_be_a_positive_integer(modules, group_id):
    with pytest.raises(ValueError, match="positive integer"):
        event(modules.events, group_id=group_id)


@pytest.mark.parametrize("field", ["source", "event_id"])
def test_required_event_identity(modules, field):
    with pytest.raises(ValueError, match="required"):
        event(modules.events, **{field: ""})


def test_consume_inputs_batches_only_adjacent_humans_and_keeps_mixed_order(modules):
    module = modules.events
    humans = [{"type": "text", "text": f"用户-{i}"} for i in range(5)]
    image = {"type": "image_url", "image_url": {"url": "https://example.test/图.png"}}
    events = [event(module, kind) for kind in EVENT_TYPES]
    inputs = [
        humans[0],
        image,
        humans[1],
        events[0],
        events[1],
        humans[2],
        events[2],
        humans[3],
        humans[4],
        events[3],
        events[4],
    ]
    snapshot = list(inputs)
    messages = module.consume_inputs(inputs)
    assert [m.type for m in messages] == [
        "human",
        "ai",
        "tool",
        "ai",
        "tool",
        "human",
        "ai",
        "tool",
        "human",
        "ai",
        "tool",
        "ai",
        "tool",
    ]
    assert [m.content for m in messages if isinstance(m, HumanMessage)] == [
        [humans[0], image, humans[1]],
        [humans[2]],
        [humans[3], humans[4]],
    ]
    assert [
        m.additional_kwargs[module.EVENT_MARKER]
        for m in messages
        if isinstance(m, ToolMessage)
    ] == [e.event_id for e in events]
    assert inputs == snapshot
    assert_pairs(module, messages)
    assert module.consume_inputs([]) == []
    assert module.consume_inputs(humans) == [HumanMessage(content=humans)]


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_enqueue_dedups_pending_occurrences_not_content_and_allows_redelivery_after_drain(
    modules, event_type
):
    module = modules.events
    human = {"type": "text", "text": "user"}
    state = SimpleNamespace(group_id=123, human_queue=[human])
    first = event(module, event_type)
    repeated = replace(first, event_id="retry-delivery")
    next_occurrence = replace(
        first, event_id="next-delivery", occurrence_key="occurrence-2"
    )
    assert module.enqueue_runtime_event(state, first) is True
    assert module.enqueue_runtime_event(state, repeated) is False
    assert module.enqueue_runtime_event(state, next_occurrence) is True
    assert state.human_queue == [human, first, next_occurrence]
    assert_pairs(module, module.consume_inputs(state.human_queue))
    state.human_queue.clear()
    assert module.enqueue_runtime_event(state, repeated) is True


@pytest.mark.parametrize("occurrence_key", [None, ""])
def test_event_id_fallback_dedups_retries_but_not_identical_independent_events(
    modules, occurrence_key
):
    module = modules.events
    state = SimpleNamespace(group_id=123, human_queue=[])
    first = event(module, occurrence_key=occurrence_key)
    retry = replace(first)
    distinct = event(module, occurrence_key=occurrence_key)
    assert first.event_id != distinct.event_id
    assert module.enqueue_runtime_event(state, first)
    assert not module.enqueue_runtime_event(state, retry)
    assert module.enqueue_runtime_event(state, distinct)
    assert state.human_queue == [first, distinct]


@pytest.mark.parametrize("override", [{"source": "other"}, {"event_type": "hook"}])
def test_occurrence_keys_are_namespaced_by_source_and_type(modules, override):
    module = modules.events
    first = event(module)
    other = replace(first, **override)
    state = SimpleNamespace(group_id=123, human_queue=[])
    assert module.enqueue_runtime_event(state, first)
    assert module.enqueue_runtime_event(state, other)


def test_cross_group_rejection_never_mutates_queue(modules):
    state = SimpleNamespace(
        group_id=123, human_queue=[{"type": "text", "text": "keep"}]
    )
    before = list(state.human_queue)
    with pytest.raises(ValueError, match="another group"):
        modules.events.enqueue_runtime_event(state, event(modules.events, group_id=456))
    assert state.human_queue == before


def test_stable_event_key_is_unicode_and_mapping_order_safe(modules):
    key = modules.events.stable_event_key
    assert key("中文", {"b": 2, "a": 1}) == key("中文", {"a": 1, "b": 2})
    assert key("中文", 1) != key("中文", 2)


@pytest.mark.parametrize(
    "cutoff,expected",
    [(-3, 0), (0, 0), (1, 1), (2, 1), (3, 3), (4, 3), (5, 5), (99, 5)],
)
def test_safe_cutoff_never_splits_adjacent_event_pairs(modules, cutoff, expected):
    module = modules.events
    messages = [
        HumanMessage("before"),
        *module.event_messages(event(module)),
        *module.event_messages(event(module, "agent")),
    ]
    assert module.safe_cutoff(messages, cutoff) == expected
    assert_pairs(module, messages[expected:])


def test_safe_cutoff_backtracks_across_multiple_real_tool_calls(modules):
    first = AIMessage("", tool_calls=[{"name": "one", "args": {}, "id": "one"}])
    second = AIMessage("", tool_calls=[{"name": "two", "args": {}, "id": "two"}])
    messages = [
        HumanMessage("keep"),
        first,
        second,
        ToolMessage("one", tool_call_id="one"),
        ToolMessage("two", tool_call_id="two"),
    ]
    # Cutting at 4 first crosses 'two', then crosses 'one': one pass is insufficient.
    assert modules.events.safe_cutoff(messages, 4) == 1
    assert modules.events.safe_cutoff(messages, 5) == 5


@pytest.mark.parametrize("with_human", [False, True])
@pytest.mark.parametrize("with_auxiliary", [False, True])
def test_assemble_input_preserves_pairs_and_merges_only_human_content(
    modules, with_human, with_auxiliary
):
    module = modules.events
    history = [SystemMessage("policy"), HumanMessage("earlier")]
    memory = [HumanMessage("记忆")]
    pair = module.event_messages(event(module))
    human = HumanMessage("当前问题", id="current-user")
    current = [*pair, *([human] if with_human else [])]
    auxiliary = [{"type": "text", "text": "背景"}] if with_auxiliary else []
    before = [m.model_dump() for m in history + memory + current]
    result = module.assemble_input(history, current, memory, auxiliary)
    assert result[: len(history) + len(memory)] == history + memory
    assert_pairs(module, result)
    index = result.index(pair[0])
    assert result[index : index + 2] == pair
    if with_auxiliary and with_human:
        assert result[-1].id == human.id
        assert result[-1].content == [
            {"type": "text", "text": "## 背景聊天记录："},
            *auxiliary,
            {"type": "text", "text": "## 当前聊天记录："},
            {"type": "text", "text": human.content},
        ]
    elif with_auxiliary:
        assert isinstance(result[index - 1], HumanMessage)
        assert result[index - 1].content == [
            {"type": "text", "text": "## 背景聊天记录："},
            *auxiliary,
        ]
        assert result[-2:] == pair
    else:
        assert result == history + memory + current
    assert [m.model_dump() for m in history + memory + current] == before


class RecordingModel(FakeMessagesListChatModel):
    _inputs: list = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._inputs.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.parametrize("event_type", EVENT_TYPES)
def test_first_invocation_can_start_with_only_a_runtime_event(modules, event_type):
    module = modules.events
    inputs = module.assemble_input(
        [], module.consume_inputs([event(module, event_type)]), [], []
    )
    model = RecordingModel(responses=[AIMessage("已处理")])
    graph = create_agent(model, tools=[])
    result = asyncio.run(graph.ainvoke({"messages": inputs}))
    assert result["messages"][-1].content == "已处理"
    assert len(model._inputs) == 1
    assert [m.type for m in model._inputs[0]] == ["ai", "tool"]
    assert_pairs(module, model._inputs[0])


@pytest.mark.parametrize("asynchronous", [False, True])
def test_delegation_ignores_synthetic_messages_added_after_initial_prefix(
    modules, asynchronous
):
    loop = modules.loop.ChatLoopDelegationMiddleware(initial_message_count=2)
    prefix = [HumanMessage("prior", id="prior"), AIMessage("old", id="old")]
    messages = list(prefix)

    def observe():
        state = {"messages": messages}
        if asynchronous:
            return asyncio.run(loop.abefore_model(state, None))
        return loop.before_model(state, None)

    assert observe() is None
    # These are genuinely new messages, not merely excluded by initial_message_count.
    for index in range(8):
        messages.extend(
            modules.events.event_messages(event(modules.events, EVENT_TYPES[index % 5]))
        )
    assert observe() is None
    assert loop._rounds == 0
    for index in range(7):
        messages.append(
            AIMessage(
                "",
                id=f"round-{index}",
                tool_calls=[
                    {"name": "inspect", "args": {}, "id": f"call-{index}-a"},
                    {"name": "inspect", "args": {}, "id": f"call-{index}-b"},
                ],
            )
        )
        update = observe()
        assert loop._rounds == index + 1
        if index < 6:
            assert update is None
    assert update["messages"][0].id == loop.reminder_id
    assert update["messages"][0].content == modules.loop.CHAT_LOOP_DELEGATION_MESSAGE
    assert observe() is None
    assert loop._rounds == 7
    # Compaction and a second MCP pass do not recount reconstructed messages.
    messages = [m.model_copy() for m in messages[2:]]
    assert observe() is None
    assert loop._rounds == 7


@pytest.mark.parametrize("asynchronous", [False, True])
def test_send_text_first_never_executes_runtime_receiver_before_or_after_send(
    modules, asynchronous
):
    middleware = modules.loop.SendTextFirstMiddleware()
    handler = (
        AsyncMock(return_value="sent") if asynchronous else Mock(return_value="sent")
    )

    def invoke(name, call_id):
        request = SimpleNamespace(tool_call={"name": name, "id": call_id, "args": {}})
        if asynchronous:
            return asyncio.run(middleware.awrap_tool_call(request, handler))
        return middleware.wrap_tool_call(request, handler)

    for sent in (False, True):
        blocked = invoke(modules.events.INJECTED_EVENT_TOOL, f"receiver-{sent}")
        assert isinstance(blocked, ToolMessage)
        assert blocked.status == "error"
        assert blocked.tool_call_id == f"receiver-{sent}"
        assert blocked.name == modules.events.INJECTED_EVENT_TOOL
        assert "Runtime-only" in blocked.content and "forbidden" in blocked.content
        assert middleware._send_text_started is sent
        assert handler.call_count == int(sent)
        if not sent:
            shell = invoke("shell_executor", "blocked-shell")
            assert shell.content == modules.loop.SEND_TEXT_FIRST_WARNING
            assert handler.call_count == 0
            assert invoke("send_text", "send") == "sent"
    assert invoke("shell_executor", "allowed-shell") == "sent"
    assert handler.call_count == 2
    if asynchronous:
        assert handler.await_count == 2


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("pair_at_start", [False, True])
def test_context_compaction_adjusts_cutoff_before_event_pair(
    modules, monkeypatch, asynchronous, pair_at_start
):
    pair = modules.events.event_messages(event(modules.events))
    prefix = (
        [] if pair_at_start else [HumanMessage("past"), AIMessage("previous answer")]
    )
    messages = [*prefix, *pair, HumanMessage("continue")]
    middleware = modules.context.AgentSummarizationMiddleware(
        model=FakeMessagesListChatModel(responses=[AIMessage("summary")]),
        trigger=("messages", 1),
        keep=("messages", 1),
    )
    monkeypatch.setattr(middleware, "_should_summarize", lambda *args: True)
    monkeypatch.setattr(
        middleware, "_determine_cutoff_index", lambda _: len(prefix) + 1
    )
    summary = (
        AsyncMock(return_value="summary")
        if asynchronous
        else Mock(return_value="summary")
    )
    monkeypatch.setattr(
        middleware, "_acreate_summary" if asynchronous else "_create_summary", summary
    )
    if asynchronous:
        update = asyncio.run(middleware.abefore_model({"messages": messages}, None))
    else:
        update = middleware.before_model({"messages": messages}, None)
    if pair_at_start:
        assert update is None
        summary.assert_not_called()
    else:
        summary.assert_called_once_with(prefix)
        compacted = [m for m in update["messages"] if m.type != "remove"]
        assert compacted[-3:] == [*pair, messages[-1]]
        assert_pairs(modules.events, compacted)
