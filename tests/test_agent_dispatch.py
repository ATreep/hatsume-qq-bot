"""Tests for agent_dispatch tool and agents registry."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Set up package hierarchy so the real module can be imported
ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy():
    """Ensure hatsume.plugins.hatsume_plugin.graph package hierarchy exists."""
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

    # Create alias so hatsume_plugin resolves to hatsume-plugin
    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias

    # Stub nonebot.adapters.onebot.v11 (imported by tools / agents)
    if "nonebot" not in sys.modules:
        nb = types.ModuleType("nonebot")
        nb.require = lambda name: None
        nb.get_bot = lambda: None
        sys.modules["nonebot"] = nb
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
        v11.Message = type("Message", (), {})
        v11.MessageSegment = types.SimpleNamespace(
            text=lambda s: s, image=lambda *a, **kw: None
        )
        v11.GroupMessageEvent = type("GroupMessageEvent", (), {})
        sys.modules[v11_name] = v11
    # Stub nonebot_plugin_localstore (imported by memory.engine)
    if "nonebot_plugin_localstore" not in sys.modules:
        localstore = types.ModuleType("nonebot_plugin_localstore")
        localstore.get_plugin_data_file = lambda name: Path("/tmp")
        sys.modules["nonebot_plugin_localstore"] = localstore
    # Stub apscheduler (imported by memory.engine)
    if "apscheduler" not in sys.modules:
        aps = types.ModuleType("apscheduler")
        sys.modules["apscheduler"] = aps
    aps_triggers_name = "apscheduler.triggers"
    if aps_triggers_name not in sys.modules:
        aps_trig = types.ModuleType(aps_triggers_name)
        aps_trig.__path__ = []
        sys.modules[aps_triggers_name] = aps_trig
    aps_cron_name = "apscheduler.triggers.cron"
    if aps_cron_name not in sys.modules:
        aps_cron = types.ModuleType(aps_cron_name)
        aps_cron.CronTrigger = type("CronTrigger", (), {})
        sys.modules[aps_cron_name] = aps_cron
    # Stub nonebot_plugin_apscheduler (imported by memory.engine)
    if "nonebot_plugin_apscheduler" not in sys.modules:
        nbp_aps = types.ModuleType("nonebot_plugin_apscheduler")
        scheduler_stub = types.SimpleNamespace()
        scheduler_stub.scheduled_job = lambda *a, **kw: (lambda f: f)
        nbp_aps.scheduler = scheduler_stub
        sys.modules["nonebot_plugin_apscheduler"] = nbp_aps
    # Fix the nonebot.require stub to return the apscheduler module when asked
    sys.modules["nonebot"].require = lambda name: sys.modules.get(name, types.SimpleNamespace())
    # Stub jieba (imported by memory.tokenizer — must be a package for posseg)
    jieba_posseg_name = "jieba.posseg"
    if jieba_posseg_name not in sys.modules:
        jieba_pseg = types.ModuleType(jieba_posseg_name)
        jieba_pseg.cut = lambda text: [(w, "n") for w in text.split()]
        sys.modules[jieba_posseg_name] = jieba_pseg
    if "jieba" not in sys.modules:
        jieba_mod = types.ModuleType("jieba")
        jieba_mod.__path__ = []  # Make it a package so submodules resolve
        jieba_mod.cut = lambda text, cut_all=False: text.split()
        jieba_mod.posseg = sys.modules[jieba_posseg_name]
        sys.modules["jieba"] = jieba_mod


_setup_package_hierarchy()


class TestAgentRegistry:
    """Tests for graph/agents.py registry functions."""

    def test_register_and_get_agent_list(self):
        """get_agent_list returns all registered agents."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
            register_agent,
            get_agent_list,
            get_agent_handler,
        )

        original = dict(AGENT_REGISTRY)
        AGENT_REGISTRY.clear()
        try:
            async def dummy_handler(task: str, user_id: int) -> str:
                return f"done: {task}"

            register_agent("test_agent", "A test agent", dummy_handler)

            agent_list = get_agent_list()
            assert len(agent_list) == 1
            assert agent_list[0]["name"] == "test_agent"
            assert agent_list[0]["description"] == "A test agent"

            handler = get_agent_handler("test_agent")
            assert handler is not None
            assert handler is dummy_handler
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(original)

    def test_get_agent_handler_unknown_returns_none(self):
        """get_agent_handler returns None for unknown agent name."""
        from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_handler

        result = get_agent_handler("nonexistent_agent")
        assert result is None


class TestAgentContext:
    """Tests for get_agent_context() — US1."""

    def test_get_agent_context_returns_stored_context(self):
        """get_agent_context returns the context stored via agent state."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            add_agent_instance,
            get_agent_context,
        )

        add_agent_instance("test_ctx_agent", context="用户讨论性能优化", status="running")
        assert get_agent_context("test_ctx_agent") == "用户讨论性能优化"

    def test_get_agent_context_returns_empty_for_missing(self):
        """get_agent_context returns '' when agent has no state."""
        from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_context

        assert get_agent_context("nonexistent_ctx_agent") == ""

    def test_get_agent_context_returns_empty_when_no_context_field(self):
        """get_agent_context returns '' when state exists but no context field."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            add_agent_instance,
            get_agent_context,
        )

        add_agent_instance("test_ctx_agent2", status="running")  # no context
        assert get_agent_context("test_ctx_agent2") == ""
