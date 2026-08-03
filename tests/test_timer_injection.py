"""Tests for timer graph injection."""

from __future__ import annotations

import sys
import types
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_BASE = ROOT / "hatsume/plugins/hatsume-plugin"


class MockMessage:
    """Lightweight stand-in for LangChain message objects."""
    def __init__(self, content="", msg_type="human", msg_id=None):
        self.content = content
        self.type = msg_type
        self.id = msg_id or f"msg-{id(self)}"


class MockState:
    """Minimal state object matching ai.py's _state interface."""
    def __init__(self):
        self.is_chatting = False
        self.human_queue: list[dict] = []
        self.chat_peers: set[str] = set()


def _set_group_state(ai_mod, group_id: int, state: MockState) -> None:
    runtime = ai_mod.group_runtime_registry.get_or_create(group_id)
    runtime.conversation = state


def _load_ai_module():
    """Load graph/nodes/ai.py with all external dependencies stubbed."""
    pkg_prefixes = [
        "hatsume", "hatsume.plugins", "hatsume.plugins.hatsume_plugin",
        "hatsume.plugins.hatsume-plugin",
    ]
    for name in list(sys.modules):
        if any(name.startswith(p) for p in pkg_prefixes) or name in (
            "nonebot", "nonebot_plugin_localstore",
            "nonebot.adapters", "nonebot.adapters.onebot",
            "nonebot.adapters.onebot.v11",
            "langchain", "langchain.messages", "langchain.agents",
            "langchain_core", "langchain_core.messages",
            "langchain_community", "langchain_community.tools",
            "langgraph", "langgraph.graph", "openai",
        ):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for stub_name, stub_path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
        ("hatsume.plugins.hatsume-plugin.graph", base / "graph"),
        ("hatsume.plugins.hatsume-plugin.memory", base / "memory"),
        ("hatsume.plugins.hatsume-plugin.timer", base / "timer"),
        ("hatsume.plugins.hatsume-plugin.skills", base / "skills"),
    ]:
        mod = types.ModuleType(stub_name)
        mod.__path__ = [str(stub_path)]
        sys.modules[stub_name] = mod

    # Stub langchain
    langchain_mod = types.ModuleType("langchain")
    langchain_mod.__path__ = []
    sys.modules["langchain"] = langchain_mod

    class _AIMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "ai"

    class _HumanMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "human"

    class _SystemMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "system"

    lc_msgs = types.ModuleType("langchain.messages")
    lc_msgs.AIMessage = _AIMessage
    lc_msgs.HumanMessage = _HumanMessage
    lc_msgs.SystemMessage = _SystemMessage
    sys.modules["langchain.messages"] = lc_msgs

    lc_agents = types.ModuleType("langchain.agents")
    lc_agents.create_agent = lambda *a, **kw: None
    sys.modules["langchain.agents"] = lc_agents

    sys.modules["langchain_core"] = types.ModuleType("langchain_core")
    lc_core_msgs = types.ModuleType("langchain_core.messages")
    lc_core_msgs.RemoveMessage = type("RemoveMessage", (), {})
    sys.modules["langchain_core.messages"] = lc_core_msgs

    sys.modules["langgraph"] = types.ModuleType("langgraph")
    lg_graph = types.ModuleType("langgraph.graph")
    lg_graph.MessagesState = dict
    sys.modules["langgraph.graph"] = lg_graph

    # Stub nonebot
    sys.modules["nonebot"] = types.ModuleType("nonebot")
    nonebot_mod = sys.modules["nonebot"]
    nonebot_mod.get_bot = lambda: None
    adapters = types.ModuleType("nonebot.adapters")
    adapters = types.ModuleType("nonebot.adapters")
    sys.modules["nonebot.adapters"] = adapters
    onebot = types.ModuleType("nonebot.adapters.onebot")
    sys.modules["nonebot.adapters.onebot"] = onebot
    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.MessageSegment = types.SimpleNamespace(text=lambda s: s)
    v11.Message = type("Message", (list,), {"extract_plain_text": lambda self: ""})
    sys.modules["nonebot.adapters.onebot.v11"] = v11

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = lambda name: types.SimpleNamespace(
        iterdir=lambda: [], absolute=lambda: Path("/tmp"),
    )
    sys.modules["nonebot_plugin_localstore"] = localstore

    async def _get_timer_overview():
        return ""

    stub_defs = {
        "hatsume.plugins.hatsume-plugin.models": {
            "get_advance_model": lambda thinking=True: None,
            "get_code_model": lambda thinking=True: None,
            "get_lite_model": lambda thinking=True: None,
            "get_mini_model": lambda thinking=True: None,
        },
        "hatsume.plugins.hatsume-plugin.prompts": {
            "role_sys_prompt": "test role prompt",
            "build_face_emotion_classifier_prompt": lambda e: "",
            "build_face_injection_prompt": lambda e: "",
            "build_memory_context_prompt": lambda m: "",
            "build_skill_prompt": lambda s: "",
            "build_agent_state_prompt": lambda s: "",
            "build_admin_mode_prompt": lambda admin_qq_id: "",
            "build_character_proxy_role_prompt": lambda **kw: "",
            "build_todo_prompt": lambda items, available=True: "todo prompt",
            "AUXILIARY_COMPACTION_PROMPT": "",
            "CHAT_END_DETECT_PROMPT": "detect_end",
        },
        "hatsume.plugins.hatsume-plugin.skills": {
            "get_skill_manager": lambda: types.SimpleNamespace(list_skills=lambda: []),
        },
        "hatsume.plugins.hatsume-plugin.graph": {},
        "hatsume.plugins.hatsume-plugin.utils": {
            "CQ_AT_PATTERN": re.compile(r"\[CQ:at,qq=(\d+)\]"),
            "get_group_member_name": lambda *a, **kw: "",
            "get_date": lambda: "2026-01-01",
            "message_to_json": lambda *a, **kw: {},
        },
        "hatsume.plugins.hatsume-plugin.utils.md_to_image": {
            "auto_convert_text": lambda *a, **kw: None,
        },
        "hatsume.plugins.hatsume-plugin.graph.tools": {
            "search_web": None, "shell_executor": None, "find_memory": None,
            "query_memory": lambda *a, **kw: "", "capture_html_shot": None,
            "generate_image": None, "generate_video": None, "view_image": None,
            "send_image": None, "send_video": None,
            "reset_capture_flag": lambda: None,
            "get_avatar": None, "random_acg_photo": None,
            "create_daily_timer": None, "create_weekly_timer": None,
            "create_monthly_timer": None, "create_at_timer": None,
            "create_todo": None, "mark_todo": None,
            "list_timers": None,
            "get_timer_overview": _get_timer_overview,
            "delete_timer": None, "skill_loader": None, "skill_remove": None,
            "skill_download": None, "skill_create": None, "membersearch": None,
            "agent_dispatch": None, "respond_to_shell_prompt": None,
            "CHAT_TOOLS": [None] * 25,
            "get_chat_tools": lambda: [None] * 25,
            "set_shell_executor_limit": None,
            "get_current_group_id": lambda: 0,
            "_current_group_id": 0, "_capture_html_shot_used": False,
            "_generate_image_used": False, "_last_capture_html_demand": "",
        },
        "hatsume.plugins.hatsume-plugin.character_proxy": {
            "get_character_proxy": lambda: None,
            "build_active_character_proxy_role_prompt": lambda proxy: "",
            "message_mentions_character_proxy": lambda content: False,
        },
        "hatsume.plugins.hatsume-plugin.todo": {
            "get_store": lambda: types.SimpleNamespace(
                delete_expired=lambda: 0,
                list_items=lambda group_id: [],
            ),
        },
    }
    for name, attrs in stub_defs.items():
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod

    import importlib.util
    full_name = "hatsume.plugins.hatsume-plugin.graph.nodes"
    spec = importlib.util.spec_from_file_location(full_name, PLUGIN_BASE / "graph/nodes.py")
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestInjectTimer:
    """T004: inject_timer builds correct message and injects into state."""

    def test_injects_into_human_queue_when_chatting(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        _set_group_state(ai_mod, 101, mock_state)
        ai_mod.inject_timer(
            user_id=123, group_id=101, timer_prompt="提醒开会",
        )
        assert len(mock_state.human_queue) == 1
        msg = mock_state.human_queue[0]
        assert msg["type"] == "text"
        assert msg[ai_mod.SYSTEM_TRIGGER_KEY] == "timer"
        assert "__timer__" not in msg["text"]
        assert "提醒开会" in msg["text"]
        assert "coroutine" not in msg["text"]
        assert mock_state.chat_peers == set()

    def test_includes_notified_user_identity_in_prompt(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        _set_group_state(ai_mod, 102, mock_state)
        ai_mod.inject_timer(
            user_id=123,
            group_id=102,
            timer_prompt="提醒开会",
            notified_user_name="小明",
        )
        msg = mock_state.human_queue[0]["text"]
        assert "用户名：小明" in msg
        assert "QQ号：123" in msg
        assert "[CQ:at,qq=123]" in msg

    def test_calls_start_conversation_cb_when_not_chatting(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = False
        _set_group_state(ai_mod, 103, mock_state)
        cb_called = {"called": False, "user_id": 0, "msg": ""}
        def cb(uid, gid, msg):
            cb_called["called"] = True
            cb_called["user_id"] = uid
            cb_called["msg"] = msg
        ai_mod.inject_timer(
            user_id=456, group_id=103, timer_prompt="喝水提醒",
            start_conversation_cb=cb,
        )
        assert cb_called["called"]
        assert cb_called["user_id"] == 456
        assert "__timer__" not in cb_called["msg"]
        assert "喝水提醒" in cb_called["msg"]

    @pytest.mark.skip(reason="Merged nodes.py inject_timer calls _start_direct_conv which requires full dialogue.py import chain; out of scope for this test file")
    def test_no_callback_when_not_chatting_no_cb(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = False
        _set_group_state(ai_mod, 104, mock_state)
        ai_mod.inject_timer(user_id=789, group_id=104, timer_prompt="test")


class TestTimerInjectionRoundTrip:
    """T025: Full message format verification."""

    def test_inject_timer_to_graph_builds_correct_context(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        _set_group_state(ai_mod, 105, mock_state)
        ai_mod.inject_timer(
            user_id=111, group_id=105, timer_prompt="定时提醒：喝水",
            start_conversation_cb=None,
        )
        msg = mock_state.human_queue[0]
        assert "__timer__" not in msg["text"]
        assert "定时提醒：喝水" in msg["text"]
        assert mock_state.chat_peers == set()


class TestInjectAgentNotification:
    """Agent notification injection carries notified user identity."""

    def test_includes_notified_user_identity_in_prompt(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        _set_group_state(ai_mod, 9, mock_state)
        ai_mod.inject_agent_notification(
            user_id=234,
            group_id=9,
            agent_name="coding_agent",
            result="执行完成",
            task="修一下测试",
            context="用户要求修测试",
            notified_user_name="Treep",
        )
        msg = mock_state.human_queue[0]["text"]
        assert "__agent_notify__" not in msg
        assert "用户名：Treep" in msg
        assert "QQ号：234" in msg
        assert "[CQ:at,qq=234]" in msg
        assert mock_state.chat_peers == set()

    def test_marks_agent_notification_as_system_trigger(self):
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        _set_group_state(ai_mod, 9, mock_state)

        ai_mod.inject_agent_notification(
            user_id=234,
            group_id=9,
            agent_name="coding_agent",
            result="执行完成",
            task="修一下测试",
        )

        assert mock_state.human_queue[0][ai_mod.SYSTEM_TRIGGER_KEY] == "agent"
