"""Tests for background_shell agent handler.

Uses the same package hierarchy setup as test_agent_dispatch.py.
Only adds attributes to modules that are missing; never replaces
modules that have already been loaded by other tests.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _ensure_module(name: str, path: str | None = None, as_package: bool = False):
    """Ensure a module exists in sys.modules without overwriting existing ones."""
    if name in sys.modules:
        mod = sys.modules[name]
    else:
        mod = types.ModuleType(name)
        if as_package and path:
            mod.__path__ = [str(path)]
        sys.modules[name] = mod

    parent_name, _, child_name = name.rpartition(".")
    if parent_name in sys.modules and child_name:
        setattr(sys.modules[parent_name], child_name, mod)
    return mod


def _ensure_attr(mod, attr: str, value):
    """Add an attribute to a module only if it's missing."""
    if not hasattr(mod, attr):
        setattr(mod, attr, value)


def _setup_package_hierarchy():
    """Ensure hatsume.plugins.hatsume_plugin package hierarchy exists."""
    # Package hierarchy
    _ensure_module("hatsume", str(ROOT / "hatsume"), as_package=True)
    _ensure_module("hatsume.plugins", str(ROOT / "hatsume/plugins"), as_package=True)
    _ensure_module("hatsume.plugins.hatsume-plugin", str(PLUGIN_DIR), as_package=True)
    # Alias
    _ensure_module("hatsume.plugins.hatsume_plugin", str(PLUGIN_DIR), as_package=True)

    # Sub-packages
    _ensure_module("hatsume.plugins.hatsume_plugin.graph", str(PLUGIN_DIR / "graph"), as_package=True)
    _ensure_module("hatsume.plugins.hatsume_plugin.memory", str(PLUGIN_DIR / "memory"), as_package=True)

    # Leaf modules — only stub what the handler directly imports.
    # Do NOT stub modules that other tests may need to load from disk.
    _ensure_module("hatsume.plugins.hatsume_plugin.infra")
    _ensure_module("hatsume.plugins.hatsume_plugin.models")
    _ensure_module("hatsume.plugins.hatsume_plugin.config")
    _ensure_module("hatsume.plugins.hatsume_plugin.graph.nodes")
    _ensure_module("hatsume.plugins.hatsume_plugin.graph.nodes.ai")
    _ensure_module("hatsume.plugins.hatsume_plugin.graph.tools")
    _ensure_module("hatsume.plugins.hatsume_plugin.group_runtime")
    # prompts: only stub if not already a real module (loaded by other tests)
    prompts_name = "hatsume.plugins.hatsume_plugin.prompts"
    if prompts_name not in sys.modules:
        _ensure_module(prompts_name)

    # Add missing attributes to config
    config_mod = sys.modules["hatsume.plugins.hatsume_plugin.config"]
    _ensure_attr(config_mod, "DOCKER_ENV_PATH", Path("/tmp/test_docker"))
    _ensure_attr(config_mod, "SHELL_MAX_OUTPUT", 1000)
    _ensure_attr(config_mod, "SHELL_TIMEOUT", 10)

    # Add missing attributes to infra
    infra_mod = sys.modules["hatsume.plugins.hatsume_plugin.infra"]
    _ensure_attr(infra_mod, "run_cmd", lambda *a, **kw: "")
    _ensure_attr(infra_mod, "ensure_container_running", AsyncMock(return_value=None))
    _ensure_attr(infra_mod, "delete_container", lambda *a, **kw: None)
    _ensure_attr(infra_mod, "_background_procs", {})
    _ensure_attr(infra_mod, "start_background_cmd", MagicMock(return_value=Path("/tmp/test_bg.log")))
    _ensure_attr(infra_mod, "read_background_output", MagicMock(return_value=("", 0)))
    _ensure_attr(infra_mod, "kill_background_cmd", MagicMock(return_value=None))
    _ensure_attr(
        infra_mod,
        "get_background_process",
        lambda proc_id, **_kwargs: infra_mod._background_procs.get(proc_id),
    )

    runtime_mod = sys.modules["hatsume.plugins.hatsume_plugin.group_runtime"]
    _ensure_attr(runtime_mod, "get_current_group_id", lambda: 101)

    # Add missing attributes to graph.nodes (merged, not graph.nodes.ai)
    nodes_mod = sys.modules["hatsume.plugins.hatsume_plugin.graph.nodes"]
    _ensure_attr(nodes_mod, "inject_agent_notification", lambda *a, **kw: None)

    # Add missing attributes to graph.tools
    tools_mod = sys.modules["hatsume.plugins.hatsume_plugin.graph.tools"]
    _ensure_attr(tools_mod, "_agent_notification_callback", None)

    # Add missing attributes to prompts
    prompts_mod = sys.modules["hatsume.plugins.hatsume_plugin.prompts"]
    _ensure_attr(prompts_mod, "BACKGROUND_SHELL_DECISION_PROMPT",
        "You are a background shell process monitor... DONE, KILL, CONTINUE:N, NOTIFY:N")
    _ensure_attr(prompts_mod, "BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT",
        "You are managing a background shell process waiting for stdin...")

    # Add missing attributes to models
    models_mod = sys.modules["hatsume.plugins.hatsume_plugin.models"]
    _ensure_attr(models_mod, "get_code_model", MagicMock())

    # Stub langchain messages
    lc_name = "langchain.messages"
    if lc_name not in sys.modules:
        lc_msg = types.ModuleType(lc_name)
        sys.modules[lc_name] = lc_msg
    else:
        lc_msg = sys.modules[lc_name]

    class _StubSystemMessage:
        def __init__(self, content=""):
            self.content = content
        type = "system"

    class _StubHumanMessage:
        def __init__(self, content=""):
            self.content = content
        type = "human"

    _ensure_attr(lc_msg, "SystemMessage", _StubSystemMessage)
    _ensure_attr(lc_msg, "HumanMessage", _StubHumanMessage)

    # Stub nonebot (only if missing)
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adap_name = "nonebot.adapters"
    if adap_name not in sys.modules:
        adap = types.ModuleType(adap_name)
        adap.__path__ = []
        sys.modules[adap_name] = adap
    adapters_mod = sys.modules[adap_name]
    _ensure_attr(adapters_mod, "Bot", type("Bot", (), {}))
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
            text=lambda s: s, image=lambda *a, **kw: None)
        v11.GroupMessageEvent = type("GroupMessageEvent", (), {})
        sys.modules[v11_name] = v11


def _cleanup_package_hierarchy():
    for name in list(sys.modules):
        if name.startswith("hatsume.plugins.hatsume_plugin"):
            del sys.modules[name]
    plugins_mod = sys.modules.get("hatsume.plugins")
    if plugins_mod is not None and hasattr(plugins_mod, "hatsume_plugin"):
        delattr(plugins_mod, "hatsume_plugin")


def _restore_package_hierarchy(
    saved_modules: dict[str, types.ModuleType],
    saved_plugins_attr,
) -> None:
    for name, mod in sorted(saved_modules.items(), key=lambda item: item[0].count(".")):
        sys.modules[name] = mod
        parent_name, _, child_name = name.rpartition(".")
        if parent_name in sys.modules and child_name:
            setattr(sys.modules[parent_name], child_name, mod)

    plugins_mod = sys.modules.get("hatsume.plugins")
    if plugins_mod is None:
        return
    if saved_plugins_attr is _MISSING:
        if hasattr(plugins_mod, "hatsume_plugin"):
            delattr(plugins_mod, "hatsume_plugin")
    else:
        setattr(plugins_mod, "hatsume_plugin", saved_plugins_attr)


_MISSING = object()


@pytest.fixture(autouse=True)
def _isolated_package_hierarchy():
    saved_modules = {
        name: mod
        for name, mod in sys.modules.items()
        if name.startswith("hatsume.plugins.hatsume_plugin")
    }
    plugins_mod = sys.modules.get("hatsume.plugins")
    saved_plugins_attr = (
        getattr(plugins_mod, "hatsume_plugin")
        if plugins_mod is not None and hasattr(plugins_mod, "hatsume_plugin")
        else _MISSING
    )
    _cleanup_package_hierarchy()
    _setup_package_hierarchy()
    yield
    _cleanup_package_hierarchy()
    _restore_package_hierarchy(saved_modules, saved_plugins_attr)


# ---------------------------------------------------------------------------
# Helpers for constructing mock code models
# ---------------------------------------------------------------------------

def _make_mock_code_model(responses: list[str]):
    """Return a mock code model that returns responses in sequence."""
    call_count = [0]

    class MockResponse:
        def __init__(self, content):
            self.content = content

    async def mock_ainvoke(messages):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return MockResponse(responses[idx])
        return MockResponse("DONE")

    return types.SimpleNamespace(ainvoke=mock_ainvoke)


def _make_mock_code_model_raw(content: str):
    """Return a mock that always returns the same content."""
    class MockResponse:
        def __init__(self, c):
            self.content = c

    async def mock_ainvoke(messages):
        return MockResponse(content)

    return types.SimpleNamespace(ainvoke=mock_ainvoke)


async def _run_bound_background_shell(task: str, user_id: int = 123) -> str:
    from hatsume.plugins.hatsume_plugin.graph.agents import (
        _run_background_shell,
        add_agent_instance,
        bind_agent_instance,
    )

    instance_id = add_agent_instance(
        "background_shell",
        group_id=101,
        status="running",
        task=task,
    )
    with bind_agent_instance(instance_id):
        return await _run_background_shell(task, user_id)


# ---------------------------------------------------------------------------
# Test: agent is registered
# ---------------------------------------------------------------------------

class TestBackgroundShellRegistration:
    """background_shell is correctly registered in AGENT_REGISTRY."""

    def test_agent_is_registered(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            get_agent_list, get_agent_handler)
        agent_names = [a["name"] for a in get_agent_list()]
        assert "background_shell" in agent_names
        assert get_agent_handler("background_shell") is not None

    def test_agent_description_is_non_empty(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import AGENT_REGISTRY
        info = AGENT_REGISTRY.get("background_shell")
        assert info is not None and len(info["description"]) > 10


# ---------------------------------------------------------------------------
# Test: parse task
# ---------------------------------------------------------------------------

class TestBackgroundShellParseTask:

    def test_parse_failure_returns_error(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model_raw("not valid {{{")):
            result = asyncio.run(_run_bound_background_shell("bad task"))
        assert "failed to parse" in result.lower()

    def test_empty_cmd_returns_error(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        parse_json = json.dumps({
            "cmd": "", "description": "nothing", "total_timeout": 300})
        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model_raw(parse_json)):
            result = asyncio.run(_run_bound_background_shell("empty cmd"))
        assert "no command" in result.lower()

    def test_cancellation_propagates_after_process_cleanup(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _run_background_shell,
        )

        async def scenario():
            parse_json = json.dumps(
                {
                    "cmd": "sleep 300",
                    "description": "wait",
                    "total_timeout": 300,
                }
            )
            sleep_entered = asyncio.Event()

            async def blocked_sleep(_seconds):
                sleep_entered.set()
                await asyncio.Event().wait()

            with (
                patch(
                    "hatsume.plugins.hatsume_plugin.models.get_code_model",
                    return_value=_make_mock_code_model_raw(parse_json),
                ),
                patch(
                    "hatsume.plugins.hatsume_plugin.infra.ensure_container_running",
                    new=AsyncMock(),
                ),
                patch(
                    "hatsume.plugins.hatsume_plugin.infra.start_background_cmd",
                    return_value=Path("/tmp/cancelled-background.log"),
                ),
                patch(
                    "hatsume.plugins.hatsume_plugin.infra.kill_background_cmd"
                ) as kill,
                patch("asyncio.sleep", new=blocked_sleep),
            ):
                task = asyncio.create_task(
                    _run_bound_background_shell("sleep until cancelled")
                )
                await asyncio.wait_for(sleep_entered.wait(), timeout=1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

            kill.assert_called_once()
            assert kill.call_args.kwargs == {"group_id": 101}

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Test: decision loop
# ---------------------------------------------------------------------------

class TestBackgroundShellDecisionLoop:

    def test_done_decision_stops_loop(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        parse_json = json.dumps({
            "cmd": "echo done", "description": "done", "total_timeout": 300})
        response_seq = [parse_json, "DONE"]

        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model(response_seq)), \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_tmp = Path("/tmp/test_done_bg.log")
            mock_tmp.write_text("finished")
            with patch("hatsume.plugins.hatsume_plugin.infra.start_background_cmd",
                       return_value=mock_tmp), \
                 patch("hatsume.plugins.hatsume_plugin.infra.read_background_output",
                       return_value=("finished", 100)), \
                 patch("hatsume.plugins.hatsume_plugin.infra.kill_background_cmd") as mk:
                mp = MagicMock(); mp.poll.return_value = None
                with patch(
                    "hatsume.plugins.hatsume_plugin.infra.get_background_process",
                    return_value=(mp, mock_tmp),
                ):
                    r = asyncio.run(asyncio.wait_for(
                        _run_bound_background_shell("echo done"), timeout=2.0))
            assert isinstance(r, str)
            # kill_background_cmd is called during cleanup after DONE decision
            if mock_tmp.exists(): mock_tmp.unlink()

    def test_continue_decision_loops(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        parse_json = json.dumps({
            "cmd": "sleep 10", "description": "long", "total_timeout": 300})
        response_seq = [parse_json, "CONTINUE:1", "CONTINUE:1", "DONE"]
        reads = []
        def _read(*a): reads.append(1); return ("running...", 100)

        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model(response_seq)), \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_tmp = Path("/tmp/test_loop_bg.log"); mock_tmp.write_text("x")
            with patch("hatsume.plugins.hatsume_plugin.infra.start_background_cmd",
                       return_value=mock_tmp), \
                 patch("hatsume.plugins.hatsume_plugin.infra.read_background_output",
                       side_effect=_read), \
                 patch("hatsume.plugins.hatsume_plugin.infra.kill_background_cmd"):
                mp = MagicMock(); mp.poll.return_value = None
                with patch(
                    "hatsume.plugins.hatsume_plugin.infra.get_background_process",
                    return_value=(mp, mock_tmp),
                ):
                    asyncio.run(asyncio.wait_for(
                        _run_bound_background_shell("sleep 10"), timeout=5.0))
            assert len(reads) >= 3
            if mock_tmp.exists(): mock_tmp.unlink()

    def test_notify_injects_mid_progress(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        parse_json = json.dumps({
            "cmd": "gh auth login", "description": "auth", "total_timeout": 300})
        response_seq = [parse_json, "NOTIFY:1", "DONE"]

        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model(response_seq)), \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_tmp = Path("/tmp/test_notify_bg.log")
            mock_tmp.write_text("https://github.com/login/device\n")
            with patch("hatsume.plugins.hatsume_plugin.infra.start_background_cmd",
                       return_value=mock_tmp), \
                 patch("hatsume.plugins.hatsume_plugin.infra.read_background_output",
                       return_value=("https://github.com/login/device\n", 100)), \
                 patch("hatsume.plugins.hatsume_plugin.infra.kill_background_cmd"), \
                 patch("hatsume.plugins.hatsume_plugin.graph.nodes.inject_agent_notification") as mi, \
                 patch("hatsume.plugins.hatsume_plugin.graph.tools._agent_notification_callback", None):
                mp = MagicMock(); mp.poll.return_value = None
                with patch(
                    "hatsume.plugins.hatsume_plugin.infra.get_background_process",
                    return_value=(mp, mock_tmp),
                ):
                    asyncio.run(asyncio.wait_for(
                        _run_bound_background_shell("gh auth login"), timeout=3.0))
            assert mi.call_count >= 1
            if mock_tmp.exists(): mock_tmp.unlink()

    def test_timeout_forces_termination(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        parse_json = json.dumps({
            "cmd": "sleep 999", "description": "long", "total_timeout": 1})
        response_seq = [parse_json, "CONTINUE:30"]

        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model(response_seq)), \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_tmp = Path("/tmp/test_timeout_bg.log")
            mock_tmp.write_text("running...")
            with patch("hatsume.plugins.hatsume_plugin.infra.start_background_cmd",
                       return_value=mock_tmp), \
                 patch("hatsume.plugins.hatsume_plugin.infra.read_background_output",
                       return_value=("running...", 100)), \
                 patch("hatsume.plugins.hatsume_plugin.infra.kill_background_cmd") as mk:
                mk.return_value = "killed output"
                mp = MagicMock(); mp.poll.return_value = None
                with patch(
                    "hatsume.plugins.hatsume_plugin.infra.get_background_process",
                    return_value=(mp, mock_tmp),
                ):
                    r = asyncio.run(asyncio.wait_for(
                        _run_bound_background_shell("sleep 999"), timeout=5.0))
            assert "超时" in r
            # kill_background_cmd called once on timeout + once in cleanup
            assert mk.call_count >= 1
            if mock_tmp.exists(): mock_tmp.unlink()

    def test_kill_decision_terminates_process(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell
        parse_json = json.dumps({
            "cmd": "bad", "description": "fail", "total_timeout": 300})
        response_seq = [parse_json, "KILL"]

        with patch("hatsume.plugins.hatsume_plugin.models.get_code_model",
                   return_value=_make_mock_code_model(response_seq)), \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_tmp = Path("/tmp/test_kill_bg.log")
            mock_tmp.write_text("Permission denied")
            with patch("hatsume.plugins.hatsume_plugin.infra.start_background_cmd",
                       return_value=mock_tmp), \
                 patch("hatsume.plugins.hatsume_plugin.infra.read_background_output",
                       return_value=("Permission denied", 100)), \
                 patch("hatsume.plugins.hatsume_plugin.infra.kill_background_cmd") as mk:
                mk.return_value = "remaining"
                mp = MagicMock(); mp.poll.return_value = None
                with patch(
                    "hatsume.plugins.hatsume_plugin.infra.get_background_process",
                    return_value=(mp, mock_tmp),
                ):
                    r = asyncio.run(asyncio.wait_for(
                        _run_bound_background_shell("bad"), timeout=2.0))
            assert "终止" in r; mk.assert_called_once()
            if mock_tmp.exists(): mock_tmp.unlink()
