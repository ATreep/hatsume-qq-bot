# Auto-Stop Docker Container When All Subprocesses Finish

**Date:** 2026-07-01
**Status:** Design Approved

## Overview

When `run_cmd` or `start_background_cmd` creates a subprocess that executes `docker exec` inside the persistent container `hatsume-space-kali`, the container is started lazily and remains running indefinitely. This design adds a reference-counting mechanism with a grace-period timer: when the last active subprocess finishes, the container is automatically stopped after 5 minutes of inactivity.

## Motivation

The container `hatsume-space-kali` currently only stops when an admin manually runs `/resetsandbox`. This wastes resources when the bot is idle — the container sits in memory consuming RAM and CPU. However, during active use, the container should stay up to avoid the overhead of repeated `docker start`/`docker create` cycles.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope of "active subprocess" | Both `run_cmd` and `start_background_cmd` | All `docker exec` invocations should be tracked |
| Grace period | 5 minutes | Long enough to avoid thrashing during multi-call sessions; short enough to reclaim resources reasonably soon |
| Timer implementation | asyncio task (`create_task` + `asyncio.sleep`) | Simple, no external deps, minimal code. Lost timer on bot restart is harmless (container just stays up) |
| Lock type | `threading.Lock` | `run_cmd()` is synchronous and cannot use `asyncio.Lock` |

## Architecture

### New State (in `infra.py`)

```python
_subprocess_refcount: int = 0
_subprocess_refcount_lock: threading.Lock = threading.Lock()
_stop_timer_task: asyncio.Task | None = None
_STOP_GRACE_SECONDS: float = 300.0  # 5 minutes
```

### New Functions (in `infra.py`)

#### `_acquire_subprocess()`

Called when any subprocess starts (before `subprocess.run()` or `subprocess.Popen()`).

1. Acquire `_subprocess_refcount_lock`.
2. Increment `_subprocess_refcount` by 1.
3. If a pending `_stop_timer_task` exists and is not done, cancel it and set to `None`.

#### `_release_subprocess()`

Called when any subprocess finishes (in `finally` block or in `kill_background_cmd`).

1. Acquire `_subprocess_refcount_lock`.
2. Decrement `_subprocess_refcount` (clamped to >= 0).
3. If refcount reaches 0:
   - Obtain the asyncio event loop (handles both async and sync contexts).
   - Create a task: `_delayed_stop_container()`.

#### `_delayed_stop_container()` (async)

1. `await asyncio.sleep(_STOP_GRACE_SECONDS)`.
2. Acquire `_subprocess_refcount_lock`.
3. **Re-check** `_subprocess_refcount == 0` (in case a new process started during the sleep).
4. If still 0: call `stop_container()`, set `_container_active = False`.
5. Set `_stop_timer_task = None`.

### Integration Points

#### `run_cmd()` — synchronous command

```python
def run_cmd(code: str, timeout: float = SHELL_TIMEOUT) -> str:
    ensure_container_running()
    _acquire_subprocess()
    try:
        # ... existing logic: write script.sh, subprocess.run, check HALT, truncate ...
        return output
    finally:
        _release_subprocess()
```

`try/finally` ensures refcount correctness even on `TimeoutExpired` or other exceptions.

#### `start_background_cmd()` — background process start

```python
def start_background_cmd(code: str, proc_id: str) -> Path:
    ensure_container_running()
    _acquire_subprocess()
    # ... existing logic: write script.sh, create tmp, Popen, store in _background_procs ...
    return tmp_path
```

No `finally` — `_release` is deferred to `kill_background_cmd()`.

#### `kill_background_cmd()` — background process end

```python
def kill_background_cmd(proc_id: str) -> str | None:
    # ... existing logic: terminate/kill/wait, read output, delete tmp ...
    _release_subprocess()
    return remaining
```

#### `cleanup_persistent_container()` — manual reset

```python
def cleanup_persistent_container() -> None:
    global _stop_timer_task
    if _stop_timer_task is not None and not _stop_timer_task.done():
        _stop_timer_task.cancel()
        _stop_timer_task = None
    delete_container()
    global _container_active
    _container_active = False
```

Cancels any pending grace timer before forcefully removing the container.

## Edge Cases

| Scenario | Handling |
|----------|----------|
| `run_cmd` in sync context (`/shell` command) | `_release_subprocess` uses `RuntimeError` catch to fall back to `asyncio.get_event_loop()` |
| Background shell agent crashes before `kill_background_cmd` | Agent's existing `finally` block already calls `kill_background_cmd`, which calls `_release` ✅ |
| Multiple concurrent background shells | Refcount handles any number of concurrent acquires/releases |
| New subprocess starts during grace period | `_acquire_subprocess` cancels the timer, refcount goes back to 1 |
| Container externally deleted during grace period | `docker stop` on nonexistent container is harmless (non-zero exit, not checked) |
| Bot restarts during grace period | Timer is lost; container stays running until next `/resetsandbox` or manual cleanup. Acceptable. |
| `ensure_container_running` called after auto-stop | Detects `_container_active = False`, restarts the container normally |

## Test Plan

| Test | What it verifies |
|------|-----------------|
| `run_cmd` releases refcount on success | Mock `subprocess.run`, verify `_release_subprocess` called via refcount decrement |
| `run_cmd` releases refcount on exception | Simulate `TimeoutExpired`, verify refcount still decrements |
| `start_background_cmd` + `kill_background_cmd` refcount cycle | Start → refcount=1, Kill → refcount=0 |
| Grace timer fires after refcount hits zero | Refcount 0 → wait 300s (mocked sleep) → `stop_container` called |
| New subprocess cancels grace timer | Refcount 0 → timer starts → acquire → timer cancelled, refcount=1 |
| `cleanup_persistent_container` cancels timer | Timer pending → cleanup → timer cancelled |
| Multiple concurrent refcount | acquire × 3 → release × 2 (refcount=1) → release (refcount=0 → timer starts) |
| `_release_subprocess` in sync context | No running loop → falls back to `get_event_loop()` without error |

## Files Changed

| File | Change |
|------|--------|
| `hatsume/plugins/hatsume-plugin/infra.py` | ~60 lines added: refcount state, 3 new functions, 4 integration points |
| `tests/test_container_lifecycle.py` (new) | ~100 lines: test cases covering the test plan above |

## Dependencies

None — pure Python stdlib (`threading`, `asyncio`).
