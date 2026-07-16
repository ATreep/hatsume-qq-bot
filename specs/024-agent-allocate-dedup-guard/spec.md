# Feature Specification: Agent Allocate Deduplication Guard

**Feature Branch**: `024-agent-allocate-dedup-guard`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "Update agent_allocate tool in graph/tools.py: If the chat agent tries to allocate a new agent that agent name was existed in the running agent list (Which can view by check agent function), Refuse and ask the LLM to invoke the check agent tool first. And then, the allocate agent tool detected the check agent tool has just been invoked. And then, the LLM can successfully allocate a new agent."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prevent Accidental Duplicate Agent Allocation (Priority: P1)

When the chat LLM attempts to allocate an agent whose name already has a running instance, the system refuses the allocation and instructs the LLM to first inspect the running agent state via the `check_agent` tool. This prevents silent duplicate agent creation and ensures the LLM makes an informed decision.

**Why this priority**: This is the core feature — without it, duplicate agents can be created unintentionally, wasting resources and causing confusion.

**Independent Test**: Can be fully tested by simulating a running agent instance and verifying that `agent_allocate` returns a refusal message containing "分配失败" and "check_agent".

**Acceptance Scenarios**:

1. **Given** an agent "coding_agent" has a running instance, **When** the LLM calls `agent_allocate(agent_name="coding_agent", ...)` without having called `check_agent` first, **Then** the system returns a refusal message instructing to call `check_agent` first.
2. **Given** an agent "coding_agent" has a running instance AND the LLM has just called `check_agent` in the same turn, **When** the LLM calls `agent_allocate(agent_name="coding_agent", ...)`, **Then** the allocation proceeds normally (the LLM made an informed decision).
3. **Given** an agent "coding_agent" has NO running instance, **When** the LLM calls `agent_allocate(agent_name="coding_agent", ...)`, **Then** the allocation proceeds normally (no guard needed).

---

### Edge Cases

- What happens when `_check_agent_used` flag is reset between turns? The flag is reset by `reset_capture_flag()` at the start of each `ai_node` invocation, ensuring per-turn scope. A stale `True` value cannot persist across conversation turns.
- What happens when multiple instances of the same agent type exist? `is_agent_running()` returns True if ANY instance has status "running", which is the correct behavior — the guard should fire regardless of which specific instance is running.
- What happens when the agent name is not in the registry? The existing "unknown agent" error fires before the dedup guard, so invalid names are rejected first.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `agent_allocate` tool MUST check whether an agent with the given name already has a running instance before dispatching a new one.
- **FR-002**: If a running instance exists AND the `check_agent` tool has NOT been called in the current turn, `agent_allocate` MUST refuse the allocation and return a message instructing the LLM to call `check_agent` first.
- **FR-003**: If a running instance exists AND the `check_agent` tool HAS been called in the current turn, `agent_allocate` MUST allow the allocation to proceed (the LLM has inspected the state and made an informed decision).
- **FR-004**: If no running instance exists, `agent_allocate` MUST proceed with allocation as before (no change to existing behavior).
- **FR-005**: The refusal message MUST explain why allocation was refused and what action the LLM should take (call `check_agent`).

### Key Entities

- **Agent Instance**: A running or completed execution of a registered agent, tracked in `_AGENT_STATES` with fields: `instance_id`, `name`, `status` (running/done/idle), `task`, `user_id`, `started_at`.
- **Check Agent Flag (`_check_agent_used`)**: A per-turn boolean flag set to `True` when `check_agent` is called, reset to `False` by `reset_capture_flag()` at the start of each AI node invocation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero duplicate agent allocations occur when the LLM has not inspected running state — every allocation attempt for an already-running agent is refused with the correct error message.
- **SC-002**: 100% of intentional re-allocations (after `check_agent` was called) proceed without blocking.
- **SC-003**: Existing agent allocation behavior (when no duplicate exists) is fully preserved with no regressions.
- **SC-004**: All existing tests in `test_agent_allocate.py` continue to pass.

## Assumptions

- The existing `is_agent_running()` function in `graph/agents.py` correctly identifies running agent instances.
- The existing `_check_agent_used` flag in `graph/tools.py` accurately tracks whether `check_agent` was called in the current turn.
- The `reset_capture_flag()` function is reliably called at the start of each AI node turn, ensuring the flag does not carry stale state between turns.
- Agent state tracking (`_AGENT_STATES`) is in-memory only and resets on process restart — this is acceptable given the current architecture.
