"""Tests for handlers/dialogue.py — the extracted conversation startup logic."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
    state = ConversationState()
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

    # Stub graph.nodes
    nodes_name = "hatsume.plugins.hatsume-plugin.graph.nodes"
    if nodes_name not in sys.modules:
        nodes_mod = types.ModuleType(nodes_name)
        nodes_mod.bind_state = MagicMock()
        nodes_mod.reset_memory_record_context = MagicMock()
        nodes_mod.set_current_query_user_id = MagicMock()
        nodes_mod.get_role_sys_prompt = MagicMock(return_value="role-prompt")
        nodes_mod.append_auxiliary_message = MagicMock()
        sys.modules[nodes_name] = nodes_mod

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
    if "hatsume.plugins.hatsume-plugin.memory" in sys.modules:
        memory = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
        memory.get_mem_list = MagicMock(return_value=[])
        memory.add_mem = MagicMock()
        memory.query_mems = MagicMock(return_value=[])

    # Stub graph.tools (imported by chat.py)
    tools_name = "hatsume.plugins.hatsume-plugin.graph.tools"
    if tools_name not in sys.modules:
        tools_mod = types.ModuleType(tools_name)
        tools_mod.configure_agent_notification_callback = MagicMock()
        tools_mod.configure_tool_callbacks = MagicMock()
        sys.modules[tools_name] = tools_mod

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


def test_handle_ai_message_sends_plain_text_segments_without_at_prefix():
    dialogue = _load_conversation_module()
    dialogue.auto_convert_text = AsyncMock(return_value=["plain-text-segment"])
    dialogue.MessageSegment.at = MagicMock(return_value="at-segment")
    matcher = types.SimpleNamespace(send=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("hello", matcher))

    dialogue.MessageSegment.at.assert_not_called()
    matcher.send.assert_awaited_once_with("plain-text-segment")


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
    matcher = types.SimpleNamespace(send=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("hi [CQ:at,qq=123456]", matcher, group_id=7))

    payload = matcher.send.await_args.args[0]
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
    matcher = types.SimpleNamespace(send=AsyncMock())

    asyncio.run(dialogue.handle_ai_message("# [CQ:at,qq=123456]\nresult", matcher, group_id=7))

    payload = matcher.send.await_args.args[0]
    assert [seg.type for seg in payload] == ["at", "image"]
    assert payload[0].data["qq"] == 123456
