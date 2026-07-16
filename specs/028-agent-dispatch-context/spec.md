# Feature Specification: Agent Dispatch Context

**Feature Branch**: `028-agent-dispatch-context`

**Created**: 2026-07-06

**Status**: Draft

**Input**: User description: "Add a new argument named 'context' to agent_allocate (renamed to agent_dispatch). `context` is a str type argument, requiring chat_agent passes the background story context when dispatching a new agent. Context should include: the background that users just chatted about, the requirements or tasks that user published and why you need to dispatch an agent to finish it. When agent finishes and injects to human_queue, also add context to the injection message."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Chat Agent Dispatches Subagent with Context (Priority: P1)

When a user is chatting with the bot and asks it to perform a complex task (e.g., refactor code, run a long shell command), the main chat agent dispatches a subagent and records the conversation context — what was being discussed, what the user requested, and why a subagent is needed. When the subagent finishes, the context is injected back into the conversation so the chat agent immediately understands why the subagent was dispatched without re-reading the full chat history.

**Why this priority**: This is the core behavior — without it, the entire feature has no value. It directly improves conversation continuity after subagent handoffs.

**Independent Test**: Can be tested by triggering a subagent dispatch with known context, then verifying the injected notification message contains that context in the expected format.

**Acceptance Scenarios**:

1. **Given** a user is chatting with the bot about performance optimization, **When** the chat agent dispatches a `coding_agent` with the context "用户讨论网站性能问题，需要优化 webpack 配置", **Then** the agent instance state records this context string.
2. **Given** a subagent has completed its task and its instance state contains a `context` string, **When** `inject_agent_notification` is called, **Then** the injected message contains `📋 派发背景：<context>` immediately after the SYSTEM header line.
3. **Given** the conversation was idle when the subagent was dispatched, **When** the subagent completes and triggers a new conversation via the callback, **Then** the injected notification message still contains the context string.

---

### User Story 2 - Tool Renamed for Semantic Clarity (Priority: P2)

The LLM tool name `agent_allocate` is renamed to `agent_dispatch` across the entire project — code, prompts, tests, and documentation. The new name better describes what the tool does (dispatching an agent to execute a task) versus the old name (which implied resource allocation).

**Why this priority**: While important for clarity and long-term maintainability, this is a mechanical rename that doesn't change behavior. The context feature (P1) is the actual value-add.

**Independent Test**: Can be tested by running `grep -r "agent_allocate"` across the project (excluding `.git/` and historical spec docs) and confirming zero results.

**Acceptance Scenarios**:

1. **Given** the rename is complete, **When** the LLM wants to dispatch a subagent, **Then** it uses the tool named `agent_dispatch`.
2. **Given** all project files are updated, **When** running `grep -r "agent_allocate"` on source files, **Then** no references remain.
3. **Given** existing tests reference `agent_allocate`, **When** tests are updated, **Then** all tests pass with the new name `agent_dispatch`.

---

### User Story 3 - Conversation Continuity After Agent Completion (Priority: P3)

Group members see clearer agent completion notifications. When the bot announces a subagent has finished, the context line helps users recall what was happening before the subagent was dispatched, even if the subagent ran for a long time.

**Why this priority**: This is a quality-of-life improvement for group chat participants. The primary beneficiary is the LLM itself (P1), but human-readable context is a nice bonus.

**Independent Test**: Can be tested by triggering a subagent dispatch, waiting for completion, and inspecting the group message to verify the context line appears.

**Acceptance Scenarios**:

1. **Given** a subagent completed after 5 minutes of background work, **When** the bot sends the completion notification to the group, **Then** the message includes a context summary so users know what this result relates to.

---

### Edge Cases

- **Empty context**: If the chat agent dispatches a subagent with an empty `context` string, the `📋 派发背景：` line is omitted entirely from the notification (keeping the message clean).
- **Very long context**: Context strings over 500 characters are preserved verbatim — the LLM context window can handle them, and truncation would lose valuable detail.
- **Multiple sequential subagents**: Each subagent dispatch stores its own context independently in the instance state. When they complete, each notification carries its own context without cross-contamination.
- **Subagent dispatched during idle**: When the bot is not actively chatting and a subagent result triggers a new conversation, context is still embedded in the notification via `start_conversation_cb`.
- **Subagent fails**: If the handler fails, the error result is still injected with context, so the chat agent understands which task failed and why it was attempted.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The subagent dispatch tool MUST accept a `context` parameter of type `str` that describes the conversation background, user requirements, and reason for dispatch.
- **FR-002**: The context string MUST be stored in the agent instance state at the time of dispatch.
- **FR-003**: When a subagent completes and its result is injected into the conversation, the context string MUST be embedded in the injection message in the format `📋 派发背景：<context>` immediately after the SYSTEM header.
- **FR-004**: If the context string is empty, the context line MUST be omitted from the injection message (no dangling header).
- **FR-005**: The dispatch tool MUST be named `agent_dispatch` (renamed from `agent_allocate`).
- **FR-006**: All references to `agent_allocate` in project source code, tests, prompts, and documentation MUST be updated to `agent_dispatch`.
- **FR-007**: The renamed tool MUST appear in the main chat agent's bound tools list so the LLM can invoke it.
- **FR-008**: The chat agent's system prompt MUST reference the new tool name `agent_dispatch` in any guidance text.

### Key Entities

- **Agent Instance State**: In-memory record tracking a dispatched subagent. Key attributes include: `name` (agent type), `instance_id` (unique identifier), `status` (running/done), `task` (task description), `context` (NEW — background story), `result` (completion output).
- **Agent Notification Message**: The message injected into `human_queue` when a subagent completes. Contains: agent name, context line (NEW), task description, and execution result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All subagent dispatch operations include a non-empty context string in the agent instance state.
- **SC-002**: Subagent completion notifications consistently include the context line when context was provided at dispatch time.
- **SC-003**: Zero references to `agent_allocate` remain in active project source files (code, tests, prompts).
- **SC-004**: Existing test suite passes with all renamed references and new context parameter.
- **SC-005**: The chat agent, when prompted to dispatch a subagent, correctly uses the `agent_dispatch` tool with the `context` argument filled in.

## Assumptions

- The chat agent (LLM) will reliably populate the `context` parameter based on the system prompt instructions describing the tool.
- Agent handlers (`_run_coding_agent`, `_run_background_shell`) do not need access to context during execution — context is only needed at dispatch time (for state tracking) and completion time (for injection).
- The in-memory agent state storage is sufficient; no database persistence is needed for context.
- The `📋 派发背景：` prefix is appropriate for the target audience (Chinese-speaking group chat users and a Chinese-prompted LLM).
- Historical spec documents under `specs/024-agent-allocate-*` are immutable records and should NOT be renamed.
