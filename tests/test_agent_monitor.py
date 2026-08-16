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
        mod.set_agent_state(
            "coding_agent",
            group_id=101,
            status="running",
            task="test task",
            user_id=123,
        )
        state = mod.get_agent_state("coding_agent", 101)
        assert state is not None
        assert state["status"] == "running"
        assert state["task"] == "test task"
        assert state["user_id"] == 123

    def test_is_agent_running(self):
        mod = _load_agents_module()
        assert mod.is_agent_running("coding_agent", 101) is False
        mod.set_agent_state("coding_agent", group_id=101, status="running")
        assert mod.is_agent_running("coding_agent", 101) is True
        assert mod.is_agent_running("coding_agent", 202) is False
        mod.set_agent_state("coding_agent", group_id=101, status="done")
        assert mod.is_agent_running("coding_agent", 101) is False
        mod.set_agent_state("coding_agent", group_id=101, status="idle")
        assert mod.is_agent_running("coding_agent", 101) is False

    def test_get_agent_state_unknown(self):
        mod = _load_agents_module()
        assert mod.get_agent_state("nonexistent_agent", 101) is None

    def test_set_agent_state_preserves_fields(self):
        mod = _load_agents_module()
        mod.set_agent_state(
            "coding_agent", group_id=101, status="running", task="initial task"
        )
        mod.set_agent_state("coding_agent", group_id=101, result="some output")
        state = mod.get_agent_state("coding_agent", 101)
        assert state["status"] == "running"
        assert state["task"] == "initial task"
        assert state["result"] == "some output"

    def test_set_agent_state_records_started_at(self):
        mod = _load_agents_module()
        now = time.time()
        mod.set_agent_state(
            "generate_video", group_id=101, status="running", started_at=now
        )
        state = mod.get_agent_state("generate_video", 101)
        assert state["started_at"] == now


# Import needed for mock:
import types
from unittest.mock import MagicMock


class TestUnfinishedAgentInstances:
    """Cross-group 'unfinished Agent' judgment for the restart gate."""

    def test_returns_running_instances_across_all_groups(self):
        mod = _load_agents_module()
        mod._AGENT_STATES.clear()
        mod._agent_tasks.clear()
        try:
            # set_agent_state upserts the latest running instance of the same
            # group, so the done row must be created before the running ones.
            mod.add_agent_instance(
                "coding_agent", group_id=101, status="done", task="task c"
            )
            mod.set_agent_state(
                "coding_agent", group_id=101, status="running", task="task a"
            )
            mod.set_agent_state(
                "background_shell", group_id=202, status="running", task="task b"
            )

            unfinished = mod.get_unfinished_agent_instances()

            assert len(unfinished) == 2
            assert {(i["name"], i["group_id"]) for i in unfinished} == {
                ("coding_agent", 101),
                ("background_shell", 202),
            }
        finally:
            mod._AGENT_STATES.clear()
            mod._agent_tasks.clear()

    def test_includes_tracked_tasks_that_are_not_done(self):
        mod = _load_agents_module()
        mod._AGENT_STATES.clear()
        mod._agent_tasks.clear()
        try:

            async def scenario():
                async def worker():
                    await asyncio.sleep(60)

                task = asyncio.create_task(worker())
                mod.track_agent_task("inst-1", 101, task)

                unfinished = mod.get_unfinished_agent_instances()

                assert any(i["instance_id"] == "inst-1" for i in unfinished)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            asyncio.run(scenario())
        finally:
            mod._AGENT_STATES.clear()
            mod._agent_tasks.clear()

    def test_finished_tracked_tasks_are_not_unfinished(self):
        mod = _load_agents_module()
        mod._AGENT_STATES.clear()
        mod._agent_tasks.clear()
        try:

            async def scenario():
                async def worker():
                    return "done"

                task = asyncio.create_task(worker())
                mod.track_agent_task("inst-2", 202, task)
                await task

                assert mod.get_unfinished_agent_instances() == []

            asyncio.run(scenario())
        finally:
            mod._AGENT_STATES.clear()
            mod._agent_tasks.clear()

    def test_running_instance_with_tracked_task_is_counted_once(self):
        mod = _load_agents_module()
        mod._AGENT_STATES.clear()
        mod._agent_tasks.clear()
        try:

            async def scenario():
                async def worker():
                    await asyncio.sleep(60)

                instance_id = mod.add_agent_instance(
                    "coding_agent", group_id=101, status="running"
                )
                task = asyncio.create_task(worker())
                mod.track_agent_task(instance_id, 101, task)

                unfinished = mod.get_unfinished_agent_instances()

                assert len(unfinished) == 1
                assert unfinished[0]["instance_id"] == instance_id
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            asyncio.run(scenario())
        finally:
            mod._AGENT_STATES.clear()
            mod._agent_tasks.clear()
