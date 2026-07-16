"""Tests for agent state monitoring system."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

# Path-based import (matching project convention for graph modules)
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/agents.py"
TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"


def _load_agents_module():
    """Load agents.py via spec to get state functions."""
    # Mock chain imports that agents.py doesn't need for state functions
    if "langchain_openai" not in sys.modules:
        lc = types.ModuleType("langchain_openai")
        lc.ChatOpenAI = MagicMock()
        sys.modules["langchain_openai"] = lc
    if "langchain.agents" not in sys.modules:
        la = types.ModuleType("langchain.agents")
        la.create_agent = MagicMock()
        sys.modules["langchain.agents"] = la
    if "langchain.messages" not in sys.modules:
        lm = types.ModuleType("langchain.messages")
        lm.HumanMessage = MagicMock()
        sys.modules["langchain.messages"] = lm

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.graph.agents", AGENTS_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.graph.agents"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestAgentStateTracking:
    """Tests for _AGENT_STATES dict and state management functions."""

    def test_set_and_get_agent_state(self):
        mod = _load_agents_module()
        mod.set_agent_state("coding_agent", status="running", task="test task", user_id=123)
        state = mod.get_agent_state("coding_agent")
        assert state is not None
        assert state["status"] == "running"
        assert state["task"] == "test task"
        assert state["user_id"] == 123

    def test_is_agent_running(self):
        mod = _load_agents_module()
        assert mod.is_agent_running("coding_agent") is False
        mod.set_agent_state("coding_agent", status="running")
        assert mod.is_agent_running("coding_agent") is True
        mod.set_agent_state("coding_agent", status="done")
        assert mod.is_agent_running("coding_agent") is False
        mod.set_agent_state("coding_agent", status="idle")
        assert mod.is_agent_running("coding_agent") is False

    def test_get_agent_state_unknown(self):
        mod = _load_agents_module()
        assert mod.get_agent_state("nonexistent_agent") is None

    def test_set_agent_state_preserves_fields(self):
        mod = _load_agents_module()
        mod.set_agent_state("coding_agent", status="running", task="initial task")
        mod.set_agent_state("coding_agent", result="some output")
        state = mod.get_agent_state("coding_agent")
        assert state["status"] == "running"
        assert state["task"] == "initial task"
        assert state["result"] == "some output"

    def test_set_agent_state_records_started_at(self):
        mod = _load_agents_module()
        now = time.time()
        mod.set_agent_state("generate_video", status="running", started_at=now)
        state = mod.get_agent_state("generate_video")
        assert state["started_at"] == now


# Import needed for mock:
import types
from unittest.mock import MagicMock
