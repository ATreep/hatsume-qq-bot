"""APScheduler heartbeat jobs and bounded Hook subprocess execution."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger
from nonebot import require

from ..config import HOOKS_DIR
from ..group_runtime import group_runtime_registry
from ..utils.security import mask_secret_keys
from .store import HOOK_MAX_TIMEOUT_SECONDS, HookStore

scheduler = require("nonebot_plugin_apscheduler").scheduler

HOOK_JOB_PREFIX = "hook_heartbeat_"
HOOK_STDOUT_LIMIT_BYTES = 8 * 1024
HOOK_STDERR_LIMIT_BYTES = 8 * 1024
_PROCESS_STOP_GRACE_SECONDS = 0.5

_execution_locks: dict[int, asyncio.Lock] = {}
_running_processes: dict[int, asyncio.subprocess.Process] = {}
_running_tasks: set[asyncio.Task[Any]] = set()


@dataclass(frozen=True)
class HookScriptResult:
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None


class HookOutputLimitError(RuntimeError):
    """Raised when a Hook writes more than its bounded output allowance."""


def validate_hook_script_path(
    script_path: str | Path,
    group_id: int,
    *,
    hooks_root: Path = HOOKS_DIR,
) -> Path:
    """Return one executable script resolved inside the shared Hook directory."""
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
        raise ValueError("group_id must be a positive integer")
    raw_path = str(script_path)
    if not raw_path or "\0" in raw_path:
        raise ValueError("script_path must not be empty")
    if not Path(raw_path).is_absolute():
        raise ValueError("script_path must be an absolute path")
    hooks_root = Path(hooks_root).expanduser().resolve()
    try:
        resolved = Path(raw_path).expanduser().resolve(strict=True)
        resolved.relative_to(hooks_root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise ValueError("script_path must be inside the shared Hook directory") from exc
    if not resolved.is_file():
        raise ValueError("Hook script must be a regular file")
    if not os.access(resolved, os.X_OK):
        raise ValueError("Hook script must be executable")
    try:
        with resolved.open("rb") as handle:
            if handle.read(2) != b"#!":
                raise ValueError("Hook script must start with a shebang")
    except OSError as exc:
        raise ValueError(f"Unable to read Hook script: {exc}") from exc
    return resolved


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> bytes:
    if stream is None:
        return b""
    data = bytearray()
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > limit:
            raise HookOutputLimitError("Hook output limit exceeded")


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        await process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=_PROCESS_STOP_GRACE_SECONDS)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


def _task_bytes(task: asyncio.Task[bytes]) -> bytes:
    if not task.done() or task.cancelled():
        return b""
    try:
        return task.result()
    except (asyncio.CancelledError, HookOutputLimitError, RuntimeError):
        return b""


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").strip()


def _redacted_error(value: str) -> str:
    return mask_secret_keys(str(value)).strip()


def _heartbeat_log(message: str) -> None:
    print(f"🪝 [hook-heartbeat] {message}", flush=True)


async def run_hook_script(
    script_path: Path,
    *,
    timeout_seconds: float,
    validation: bool = False,
    workdir: Path = Path("/work"),
    hook_id: int | None = None,
) -> HookScriptResult:
    """Run one executable Hook with timeout and bounded output collection."""
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise TypeError("timeout_seconds must be numeric")
    if timeout_seconds < 1 or timeout_seconds > HOOK_MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 1 and {HOOK_MAX_TIMEOUT_SECONDS}")
    env = {**os.environ, "HOME": "/root"}
    if validation:
        env["HATSUME_HOOK_VALIDATION"] = "1"
    else:
        env.pop("HATSUME_HOOK_VALIDATION", None)
    try:
        process = await asyncio.create_subprocess_exec(
            str(script_path),
            cwd=str(workdir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001 - launch failures become persisted state
        return HookScriptResult(None, "", "", _redacted_error(f"Hook launch failed: {exc}"))

    if hook_id is not None:
        _running_processes[hook_id] = process
    stdout_task = asyncio.create_task(
        _read_bounded(process.stdout, HOOK_STDOUT_LIMIT_BYTES)
    )
    stderr_task = asyncio.create_task(
        _read_bounded(process.stderr, HOOK_STDERR_LIMIT_BYTES)
    )
    wait_task = asyncio.create_task(process.wait())
    tasks: tuple[asyncio.Task[Any], ...] = (wait_task, stdout_task, stderr_task)
    try:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=float(timeout_seconds),
            )
        except TimeoutError:
            await _terminate_process(process)
            await asyncio.gather(*tasks, return_exceptions=True)
            return HookScriptResult(
                process.returncode,
                _decode(_task_bytes(stdout_task)),
                _decode(_task_bytes(stderr_task)),
                _redacted_error(f"Hook timed out after {timeout_seconds} seconds"),
            )
        except HookOutputLimitError:
            await _terminate_process(process)
            await asyncio.gather(*tasks, return_exceptions=True)
            return HookScriptResult(
                process.returncode,
                _decode(_task_bytes(stdout_task)),
                _decode(_task_bytes(stderr_task)),
                "Hook output limit exceeded",
            )
        except asyncio.CancelledError:
            await _terminate_process(process)
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        stdout = _decode(stdout_task.result())
        stderr = _decode(stderr_task.result())
        exit_code = int(process.returncode or 0)
        if exit_code == 0:
            if stdout:
                return HookScriptResult(
                    exit_code,
                    stdout,
                    stderr,
                    "Hook exit code 0 requires empty stdout",
                )
            return HookScriptResult(exit_code, stdout, stderr, None)
        if exit_code == 10:
            if not stdout:
                return HookScriptResult(
                    exit_code,
                    stdout,
                    stderr,
                    "Hook exit code 10 requires non-empty stdout",
                )
            return HookScriptResult(exit_code, stdout, stderr, None)
        detail = f": {stderr}" if stderr else ""
        return HookScriptResult(
            exit_code,
            stdout,
            stderr,
            _redacted_error(f"Hook exited with exit code {exit_code}{detail}"),
        )
    finally:
        if hook_id is not None and _running_processes.get(hook_id) is process:
            _running_processes.pop(hook_id, None)


def hook_job_id(hook_id: int) -> str:
    return f"{HOOK_JOB_PREFIX}{int(hook_id)}"


def cancel_hook_job(hook_id: int) -> None:
    job_id = hook_job_id(hook_id)
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)


def _resolve_store(store: HookStore | None) -> HookStore:
    if store is not None:
        return store
    from . import get_store

    return get_store()


async def execute_hook(
    hook_id: int,
    store: HookStore | None = None,
    *,
    workdir: Path = Path("/work"),
    inject_fn: Callable[..., None] | None = None,
) -> bool:
    """Execute one due Hook. Return False when it was skipped as already running."""
    lock = _execution_locks.setdefault(int(hook_id), asyncio.Lock())
    if lock.locked():
        _heartbeat_log(f"skip hook_id={hook_id} reason=already_running")
        return False
    current_task = asyncio.current_task()
    if current_task is not None:
        _running_tasks.add(current_task)
    try:
        async with lock:
            resolved_store = _resolve_store(store)
            record = resolved_store.get_hook(int(hook_id))
            if record is None:
                _heartbeat_log(f"skip hook_id={hook_id} reason=not_found")
                return True
            if not record["enabled"]:
                _heartbeat_log(f"skip hook_id={hook_id} reason=disabled")
                return True
            group_id = int(record["group_id"])
            hook_name = str(record["name"])
            context = f"hook_id={hook_id} group_id={group_id} name={hook_name!r}"
            if group_id not in group_runtime_registry.routed_group_ids():
                _heartbeat_log(f"skip {context} reason=group_not_routed")
                return True
            run_at = time.time()
            started_at = time.monotonic()
            _heartbeat_log(
                f"start {context} script={record['script_path']!r} "
                f"timeout={record['timeout_seconds']}s"
            )
            try:
                path = validate_hook_script_path(record["script_path"], group_id)
            except ValueError as exc:
                error = _redacted_error(str(exc))
                resolved_store.record_failure(
                    int(hook_id),
                    None,
                    error,
                    run_at,
                )
                _heartbeat_log(f"failure {context} stage=path_validation error={error!r}")
                return True
            result = await run_hook_script(
                path,
                timeout_seconds=int(record["timeout_seconds"]),
                workdir=workdir,
                hook_id=int(hook_id),
            )
            elapsed = time.monotonic() - started_at
            stdout_bytes = len(result.stdout.encode("utf-8"))
            stderr_bytes = len(result.stderr.encode("utf-8"))
            if result.error is not None:
                outcome = "failure"
            elif result.exit_code == 10:
                outcome = "trigger"
            else:
                outcome = "no_event"
            _heartbeat_log(
                f"finish {context} outcome={outcome} exit_code={result.exit_code} "
                f"elapsed={elapsed:.3f}s stdout_bytes={stdout_bytes} "
                f"stderr_bytes={stderr_bytes}"
            )
            latest = resolved_store.get_hook(int(hook_id))
            if (
                latest is None
                or not latest["enabled"]
                or latest["updated_at"] != record["updated_at"]
            ):
                _heartbeat_log(f"skip_result {context} reason=hook_changed_during_run")
                return True
            if result.error is not None:
                error = _redacted_error(result.error)
                resolved_store.record_failure(
                    int(hook_id),
                    result.exit_code,
                    error,
                    run_at,
                )
                _heartbeat_log(f"failure {context} stage=script error={error!r}")
                return True
            if result.exit_code == 10:
                if group_id not in group_runtime_registry.routed_group_ids():
                    error = "Hook group route disappeared before injection"
                    resolved_store.record_failure(
                        int(hook_id),
                        result.exit_code,
                        error,
                        run_at,
                    )
                    _heartbeat_log(f"failure {context} stage=injection error={error!r}")
                    return True
                if inject_fn is None:
                    from ..graph.nodes import inject_hook as resolved_inject

                    inject_fn = resolved_inject
                try:
                    _heartbeat_log(f"inject {context} event_bytes={stdout_bytes}")
                    inject_fn(
                        group_id=group_id,
                        hook_name=hook_name,
                        prompt=str(record["prompt"]),
                        event_text=result.stdout,
                    )
                except Exception as exc:  # noqa: BLE001 - callback boundary
                    error = _redacted_error(f"Hook injection failed: {exc}")
                    resolved_store.record_failure(
                        int(hook_id),
                        result.exit_code,
                        error,
                        run_at,
                    )
                    _heartbeat_log(f"failure {context} stage=injection error={error!r}")
                    return True
                _heartbeat_log(f"injected {context}")
            resolved_store.record_success(int(hook_id), int(result.exit_code or 0), run_at)
            _heartbeat_log(f"success {context} outcome={outcome}")
            return True
    finally:
        if current_task is not None:
            _running_tasks.discard(current_task)
        if not lock.locked():
            _execution_locks.pop(int(hook_id), None)


def _next_run_timestamp(record: dict[str, Any], now: float) -> float:
    last_run_at = record.get("last_run_at")
    if last_run_at is None:
        return now + int(record["interval_seconds"])
    expected = float(last_run_at) + int(record["interval_seconds"])
    return max(now, expected)


def register_hook_job(
    record: dict[str, Any],
    store: HookStore | None = None,
    *,
    now: float | None = None,
) -> Any | None:
    """Register or replace one enabled Hook job when its group is routable."""
    hook_id = int(record["id"])
    group_id = int(record["group_id"])
    if not record["enabled"] or group_id not in group_runtime_registry.routed_group_ids():
        cancel_hook_job(hook_id)
        return None
    current = time.time() if now is None else float(now)
    start_at = datetime.fromtimestamp(
        _next_run_timestamp(record, current),
        tz=UTC,
    )
    trigger = IntervalTrigger(
        seconds=int(record["interval_seconds"]),
        start_date=start_at,
        timezone=UTC,
    )
    return scheduler.add_job(
        execute_hook,
        trigger,
        id=hook_job_id(hook_id),
        args=[hook_id],
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=int(record["interval_seconds"]),
    )


def restore_hook_jobs(
    store: HookStore,
    routable_group_ids: list[int] | tuple[int, ...] | set[int],
    *,
    now: float | None = None,
) -> None:
    routed = {int(group_id) for group_id in routable_group_ids if int(group_id) > 0}
    for job in tuple(scheduler.get_jobs()):
        if str(getattr(job, "id", "")).startswith(HOOK_JOB_PREFIX):
            scheduler.remove_job(job.id)
    enabled = store.list_enabled_hooks()
    for record in enabled:
        if int(record["group_id"]) in routed:
            register_hook_job(record, store, now=now)
        else:
            cancel_hook_job(int(record["id"]))


def pause_hook_jobs_for_groups(store: HookStore, group_ids: list[int] | tuple[int, ...]) -> None:
    for group_id in group_ids:
        for record in store.list_hooks(int(group_id)):
            cancel_hook_job(int(record["id"]))


async def cancel_hook_execution(hook_id: int) -> None:
    cancel_hook_job(hook_id)
    process = _running_processes.get(int(hook_id))
    if process is not None:
        await _terminate_process(process)
    lock = _execution_locks.get(int(hook_id))
    if lock is not None and lock.locked():
        await lock.acquire()
        lock.release()


async def shutdown_hook_executor() -> None:
    for job in tuple(scheduler.get_jobs()):
        if str(getattr(job, "id", "")).startswith(HOOK_JOB_PREFIX):
            scheduler.remove_job(job.id)
    for process in tuple(_running_processes.values()):
        await _terminate_process(process)
    current = asyncio.current_task()
    pending = [task for task in _running_tasks if task is not current and not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    _running_processes.clear()
    _running_tasks.clear()
    _execution_locks.clear()


def get_hook_next_run(hook_id: int) -> datetime | None:
    job = scheduler.get_job(hook_job_id(hook_id))
    return None if job is None else getattr(job, "next_run_time", None)
