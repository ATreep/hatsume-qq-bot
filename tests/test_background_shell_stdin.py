"""Tests for background shell stdin injection helpers."""
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


@pytest.fixture(autouse=True)
def _reset_stdin_queues():
    """Reset _stdin_queues before each test."""
    from hatsume.plugins.hatsume_plugin.graph.agents import _stdin_queues
    _stdin_queues.clear()
    yield
    _stdin_queues.clear()


class TestWriteStdin:
    """Tests for _write_stdin() helper."""

    def test_writes_text_to_stdin(self):
        """_write_stdin writes text to process stdin and returns True."""
        proc = subprocess.Popen(
            ["cat", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        result = _write_stdin(proc, "hello")

        stdout, _ = proc.communicate(timeout=2)
        assert result is True
        assert stdout == b"hello\n"

    def test_returns_false_when_process_exited(self):
        """_write_stdin returns False if process already exited."""
        proc = subprocess.Popen(
            ["true"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        proc.wait(timeout=2)
        proc.communicate(timeout=2)

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        result = _write_stdin(proc, "hello")
        assert result is False

    def test_adds_newline_if_missing(self):
        """_write_stdin appends newline if text doesn't end with one."""
        proc = subprocess.Popen(
            ["cat", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        _write_stdin(proc, "no_newline")
        stdout, _ = proc.communicate(timeout=2)
        assert stdout == b"no_newline\n"

    def test_preserves_existing_newline(self):
        """_write_stdin does not double-append newline."""
        proc = subprocess.Popen(
            ["cat", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        _write_stdin(proc, "has_newline\n")
        stdout, _ = proc.communicate(timeout=2)
        assert stdout == b"has_newline\n"


class TestCleanupStdinQueues:
    """Tests for _cleanup_stdin_queues() helper."""

    def test_wakes_pending_waiters(self):
        """_cleanup_stdin_queues puts None into all matching queues."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _stdin_queues,
            _cleanup_stdin_queues,
        )

        q = asyncio.Queue()
        _stdin_queues["stdin_test_abc_0"] = q
        _stdin_queues["stdin_test_abc_1"] = asyncio.Queue()
        _stdin_queues["stdin_other_xyz_0"] = asyncio.Queue()

        _cleanup_stdin_queues("test_abc")

        assert q.get_nowait() is None
        assert "stdin_test_abc_0" not in _stdin_queues
        assert "stdin_test_abc_1" not in _stdin_queues
        assert "stdin_other_xyz_0" in _stdin_queues

        # Clean up remaining
        _stdin_queues.pop("stdin_other_xyz_0", None)


class TestStdinQueuesDict:
    """Tests for _stdin_queues module-level dict."""

    def test_dict_exists_as_module_attr(self):
        """_stdin_queues is a module-level dict."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _stdin_queues
        assert isinstance(_stdin_queues, dict)
