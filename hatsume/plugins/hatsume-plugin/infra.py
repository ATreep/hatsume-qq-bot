"""Infrastructure: Docker sandbox and HTML rendering."""

from __future__ import annotations

import asyncio
import base64
import binascii
from io import BytesIO
import os
import re
import shlex
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from PIL import Image, UnidentifiedImageError

from .config import CONTAINER_NAME_BASE, DOCKER_ENV_PATH, SHELL_TIMEOUT
from .group_runtime import get_current_group_id, validate_group_id

# ===========================================================================
# Subprocess reference counting (for auto-stop container)
# ===========================================================================
_STOP_GRACE_SECONDS: float = 300.0  # 5 minutes


@dataclass
class ContainerRuntime:
    group_id: int
    name: str
    startup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: bool = False
    refcount: int = 0
    refcount_lock: threading.Lock = field(default_factory=threading.Lock)
    stop_task: asyncio.Task[Any] | None = None
    foreground_processes: set[asyncio.subprocess.Process] = field(default_factory=set)
    foreground_tasks: dict[
        asyncio.subprocess.Process,
        asyncio.Task[Any],
    ] = field(default_factory=dict)
    resetting: bool = False


_container_states: dict[int, ContainerRuntime] = {}


def _resolve_group_id(group_id: int | None = None) -> int:
    if group_id is None:
        current = get_current_group_id()
        if current is None:
            raise RuntimeError("group runtime is not bound")
        group_id = current
    return validate_group_id(group_id)


def container_name_for_group(group_id: int) -> str:
    return f"{CONTAINER_NAME_BASE}-{validate_group_id(group_id)}"


def _track_foreground_process(
    state: ContainerRuntime,
    process: asyncio.subprocess.Process,
) -> None:
    state.foreground_processes.add(process)
    task = asyncio.current_task()
    if task is not None:
        state.foreground_tasks[process] = task


def _untrack_foreground_process(
    state: ContainerRuntime,
    process: asyncio.subprocess.Process,
) -> None:
    state.foreground_processes.discard(process)
    state.foreground_tasks.pop(process, None)


async def _terminate_async_process(
    process: asyncio.subprocess.Process,
) -> tuple[bytes, bytes]:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        return await process.communicate()
    except (ProcessLookupError, RuntimeError):
        return b"", b""


def _get_container_state(group_id: int, *, create: bool) -> ContainerRuntime | None:
    resolved_group_id = validate_group_id(group_id)
    state = _container_states.get(resolved_group_id)
    if state is None and create:
        state = ContainerRuntime(
            group_id=resolved_group_id,
            name=container_name_for_group(resolved_group_id),
        )
        _container_states[resolved_group_id] = state
    return state


def _acquire_subprocess(group_id: int | None = None) -> ContainerRuntime:
    state = _get_container_state(_resolve_group_id(group_id), create=True)
    assert state is not None
    with state.refcount_lock:
        state.refcount += 1
        if state.stop_task is not None and not state.stop_task.done():
            state.stop_task.cancel()
        state.stop_task = None
    return state


def _release_subprocess(group_id: int | None = None) -> None:
    state = _get_container_state(_resolve_group_id(group_id), create=False)
    if state is None:
        return
    with state.refcount_lock:
        state.refcount = max(0, state.refcount - 1)
        if state.refcount != 0 or state.resetting:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        state.stop_task = loop.create_task(_delayed_stop_container(state))


async def _delayed_stop_container(state: ContainerRuntime) -> None:
    """Wait grace period then stop container if still no active subprocesses."""
    try:
        await asyncio.sleep(_STOP_GRACE_SECONDS)
        with state.refcount_lock:
            should_stop = state.refcount == 0 and not state.resetting
        if should_stop:
            stop_container(state.group_id)
            state.active = False
    finally:
        if state.stop_task is asyncio.current_task():
            state.stop_task = None


# ===========================================================================
# Docker sandbox
# ===========================================================================
USER_IMAGE_SANDBOX_DIR = "/tmp/hatsume-user-images"


async def ensure_container_running(group_id: int | None = None) -> None:
    resolved_group_id = _resolve_group_id(group_id)
    state = _get_container_state(resolved_group_id, create=True)
    assert state is not None
    async with state.startup_lock:
        if state.active:
            return
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(Path(DOCKER_ENV_PATH, "launch_image.sh")),
            state.name,
            cwd=DOCKER_ENV_PATH,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _track_foreground_process(state, proc)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=b"echo ready\n"),
                timeout=SHELL_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            await _terminate_async_process(proc)
            raise AssertionError("Docker container startup timed out") from exc
        except asyncio.CancelledError:
            await _terminate_async_process(proc)
            raise
        except Exception:
            await _terminate_async_process(proc)
            raise
        finally:
            _untrack_foreground_process(state, proc)
        decoded_stdout = _strip_ansi(stdout)
        if proc.returncode != 0 or decoded_stdout.startswith("[HALT]"):
            detail = _strip_ansi(stderr).strip() or decoded_stdout.strip()
            raise AssertionError(detail or "Docker container startup failed")
        state.active = True


async def cleanup_persistent_container(group_id: int) -> bool:
    """Terminate and delete one group's existing sandbox without creating it."""
    resolved_group_id = validate_group_id(group_id)
    state = _get_container_state(resolved_group_id, create=False)
    if state is None and not _container_exists(resolved_group_id):
        return False
    if state is None:
        state = _get_container_state(resolved_group_id, create=True)
        assert state is not None
    await _shutdown_container_state(state, delete=True)
    _container_states.pop(resolved_group_id, None)
    return True


# ---- ANSI escape code stripping ----
_ANSI_RE = re.compile(rb"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(data: bytes | str) -> str:
    """Remove ANSI escape sequences and decode to str if bytes."""
    if isinstance(data, str):
        data = data.encode()
    return _ANSI_RE.sub(b"", data).decode(errors="replace")


async def run_cmd(
    code: str,
    timeout: float = SHELL_TIMEOUT,
    *,
    group_id: int | None = None,
) -> str:
    """Execute a bash command in Docker. Returns stdout+stderr."""
    resolved_group_id = _resolve_group_id(group_id)
    await ensure_container_running(resolved_group_id)
    state = _acquire_subprocess(resolved_group_id)
    command = "source ~/.bashrc\n" + code + "\n"
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(Path(DOCKER_ENV_PATH, "launch_image.sh")),
            state.name,
            cwd=DOCKER_ENV_PATH,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _track_foreground_process(state, proc)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=command.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            stdout, stderr = await _terminate_async_process(proc)
            return (
                f"Executing Timeout (timeout={timeout}s)\n"
                f"stdout:\n{_strip_ansi(stdout)}\n"
                f"stderr:\n{_strip_ansi(stderr)}"
            )
        except asyncio.CancelledError:
            await _terminate_async_process(proc)
            raise
        except Exception:
            await _terminate_async_process(proc)
            raise
        finally:
            _untrack_foreground_process(state, proc)

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
        _release_subprocess(resolved_group_id)


async def read_sandbox_image_data_uri(
    sandbox_path: str,
    *,
    group_id: int,
) -> str:
    """Read and validate an image from one group's sandbox as a data URI."""
    if not sandbox_path.startswith("/") or "\0" in sandbox_path:
        raise ValueError("sandbox image path must be an absolute path")

    resolved_group_id = validate_group_id(group_id)
    quoted_path = shlex.quote(sandbox_path)
    output = await run_cmd(
        f"base64 -w 0 -- {quoted_path} 2>&1; echo '::EXIT::'$?",
        timeout=30,
        group_id=resolved_group_id,
    )
    if "::EXIT::" not in output:
        raise RuntimeError("sandbox image read did not return an exit status")
    encoded, exit_text = output.rsplit("::EXIT::", 1)
    encoded = encoded.strip()
    if exit_text.strip() != "0" or not encoded:
        raise RuntimeError(encoded or "sandbox image read returned no data")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("sandbox image returned invalid base64 data") from exc

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("sandbox file is not a valid image") from exc

    mime = Image.MIME.get(image_format or "")
    if not mime or not mime.startswith("image/"):
        raise ValueError(f"unsupported sandbox image format: {image_format or 'unknown'}")

    normalized = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{normalized}"


def _user_image_basename(message_id: int, image_order: int) -> str:
    normalized_message_id = int(message_id)
    normalized_image_order = int(image_order)
    if normalized_image_order < 1:
        raise ValueError("image_order must be at least 1")
    return f"{normalized_message_id}-{normalized_image_order}"


async def _ensure_user_image_sandbox_dir(group_id: int) -> None:
    resolved_group_id = validate_group_id(group_id)
    await ensure_container_running(resolved_group_id)
    quoted_dir = shlex.quote(USER_IMAGE_SANDBOX_DIR)
    output = await run_cmd(
        f"mkdir -p -- {quoted_dir}; echo '::EXIT::'$?",
        timeout=30,
        group_id=resolved_group_id,
    )
    if "::EXIT::" not in output:
        raise RuntimeError("Unable to create sandbox user image directory")
    detail, exit_text = output.rsplit("::EXIT::", 1)
    if exit_text.strip() != "0":
        raise RuntimeError(
            "Unable to create sandbox user image directory: "
            f"{detail.strip() or '(no output)'}"
        )


async def find_sandbox_user_image(
    message_id: int,
    image_order: int,
    *,
    group_id: int,
) -> str | None:
    """Return an existing deterministic user-image path from the sandbox."""
    basename = _user_image_basename(message_id, image_order)
    resolved_group_id = validate_group_id(group_id)
    await _ensure_user_image_sandbox_dir(resolved_group_id)
    quoted_dir = shlex.quote(USER_IMAGE_SANDBOX_DIR)
    quoted_pattern = shlex.quote(f"{basename}.*")
    output = await run_cmd(
        (
            f"find {quoted_dir} -maxdepth 1 -type f "
            f"-name {quoted_pattern} -print -quit; echo '::EXIT::'$?"
        ),
        timeout=30,
        group_id=resolved_group_id,
    )
    if "::EXIT::" not in output:
        raise RuntimeError("Unable to search sandbox user image directory")
    detail, exit_text = output.rsplit("::EXIT::", 1)
    if exit_text.strip() != "0":
        raise RuntimeError(
            "Unable to search sandbox user image directory: "
            f"{detail.strip() or '(no output)'}"
        )

    expected_prefix = f"{USER_IMAGE_SANDBOX_DIR}/{basename}."
    for line in detail.splitlines():
        candidate = line.strip()
        if candidate.startswith(expected_prefix):
            return candidate
    return None


async def save_sandbox_user_image(
    image_bytes: bytes,
    message_id: int,
    image_order: int,
    extension: str,
    *,
    group_id: int,
) -> str:
    """Copy validated image bytes to their deterministic sandbox path."""
    basename = _user_image_basename(message_id, image_order)
    normalized_extension = extension.lower().lstrip(".")
    if not normalized_extension or not normalized_extension.isalnum():
        raise ValueError("extension must contain only letters and numbers")

    resolved_group_id = validate_group_id(group_id)
    await _ensure_user_image_sandbox_dir(resolved_group_id)
    destination = (
        f"{USER_IMAGE_SANDBOX_DIR}/{basename}.{normalized_extension}"
    )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="hatsume-user-image-",
            suffix=f".{normalized_extension}",
            delete=False,
        ) as temporary_file:
            temporary_file.write(image_bytes)
            temporary_path = Path(temporary_file.name)

        await copy_host_file_to_sandbox(
            temporary_path,
            destination,
            timeout=SHELL_TIMEOUT,
            group_id=resolved_group_id,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return destination


async def copy_host_file_to_sandbox(
    host_path: str | Path,
    destination: str,
    *,
    timeout: float = SHELL_TIMEOUT,
    group_id: int | None = None,
) -> None:
    """Copy one host file into the selected group's container."""
    if not destination.startswith("/") or "\0" in destination:
        raise ValueError("sandbox destination must be an absolute path")
    source = Path(host_path)
    if not source.is_file():
        raise FileNotFoundError(source)

    resolved_group_id = _resolve_group_id(group_id)
    await ensure_container_running(resolved_group_id)
    state = _acquire_subprocess(resolved_group_id)
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "cp",
            str(source),
            f"{state.name}:{destination}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _track_foreground_process(state, process)
        try:
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                await _terminate_async_process(process)
                raise RuntimeError("Copying file into sandbox timed out") from exc
            except asyncio.CancelledError:
                await _terminate_async_process(process)
                raise
            except Exception:
                await _terminate_async_process(process)
                raise
            if process.returncode != 0:
                detail = _strip_ansi(stderr or stdout).strip()
                raise RuntimeError(
                    "Unable to copy file into sandbox: "
                    f"{detail or '(no output)'}"
                )
        finally:
            _untrack_foreground_process(state, process)
    finally:
        _release_subprocess(resolved_group_id)


def _container_exists(group_id: int) -> bool:
    name = container_name_for_group(group_id)
    probe = subprocess.run(
        ["docker", "container", "inspect", name],
        cwd=DOCKER_ENV_PATH,
        capture_output=True,
    )
    return probe.returncode == 0


def delete_container(group_id: int) -> None:
    name = container_name_for_group(group_id)
    subprocess.run(
        ["bash", Path(DOCKER_ENV_PATH, "delete_container.sh"), name],
        cwd=DOCKER_ENV_PATH,
        capture_output=True,
    )


def stop_container(group_id: int) -> None:
    name = container_name_for_group(group_id)
    subprocess.run(
        ["bash", Path(DOCKER_ENV_PATH, "stop_container.sh"), name],
        cwd=DOCKER_ENV_PATH,
        capture_output=True,
    )


# ===========================================================================
# Background process management (used by background_shell agent)
# ===========================================================================
_background_procs: dict[str, tuple[subprocess.Popen, Path]] = {}
_background_proc_groups: dict[str, int] = {}
_background_output_handles: dict[str, BinaryIO] = {}


def start_background_cmd(
    code: str,
    proc_id: str,
    *,
    group_id: int | None = None,
) -> Path:
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
    resolved_group_id = _resolve_group_id(group_id)
    state = _get_container_state(resolved_group_id, create=True)
    assert state is not None
    _acquire_subprocess(resolved_group_id)

    file_descriptor, raw_path = tempfile.mkstemp(
        prefix="hatsume-bg-",
        suffix=".log",
    )
    tmp = Path(raw_path)
    output_handle = os.fdopen(file_descriptor, "wb")
    try:
        proc = subprocess.Popen(
            ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh"), state.name],
            cwd=DOCKER_ENV_PATH,
            stdin=subprocess.PIPE,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
        )
        assert proc.stdin is not None
        proc.stdin.write(("source ~/.bashrc\n" + code + "\n").encode("utf-8"))
        proc.stdin.flush()
    except Exception:
        output_handle.close()
        tmp.unlink(missing_ok=True)
        _release_subprocess(resolved_group_id)
        raise
    _background_procs[proc_id] = (proc, tmp)
    _background_proc_groups[proc_id] = resolved_group_id
    _background_output_handles[proc_id] = output_handle
    return tmp


def get_background_process(
    proc_id: str,
    *,
    group_id: int | None = None,
) -> tuple[subprocess.Popen, Path] | None:
    resolved_group_id = _resolve_group_id(group_id)
    if _background_proc_groups.get(proc_id) != resolved_group_id:
        return None
    return _background_procs.get(proc_id)


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


def kill_background_cmd(
    proc_id: str,
    *,
    group_id: int | None = None,
) -> str | None:
    """Terminate a background process and clean up its tmp file.

    Args:
        proc_id: The identifier used when the process was started.

    Returns:
        Any remaining unread output from the tmp file, or None if the
        proc_id was not found (already cleaned up).
    """
    resolved_group_id = _resolve_group_id(group_id)
    if _background_proc_groups.get(proc_id) != resolved_group_id:
        return None
    entry = _background_procs.pop(proc_id, None)
    if entry is None:
        return None
    _background_proc_groups.pop(proc_id, None)

    proc, tmp = entry
    remaining = ""

    try:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass

    output_handle = _background_output_handles.pop(proc_id, None)
    if output_handle is not None:
        output_handle.close()

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

    _release_subprocess(resolved_group_id)
    return remaining


async def _shutdown_container_state(
    state: ContainerRuntime,
    *,
    delete: bool,
) -> None:
    state.resetting = True
    if state.stop_task is not None and not state.stop_task.done():
        state.stop_task.cancel()
    state.stop_task = None

    current_task = asyncio.current_task()
    foreground_tasks = {
        task
        for task in state.foreground_tasks.values()
        if task is not current_task and not task.done()
    }
    for task in foreground_tasks:
        task.cancel()
    if foreground_tasks:
        await asyncio.gather(*foreground_tasks, return_exceptions=True)

    foreground = list(state.foreground_processes)
    if foreground:
        await asyncio.gather(
            *(_terminate_async_process(process) for process in foreground),
            return_exceptions=True,
        )
    state.foreground_processes.clear()
    state.foreground_tasks.clear()

    for proc_id, owner_group_id in list(_background_proc_groups.items()):
        if owner_group_id == state.group_id:
            kill_background_cmd(proc_id, group_id=state.group_id)

    with state.refcount_lock:
        state.refcount = 0
    if delete:
        delete_container(state.group_id)
    elif state.active or _container_exists(state.group_id):
        stop_container(state.group_id)
    state.active = False
    state.resetting = False


async def shutdown_all_containers() -> None:
    for state in list(_container_states.values()):
        await _shutdown_container_state(state, delete=False)
    _container_states.clear()
