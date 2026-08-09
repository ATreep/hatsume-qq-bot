"""Tests for /agents command handler."""

from __future__ import annotations

import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


class MockFinished(Exception):
    """Simulate NoneBot's FinishedException for matcher.finish()."""
    pass


def _finish_that_stops(*args, **kwargs):
    """Mock finish that raises MockFinished to stop execution."""
    raise MockFinished


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy() -> None:
    """Ensure package hierarchy exists with hyphen-to-underscore alias."""
    packages = [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]
    for name, path in packages:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Alias so hatsume_plugin resolves to hatsume-plugin
    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias

    # Stub nonebot
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adap_name = "nonebot.adapters"
    if adap_name not in sys.modules:
        adap = types.ModuleType(adap_name)
        adap.__path__ = []
        sys.modules[adap_name] = adap
    if not hasattr(sys.modules[adap_name], "Bot"):
        sys.modules[adap_name].Bot = type("Bot", (), {})
    onebot_name = "nonebot.adapters.onebot"
    if onebot_name not in sys.modules:
        ob = types.ModuleType(onebot_name)
        ob.__path__ = []
        sys.modules[onebot_name] = ob
    v11_name = "nonebot.adapters.onebot.v11"
    if v11_name not in sys.modules:
        v11 = types.ModuleType(v11_name)
    else:
        v11 = sys.modules[v11_name]
    v11.Message = type("Message", (), {})
    v11.MessageSegment = types.SimpleNamespace(
        text=lambda s: s, image=lambda *a, **kw: None
    )
    v11.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules.setdefault(v11_name, v11)

    # Stub infra module (imported by commands.py)
    infra_name = "hatsume.plugins.hatsume-plugin.infra"
    if infra_name not in sys.modules:
        infra = types.ModuleType(infra_name)
        infra.run_cmd = lambda *a, **kw: ""
        infra.run_cmd_async = AsyncMock(return_value="")
        infra.delete_container = lambda: None
        infra.cleanup_persistent_container = AsyncMock(return_value=False)
        infra.ensure_container_running = lambda: None
        infra.render_html_to_image = AsyncMock(return_value=b"")
        infra.cache_sandbox_message_image = AsyncMock()
        sys.modules[infra_name] = infra
        sys.modules["hatsume.plugins.hatsume_plugin.infra"] = infra

    infra = sys.modules[infra_name]
    if not hasattr(infra, "cache_sandbox_message_image"):
        infra.cache_sandbox_message_image = AsyncMock()
    sys.modules["hatsume.plugins.hatsume_plugin.infra"] = infra

    # Stub models module
    models_name = "hatsume.plugins.hatsume-plugin.models"
    if models_name not in sys.modules:
        models = types.ModuleType(models_name)
        models.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
        models.generate_video_for = AsyncMock(return_value="http://example.com/vid.mp4")
        models.choose_video_model = lambda: "1.0"
        models.get_code_model = MagicMock()
        sys.modules[models_name] = models
        sys.modules["hatsume.plugins.hatsume_plugin.models"] = models

    # Stub config module
    config_name = "hatsume.plugins.hatsume-plugin.config"
    if config_name not in sys.modules:
        config = types.ModuleType(config_name)
        config.ADMIN_QQ_ID = "12345"
        config.SKILLS_DIR = PLUGIN_DIR / "data" / "skills"
        sys.modules[config_name] = config
        sys.modules["hatsume.plugins.hatsume_plugin.config"] = config

    runtime_name = "hatsume.plugins.hatsume_plugin.group_runtime"
    runtime = types.ModuleType(runtime_name)

    @contextmanager
    def bind_group_runtime(value):
        yield value

    runtime.bind_group_runtime = bind_group_runtime
    runtime.group_runtime_registry = types.SimpleNamespace(
        get_or_create=lambda group_id: types.SimpleNamespace(group_id=group_id),
        get_existing=lambda _group_id: None,
    )
    sys.modules[runtime_name] = runtime

    # Stub state module
    state_name = "hatsume.plugins.hatsume-plugin.state"
    if state_name not in sys.modules:
        state = types.ModuleType(state_name)
        state.ConversationState = MagicMock()
        sys.modules[state_name] = state
        sys.modules["hatsume.plugins.hatsume_plugin.state"] = state

    # Stub utils module
    utils_name = "hatsume.plugins.hatsume-plugin.utils"
    if utils_name not in sys.modules:
        utils = types.ModuleType(utils_name)
        utils.get_qq_avatar_url = lambda qq: f"http://avatar.example.com/{qq}"
        utils.get_group_member_name = AsyncMock(return_value="TestUser")
        utils.search_group_members = AsyncMock(return_value=[])
        sys.modules[utils_name] = utils
        sys.modules["hatsume.plugins.hatsume_plugin.utils"] = utils


_setup_package_hierarchy()


def _get_agents_module():
    """Load and return the agents module (load directly, not through commands)."""
    import importlib.util
    agents_path = PLUGIN_DIR / "graph" / "agents.py"
    full_name = "hatsume.plugins.hatsume_plugin.graph.agents"
    if full_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(full_name, agents_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[full_name]


def _get_commands_module():
    """Load and return the commands module (always reload to avoid stale stubs)."""
    # Force-set nonebot stubs (other tests may have polluted them)
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adap_name = "nonebot.adapters"
    if adap_name not in sys.modules:
        sys.modules[adap_name] = types.ModuleType(adap_name)
        sys.modules[adap_name].__path__ = []
    sys.modules[adap_name].Bot = type("Bot", (), {})
    v11_name = "nonebot.adapters.onebot.v11"
    if v11_name not in sys.modules:
        sys.modules[v11_name] = types.ModuleType(v11_name)
    if not hasattr(sys.modules[v11_name], "Message"):
        sys.modules[v11_name].Message = type("Message", (), {})
    if not hasattr(sys.modules[v11_name], "MessageSegment"):
        sys.modules[v11_name].MessageSegment = types.SimpleNamespace(text=lambda s: s, image=lambda *a, **kw: None)
    if not hasattr(sys.modules[v11_name], "PokeNotifyEvent"):
        sys.modules[v11_name].PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    runtime_name = "hatsume.plugins.hatsume_plugin.group_runtime"
    runtime = sys.modules.setdefault(runtime_name, types.ModuleType(runtime_name))

    @contextmanager
    def bind_group_runtime(value):
        yield value

    runtime.bind_group_runtime = bind_group_runtime
    runtime.group_runtime_registry = types.SimpleNamespace(
        get_or_create=lambda group_id: types.SimpleNamespace(group_id=group_id),
        get_existing=lambda _group_id: None,
    )
    for config_name in (
        "hatsume.plugins.hatsume-plugin.config",
        "hatsume.plugins.hatsume_plugin.config",
    ):
        sys.modules[config_name].ADMIN_QQ_ID = "12345"
    # Reload the module
    import importlib.util
    full_name = "hatsume.plugins.hatsume_plugin.handlers.tools"
    commands_path = PLUGIN_DIR / "handlers" / "tools.py"
    if full_name in sys.modules:
        del sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, commands_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[full_name]


def _run_and_capture_msg(
    matcher,
    *,
    args_text: str = "",
    user_id: str = "77",
) -> str:
    """Run handle_agents, catch MockFinished, return the finish message."""
    import asyncio
    cmd = _get_commands_module()
    event = types.SimpleNamespace(group_id=101, get_user_id=lambda: user_id)
    args = types.SimpleNamespace(extract_plain_text=lambda: args_text)
    try:
        asyncio.run(cmd.handle_agents(event, matcher, args))
    except MockFinished:
        pass
    matcher.finish.assert_awaited_once()
    return matcher.finish.call_args[0][0]


class TestHandleAgents:
    """Tests for handle_agents command handler."""

    def test_no_agents_registered(self):
        """When no agents are registered, returns appropriate message."""
        ag = _get_agents_module()

        original_registry = dict(ag.AGENT_REGISTRY)
        original_states = dict(ag._AGENT_STATES)
        ag.AGENT_REGISTRY.clear()
        ag._AGENT_STATES.clear()

        try:
            matcher = MagicMock()
            matcher.finish = AsyncMock(side_effect=_finish_that_stops)
            msg = _run_and_capture_msg(matcher)
            assert "没有已注册的 Agent" in msg or "没有" in msg
        finally:
            ag.AGENT_REGISTRY.update(original_registry)
            ag._AGENT_STATES.update(original_states)

    def test_all_agents_idle(self):
        """When all agents are idle (no running), shows no-running message."""
        ag = _get_agents_module()
        ag._AGENT_STATES.clear()

        try:
            matcher = MagicMock()
            matcher.finish = AsyncMock(side_effect=_finish_that_stops)
            msg = _run_and_capture_msg(matcher)
            assert "当前没有正在运行的 Agent" in msg
        finally:
            ag._AGENT_STATES.clear()

    def test_agent_running_shows_task_and_time(self):
        """Running agent shows task description and start time."""
        ag = _get_agents_module()
        ag._AGENT_STATES.clear()
        now = time.time()
        ag.set_agent_state(
            "coding_agent",
            group_id=101,
            status="running",
            task="fix login bug",
            started_at=now,
        )

        try:
            matcher = MagicMock()
            matcher.finish = AsyncMock(side_effect=_finish_that_stops)
            msg = _run_and_capture_msg(matcher)
            assert "coding_agent" in msg
            assert "执行中" in msg
            assert "fix login bug" in msg
        finally:
            ag._AGENT_STATES.clear()

    def test_agent_done_shows_result(self):
        """Completed (non-running) agents are not shown in the running-only view."""
        ag = _get_agents_module()
        ag._AGENT_STATES.clear()
        ag.set_agent_state(
            "coding_agent",
            group_id=101,
            status="done",
            task="refactor module",
            result="success",
        )

        try:
            matcher = MagicMock()
            matcher.finish = AsyncMock(side_effect=_finish_that_stops)
            msg = _run_and_capture_msg(matcher)
            # Done agents are not running, so the no-running message is expected
            assert "当前没有正在运行的 Agent" in msg
        finally:
            ag._AGENT_STATES.clear()

    def test_mixed_states(self):
        """Only running agents are shown; non-running agents are omitted."""
        ag = _get_agents_module()
        ag._AGENT_STATES.clear()
        ag.set_agent_state(
            "coding_agent",
            group_id=101,
            status="running",
            task="task A",
            started_at=time.time(),
        )
        ag.set_agent_state(
            "generate_video",
            group_id=101,
            status="done",
            task="task B",
            result="video ok",
        )

        try:
            matcher = MagicMock()
            matcher.finish = AsyncMock(side_effect=_finish_that_stops)
            msg = _run_and_capture_msg(matcher)
            assert "coding_agent" in msg
            assert "执行中" in msg
            # Done agents are not shown in the running-only view
            assert "generate_video" not in msg
        finally:
            ag._AGENT_STATES.clear()

    def test_admin_can_select_another_group_without_leaking_current_group(self):
        ag = _get_agents_module()
        ag._AGENT_STATES.clear()
        ag.set_agent_state(
            "coding_agent",
            group_id=101,
            status="running",
            task="current group task",
            started_at=time.time(),
        )
        ag.set_agent_state(
            "coding_agent",
            group_id=202,
            status="running",
            task="selected group task",
            started_at=time.time(),
        )
        matcher = MagicMock()
        matcher.finish = AsyncMock(side_effect=_finish_that_stops)

        try:
            msg = _run_and_capture_msg(
                matcher,
                args_text="202",
                user_id="12345",
            )
            assert "selected group task" in msg
            assert "current group task" not in msg
        finally:
            ag._AGENT_STATES.clear()

    def test_non_admin_cannot_select_another_group(self):
        matcher = MagicMock()
        matcher.finish = AsyncMock(side_effect=_finish_that_stops)

        msg = _run_and_capture_msg(matcher, args_text="202", user_id="77")

        assert msg == "只有管理员可以访问其他群的数据。"

    def test_invalid_group_argument_is_rejected(self):
        matcher = MagicMock()
        matcher.finish = AsyncMock(side_effect=_finish_that_stops)

        msg = _run_and_capture_msg(
            matcher,
            args_text="202 extra",
            user_id="12345",
        )

        assert "群号必须是正整数" in msg
