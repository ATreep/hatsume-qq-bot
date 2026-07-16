# Feature Specification: Auto-Stop Docker Container When Idle

**Feature Branch**: `023-auto-stop-container`

**Created**: 2026-07-01

**Status**: Draft

**Input**: User description: "When using run_cmd or start_background_cmd to create a new subprocess executing `docker exec`, the docker container will be started and keep running state. I want to add a checker: When the last active subprocess finished, auto stop the container."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Container Automatically Stops After Inactivity (Priority: P1)

The bot operator wants the Docker sandbox container (`hatsume-space-kali`) to automatically stop when no commands have been executed inside it for a period of time, freeing system resources (RAM, CPU) without manual intervention.

**Why this priority**: This is the core value proposition — eliminating the need for the operator to manually run `/resetsandbox` to reclaim resources. Without this, the container runs indefinitely, wasting memory.

**Independent Test**: Can be fully tested by running a shell command through the bot, waiting for the grace period to elapse, and verifying the container has stopped. Delivers immediate value as the first auto-cleanup behavior.

**Acceptance Scenarios**:

1. **Given** the container is running and a single synchronous shell command is executing, **When** that command completes, **Then** after 5 minutes with no further commands, the container is automatically stopped.
2. **Given** the container is running and a single background shell process is active, **When** that background process finishes (naturally or via kill), **Then** after 5 minutes of no further activity, the container is automatically stopped.
3. **Given** the container is stopped after auto-cleanup, **When** a new shell command is issued, **Then** the container restarts and executes the command normally.

---

### User Story 2 — Active Commands Prevent Premature Shutdown (Priority: P2)

The bot operator wants the auto-stop mechanism to never interrupt active work. If multiple commands or background processes are running concurrently, the container must stay up until ALL of them finish, plus the grace period.

**Why this priority**: Prevents data loss and interrupted workflows. Without this, a poorly-timed auto-stop could kill running processes.

**Independent Test**: Start two background processes concurrently, terminate one, verify the container stays up. Terminate the second, verify the grace timer starts and eventually stops the container.

**Acceptance Scenarios**:

1. **Given** two background shell processes are running concurrently, **When** one process finishes, **Then** the container remains running (refcount > 0, no timer started).
2. **Given** one background process is running and a synchronous command starts, **When** the synchronous command finishes, **Then** the container remains running (the background process is still active).
3. **Given** all processes have finished and the grace timer has started, **When** a new command starts during the grace period, **Then** the timer is cancelled and the container stays up.

---

### User Story 3 — Manual Cleanup Still Works (Priority: P3)

The bot operator wants the existing `/resetsandbox` command to continue working, and to properly cancel any pending auto-stop timer when it's invoked.

**Why this priority**: Ensures backward compatibility. The manual reset path must coexist with the auto-stop mechanism.

**Independent Test**: Start a command, let it finish (timer starts), then run `/resetsandbox` — the timer is cancelled and the container is immediately deleted.

**Acceptance Scenarios**:

1. **Given** the grace timer is counting down, **When** the operator runs `/resetsandbox`, **Then** the timer is cancelled and the container is immediately removed.
2. **Given** no timer is active, **When** the operator runs `/resetsandbox`, **Then** the container is removed as before (no behavioral change).

---

### Edge Cases

- What happens when the bot process is restarted during the grace period? The in-memory timer is lost; the container remains running until the next manual cleanup or the next auto-stop cycle after new activity.
- What happens when a synchronous command times out? The refcount is decremented in the `finally` block, ensuring correct accounting even on `TimeoutExpired`.
- What happens when a synchronous command encounters a Docker HALT error? The refcount is decremented in the `finally` block before the `AssertionError` propagates.
- What happens when `kill_background_cmd` is called for an unknown proc_id? The refcount is not decremented (the function returns early with `None`); no double-release occurs.
- What happens when the container is externally removed (e.g., `docker rm -f` from outside the bot) while the grace timer is running? The `docker stop` call fails harmlessly (non-zero exit from a bash script that is not checked).
- What happens if `_release_subprocess` is called from a pure synchronous context (no asyncio event loop running)? The `RuntimeError` from `asyncio.get_running_loop()` is caught, and `asyncio.get_event_loop()` is used as fallback.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST track the count of active Docker subprocesses (`run_cmd` and `start_background_cmd`) using a reference counter protected by a concurrency-safe mechanism.
- **FR-002**: System MUST increment the reference counter before any Docker subprocess starts (`_acquire_subprocess`).
- **FR-003**: System MUST decrement the reference counter after any Docker subprocess finishes, including on error paths (`_release_subprocess`).
- **FR-004**: System MUST, when the reference counter reaches zero, start a 5-minute grace period timer before stopping the container.
- **FR-005**: System MUST cancel the grace period timer if a new subprocess starts before the timer expires.
- **FR-006**: System MUST, after the grace period elapses, re-check that the reference counter is still zero before stopping the container (preventing race conditions).
- **FR-007**: System MUST stop the Docker container (`docker stop hatsume-space-kali`) when the grace timer expires with refcount still at zero.
- **FR-008**: System MUST cancel any pending grace timer when the manual container cleanup function (`cleanup_persistent_container`) is invoked.
- **FR-009**: System MUST ensure the reference counter is decremented even when a synchronous command encounters a timeout or Docker HALT error (guaranteed cleanup on both success and error paths).
- **FR-010**: System MUST handle `_release_subprocess` calls from both asynchronous and synchronous contexts without crashing.

### Key Entities

- **Subprocess Reference Counter**: An integer tracking the number of currently-active Docker subprocesses. Protected by a concurrency-safe lock. Starts at 0; incremented on subprocess start, decremented on subprocess end. Clamped to never go below 0.
- **Grace Timer**: A scheduled delayed action that waits for 5 minutes then conditionally stops the container. Created when refcount reaches 0; cancelled when refcount rises above 0 or on manual cleanup. At most one exists at any time.
- **Container Active Flag**: A boolean (`_container_active`) indicating whether the Docker container is believed to be running. Set to `True` by `ensure_container_running`, set to `False` by auto-stop or manual cleanup.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the last active subprocess finishes and 5 minutes elapse with no new subprocesses, the Docker container is in a stopped state (verified via `docker ps` showing the container is not running).
- **SC-002**: During active use with concurrent subprocesses, the container remains running for the entire duration of activity plus the grace period (zero premature shutdowns).
- **SC-003**: The existing manual `/resetsandbox` command continues to function identically to before the change, including properly cleaning up any pending auto-stop state.
- **SC-004**: All existing tests for `run_cmd`, background shell, and container lifecycle pass without modification (zero regressions).
- **SC-005**: New tests for the reference counting mechanism achieve at least 80% line coverage of the added code paths in `infra.py`.

## Assumptions

- The bot process has a running asyncio event loop in all code paths that call `_release_subprocess` (the sync-only `/shell` command handler path is the only expected exception and is handled via RuntimeError fallback).
- Docker is installed and available on the host machine (existing assumption, unchanged).
- The 5-minute grace period is a reasonable default that balances resource reclamation against container startup overhead. This value is defined as a module-level constant and can be changed without logic modifications.
- The `stop_container()` function's `docker stop` command is idempotent — calling it on an already-stopped or nonexistent container is harmless.
- The `_background_procs` dictionary in `infra.py` is the single source of truth for active background processes. No other code path creates Docker subprocesses outside of `run_cmd` and `start_background_cmd`.
