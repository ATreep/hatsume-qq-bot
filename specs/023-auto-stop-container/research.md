# Research: Auto-Stop Docker Container

**Feature**: 023-auto-stop-container | **Date**: 2026-07-01

## Design Decisions

### Decision 1: Reference Counting over Event-Driven Tracking

**Decision**: Simple integer refcount with `threading.Lock` protection.

**Rationale**: The subprocess lifecycle is already well-defined — `run_cmd` is synchronous (start→end in one call), background procs are tracked in `_background_procs` dict. A refcount is the simplest mechanism that correctly models "N active subprocesses." An event-driven approach (pub/sub on process start/end) would add complexity without benefit since all integration points are in the same module.

**Alternatives considered**:
- Event bus / pub-sub: Overengineered for 4 integration points in one file.
- Process group tracking (PGID): Doesn't work because each `docker exec` is a separate bash invocation, not child processes of one parent.

### Decision 2: asyncio Timer over threading.Timer

**Decision**: `asyncio.create_task` with `asyncio.sleep(300)`.

**Rationale**: The bot's main loop is asyncio-based. Using an asyncio task integrates naturally with the event loop and avoids thread-safety concerns. `threading.Timer` would require extra care with the GIL and asyncio event loop interaction.

**Alternatives considered**:
- `threading.Timer`: Would require `call_soon_threadsafe` to interact with asyncio loop; more error-prone.
- Existing `timer/` module (SQLite): Overkill — adds persistence dependency for a feature that tolerates timer loss on restart.

### Decision 3: threading.Lock over asyncio.Lock

**Decision**: `threading.Lock` for refcount protection.

**Rationale**: `run_cmd()` is synchronous and cannot use `asyncio.Lock` (requires `await`). `threading.Lock` works correctly from both sync and async contexts without blocking the event loop for the microsecond-scale critical section (just an integer increment/decrement + optional task cancel/create).

**Alternatives considered**:
- `asyncio.Lock` with `asyncio.run_coroutine_threadsafe`: Workable but adds unnecessary complexity.
- No lock (relying on GIL for integer ops): Unsafe for the timer cancellation logic which involves multiple operations (check done → cancel → set None).

### Decision 4: Re-check Refcount After Grace Sleep

**Decision**: After `asyncio.sleep(300)`, re-acquire lock and verify `refcount == 0` before calling `stop_container()`.

**Rationale**: Prevents a race where a subprocess starts at t=299.9s and the timer fires at t=300s before `_acquire_subprocess` cancels it. The re-check under lock eliminates this window.

**Alternatives considered**:
- Relying solely on timer cancellation: The window between sleep expiry and lock acquisition is unavoidable without re-check.
- Double-checked locking pattern: Unnecessary — a single re-check under lock is sufficient.

### Decision 5: RuntimeError Fallback for Sync Contexts

**Decision**: Catch `RuntimeError` from `asyncio.get_running_loop()` and fall back to `asyncio.get_event_loop()`.

**Rationale**: The `/shell` command handler calls `run_cmd()` from a synchronous NoneBot handler. `get_running_loop()` throws `RuntimeError` when no loop is running. `get_event_loop()` returns the loop that will be running when the current sync handler returns (the NoneBot event loop).

**Alternatives considered**:
- Always use `get_event_loop()`: Deprecated in Python 3.12 and can return the wrong loop in nested async contexts.
- Require all callers to be async: Would break existing `/shell` command handler.
