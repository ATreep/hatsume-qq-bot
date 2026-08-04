"""Tests for handlers/dialogue.py — the extracted conversation startup logic."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
import types
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
STATE_PATH = PLUGIN_DIR / "state.py"

# ---------------------------------------------------------------------------
# Module bootstrapping — stub the package hierarchy so we can import
# handlers/dialogue.py without pulling in nonebot / langchain / langgraph.
# ---------------------------------------------------------------------------


def _stub_package_hierarchy():
    """Create minimal package stubs for the plugin directory."""
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
        ("hatsume.plugins.hatsume-plugin.handlers", PLUGIN_DIR / "handlers"),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


def _stub_config():
    """Stub the config module with test defaults."""
    name = "hatsume.plugins.hatsume-plugin.config"
    if name not in sys.modules:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    else:
        mod = sys.modules[name]
    mod.CONTEXT_QUEUE_LEN = 5
    mod.CONTEXT_QUEUE_OVERLAP_LEN = 2
    mod.GENERATE_IMAGE_RATE_LIMIT_SECONDS = 60
    mod.VIDEO_RATE_LIMIT_SECONDS = 60
    mod.IMAGE_MAX_PIXELS = 36_000_000
    mod.IMAGE_MAX_SIZE_BYTES = 9 * 1024 * 1024
    mod.MAX_FORWARD_DEPTH = 3
    mod.FORWARD_API_TIMEOUT_SECONDS = 10
    mod.MESSAGE_MAX_LENGTH = 2000
    mod.REPLY_MAX_LENGTH = 200
    mod.USER_INPUT_CONFIRM_DURING_TIME = 3
    mod.DOCKER_ENV_PATH = "/tmp"
    mod.SHELL_MAX_OUTPUT = 1000
    mod.SHELL_TIMEOUT = 10
    mod.BOT_QQ_ID = 1234567890


def _load_state_module():
    """Load the real state.py with config stubbed."""
    _stub_package_hierarchy()
    _stub_config()

    name = "hatsume.plugins.hatsume-plugin.state"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, STATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_state_mod = _load_state_module()
ConversationState = _state_mod.ConversationState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> ConversationState:
    state = ConversationState(group_id=101)
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def test_request_end_conversation_blocks_until_reactivated():
    state = _make_state()
    state.activate_chat("group_1_2")

    state.request_end_conversation()

    assert not state.is_chatting
    assert state.chat_peers == set()
    assert state.end_requested

    state.activate_chat("group_1_3")
    assert state.is_chatting
    assert state.chat_peers == {"group_1_3"}
    assert not state.end_requested


# ---------------------------------------------------------------------------
# Import the module under test (handlers/dialogue.py)
# ---------------------------------------------------------------------------


def _load_conversation_module():
    """Load handlers/dialogue.py with dependencies stubbed."""
    _stub_package_hierarchy()
    _stub_config()

    runtime_name = "hatsume.plugins.hatsume-plugin.group_runtime"
    runtime_mod = sys.modules.get(runtime_name)
    if runtime_mod is None or not hasattr(runtime_mod, "GroupRuntime"):
        runtime_spec = importlib.util.spec_from_file_location(
            runtime_name,
            PLUGIN_DIR / "group_runtime.py",
        )
        runtime_mod = importlib.util.module_from_spec(runtime_spec)
        sys.modules[runtime_name] = runtime_mod
        runtime_spec.loader.exec_module(runtime_mod)

    # Stub graph.nodes
    nodes_name = "hatsume.plugins.hatsume-plugin.graph.nodes"
    if nodes_name not in sys.modules:
        sys.modules[nodes_name] = types.ModuleType(nodes_name)
    nodes_mod = sys.modules[nodes_name]
    nodes_mod.bind_state = MagicMock()
    nodes_mod.reset_memory_record_context = MagicMock()
    nodes_mod.set_current_query_user_id = MagicMock()
    nodes_mod.get_role_sys_prompt = MagicMock(return_value="role-prompt")
    nodes_mod.append_auxiliary_message = MagicMock()
    nodes_mod.make_system_trigger_message = MagicMock(
        side_effect=lambda text, trigger_type: {
            "type": "text",
            "text": text,
            "_hatsume_system_trigger": trigger_type,
        }
    )

    # Stub graph.builder
    builder_name = "hatsume.plugins.hatsume-plugin.graph.builder"
    if builder_name not in sys.modules:
        builder_mod = types.ModuleType(builder_name)
        builder_mod.graph = MagicMock()
        builder_mod.graph.ainvoke = AsyncMock()
        sys.modules[builder_name] = builder_mod

    # Stub graph package
    graph_name = "hatsume.plugins.hatsume-plugin.graph"
    if graph_name not in sys.modules:
        graph_mod = types.ModuleType(graph_name)
        graph_mod.__path__ = [str(PLUGIN_DIR / "graph")]
        sys.modules[graph_name] = graph_mod

    # Stub utils.md_to_image (pulls in nonebot_plugin_htmlrender which isn't available in tests)
    mti_name = "hatsume.plugins.hatsume-plugin.utils.md_to_image"
    if mti_name not in sys.modules:
        mti_mod = types.ModuleType(mti_name)
        mti_mod.auto_convert_text = MagicMock()
        sys.modules[mti_name] = mti_mod

    # Stub handlers.tools (imported by dialogue.py)
    commands_name = "hatsume.plugins.hatsume-plugin.handlers.tools"
    if commands_name not in sys.modules:
        commands_mod = types.ModuleType(commands_name)
        commands_mod._wire_conv_state = MagicMock()
        sys.modules[commands_name] = commands_mod

    # Stub graph.agents (imported by tools.py)
    agents_name = "hatsume.plugins.hatsume-plugin.graph.agents"
    if agents_name not in sys.modules:
        agents_mod = types.ModuleType(agents_name)
        agents_mod.get_agent_list = MagicMock(return_value=[])
        agents_mod.get_agent_handler = MagicMock()
        sys.modules[agents_name] = agents_mod

    # Stub infra (imported by tools.py)
    infra_name = "hatsume.plugins.hatsume-plugin.infra"
    if infra_name not in sys.modules:
        infra_mod = types.ModuleType(infra_name)
        infra_mod.run_cmd = MagicMock(return_value="")
        infra_mod.ensure_container_running = MagicMock()
        sys.modules[infra_name] = infra_mod
    infra_mod = sys.modules[infra_name]
    infra_mod.copy_host_file_to_sandbox = AsyncMock()
    infra_mod.find_sandbox_user_image = AsyncMock(return_value=None)
    infra_mod.save_sandbox_user_image = AsyncMock()

    # Stub prompts (imported by tools.py)
    prompts_name = "hatsume.plugins.hatsume-plugin.prompts"
    if prompts_name not in sys.modules:
        prompts_mod = types.ModuleType(prompts_name)
        prompts_mod.HTML_GENERATION_PROMPT = "Generate HTML"
        sys.modules[prompts_name] = prompts_mod
    sys.modules[prompts_name].get_auto_response_prompt = MagicMock(return_value="")

    # Stub utils with the complete interface dialogue.py imports. Other tests may
    # leave a partial utils stub in sys.modules, so fill missing attrs here.
    utils_name = "hatsume.plugins.hatsume-plugin.utils"
    if utils_name not in sys.modules:
        utils_mod = types.ModuleType(utils_name)
        sys.modules[utils_name] = utils_mod
    utils_mod = sys.modules[utils_name]
    utils_mod.build_forward_json = MagicMock(return_value={})
    utils_mod.CQ_AT_PATTERN = re.compile(r"\[CQ:at,qq=(\d+)\]")
    utils_mod.get_date = MagicMock(return_value="2026/01/01 00:00:00")
    utils_mod.get_group_member_name = AsyncMock(return_value="user")
    utils_mod.get_qq_avatar_url = MagicMock(
        side_effect=lambda user_id: f"https://q.qlogo.cn/avatar/{user_id}"
    )
    utils_mod.mask_secret_keys = MagicMock(side_effect=lambda text: text)
    utils_mod.message_to_json = MagicMock(return_value={})
    utils_mod.render_cq_at_placeholders = AsyncMock(side_effect=lambda text, group_id: (text, []))

    # Stub memory.engine (imported by tools.py)
    mem_engine_name = "hatsume.plugins.hatsume-plugin.memory.engine"
    if mem_engine_name not in sys.modules:
        mem_engine_mod = types.ModuleType(mem_engine_name)
        mem_engine_mod.get_mem_list = MagicMock(return_value=[])
        mem_engine_mod.add_mem = MagicMock()
        mem_engine_mod.query_mems = MagicMock(return_value=[])
        sys.modules[mem_engine_name] = mem_engine_mod

    # Also set directly on memory module since __init__.py re-exports from engine
    memory_name = "hatsume.plugins.hatsume-plugin.memory"
    if memory_name not in sys.modules:
        memory_mod = types.ModuleType(memory_name)
        memory_mod.__path__ = [str(PLUGIN_DIR / "memory")]
        sys.modules[memory_name] = memory_mod
    memory = sys.modules[memory_name]
    memory.get_mem_list = MagicMock(return_value=[])
    memory.add_mem = MagicMock()
    memory.query_mems = MagicMock(return_value=[])
    memory.is_group_activated = MagicMock(return_value=False)

    # Stub graph.tools (imported by chat.py)
    tools_name = "hatsume.plugins.hatsume-plugin.graph.tools"
    if tools_name not in sys.modules:
        sys.modules[tools_name] = types.ModuleType(tools_name)
    tools_mod = sys.modules[tools_name]
    tools_mod.configure_agent_notification_callback = MagicMock()
    tools_mod.configure_tool_callbacks = MagicMock()
    tools_mod.set_current_group_id = MagicMock()

    # Stub nonebot.adapters (imported by chat.py)
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adapters_name = "nonebot.adapters"
    if adapters_name not in sys.modules or not hasattr(sys.modules[adapters_name], "Bot"):
        if adapters_name not in sys.modules:
            sys.modules[adapters_name] = types.ModuleType(adapters_name)
            sys.modules[adapters_name].__path__ = []
        sys.modules[adapters_name].Bot = MagicMock()
    onebot_name = "nonebot.adapters.onebot"
    if onebot_name not in sys.modules:
        sys.modules[onebot_name] = types.ModuleType(onebot_name)
        sys.modules[onebot_name].__path__ = []
    v11_name = "nonebot.adapters.onebot.v11"
    if v11_name not in sys.modules:
        sys.modules[v11_name] = types.ModuleType(v11_name)

    class _Message(list):
        def extract_plain_text(self):
            return "".join(
                str(getattr(seg, "data", {}).get("text", ""))
                for seg in self
                if getattr(seg, "type", None) == "text"
            )

    sys.modules[v11_name].Message = _Message
    sys.modules[v11_name].MessageSegment = MagicMock()
    sys.modules[v11_name].GroupMessageEvent = MagicMock()
    sys.modules[v11_name].GroupIncreaseNoticeEvent = MagicMock()
    sys.modules[v11_name].MessageEvent = MagicMock()
    sys.modules[v11_name].PokeNotifyEvent = MagicMock()

    # Load dialogue.py — force reload even if a stale stub exists
    conv_path = PLUGIN_DIR / "handlers" / "dialogue.py"
    conv_name = "hatsume.plugins.hatsume-plugin.handlers.dialogue"
    if conv_name in sys.modules:
        del sys.modules[conv_name]
    spec = importlib.util.spec_from_file_location(conv_name, conv_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[conv_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_start_new_conversation_marks_system_task_for_detection_bypass():
    dialogue = _load_conversation_module()
    dialogue.group_runtime_registry.clear_for_tests()
    runtime = dialogue.group_runtime_registry.get_or_create(101)
    state = runtime.conversation
    dialogue.graph.ainvoke = AsyncMock()

    asyncio.run(
        dialogue.start_new_conversation(
            runtime,
            AsyncMock(),
            MagicMock(),
            system_task_text="scheduled work",
        )
    )

    assert state.human_queue == [
        {
            "type": "text",
            "text": "scheduled work",
            "_hatsume_system_trigger": "system_task",
        }
    ]


def test_group_runtime_registry_and_task_local_binding_are_isolated():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    runtime_mod = sys.modules[
        "hatsume.plugins.hatsume-plugin.group_runtime"
    ]
    first = registry.get_or_create(101)
    same = registry.get_or_create(101)
    second = registry.get_or_create(202)

    assert first is same
    assert first is not second
    assert first.conversation is not second.conversation
    assert registry.get_existing(303) is None

    async def exercise_binding():
        both_ready = asyncio.Event()
        release = asyncio.Event()
        ready: set[int] = set()

        async def worker(runtime):
            with runtime_mod.bind_group_runtime(runtime):
                assert runtime_mod.get_current_group_runtime() is runtime
                ready.add(runtime.group_id)
                if len(ready) == 2:
                    both_ready.set()
                await release.wait()
                assert runtime_mod.get_current_group_runtime() is runtime

        first_task = asyncio.create_task(worker(first))
        second_task = asyncio.create_task(worker(second))
        await asyncio.wait_for(both_ready.wait(), timeout=1)
        assert ready == {101, 202}
        release.set()
        await asyncio.gather(first_task, second_task)
        assert runtime_mod.get_current_group_runtime(required=False) is None

        with runtime_mod.bind_group_runtime(first):
            with runtime_mod.bind_group_runtime(second):
                assert runtime_mod.get_current_group_runtime() is second
            assert runtime_mod.get_current_group_runtime() is first

    asyncio.run(exercise_binding())
    registry.clear_for_tests()


def test_group_runtime_rejects_invalid_ids_and_owns_distinct_mutable_state():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()

    for invalid in (0, -1, True, "101"):
        with pytest.raises(ValueError, match="positive integer"):
            registry.get_or_create(invalid)

    first = registry.get_or_create(101)
    second = registry.get_or_create(202)
    first.conversation.chat_peers.add("peer")
    first.conversation.pending_queue.append({"text": "pending"})
    first.auxiliary_messages_queue.append({"text": "aux"})
    first.send_image_count = 2
    first.generate_video_used = True

    assert second.conversation.chat_peers == set()
    assert second.conversation.pending_queue == []
    assert second.auxiliary_messages_queue == []
    assert second.send_image_count == 0
    assert second.generate_video_used is False
    registry.clear_for_tests()


def test_group_runtime_discovers_and_unbinds_target_group_bots():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    first_bot = types.SimpleNamespace(
        get_group_list=AsyncMock(
            return_value=[{"group_id": 101}, {"group_id": "202"}]
        )
    )
    second_bot = object()

    discovered = asyncio.run(registry.discover_bot_groups(first_bot))
    registry.bind_bot(303, second_bot)

    assert discovered == (101, 202)
    assert registry.routed_group_ids() == (101, 202, 303)
    assert registry.get_bot(101) is first_bot
    assert registry.get_or_create(202).bot is first_bot
    assert registry.get_bot(303) is second_bot

    assert registry.unbind_bot(first_bot) == (101, 202)
    with pytest.raises(LookupError, match="group 101"):
        registry.get_bot(101)
    assert registry.routed_group_ids() == (303,)
    assert registry.get_bot(303) is second_bot
    registry.clear_for_tests()


def test_external_trigger_uses_the_target_groups_registered_bot():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    first_bot = object()
    second_bot = object()
    registry.bind_bot(101, first_bot)
    registry.bind_bot(202, second_bot)
    dialogue._send_group_ai_message = AsyncMock()
    dialogue.start_new_conversation = AsyncMock()

    async def scenario():
        dialogue._start_conv_for_trigger(
            42,
            202,
            "timer result",
            trigger_type="timer",
        )
        await asyncio.sleep(0)
        callback = registry.get_existing(202).conversation.ai_answer
        await callback("answer")
        await asyncio.sleep(0)

    asyncio.run(scenario())

    dialogue._send_group_ai_message.assert_awaited_once_with(
        second_bot,
        202,
        "answer",
        reply_to_message_id=None,
    )
    registry.clear_for_tests()


def test_different_group_graphs_run_in_parallel():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    runtime_mod = sys.modules[
        "hatsume.plugins.hatsume-plugin.group_runtime"
    ]
    first = registry.get_or_create(101)
    second = registry.get_or_create(202)

    async def scenario():
        both_entered = asyncio.Event()
        release = asyncio.Event()
        entered: set[int] = set()

        async def invoke(_state, _config):
            group_id = runtime_mod.get_current_group_id()
            entered.add(group_id)
            if len(entered) == 2:
                both_entered.set()
            await release.wait()

        dialogue.graph.ainvoke = AsyncMock(side_effect=invoke)
        first_task = asyncio.create_task(
            dialogue.start_new_conversation(
                first,
                AsyncMock(),
                MagicMock(),
                system_task_text="first",
            )
        )
        second_task = asyncio.create_task(
            dialogue.start_new_conversation(
                second,
                AsyncMock(),
                MagicMock(),
                system_task_text="second",
            )
        )

        await asyncio.wait_for(both_entered.wait(), timeout=1)
        assert entered == {101, 202}
        assert not first_task.done()
        assert not second_task.done()
        release.set()
        await asyncio.gather(first_task, second_task)

    asyncio.run(scenario())
    registry.clear_for_tests()


def test_graph_failure_releases_only_its_group_slot():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    runtime_mod = sys.modules[
        "hatsume.plugins.hatsume-plugin.group_runtime"
    ]
    failing = registry.get_or_create(101)
    healthy = registry.get_or_create(202)

    async def scenario():
        healthy_entered = asyncio.Event()
        release_healthy = asyncio.Event()

        async def invoke(_state, _config):
            if runtime_mod.get_current_group_id() == 101:
                raise RuntimeError("group 101 failed")
            healthy_entered.set()
            await release_healthy.wait()

        dialogue.graph.ainvoke = AsyncMock(side_effect=invoke)
        failing_task = asyncio.create_task(
            dialogue.start_new_conversation(
                failing,
                AsyncMock(),
                MagicMock(),
                system_task_text="fail",
            )
        )
        healthy_task = asyncio.create_task(
            dialogue.start_new_conversation(
                healthy,
                AsyncMock(),
                MagicMock(),
                system_task_text="healthy",
            )
        )

        await asyncio.wait_for(healthy_entered.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="group 101 failed"):
            await failing_task
        assert failing.conversation.is_graph_running is False
        assert failing.conversation._graph_task is None
        assert healthy.conversation.is_graph_running is True
        assert not healthy_task.done()

        release_healthy.set()
        await healthy_task

    asyncio.run(scenario())
    registry.clear_for_tests()


def test_same_group_graph_starts_coalesce_without_losing_trigger():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    runtime = registry.get_or_create(101)

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def invoke(_state, _config):
            entered.set()
            await release.wait()

        dialogue.graph.ainvoke = AsyncMock(side_effect=invoke)
        first_task = asyncio.create_task(
            dialogue.start_new_conversation(
                runtime,
                AsyncMock(),
                MagicMock(),
                system_task_text="first",
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

        await dialogue.start_new_conversation(
            runtime,
            AsyncMock(),
            MagicMock(),
            system_task_text="second",
        )

        assert dialogue.graph.ainvoke.await_count == 1
        assert [message["text"] for message in runtime.conversation.human_queue] == [
            "first",
            "second",
        ]
        release.set()
        await first_task

    asyncio.run(scenario())
    registry.clear_for_tests()


def test_shutdown_continues_to_containers_after_agent_cleanup_failure():
    dialogue = _load_conversation_module()
    registry = dialogue.group_runtime_registry
    registry.clear_for_tests()
    registry.get_or_create(101)
    agents = sys.modules["hatsume.plugins.hatsume-plugin.graph.agents"]
    infra = sys.modules["hatsume.plugins.hatsume-plugin.infra"]
    previous_agent_shutdown = getattr(agents, "shutdown_all_agents", None)
    previous_container_shutdown = getattr(infra, "shutdown_all_containers", None)
    agents.shutdown_all_agents = AsyncMock(side_effect=RuntimeError("agent cleanup"))
    infra.shutdown_all_containers = AsyncMock()

    try:
        asyncio.run(registry.shutdown())
        infra.shutdown_all_containers.assert_awaited_once_with()
        assert registry.values() == ()
    finally:
        if previous_agent_shutdown is None:
            delattr(agents, "shutdown_all_agents")
        else:
            agents.shutdown_all_agents = previous_agent_shutdown
        if previous_container_shutdown is None:
            delattr(infra, "shutdown_all_containers")
        else:
            infra.shutdown_all_containers = previous_container_shutdown


def _make_group_increase_event(*, group_id=100, user_id=123456, self_id=999999):
    return types.SimpleNamespace(
        group_id=group_id,
        user_id=user_id,
        self_id=self_id,
        get_session_id=lambda: f"group_{group_id}_{user_id}",
    )


def test_group_increase_starts_conversation_and_activates_new_member_peer():
    dialogue = _load_conversation_module()
    dialogue.is_group_activated = MagicMock(return_value=True)
    dialogue.group_runtime_registry.clear_for_tests()
    dialogue.get_group_member_name = AsyncMock(return_value="新成员")
    dialogue.get_qq_avatar_url = MagicMock(
        return_value="https://q.qlogo.cn/avatar/123456"
    )
    dialogue._start_conv_for_trigger = MagicMock()
    bot = MagicMock()
    event = _make_group_increase_event(group_id=101)

    asyncio.run(dialogue.handle_group_increase(bot, event))

    state = dialogue.group_runtime_registry.get_existing(101).conversation
    assert state.is_chatting
    assert state.chat_peers == {"group_101_123456"}
    dialogue.get_group_member_name.assert_awaited_once_with(bot, 101, 123456)
    dialogue._start_conv_for_trigger.assert_called_once()
    user_id, group_id, prompt = dialogue._start_conv_for_trigger.call_args.args
    assert (user_id, group_id) == (123456, 101)
    assert dialogue._start_conv_for_trigger.call_args.kwargs == {
        "trigger_type": "group_increase",
        "bot": bot,
    }
    assert prompt == (
        "(SYSTEM) 有新的成员加入了群聊。\n"
        "用户名：新成员\n"
        "用户QQ号：123456\n"
        "用户头像：https://q.qlogo.cn/avatar/123456\n"
        "请 at 该用户表示欢迎，并简单做个自我介绍。"
        "向新用户说明除了聊天以外，你还有哪些能力。"
    )


def test_group_increase_injects_active_conversation_without_starting_another():
    dialogue = _load_conversation_module()
    dialogue.is_group_activated = MagicMock(return_value=True)
    dialogue.group_runtime_registry.clear_for_tests()
    state = dialogue.group_runtime_registry.get_or_create(100).conversation
    state.activate_chat("group_100_1")
    dialogue.get_group_member_name = AsyncMock(return_value="新成员")
    dialogue.get_qq_avatar_url = MagicMock(return_value="avatar-url")
    dialogue._start_conv_for_trigger = MagicMock()
    event = _make_group_increase_event()

    asyncio.run(dialogue.handle_group_increase(MagicMock(), event))

    assert state.chat_peers == {
        "group_100_1",
        "group_100_123456",
    }
    assert state.human_queue == [
        {
            "type": "text",
            "text": (
                "(SYSTEM) 有新的成员加入了群聊。\n"
                "用户名：新成员\n"
                "用户QQ号：123456\n"
                "用户头像：avatar-url\n"
                "请 at 该用户表示欢迎，并简单做个自我介绍。"
                "向新用户说明除了聊天以外，你还有哪些能力。"
            ),
            "_hatsume_system_trigger": "group_increase",
        }
    ]
    dialogue._start_conv_for_trigger.assert_not_called()


def test_group_increase_ignores_inactive_groups_and_the_bot_itself():
    dialogue = _load_conversation_module()
    dialogue.is_group_activated = MagicMock(
        side_effect=lambda group_id: group_id == 100
    )
    dialogue.group_runtime_registry.clear_for_tests()
    dialogue.get_group_member_name = AsyncMock(return_value="ignored")
    dialogue._start_conv_for_trigger = MagicMock()

    asyncio.run(
        dialogue.handle_group_increase(
            MagicMock(),
            _make_group_increase_event(group_id=101),
        )
    )
    asyncio.run(
        dialogue.handle_group_increase(
            MagicMock(),
            _make_group_increase_event(user_id=999999, self_id=999999),
        )
    )

    assert dialogue.group_runtime_registry.get_existing(101) is None
    assert dialogue.group_runtime_registry.get_existing(100) is None
    dialogue.get_group_member_name.assert_not_awaited()
    dialogue._start_conv_for_trigger.assert_not_called()


def test_handle_ai_message_sends_plain_text_segments_without_at_prefix():
    dialogue = _load_conversation_module()
    dialogue.auto_convert_text = AsyncMock(return_value=["plain-text-segment"])
    dialogue.MessageSegment.at = MagicMock(return_value="at-segment")
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("hello", bot, group_id=7))

    dialogue.MessageSegment.at.assert_not_called()
    bot.send_group_msg.assert_awaited_once_with(
        group_id=7,
        message="plain-text-segment",
    )


def test_handle_ai_message_sends_to_explicit_group_without_matcher_context():
    dialogue = _load_conversation_module()
    text_segment = types.SimpleNamespace(type="text", data={"text": "answer"})
    dialogue.auto_convert_text = AsyncMock(return_value=[text_segment])
    dialogue.asyncio.sleep = AsyncMock()
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("answer", bot, group_id=100))

    bot.send_group_msg.assert_awaited_once_with(
        group_id=100,
        message=text_segment,
    )


def test_handle_ai_message_replaces_cq_at_in_pure_text():
    dialogue = _load_conversation_module()
    dialogue.auto_convert_text = AsyncMock(
        return_value=[types.SimpleNamespace(type="text", data={"text": "hi @Treep"})]
    )
    dialogue.render_cq_at_placeholders = AsyncMock(return_value=("hi @Treep", [123456]))
    dialogue.MessageSegment.text = MagicMock(
        side_effect=lambda text: types.SimpleNamespace(type="text", data={"text": text})
    )
    dialogue.MessageSegment.at = MagicMock(
        side_effect=lambda uid: types.SimpleNamespace(type="at", data={"qq": uid})
    )
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("hi [CQ:at,qq=123456]", bot, group_id=7))

    payload = bot.send_group_msg.await_args.kwargs["message"]
    assert [seg.type for seg in payload] == ["text", "at"]
    assert payload[0].data["text"] == "hi "
    assert payload[1].data["qq"] == 123456


def test_handle_ai_message_puts_cq_at_segments_before_rendered_image():
    dialogue = _load_conversation_module()
    image_seg = types.SimpleNamespace(type="image", data={"file": "img"})
    dialogue.auto_convert_text = AsyncMock(return_value=[image_seg])
    dialogue.render_cq_at_placeholders = AsyncMock(return_value=("# @Treep\nresult", [123456]))
    dialogue.MessageSegment.at = MagicMock(
        side_effect=lambda uid: types.SimpleNamespace(type="at", data={"qq": uid})
    )
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("# [CQ:at,qq=123456]\nresult", bot, group_id=7))

    payload = bot.send_group_msg.await_args.kwargs["message"]
    assert [seg.type for seg in payload] == ["at", "image"]
    assert payload[0].data["qq"] == 123456


def _make_received_event(
    dialogue,
    *,
    message_id: int,
    segments: list,
    reply=None,
):
    class _GroupEvent:
        group_id = 7
        user_id = 42

        def __init__(self):
            self.message_id = message_id
            self.original_message = dialogue.Message(segments)
            self.reply = reply

    dialogue.GroupMessageEvent = _GroupEvent
    return _GroupEvent()


def _make_image_bytes(image_format: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 3), color="red").save(output, format=image_format)
    return output.getvalue()


def _image_response(image_format: str):
    response = MagicMock()
    response.content = _make_image_bytes(image_format)
    return response


def test_get_human_message_passes_normal_event_message_id():
    dialogue = _load_conversation_module()
    dialogue.message_to_json.reset_mock()
    dialogue.message_to_json.return_value = {"type": "message"}
    dialogue.has_forward_segment = MagicMock(return_value=None)
    event = _make_received_event(
        dialogue,
        message_id=321,
        segments=[types.SimpleNamespace(type="text", data={"text": "hello"})],
    )

    _, source = asyncio.run(dialogue.get_human_message(MagicMock(), event))

    assert dialogue.message_to_json.call_args.kwargs["message_id"] == 321
    assert source["source_id"] == "m321"


def test_get_human_message_passes_forward_event_message_id():
    dialogue = _load_conversation_module()
    dialogue.build_forward_json.reset_mock()
    dialogue.build_forward_json.return_value = {"type": "forward"}
    dialogue.has_forward_segment = MagicMock(return_value="forward-1")
    dialogue.resolve_forward_content = AsyncMock(return_value=[])
    event = _make_received_event(
        dialogue,
        message_id=654,
        segments=[types.SimpleNamespace(type="forward", data={"id": "forward-1"})],
    )

    asyncio.run(dialogue.get_human_message(MagicMock(), event))

    assert dialogue.build_forward_json.call_args.kwargs["message_id"] == 654


def test_get_human_message_stores_current_images_in_segment_order():
    dialogue = _load_conversation_module()
    dialogue.message_to_json.reset_mock()
    dialogue.message_to_json.return_value = {"type": "message"}
    dialogue.has_forward_segment = MagicMock(return_value=None)
    dialogue.requests.get = MagicMock(
        side_effect=[_image_response("PNG"), _image_response("JPEG")]
    )
    dialogue.save_sandbox_user_image = AsyncMock(
        side_effect=lambda _data, message_id, order, extension, *, group_id: (
            f"/tmp/hatsume-user-images/{message_id}-{order}.{extension}"
        )
    )
    event = _make_received_event(
        dialogue,
        message_id=321,
        segments=[
            types.SimpleNamespace(type="text", data={"text": "before"}),
            types.SimpleNamespace(type="image", data={"url": "https://qq/1"}),
            types.SimpleNamespace(type="text", data={"text": "after"}),
            types.SimpleNamespace(type="image", data={"url": "https://qq/2"}),
        ],
    )

    content, _ = asyncio.run(dialogue.get_human_message(MagicMock(), event))

    assert dialogue.message_to_json.call_args.args[2] == (
        "before ![图片](/tmp/hatsume-user-images/321-1.png) "
        "after ![图片](/tmp/hatsume-user-images/321-2.jpg) "
    )
    assert content == [{"type": "text", "text": '{"type": "message"}'}]
    assert dialogue.save_sandbox_user_image.await_args_list[0].args[1:] == (
        321,
        1,
        "png",
    )
    assert dialogue.save_sandbox_user_image.await_args_list[0].kwargs == {
        "group_id": 7
    }
    assert dialogue.save_sandbox_user_image.await_args_list[1].args[1:] == (
        321,
        2,
        "jpg",
    )
    assert dialogue.save_sandbox_user_image.await_args_list[1].kwargs == {
        "group_id": 7
    }


def test_get_human_message_reuses_reply_images_by_reply_message_id():
    dialogue = _load_conversation_module()
    dialogue.message_to_json.reset_mock()
    dialogue.message_to_json.return_value = {"type": "message"}
    dialogue.has_forward_segment = MagicMock(return_value=None)
    dialogue.find_sandbox_user_image = AsyncMock(
        side_effect=[
            "/tmp/hatsume-user-images/900-1.png",
            "/tmp/hatsume-user-images/900-2.webp",
        ]
    )
    dialogue.requests.get = MagicMock()
    reply = types.SimpleNamespace(
        message_id=900,
        sender=types.SimpleNamespace(user_id=84),
        message=dialogue.Message(
            [
                types.SimpleNamespace(type="text", data={"text": "old"}),
                types.SimpleNamespace(type="image", data={"url": "https://qq/a"}),
                types.SimpleNamespace(type="image", data={"url": "https://qq/b"}),
            ]
        ),
    )
    event = _make_received_event(
        dialogue,
        message_id=901,
        segments=[types.SimpleNamespace(type="text", data={"text": "replying"})],
        reply=reply,
    )

    content, _ = asyncio.run(dialogue.get_human_message(MagicMock(), event))

    reply_to = dialogue.message_to_json.call_args.kwargs["reply_to"]
    assert reply_to["content"] == (
        "old ![图片](/tmp/hatsume-user-images/900-1.png) "
        " ![图片](/tmp/hatsume-user-images/900-2.webp) "
    )
    assert dialogue.find_sandbox_user_image.await_args_list[0].args == (900, 1)
    assert dialogue.find_sandbox_user_image.await_args_list[0].kwargs == {
        "group_id": 7
    }
    assert dialogue.find_sandbox_user_image.await_args_list[1].args == (900, 2)
    assert dialogue.find_sandbox_user_image.await_args_list[1].kwargs == {
        "group_id": 7
    }
    dialogue.requests.get.assert_not_called()
    dialogue.save_sandbox_user_image.assert_not_awaited()
    assert len(content) == 1


def test_get_human_message_recovers_missing_reply_image_from_temp_url():
    dialogue = _load_conversation_module()
    dialogue.message_to_json.reset_mock()
    dialogue.message_to_json.return_value = {"type": "message"}
    dialogue.has_forward_segment = MagicMock(return_value=None)
    dialogue.find_sandbox_user_image = AsyncMock(return_value=None)
    dialogue.requests.get = MagicMock(return_value=_image_response("PNG"))
    dialogue.save_sandbox_user_image = AsyncMock(
        return_value="/tmp/hatsume-user-images/700-1.png"
    )
    reply = types.SimpleNamespace(
        message_id=700,
        sender=types.SimpleNamespace(user_id=84),
        message=dialogue.Message(
            [types.SimpleNamespace(type="image", data={"url": "https://qq/missing"})]
        ),
    )
    event = _make_received_event(
        dialogue,
        message_id=701,
        segments=[types.SimpleNamespace(type="text", data={"text": "look"})],
        reply=reply,
    )

    asyncio.run(dialogue.get_human_message(MagicMock(), event))

    reply_to = dialogue.message_to_json.call_args.kwargs["reply_to"]
    assert reply_to["content"] == (
        " ![图片](/tmp/hatsume-user-images/700-1.png) "
    )
    assert dialogue.save_sandbox_user_image.await_args.args[1:] == (
        700,
        1,
        "png",
    )
    assert dialogue.save_sandbox_user_image.await_args.kwargs == {"group_id": 7}


def test_get_human_message_recovers_reply_image_after_lookup_error():
    dialogue = _load_conversation_module()
    dialogue.message_to_json.reset_mock()
    dialogue.message_to_json.return_value = {"type": "message"}
    dialogue.has_forward_segment = MagicMock(return_value=None)
    dialogue.find_sandbox_user_image = AsyncMock(
        side_effect=RuntimeError("sandbox lookup failed")
    )
    dialogue.requests.get = MagicMock(return_value=_image_response("PNG"))
    dialogue.save_sandbox_user_image = AsyncMock(
        return_value="/tmp/hatsume-user-images/702-1.png"
    )
    reply = types.SimpleNamespace(
        message_id=702,
        sender=types.SimpleNamespace(user_id=84),
        message=dialogue.Message(
            [types.SimpleNamespace(type="image", data={"url": "https://qq/recover"})]
        ),
    )
    event = _make_received_event(
        dialogue,
        message_id=703,
        segments=[types.SimpleNamespace(type="text", data={"text": "look"})],
        reply=reply,
    )

    asyncio.run(dialogue.get_human_message(MagicMock(), event))

    reply_to = dialogue.message_to_json.call_args.kwargs["reply_to"]
    assert reply_to["content"] == (
        " ![图片](/tmp/hatsume-user-images/702-1.png) "
    )
    dialogue.requests.get.assert_called_once_with("https://qq/recover", timeout=10)


def test_get_human_message_keeps_temp_url_when_sandbox_storage_fails():
    dialogue = _load_conversation_module()
    dialogue.message_to_json.reset_mock()
    dialogue.message_to_json.return_value = {"type": "message"}
    dialogue.has_forward_segment = MagicMock(return_value=None)
    dialogue.requests.get = MagicMock(side_effect=RuntimeError("network down"))
    event = _make_received_event(
        dialogue,
        message_id=222,
        segments=[
            types.SimpleNamespace(
                type="image",
                data={"url": "https://qq/temporary"},
            )
        ],
    )

    content, _ = asyncio.run(dialogue.get_human_message(MagicMock(), event))

    assert dialogue.message_to_json.call_args.args[2] == (
        " ![图片（临时链接）](https://qq/temporary) "
    )
    assert len(content) == 1


def test_get_human_message_leaves_merged_forward_image_urls_unchanged():
    dialogue = _load_conversation_module()
    dialogue.build_forward_json.reset_mock()
    dialogue.build_forward_json.return_value = {"type": "forward"}
    dialogue.has_forward_segment = MagicMock(return_value="forward-1")
    forward_messages = [
        {
            "type": "message",
            "content": "![图片（临时链接）](https://qq/forward)",
        }
    ]
    dialogue.resolve_forward_content = AsyncMock(return_value=forward_messages)
    dialogue.requests.get = MagicMock()
    event = _make_received_event(
        dialogue,
        message_id=654,
        segments=[types.SimpleNamespace(type="forward", data={"id": "forward-1"})],
    )

    content, _ = asyncio.run(dialogue.get_human_message(MagicMock(), event))

    assert dialogue.build_forward_json.call_args.args[2] == forward_messages
    dialogue.requests.get.assert_not_called()
    assert len(content) == 1


def test_non_peer_messages_always_enter_auxiliary_queue():
    dialogue = _load_conversation_module()
    normalized = [{"type": "text", "text": "non-peer"}]
    source = {"source_id": "m1", "text": "non-peer", "people": []}
    dialogue.get_human_message = AsyncMock(return_value=(normalized, source))
    dialogue.append_auxiliary_message.reset_mock()

    character_proxy_name = "hatsume.plugins.hatsume-plugin.character_proxy"
    character_proxy = types.ModuleType(character_proxy_name)
    character_proxy.activate_character_proxy_peer = MagicMock()
    sys.modules[character_proxy_name] = character_proxy

    event = types.SimpleNamespace(
        group_id=7,
        user_id=42,
        original_message=[],
        get_session_id=lambda: "group_7_42",
    )
    matcher = types.SimpleNamespace(finish=AsyncMock())
    dialogue.group_runtime_registry.clear_for_tests()
    state = dialogue.group_runtime_registry.get_or_create(7).conversation

    for is_chatting in (False, True):
        state.is_chatting = is_chatting
        state.chat_peers = {"group_7_other"} if is_chatting else set()
        asyncio.run(dialogue.user_chat_handle(MagicMock(), event, matcher))

    assert dialogue.append_auxiliary_message.call_count == 2
    dialogue.append_auxiliary_message.assert_called_with(normalized, [source])
    assert state.idle_queue == []
    assert state.pending_queue == []
    assert state.human_queue == []


def test_user_chat_callback_sends_to_origin_group_without_matcher_context():
    dialogue = _load_conversation_module()
    text_segment = types.SimpleNamespace(type="text", data={"text": "answer"})
    dialogue.auto_convert_text = AsyncMock(return_value=[text_segment])
    dialogue.get_human_message = AsyncMock(
        return_value=(
            [{"type": "text", "text": "question"}],
            {"source_id": "m1", "text": "question", "people": []},
        )
    )
    dialogue.USER_INPUT_CONFIRM_DURING_TIME = 0

    character_proxy_name = "hatsume.plugins.hatsume-plugin.character_proxy"
    character_proxy = types.ModuleType(character_proxy_name)
    character_proxy.activate_character_proxy_peer = MagicMock()
    sys.modules[character_proxy_name] = character_proxy

    event = types.SimpleNamespace(
        group_id=100,
        user_id=42,
        original_message=[],
        get_session_id=lambda: "group_100_42",
    )
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())
    matcher = types.SimpleNamespace(send=AsyncMock())
    dialogue.group_runtime_registry.clear_for_tests()
    dialogue.group_runtime_registry.get_or_create(100).conversation.activate_chat(
        event.get_session_id()
    )

    async def invoke_ai_callback(_state, ai_callback, _configure_tools, **_kwargs):
        await ai_callback("answer")

    dialogue.start_new_conversation = AsyncMock(side_effect=invoke_ai_callback)

    asyncio.run(dialogue.user_chat_handle(bot, event, matcher))

    bot.send_group_msg.assert_awaited_once_with(
        group_id=100,
        message=text_segment,
    )
    matcher.send.assert_not_awaited()


def test_handle_ai_message_prepends_reply_segment():
    dialogue = _load_conversation_module()
    text_seg = types.SimpleNamespace(type="text", data={"text": "answer"})
    dialogue.auto_convert_text = AsyncMock(return_value=[text_seg])
    dialogue.MessageSegment.reply = MagicMock(
        side_effect=lambda message_id: types.SimpleNamespace(
            type="reply", data={"id": message_id}
        )
    )
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(
        dialogue.handle_ai_message(
            "answer", bot, group_id=7, reply_to_message_id=321
        )
    )

    payload = bot.send_group_msg.await_args.kwargs["message"]
    assert [seg.type for seg in payload] == ["reply", "text"]
    assert payload[0].data["id"] == 321


def test_handle_ai_message_reply_failure_falls_back_to_plain_send():
    dialogue = _load_conversation_module()
    text_seg = types.SimpleNamespace(type="text", data={"text": "answer"})
    dialogue.auto_convert_text = AsyncMock(return_value=[text_seg])
    dialogue.MessageSegment.reply = MagicMock(
        side_effect=lambda message_id: types.SimpleNamespace(
            type="reply", data={"id": message_id}
        )
    )
    bot = types.SimpleNamespace(
        send_group_msg=AsyncMock(side_effect=[RuntimeError("reply rejected"), None])
    )

    asyncio.run(
        dialogue.handle_ai_message(
            "answer", bot, group_id=7, reply_to_message_id=321
        )
    )

    assert bot.send_group_msg.await_count == 2
    first_payload = bot.send_group_msg.await_args_list[0].kwargs["message"]
    assert first_payload[0].type == "reply"
    assert bot.send_group_msg.await_args_list[1].kwargs["message"] is text_seg


def test_reply_segment_stays_first_with_cq_at_output():
    dialogue = _load_conversation_module()
    dialogue.auto_convert_text = AsyncMock(
        return_value=[types.SimpleNamespace(type="text", data={"text": "hi @Treep"})]
    )
    dialogue.render_cq_at_placeholders = AsyncMock(
        return_value=("hi @Treep", [123456])
    )
    dialogue.MessageSegment.text = MagicMock(
        side_effect=lambda text: types.SimpleNamespace(
            type="text", data={"text": text}
        )
    )
    dialogue.MessageSegment.at = MagicMock(
        side_effect=lambda uid: types.SimpleNamespace(type="at", data={"qq": uid})
    )
    dialogue.MessageSegment.reply = MagicMock(
        side_effect=lambda message_id: types.SimpleNamespace(
            type="reply", data={"id": message_id}
        )
    )
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(
        dialogue.handle_ai_message(
            "hi [CQ:at,qq=123456]",
            bot,
            group_id=7,
            reply_to_message_id=321,
        )
    )

    payload = bot.send_group_msg.await_args.kwargs["message"]
    assert [seg.type for seg in payload] == ["reply", "text", "at"]


def test_reply_segment_stays_first_with_rendered_image_output():
    dialogue = _load_conversation_module()
    image_seg = types.SimpleNamespace(type="image", data={"file": "img"})
    dialogue.auto_convert_text = AsyncMock(return_value=[image_seg])
    dialogue.MessageSegment.reply = MagicMock(
        side_effect=lambda message_id: types.SimpleNamespace(
            type="reply", data={"id": message_id}
        )
    )
    bot = types.SimpleNamespace(send_group_msg=AsyncMock())

    asyncio.run(
        dialogue.handle_ai_message(
            "# rendered reply",
            bot,
            group_id=7,
            reply_to_message_id=321,
        )
    )

    payload = bot.send_group_msg.await_args.kwargs["message"]
    assert [seg.type for seg in payload] == ["reply", "image"]


def test_direct_group_reply_failure_falls_back_to_plain_send(capsys):
    dialogue = _load_conversation_module()
    text_seg = types.SimpleNamespace(type="text", data={"text": "answer"})
    dialogue.auto_convert_text = AsyncMock(return_value=[text_seg])
    dialogue.MessageSegment.reply = MagicMock(
        side_effect=lambda message_id: types.SimpleNamespace(
            type="reply", data={"id": message_id}
        )
    )
    bot = types.SimpleNamespace(
        send_group_msg=AsyncMock(side_effect=[RuntimeError("reply rejected"), None])
    )

    asyncio.run(
        dialogue._send_group_ai_message(
            bot,
            7,
            "answer",
            reply_to_message_id=321,
        )
    )

    assert bot.send_group_msg.await_count == 2
    first_payload = bot.send_group_msg.await_args_list[0].kwargs["message"]
    assert first_payload[0].type == "reply"
    assert bot.send_group_msg.await_args_list[1].kwargs["message"] is text_seg
    assert "Reply target rejected" in capsys.readouterr().out
