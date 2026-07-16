# Feature Specification: Agent State Prompt Injection

**Feature Branch**: `026-agent-state-injection`

**Created**: 2026-07-05

**Status**: Draft

**Input**: User description: "1. Remove check_agent tool (also remove the dedup gate of agent_allocate) 2. Inject the background agent states into system prompt of chat_agent (similar to the skill prompt injection)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - LLM Passively Sees Running Agent States (Priority: P1)

The chat_agent (LLM) always knows which background agents are currently running without needing to call a dedicated tool. Agent state information is present in the system prompt every turn, mirroring how skill availability is already injected via `build_skill_prompt()`.

**Why this priority**: This is the core value proposition — eliminating the tool-call round-trip for querying agent states. The LLM can make informed decisions about allocating new agents without the overhead of calling `check_agent`.

**Independent Test**: Can be fully tested by verifying that when a background agent is running, the system prompt passed to `create_agent()` in `ai_node` contains a `# 后台 Agent 状态` section listing the running agent's name, task, and elapsed time.

**Acceptance Scenarios**:

1. **Given** no agents are running, **When** `ai_node` constructs the system prompt, **Then** the prompt does NOT contain a "后台 Agent 状态" section.
2. **Given** `coding_agent` is running with task "fix login bug", **When** `ai_node` constructs the system prompt, **Then** the prompt contains a section listing `coding_agent` with its task description and elapsed time.
3. **Given** `background_shell` is running with task "npm install", **When** `ai_node` constructs the system prompt, **Then** the prompt contains a section listing `background_shell` with its task description and elapsed time.
4. **Given** multiple agents are running simultaneously, **When** `ai_node` constructs the system prompt, **Then** all running agents are listed in the injected section.

---

### User Story 2 - Agent Allocation No Longer Blocked by Dedup Gate (Priority: P2)

When the LLM calls `agent_allocate` for an agent that is already running, the call succeeds immediately instead of being refused with a "call check_agent first" message. The LLM has already seen the running state via the injected system prompt and can make an informed decision.

**Why this priority**: Removing the dedup gate simplifies the `agent_allocate` tool and eliminates a source of friction (the refusal message requiring a follow-up tool call). The LLM still has full visibility via the injected prompt.

**Independent Test**: Can be tested by calling `agent_allocate` for an agent that already has a running instance and verifying it returns a success response (the allocation proceeds normally).

**Acceptance Scenarios**:

1. **Given** `coding_agent` is already running, **When** the LLM calls `agent_allocate("coding_agent", "another task")`, **Then** the allocation is accepted (returns a success message), regardless of whether `check_agent` was previously called.
2. **Given** no agent is running, **When** the LLM calls `agent_allocate("coding_agent", "new task")`, **Then** the allocation succeeds as before (no regression).

---

### User Story 3 - Code Simplification (Priority: P3)

The `check_agent` tool function, `_check_agent_used` global flag, and associated dedup gate logic are removed from the codebase, reducing maintenance burden and eliminating dead code paths.

**Why this priority**: Code cleanliness is a quality-of-life improvement for developers. It reduces the surface area for bugs and makes the agent system easier to understand.

**Independent Test**: Can be tested by verifying that `check_agent` no longer appears in `tools.py`, `_check_agent_used` no longer exists, the dedup gate is absent from `agent_allocate`, and all existing tests pass.

**Acceptance Scenarios**:

1. **Given** the changes are applied, **When** searching for `check_agent` in `tools.py`, **Then** no results are found.
2. **Given** the changes are applied, **When** searching for `_check_agent_used` across the entire codebase, **Then** no results are found.
3. **Given** the changes are applied, **When** running the full test suite, **Then** all tests pass.

---

### Edge Cases

- What happens when `_AGENT_STATES` has never been populated (no agent ever allocated)? `build_agent_state_prompt()` returns empty string — no injection occurs, and the system prompt remains unchanged.
- What happens when an agent finishes between conversation turns? The prompt is rebuilt fresh each `ai_node` call, so the next turn reflects the updated state automatically.
- What happens when multiple instances of the same agent type are running? Each instance is listed as a separate bullet in the injected prompt, with its own task and elapsed time.
- What happens when `started_at` timestamp is missing from an agent instance? The elapsed time string is omitted (no crash), only name and task are shown.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a `build_agent_state_prompt()` function in `prompts.py` that returns a markdown-formatted string listing all currently running background agents, or an empty string when none are running.
- **FR-002**: The injected prompt MUST include each running agent's name, task description (truncated to 200 characters), and elapsed time since start (when `started_at` is available).
- **FR-003**: System MUST inject the agent state prompt into the chat_agent system prompt during `ai_node` execution, after skill prompt injection and before agent creation.
- **FR-004**: System MUST remove the `check_agent` tool function from `graph/tools.py`.
- **FR-005**: System MUST remove the `_check_agent_used` global flag declaration and its reset in `reset_capture_flag()`.
- **FR-006**: System MUST remove the deduplication gate from `agent_allocate` (the conditional block that checks `is_agent_running(agent_name) and not _check_agent_used`).
- **FR-007**: System MUST remove `check_agent` from the `chat_agent` tools list and import statement in `graph/nodes/ai.py`.
- **FR-008**: System MUST add `build_agent_state_prompt` to the imports from `prompts.py` in `ai.py`.
- **FR-009**: All existing tests MUST continue to pass after the changes, with test files (`tests/test_graph_nodes.py`, `tests/test_agent_allocate.py`) updated to remove references to `check_agent` and the dedup guard tests.
- **FR-010**: `build_agent_state_prompt()` MUST use lazy import for `get_running_instances` (import inside the function body) to avoid circular import between `prompts.py` and `graph/agents.py`.

### Key Entities

- **Agent Instance**: Represents a single execution of a background agent. Key attributes: `instance_id` (unique identifier string), `name` (agent type string, e.g., "coding_agent"), `status` (one of "running", "done", "idle"), `task` (natural language description of assigned work), `started_at` (Unix timestamp float), `result` (output text string when completed).
- **Agent State Prompt**: A markdown section injected into the chat_agent system prompt listing only running agent instances. Contains agent name, task description (first 200 characters), and elapsed time for each running instance.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The `check_agent` tool is fully removed — zero occurrences of `check_agent` or `_check_agent_used` in the production source code (under `hatsume/`).
- **SC-002**: Agent state information is available to the LLM without a tool call — the system prompt includes running agent states every turn when agents are active.
- **SC-003**: All existing tests pass after the changes with zero regressions (100% pass rate on `python -m pytest tests/`).
- **SC-004**: `agent_allocate` accepts allocations for already-running agents without requiring a prior `check_agent` call — the dedup refusal message no longer appears.

## Assumptions

- The `get_running_instances()` function in `graph/agents.py` correctly returns all agent instances with `status == "running"` and will continue to be maintained.
- The lazy import pattern (importing `get_running_instances` inside `build_agent_state_prompt()`) is an acceptable pattern for avoiding circular imports, consistent with other lazy imports in the codebase.
- `is_agent_running()` utility function in `agents.py` is retained (even though the dedup gate is removed) as it may have other uses in the agent system.
- The injected prompt format (markdown list with agent name, task, elapsed time) provides sufficient information for the LLM to make informed allocation decisions without needing additional detail like the full agent output.
