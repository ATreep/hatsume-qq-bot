"""Integration test: full stdin injection flow for background_shell agent."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy():
    """Ensure hatsume.plugins.hatsume_plugin package hierarchy exists."""
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

    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias


_setup_package_hierarchy()


class TestStdinInjectionIntegration:
    """End-to-end tests for stdin injection via _write_stdin and queues."""

    def test_write_stdin_to_interactive_process(self):
        """Spawn a process that reads stdin, write to it, verify output."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin

        proc = subprocess.Popen(
            ["bash", "-c", 'read -p "Enter: " v; echo "Got: $v"'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
        )

        result = _write_stdin(proc, "hello_world\n")
        assert result is True

        stdout, _ = proc.communicate(timeout=5)
        assert b"Got: hello_world" in stdout

    def test_write_stdin_multiple_times(self):
        """Multiple stdin writes to the same process work correctly."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin

        proc = subprocess.Popen(
            ["bash", "-c", 'read v1; read v2; echo "$v1|$v2"'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
        )

        result1 = _write_stdin(proc, "first_value\n")
        assert result1 is True
        result2 = _write_stdin(proc, "second_value\n")
        assert result2 is True

        stdout, _ = proc.communicate(timeout=5)
        assert b"first_value|second_value" in stdout

    def test_queue_flow_for_stdin_request(self):
        """Simulate the full queue-based stdin request/response flow."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _stdin_queues,
            pop_stdin_request,
            register_stdin_request,
        )

        proc_id = "test_integration"
        request_id = f"stdin_{proc_id}_0"

        q: asyncio.Queue[str | None] = asyncio.Queue()
        register_stdin_request(request_id, 101, q)

        async def simulate_tool_response():
            popped_q = pop_stdin_request(request_id, 101)
            assert popped_q is not None
            await popped_q.put("my_secret_token")
            return "success"

        async def simulate_agent_wait():
            raw = await asyncio.wait_for(q.get(), timeout=2)
            return raw

        async def run():
            tool_task = asyncio.create_task(simulate_tool_response())
            agent_task = asyncio.create_task(simulate_agent_wait())
            raw = await agent_task
            await tool_task
            return raw

        raw = asyncio.run(run())
        assert raw == "my_secret_token"
        assert request_id not in _stdin_queues

    def test_cleanup_wakes_waiters(self):
        """_cleanup_stdin_queues wakes pending queue waiters with None."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _stdin_queues,
            _cleanup_stdin_queues,
            register_stdin_request,
        )

        proc_id = "test_cleanup"
        request_id = f"stdin_{proc_id}_0"
        q: asyncio.Queue[str | None] = asyncio.Queue()
        register_stdin_request(request_id, 101, q)

        async def wait_then_cleanup():
            await asyncio.sleep(0.05)
            _cleanup_stdin_queues(proc_id, 101)

        async def agent_wait():
            raw = await q.get()
            return raw

        async def run():
            cleanup_task = asyncio.create_task(wait_then_cleanup())
            agent_task = asyncio.create_task(agent_wait())
            raw = await agent_task
            await cleanup_task
            return raw

        raw = asyncio.run(run())
        assert raw is None
        assert request_id not in _stdin_queues

    def test_cross_group_response_does_not_consume_request(self):
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            pop_stdin_request,
            register_stdin_request,
        )

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        register_stdin_request("stdin_owned_0", 101, queue)

        assert pop_stdin_request("stdin_owned_0", 202) is None
        assert pop_stdin_request("stdin_owned_0", 101) is queue
