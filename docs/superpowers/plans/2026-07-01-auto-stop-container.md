# Auto-Stop Docker Container When All Subprocesses Finish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reference counting and a 5-minute grace-period timer so the Docker container `hatsume-space-kali` is automatically stopped when all active `run_cmd`/`start_background_cmd` subprocesses have finished and no new subprocess has started for 5 minutes.

**Architecture:** Three new functions (`_acquire_subprocess`, `_release_subprocess`, `_delayed_stop_container`) plus module-level state (`_subprocess_refcount`, `_subprocess_refcount_lock`, `_stop_timer_task`) are added to `infra.py`. Four existing functions (`run_cmd`, `start_background_cmd`, `kill_background_cmd`, `cleanup_persistent_container`) are modified with minimal integration calls. A `threading.Lock` protects refcount mutation since `run_cmd` is synchronous.

**Tech Stack:** Python 3.12 stdlib (`threading`, `asyncio`, `subprocess`), pytest

## Global Constraints

- `_STOP_GRACE_SECONDS: float = 300.0` — 5 minute grace period
- `_subprocess_refcount_lock` must be `threading.Lock` (not `asyncio.Lock`) because `run_cmd()` is synchronous
- `_release_subprocess()` must handle both sync and async calling contexts
- All existing behavior (HALT checking, timeout handling, output truncation) must be preserved unchanged
- Test file uses the same `_setup_package_hierarchy()` pattern as `tests/test_background_shell_infra.py`

---

### Task 1: Add refcount state and helper functions to `infra.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py:1-10` (add `asyncio` and `threading` imports)
- Create: (add new state + functions block between line 10 and line 14)

**Interfaces:**
- Produces:
  - `_acquire_subprocess() -> None`
  - `_release_subprocess() -> None`
  - `_delayed_stop_container() -> None` (async)
  - `_subprocess_refcount: int`, `_subprocess_refcount_lock: threading.Lock`, `_stop_timer_task: asyncio.Task | None`, `_STOP_GRACE_SECONDS: float`

- [ ] **Step 1: Write the failing test**

Create `tests/test_container_lifecycle.py`:

```python
"""Tests for container auto-stop lifecycle — refcount and grace timer."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

    # Stub config
    config_name = "hatsume.plugins.hatsume_plugin.config"
    if config_name not in sys.modules:
        config_mod = types.ModuleType(config_name)
        sys.modules[config_name] = config_mod
    config_mod = sys.modules[config_name]
    config_mod.DOCKER_ENV_PATH = Path("/tmp/test_docker")
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10

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
def _reset_refcount_state():
    """Reset refcount state before each test to prevent cross-test pollution."""
    from hatsume.plugins.hatsume_plugin.infra import (
        _background_procs,
    )
    _background_procs.clear()

    # Access and reset the refcount private state
    import hatsume.plugins.hatsume_plugin.infra as infra_mod
    infra_mod._subprocess_refcount = 0
    infra_mod._stop_timer_task = None
    yield
    _background_procs.clear()
    infra_mod._subprocess_refcount = 0
    infra_mod._stop_timer_task = None


# -----------------------------------------------------------------------
# _acquire_subprocess
# -----------------------------------------------------------------------


class TestAcquireSubprocess:
    """Tests for _acquire_subprocess() — increment refcount, cancel timer."""

    def test_increments_refcount(self):
        """_acquire_subprocess increments _subprocess_refcount by 1."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        assert infra_mod._subprocess_refcount == 0
        infra_mod._acquire_subprocess()
        assert infra_mod._subprocess_refcount == 1
        infra_mod._acquire_subprocess()
        assert infra_mod._subprocess_refcount == 2

    def test_cancels_pending_timer(self):
        """_acquire_subprocess cancels a pending _stop_timer_task."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        # Create a mock async task that represents a pending stop timer
        mock_task = AsyncMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        infra_mod._stop_timer_task = mock_task
        infra_mod._subprocess_refcount = 0

        infra_mod._acquire_subprocess()

        assert infra_mod._subprocess_refcount == 1
        mock_task.cancel.assert_called_once()
        assert infra_mod._stop_timer_task is None

    def test_does_not_cancel_completed_timer(self):
        """_acquire_subprocess does not try to cancel an already-done task."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        mock_task = AsyncMock(spec=asyncio.Task)
        mock_task.done.return_value = True  # already finished
        infra_mod._stop_timer_task = mock_task
        infra_mod._subprocess_refcount = 0

        infra_mod._acquire_subprocess()

        assert infra_mod._subprocess_refcount == 1
        mock_task.cancel.assert_not_called()


# -----------------------------------------------------------------------
# _release_subprocess
# -----------------------------------------------------------------------


class TestReleaseSubprocess:
    """Tests for _release_subprocess() — decrement refcount, start timer."""

    def test_decrements_refcount(self):
        """_release_subprocess decrements _subprocess_refcount by 1."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 3
        infra_mod._release_subprocess()
        assert infra_mod._subprocess_refcount == 2

    def test_clamps_at_zero(self):
        """_release_subprocess does not let refcount go below 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._release_subprocess()
        assert infra_mod._subprocess_refcount == 0

    def test_starts_timer_when_refcount_reaches_zero(self):
        """_release_subprocess creates a _stop_timer_task when refcount hits 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 1

        async def _run_in_loop():
            infra_mod._release_subprocess()
            assert infra_mod._stop_timer_task is not None
            # Clean up: cancel the timer so it doesn't linger
            infra_mod._stop_timer_task.cancel()
            try:
                await infra_mod._stop_timer_task
            except asyncio.CancelledError:
                pass
            infra_mod._stop_timer_task = None

        asyncio.run(_run_in_loop())

    def test_no_timer_when_refcount_still_positive(self):
        """_release_subprocess does NOT start a timer when refcount > 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 2
        infra_mod._stop_timer_task = None

        async def _run_in_loop():
            infra_mod._release_subprocess()
            assert infra_mod._subprocess_refcount == 1
            assert infra_mod._stop_timer_task is None

        asyncio.run(_run_in_loop())


# -----------------------------------------------------------------------
# _delayed_stop_container
# -----------------------------------------------------------------------


class TestDelayedStopContainer:
    """Tests for _delayed_stop_container() — grace period then stop."""

    def test_stops_container_after_grace_period(self):
        """After _STOP_GRACE_SECONDS, stop_container() is called if refcount still 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0

        async def _run_test():
            with patch.object(infra_mod, "stop_container") as mock_stop:
                with patch.object(infra_mod, "asyncio") as mock_asyncio:
                    # Make sleep resolve immediately
                    async def fake_sleep(_seconds):
                        pass
                    mock_asyncio.sleep = fake_sleep
                    mock_asyncio.Task = asyncio.Task

                    await infra_mod._delayed_stop_container()

                    mock_stop.assert_called_once()
                    assert infra_mod._container_active is False
                    assert infra_mod._stop_timer_task is None

        asyncio.run(_run_test())

    def test_does_not_stop_if_refcount_increased_during_sleep(self):
        """If a new subprocess started during grace period, do NOT stop container."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0

        async def _run_test():
            with patch.object(infra_mod, "stop_container") as mock_stop:
                with patch.object(infra_mod, "asyncio") as mock_asyncio:
                    called = False

                    async def fake_sleep(_seconds):
                        nonlocal called
                        if not called:
                            called = True
                            # Simulate: new subprocess started during sleep
                            infra_mod._subprocess_refcount = 1

                    mock_asyncio.sleep = fake_sleep
                    mock_asyncio.Task = asyncio.Task

                    await infra_mod._delayed_stop_container()

                    # stop_container should NOT have been called
                    mock_stop.assert_not_called()
                    assert infra_mod._stop_timer_task is None

        asyncio.run(_run_test())


# -----------------------------------------------------------------------
# Integration: run_cmd refcount
# -----------------------------------------------------------------------


class TestRunCmdRefcount:
    """Tests that run_cmd() properly acquires and releases refcount."""

    def test_run_cmd_releases_refcount_on_success(self):
        """run_cmd calls _acquire then _release, refcount returns to original."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._container_active = True  # skip ensure_container_running

        with patch.object(subprocess, "run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = b"hello world\n"
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            infra_mod.run_cmd("echo hello")

            # After run_cmd returns, refcount should be back at 0
            assert infra_mod._subprocess_refcount == 0

    def test_run_cmd_releases_refcount_on_timeout(self):
        """run_cmd releases refcount even when subprocess times out."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._container_active = True

        with patch.object(subprocess, "run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["bash", "launch_image.sh"], timeout=10,
                output=b"partial stdout", stderr=b"partial stderr"
            )

            result = infra_mod.run_cmd("sleep 999")

            # Should return timeout message (not crash)
            assert "Executing Timeout" in result
            # Refcount must be released even on exception
            assert infra_mod._subprocess_refcount == 0

    def test_run_cmd_releases_refcount_on_halt(self):
        """run_cmd releases refcount even when Docker is halted (assertion)."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._container_active = True

        with patch.object(subprocess, "run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = b"[HALT] Docker not running\n"
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            with pytest.raises(AssertionError, match="Docker is not running"):
                infra_mod.run_cmd("anything")

            # Refcount must be released even on assertion failure
            assert infra_mod._subprocess_refcount == 0


# -----------------------------------------------------------------------
# Integration: kill_background_cmd releases refcount
# -----------------------------------------------------------------------


class TestKillBackgroundCmdRefcount:
    """Tests that kill_background_cmd() properly releases refcount."""

    def test_kill_releases_refcount(self):
        """After kill_background_cmd, _subprocess_refcount is decremented."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_procs,
            kill_background_cmd,
        )

        infra_mod._subprocess_refcount = 1  # simulate one active bg proc

        # Create a real process to kill
        proc = subprocess.Popen(
            ["sleep", "60"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        tmp = Path("/tmp/test_bg_refcount.log")
        tmp.write_text("test output")
        proc_id = "test_refcount_kill"
        _background_procs[proc_id] = (proc, tmp)

        kill_background_cmd(proc_id)

        assert infra_mod._subprocess_refcount == 0
        assert not tmp.exists()

    def test_kill_unknown_proc_does_not_decrement(self):
        """Killing a non-existent proc_id does NOT affect refcount."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod
        from hatsume.plugins.hatsume_plugin.infra import kill_background_cmd

        infra_mod._subprocess_refcount = 2
        result = kill_background_cmd("nonexistent_proc_xyz")

        assert result is None
        assert infra_mod._subprocess_refcount == 2  # unchanged


# -----------------------------------------------------------------------
# Integration: cleanup_persistent_container cancels timer
# -----------------------------------------------------------------------


class TestCleanupCancelsTimer:
    """Tests that cleanup_persistent_container() cancels the grace timer."""

    def test_cleanup_cancels_pending_timer(self):
        """cleanup_persistent_container cancels _stop_timer_task if pending."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        mock_task = AsyncMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        infra_mod._stop_timer_task = mock_task
        infra_mod._container_active = True

        with patch.object(infra_mod, "delete_container"):
            infra_mod.cleanup_persistent_container()

        mock_task.cancel.assert_called_once()
        assert infra_mod._stop_timer_task is None
        assert infra_mod._container_active is False

    def test_cleanup_with_no_timer(self):
        """cleanup_persistent_container works when no timer is pending."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._stop_timer_task = None
        infra_mod._container_active = True

        with patch.object(infra_mod, "delete_container"):
            infra_mod.cleanup_persistent_container()

        assert infra_mod._stop_timer_task is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_container_lifecycle.py -v
```

Expected: all tests FAIL — `_acquire_subprocess`, `_release_subprocess`, `_delayed_stop_container` do not exist yet.

- [ ] **Step 3: Add imports and state to `infra.py`**

Modify `hatsume/plugins/hatsume-plugin/infra.py`, replacing lines 1-13:

```python
"""Infrastructure: Docker sandbox and HTML rendering."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import threading
from pathlib import Path

from .config import DOCKER_ENV_PATH, SHELL_MAX_OUTPUT, SHELL_TIMEOUT

# ===========================================================================
# Subprocess reference counting (for auto-stop container)
# ===========================================================================
_subprocess_refcount: int = 0
_subprocess_refcount_lock: threading.Lock = threading.Lock()
_stop_timer_task: asyncio.Task | None = None
_STOP_GRACE_SECONDS: float = 300.0  # 5 minutes


def _acquire_subprocess() -> None:
    """Called when a Docker subprocess starts: cancel pending stop timer, increment refcount."""
    global _subprocess_refcount, _stop_timer_task
    with _subprocess_refcount_lock:
        _subprocess_refcount += 1
        if _stop_timer_task is not None and not _stop_timer_task.done():
            _stop_timer_task.cancel()
            _stop_timer_task = None


def _release_subprocess() -> None:
    """Called when a Docker subprocess ends: decrement refcount, start grace timer if zero."""
    global _subprocess_refcount, _stop_timer_task
    with _subprocess_refcount_lock:
        _subprocess_refcount = max(0, _subprocess_refcount - 1)
        if _subprocess_refcount == 0:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            _stop_timer_task = loop.create_task(_delayed_stop_container())


async def _delayed_stop_container() -> None:
    """Wait grace period then stop container if still no active subprocesses."""
    await asyncio.sleep(_STOP_GRACE_SECONDS)
    global _subprocess_refcount, _stop_timer_task, _container_active
    with _subprocess_refcount_lock:
        if _subprocess_refcount == 0:  # re-check: no new subprocess started
            stop_container()
            _container_active = False
        _stop_timer_task = None


# ===========================================================================
# Docker sandbox
# ===========================================================================
_container_active: bool = False
```

- [ ] **Step 4: Run tests to verify the helper functions work**

```bash
python -m pytest tests/test_container_lifecycle.py -v -k "TestAcquireSubprocess or TestReleaseSubprocess or TestDelayedStopContainer"
```

Expected: Tests for the helper functions PASS; integration tests still FAIL (run_cmd, kill_background_cmd, cleanup not yet modified).

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py tests/test_container_lifecycle.py
git commit -m "feat: add subprocess refcount and grace-timer helpers for auto-stop

Add _acquire_subprocess, _release_subprocess, _delayed_stop_container
with threading.Lock-protected refcount and 5-minute asyncio grace timer.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Integrate `_acquire`/`_release` into `run_cmd()`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py:48-81` (the `run_cmd` function)

**Interfaces:**
- Consumes: `_acquire_subprocess()`, `_release_subprocess()` (from Task 1)

- [ ] **Step 1: Confirm integration tests still fail**

```bash
python -m pytest tests/test_container_lifecycle.py::TestRunCmdRefcount -v
```

Expected: 3 tests FAIL (run_cmd not yet calling acquire/release).

- [ ] **Step 2: Modify `run_cmd()` in `infra.py`**

Replace the entire `run_cmd` function (lines 48-81 in the original numbering; now shifted down by ~30 lines after Task 1 additions):

```python
def run_cmd(code: str, timeout: float = SHELL_TIMEOUT) -> str:
    """Execute a bash command in Docker. Returns stdout+stderr."""
    script_path = Path(DOCKER_ENV_PATH, "script.sh").absolute()
    SOURCE_BASHRC = "source ~/.bashrc"
    script_path.write_text(SOURCE_BASHRC + "\n" + code)

    _acquire_subprocess()
    try:
        try:
            result = subprocess.run(
                ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh")],
                cwd=DOCKER_ENV_PATH,
                timeout=timeout,
                capture_output=True,
            )
        except subprocess.TimeoutExpired as e:
            return (
                    f"Executing Timeout (timeout={timeout}s)\n"
                    f"stdout:\n{str(e.stdout)[:SHELL_MAX_OUTPUT]}\n"
                    f"stderr:\n{str(e.stderr)[:SHELL_MAX_OUTPUT]}"
                )

        try:
            decode_stdout = result.stdout.decode()
            decode_stderr = result.stderr.decode()
            assert not decode_stdout.startswith("[HALT]"), "Docker is not running!"
            output = decode_stdout
            if decode_stderr.strip() != "":
                output += "\n\n" + decode_stderr

            if len(output) > SHELL_MAX_OUTPUT:
                return f"运行结果的前 {SHELL_MAX_OUTPUT} 个字符： " + output[:SHELL_MAX_OUTPUT]
            return output
        except UnicodeDecodeError:
            raw = (str(result.stdout) + "\n\n" + str(result.stderr))[:SHELL_MAX_OUTPUT]
            return "运行结果无法解码，其字节码如下： \n\n" + raw
    finally:
        _release_subprocess()
```

The only changes from the original are:
1. `_acquire_subprocess()` added after `script_path.write_text(...)` and before `try:`
2. The entire existing body wrapped in `try:` / `finally: _release_subprocess()`

- [ ] **Step 3: Run the integration tests**

```bash
python -m pytest tests/test_container_lifecycle.py::TestRunCmdRefcount -v
```

Expected: 3 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py
git commit -m "feat: integrate refcount into run_cmd with try/finally

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Integrate `_acquire`/`_release` into background process functions

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py:115-144` (`start_background_cmd`)
- Modify: `hatsume/plugins/hatsume-plugin/infra.py:169-208` (`kill_background_cmd`)

**Interfaces:**
- Consumes: `_acquire_subprocess()`, `_release_subprocess()` (from Task 1)

- [ ] **Step 1: Confirm integration tests still fail**

```bash
python -m pytest tests/test_container_lifecycle.py::TestKillBackgroundCmdRefcount -v
```

Expected: 2 tests FAIL (kill_background_cmd not yet calling release).

- [ ] **Step 2: Modify `start_background_cmd()`**

Insert `_acquire_subprocess()` after `script_path.write_text(...)` and before `tmp = Path(...)`:

```python
def start_background_cmd(code: str, proc_id: str) -> Path:
    """Spawn a background bash process in the Docker sandbox.

    stdout and stderr are merged and redirected to a tmp file.
    Docker container must already be running (ensure_container_running
    should be called before invoking shell_executor flows; for
    background_shell agent this is handled by the existing flow).

    Args:
        code: The shell script/command to execute.
        proc_id: Unique identifier for lifecycle management.

    Returns:
        Path to the tmp file where process output is written.
        Caller is responsible for cleanup via kill_background_cmd().
    """
    SOURCE_BASHRC = "source ~/.bashrc"
    script_path = Path(DOCKER_ENV_PATH, "script.sh").absolute()
    script_path.write_text(SOURCE_BASHRC + "\n" + code)

    _acquire_subprocess()

    tmp = Path(tempfile.mkstemp(prefix="hatsume-bg-", suffix=".log")[1])
    proc = subprocess.Popen(
        ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh")],
        cwd=DOCKER_ENV_PATH,
        stdin=subprocess.PIPE,
        stdout=open(str(tmp), "w"),
        stderr=subprocess.STDOUT,
    )
    _background_procs[proc_id] = (proc, tmp)
    return tmp
```

- [ ] **Step 3: Modify `kill_background_cmd()`**

Insert `_release_subprocess()` before the `return remaining` statement:

```python
def kill_background_cmd(proc_id: str) -> str | None:
    """Terminate a background process and clean up its tmp file.

    Args:
        proc_id: The identifier used when the process was started.

    Returns:
        Any remaining unread output from the tmp file, or None if the
        proc_id was not found (already cleaned up).
    """
    entry = _background_procs.pop(proc_id, None)
    if entry is None:
        return None

    proc, tmp = entry
    remaining = ""

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass

    # Read any remaining output before cleanup
    try:
        if tmp.exists():
            remaining = tmp.read_text()
    except Exception:
        pass

    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass

    _release_subprocess()
    return remaining
```

- [ ] **Step 4: Run the integration tests**

```bash
python -m pytest tests/test_container_lifecycle.py::TestKillBackgroundCmdRefcount -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py
git commit -m "feat: integrate refcount into start/kill_background_cmd

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Integrate timer cancellation into `cleanup_persistent_container()`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py:40-45` (`cleanup_persistent_container`)

**Interfaces:**
- Consumes: `_stop_timer_task` (from Task 1)

- [ ] **Step 1: Confirm test fails**

```bash
python -m pytest tests/test_container_lifecycle.py::TestCleanupCancelsTimer -v
```

Expected: 2 tests FAIL (cleanup_persistent_container not yet cancelling timer).

- [ ] **Step 2: Modify `cleanup_persistent_container()`**

Replace the function:

```python
def cleanup_persistent_container() -> None:
    global _container_active, _stop_timer_task
    if not _container_active:
        return
    if _stop_timer_task is not None and not _stop_timer_task.done():
        _stop_timer_task.cancel()
        _stop_timer_task = None
    delete_container()
    _container_active = False
```

- [ ] **Step 3: Run the tests**

```bash
python -m pytest tests/test_container_lifecycle.py::TestCleanupCancelsTimer -v
```

Expected: 2 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py
git commit -m "feat: cancel grace timer in cleanup_persistent_container

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Final verification — run all tests

- [ ] **Step 1: Run the full test suite for the new feature**

```bash
python -m pytest tests/test_container_lifecycle.py -v
```

Expected: ALL 13 tests PASS.

- [ ] **Step 2: Run existing tests to ensure no regressions**

```bash
python -m pytest tests/test_background_shell_infra.py tests/test_background_shell_agent.py tests/test_graph_nodes.py -v
```

Expected: All existing tests PASS — no regressions.

- [ ] **Step 3: Run ruff lint check**

```bash
ruff check hatsume/plugins/hatsume-plugin/infra.py
```

Expected: No lint errors.

- [ ] **Step 4: Final commit (if any lint fixes needed)**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py
git commit -m "chore: final lint and verification of auto-stop feature

Co-Authored-By: Claude <noreply@anthropic.com>"
```
