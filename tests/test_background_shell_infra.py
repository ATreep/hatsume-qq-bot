"""Tests for infra.py background process functions.
start_background_cmd is tested indirectly via the agent handler test
since it requires a running Docker container.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
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

    # Stub config for DOCKER_ENV_PATH
    config_name = "hatsume.plugins.hatsume_plugin.config"
    if config_name not in sys.modules:
        config_mod = types.ModuleType(config_name)
        sys.modules[config_name] = config_mod
    config_mod = sys.modules[config_name]
    config_mod.DOCKER_ENV_PATH = Path("/tmp/test_docker")
    config_mod.IMAGE_MAX_PIXELS = 36_000_000
    config_mod.IMAGE_MAX_SIZE_BYTES = 9 * 1024 * 1024
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    config_mod.CONTAINER_NAME_BASE = "hatsume-space"

    runtime_name = "hatsume.plugins.hatsume_plugin.group_runtime"
    runtime_mod = types.ModuleType(runtime_name)
    runtime_mod.get_current_group_id = lambda: 101
    runtime_mod.validate_group_id = lambda group_id: (
        group_id
        if isinstance(group_id, int) and not isinstance(group_id, bool) and group_id > 0
        else (_ for _ in ()).throw(ValueError("invalid group"))
    )
    sys.modules[runtime_name] = runtime_mod

    # Load infra module from actual file
    import importlib.util
    infra_path = PLUGIN_DIR / "infra.py"
    infra_name = "hatsume.plugins.hatsume_plugin.infra"
    if infra_name in sys.modules:
        del sys.modules[infra_name]
    spec = importlib.util.spec_from_file_location(infra_name, infra_path)
    infra_mod = importlib.util.module_from_spec(spec)
    sys.modules[infra_name] = infra_mod
    spec.loader.exec_module(infra_mod)


_setup_package_hierarchy()


@pytest.fixture(autouse=True)
def _reset_background_procs():
    """Reset _background_procs before each test to prevent cross-test pollution."""
    from hatsume.plugins.hatsume_plugin.infra import (
        _background_proc_groups,
        _background_procs,
        _container_states,
    )
    _background_procs.clear()
    _background_proc_groups.clear()
    _container_states.clear()
    yield
    for proc, _path in _background_procs.values():
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    _background_procs.clear()
    _background_proc_groups.clear()
    _container_states.clear()


# -----------------------------------------------------------------------
# read_background_output
# -----------------------------------------------------------------------


class TestReadBackgroundOutput:
    """Tests for read_background_output() — incremental file reading."""

    def test_reads_new_content_from_offset_zero(self):
        """Reads all content when offset is 0."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        tmp.write_text("line 1\nline 2\nline 3\n")

        content, new_offset = read_background_output(tmp, 0)
        assert content == "line 1\nline 2\nline 3\n"
        assert new_offset == len("line 1\nline 2\nline 3\n")

        tmp.unlink()

    def test_reads_incremental_from_offset(self):
        """Reads only content after the given offset."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        full = "first chunk\nsecond chunk\n"
        tmp.write_text(full)

        content1, offset1 = read_background_output(tmp, 0)
        assert content1 == full

        # Append more content
        tmp.write_text(full + "third chunk\n")

        content2, offset2 = read_background_output(tmp, offset1)
        assert content2 == "third chunk\n"
        assert offset2 == len(full + "third chunk\n")

        tmp.unlink()

    def test_returns_empty_when_no_new_content(self):
        """Returns empty string and same offset when no new content exists."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        tmp.write_text("static content\n")

        content1, offset1 = read_background_output(tmp, 0)
        content2, offset2 = read_background_output(tmp, offset1)
        assert content2 == ""
        assert offset2 == offset1

        tmp.unlink()

    def test_returns_empty_for_missing_file(self):
        """Returns empty string when tmp file does not exist."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        content, offset = read_background_output(Path("/nonexistent/path.log"), 0)
        assert content == ""
        assert offset == 0


# -----------------------------------------------------------------------
# kill_background_cmd
# -----------------------------------------------------------------------


class TestKillBackgroundCmd:
    """Tests for kill_background_cmd() — process termination and cleanup."""

    def test_returns_none_for_unknown_proc_id(self):
        """Returns None when proc_id is not in _background_procs."""
        from hatsume.plugins.hatsume_plugin.infra import kill_background_cmd

        result = kill_background_cmd("nonexistent_proc_xyz", group_id=101)
        assert result is None

    def test_kills_running_process_and_cleans_up(self):
        """kill_background_cmd terminates the process, removes tmp file, returns output."""
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_proc_groups,
            _background_procs,
            kill_background_cmd,
        )

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        # Write test data to file, then use append mode for Popen
        f = open(str(tmp), "w")
        f.write("process output\n")
        f.close()

        # Start a long-running process (append to preserve test data)
        log_file = open(tmp, "a")
        proc = subprocess.Popen(
            ["sleep", "60"], stdout=log_file, stderr=subprocess.STDOUT
        )
        log_file.close()
        proc_id = "test_proc_kill_1"
        _background_procs[proc_id] = (proc, tmp)
        _background_proc_groups[proc_id] = 101

        remaining = kill_background_cmd(proc_id, group_id=101)

        # Process should be dead
        assert proc.poll() is not None
        # Tmp file should be cleaned up
        assert not tmp.exists()
        # Remaining output should be read
        assert "process output" in (remaining or "")

    def test_removes_entry_from_background_procs(self):
        """After kill_background_cmd, the proc_id is removed from the dict."""
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_proc_groups,
            _background_procs,
            kill_background_cmd,
        )

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        log_file = open(tmp, "a")
        proc = subprocess.Popen(
            ["sleep", "60"], stdout=log_file, stderr=subprocess.STDOUT
        )
        log_file.close()
        proc_id = "test_proc_kill_2"
        _background_procs[proc_id] = (proc, tmp)
        _background_proc_groups[proc_id] = 101

        assert proc_id in _background_procs
        kill_background_cmd(proc_id, group_id=101)
        assert proc_id not in _background_procs

    def test_other_group_cannot_kill_process(self):
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_proc_groups,
            _background_procs,
            kill_background_cmd,
        )

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        proc = subprocess.Popen(["sleep", "60"], stdout=subprocess.DEVNULL)
        _background_procs["owned"] = (proc, tmp)
        _background_proc_groups["owned"] = 101

        assert kill_background_cmd("owned", group_id=202) is None
        assert proc.poll() is None

        kill_background_cmd("owned", group_id=101)
