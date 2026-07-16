# Research: Background Shell Agent

**Date**: 2026-06-30
**Feature**: [spec.md](./spec.md)

## 1. Background Process Pattern

**Decision**: Use `subprocess.Popen` with stdout/stderr merged to a tmp file, polled asynchronously.

**Rationale**:
- `subprocess.Popen` is non-blocking — does not stall the asyncio event loop
- Tmp file approach allows incremental reading with byte-offset tracking
- Merging stdout + stderr simplifies the decision model (single output stream)
- Existing `run_cmd()` in `infra.py` already uses `subprocess.run` (blocking) with Docker; `Popen` is the natural next step for non-blocking
- `asyncio.sleep()` provides cooperative polling without busy-waiting

**Alternatives considered**:
- `asyncio.create_subprocess_exec` — would also work but adds complexity with stream management; tmp file is simpler for incremental read with offset
- Pipe-based streaming (`proc.stdout.readline`) — risks buffer deadlocks; tmp file avoids this
- Background thread with `subprocess.run` — wasted thread, no benefit over Popen

## 2. Agent Decision Model

**Decision**: Use the existing code model (`get_code_model` → doubao-seed-2.0-code) for both task parsing and per-cycle decisions.

**Rationale**:
- Code model already configured and used by `coding_agent` and `capture_html_shot`
- Single model for both parse + decision simplifies dependency management
- The decision task (interpreting shell output) is well within the code model's capabilities
- Structured decision format (DONE/KILL/CONTINUE:N/NOTIFY:N) easy to parse

**Alternatives considered**:
- Mini model for decisions — cheaper but less capable at interpreting shell output semantics
- Regex/rule-based decisions — insufficient for varied shell command output patterns
- Advance model — more expensive, not needed for this classification task

## 3. Mid-Progress Notification Injection

**Decision**: Reuse existing `inject_agent_notification()` from `graph/nodes/ai.py` for both mid-progress NOTIFY and final results.

**Rationale**:
- `inject_agent_notification` already handles: injecting system messages into `human_queue`, starting new conversations when not chatting, and calling the notification callback
- Uses existing `NOTIFY_MARK` prefix convention for message routing
- The agent stays alive across NOTIFY calls — `inject_agent_notification` does not depend on agent lifecycle
- Zero changes needed to injection infrastructure

**Alternatives considered**:
- New injection channel — unnecessary duplication; `inject_agent_notification` already works for this pattern
- Direct bot message send — would bypass the conversation graph; messages would lack context

## 4. Docker Sandbox Integration

**Decision**: Reuse the existing Docker sandbox via `ensure_container_running()` and the same script.sh mechanism used by `run_cmd()`.

**Rationale**:
- Identical to existing `shell_executor` tool behavior
- `ensure_container_running()` is called before graph execution; container is already available
- Writing command to `script.sh` and running via `launch_image.sh --cmd` is the established pattern

**Alternatives considered**:
- Direct host execution — security risk; Docker sandbox is the project standard
- Separate container per background command — over-engineering; single container handles sequential execution

## 5. Timeout Enforcement

**Decision**: Track `elapsed` time in the poll loop; force-kill via `subprocess.Popen.terminate()` → `kill()` escalation.

**Rationale**:
- `elapsed += check_interval` is a close-enough approximation (off by at most one interval)
- `terminate()` (SIGTERM) → 5s wait → `kill()` (SIGKILL) is standard graceful-then-forceful escalation
- Timeout checked before code model call (saves an LLM round-trip when already timed out)

**Alternatives considered**:
- `asyncio.wait_for` wrapping the entire loop — doesn't allow partial cleanup before exit
- Signal-based timeout — more complex, same end result
