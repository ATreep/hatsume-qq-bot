"""Infrastructure: Docker sandbox and HTML rendering."""

from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from .config import DOCKER_ENV_PATH, SHELL_TIMEOUT

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
                # A grace task is meaningful only on an actively running loop.
                return
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


async def ensure_container_running() -> None:
    global _container_active
    if _container_active:
        return

    script_path = Path(DOCKER_ENV_PATH, "script.sh").absolute()
    script_path.write_text("echo ready")

    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", str(Path(DOCKER_ENV_PATH, "launch_image.sh")),
            cwd=DOCKER_ENV_PATH,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SHELL_TIMEOUT
        )
        decode_stdout = stdout.decode()
        assert not decode_stdout.startswith("[HALT]"), "Docker is not running!"
    except asyncio.TimeoutError:
        raise AssertionError("Docker container startup timed out")

    _container_active = True


def cleanup_persistent_container() -> None:
    global _container_active, _stop_timer_task
    if not _container_active:
        return
    if _stop_timer_task is not None and not _stop_timer_task.done():
        _stop_timer_task.cancel()
        _stop_timer_task = None
    delete_container()
    _container_active = False


# ---- ANSI escape code stripping ----
_ANSI_RE = re.compile(rb"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(data: bytes | str) -> str:
    """Remove ANSI escape sequences and decode to str if bytes."""
    if isinstance(data, str):
        data = data.encode()
    return _ANSI_RE.sub(b"", data).decode(errors="replace")


async def run_cmd(code: str, timeout: float = SHELL_TIMEOUT) -> str:
    """Execute a bash command in Docker. Returns stdout+stderr."""
    script_path = Path(DOCKER_ENV_PATH, "script.sh").absolute()
    SOURCE_BASHRC = "source ~/.bashrc"
    script_path.write_text(SOURCE_BASHRC + "\n" + code)

    _acquire_subprocess()
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", str(Path(DOCKER_ENV_PATH, "launch_image.sh")),
            cwd=DOCKER_ENV_PATH,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            return (
                f"Executing Timeout (timeout={timeout}s)\n"
                f"stdout:\n{_strip_ansi(stdout)}\n"
                f"stderr:\n{_strip_ansi(stderr)}"
            )

        try:
            decode_stdout = _strip_ansi(stdout)
            decode_stderr = _strip_ansi(stderr)
            assert not decode_stdout.startswith("[HALT]"), "Docker is not running!"
            output = decode_stdout
            if decode_stderr.strip() != "":
                output += "\n\n" + decode_stderr

            return output
        except UnicodeDecodeError:
            return "运行结果无法解码。"
    finally:
        _release_subprocess()


def delete_container() -> None:
    subprocess.run(
        ["bash", Path(DOCKER_ENV_PATH, "delete_container.sh")],
        cwd=DOCKER_ENV_PATH,
        capture_output=True,
    )


def stop_container() -> None:
    subprocess.run(
        ["bash", Path(DOCKER_ENV_PATH, "stop_container.sh")],
        cwd=DOCKER_ENV_PATH,
        capture_output=True,
    )


# ===========================================================================
# Background process management (used by background_shell agent)
# ===========================================================================
_background_procs: dict[str, tuple[subprocess.Popen, Path]] = {}


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


def read_background_output(tmp_path: Path, offset: int) -> tuple[str, int]:
    """Read new output from a background process tmp file since last read.

    Args:
        tmp_path: Path to the tmp log file.
        offset: Byte offset from which to start reading.

    Returns:
        (new_content_since_offset, new_total_offset).
        If the file doesn't exist, returns ("", offset).
    """
    if not tmp_path.exists():
        return ("", offset)
    try:
        with open(tmp_path, "rb") as f:
            f.seek(offset)
            raw = f.read()
        content = _strip_ansi(raw)
        return (content, offset + len(raw))
    except Exception:
        return ("", offset)


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
            remaining = _strip_ansi(tmp.read_bytes())
    except Exception:
        pass

    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass

    _release_subprocess()
    return remaining
