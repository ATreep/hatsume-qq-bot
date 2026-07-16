# Feature Specification: Agent Allocate Tool

**Feature Branch**: `015-agent-allocate-tool`

**Created**: 2026-06-26

**Status**: Draft

**Input**: User description: "Add an agent_allocate tool. This tool can invoke built-in agents in background, and notify the user (by `at` him) when the agent finishes. Web browser and video generation are both built-in agents. You should maintain a list of built-in agents in the `agents` source files, and the list should be injected into agent_allocate tool's description prompt. The input args of `agent_allocate` are notified_user_id (int) and agent_name (str). The output of this tool is the agent's output (not the chat_agent's output). You should add a special mark (including the notified user_id) when this tool returns. And in the ai_node, when detects the special mark, should use ai_answer_with_at to send message to human."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dispatch a Built-in Agent (Priority: P1)

A user in a group chat asks the bot to perform a task that requires a background agent (e.g., searching a website or generating a video). The bot dispatches the task to the appropriate built-in agent, which runs asynchronously in the background. When the agent finishes, the bot notifies the requesting user with an @-mention containing the agent's results, integrated naturally into the conversation flow.

**Why this priority**: This is the core feature — without it, the tool provides no value. All other stories depend on this working end-to-end.

**Independent Test**: Can be fully tested by sending a message that triggers the tool dispatch, verifying the agent executes in the background, and confirming the user receives an @-notification with the agent's output when it completes.

**Acceptance Scenarios**:

1. **Given** a user is in an active conversation with the bot, **When** the bot dispatches a "web_browser" agent to search a website, **Then** the agent executes in the background and, upon completion, the bot @-mentions the user with the search results integrated into the ongoing conversation.
2. **Given** a user is in an active conversation with the bot, **When** the bot dispatches a "generate_video" agent, **Then** the video is generated in the background and the bot @-notifies the user with the result when complete.
3. **Given** a user is NOT in an active conversation with the bot, **When** a background agent completes, **Then** a new conversation is started, the user is added as a conversation participant, and the bot @-mentions the user with the agent's result.

---

### User Story 2 - Discover Available Agents (Priority: P2)

When the bot is deciding which agent to dispatch, the tool's description provides an up-to-date list of all available built-in agents with their descriptions, so the bot can correctly match user requests to the appropriate agent.

**Why this priority**: Without discoverability, the bot cannot correctly route requests to agents. However, this is a description-level concern, not a separate user-facing command.

**Independent Test**: Can be tested by inspecting the tool's description output and verifying it contains the names and descriptions of all registered agents.

**Acceptance Scenarios**:

1. **Given** built-in agents "web_browser" and "generate_video" are registered, **When** the tool description is generated, **Then** it lists both agents with their descriptions.
2. **Given** a new built-in agent is registered, **When** the system starts, **Then** the tool description automatically includes the new agent without manual updates.

---

### User Story 3 - Handle Agent Errors Gracefully (Priority: P3)

When a dispatched agent fails to complete its task (e.g., network error, generation failure), the bot still notifies the user with a clear error message instead of silently dropping the result.

**Why this priority**: Error handling is important for reliability but does not block the core happy-path functionality.

**Independent Test**: Can be tested by dispatching an agent that is configured to fail and verifying the user receives an appropriate error notification.

**Acceptance Scenarios**:

1. **Given** a web_browser agent fails due to a network error, **When** the agent completes with a failure, **Then** the bot @-notifies the user that the agent task failed with a descriptive message.
2. **Given** a generate_video agent fails due to an API error, **When** the agent completes with a failure, **Then** the bot @-notifies the user with a failure message rather than remaining silent.

---

### Edge Cases

- What happens when an unknown agent name is provided? → The tool returns an error message listing available agent names; no background task is created.
- What happens when the agent finishes but the conversation has already ended? → The bot starts a new conversation, adds the notified user, and delivers the result.
- What happens when multiple agent results arrive in the same message batch? → The system uses the last notification mark to determine which user to @-mention.
- What happens when no conversation infrastructure is available (e.g., no active bot connection)? → The notification is dropped and an error is logged.
- What happens when the agent result is extremely long? → The full result is passed to the conversation flow; the existing message handling infrastructure handles truncation if needed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST maintain a registry of built-in agents, each with a unique name, human-readable description, and handler definition.
- **FR-002**: System MUST provide a tool (`agent_allocate`) that accepts a notified user identifier, an agent name, and a task description as inputs.
- **FR-003**: The tool MUST validate the agent name against the registry and return an error if the name is not found.
- **FR-004**: The tool MUST dispatch valid agent tasks to execute asynchronously in the background and return a confirmation message immediately.
- **FR-005**: Upon agent completion, system MUST inject the agent's result into the conversation flow prefixed with a special notification mark that includes the notified user's identifier.
- **FR-006**: The notification mark format MUST be: a fixed prefix (`__agent_notify__`), followed by the user identifier, followed by the agent name, separated by colons.
- **FR-007**: When the conversation system detects the notification mark in incoming messages, it MUST route the response through the @-mention notification channel instead of the standard reply channel.
- **FR-008**: When the system is in an active conversation, the notified user MUST be added to the conversation participants and the agent result MUST be injected into the existing message queue.
- **FR-009**: When the system is NOT in an active conversation, a new conversation MUST be started with the agent result as the initiating message.
- **FR-010**: The tool's description MUST dynamically include the list of all registered agents and their descriptions.
- **FR-011**: System MUST handle agent execution failures by injecting a failure message into the conversation flow (rather than silently dropping the result).

### Key Entities

- **Built-in Agent**: Has a unique name, a description for the tool prompt, and a handler that performs the agent's work. Currently: web_browser (searches websites and returns reports) and generate_video (generates short AI videos from text descriptions).
- **Agent Notification Mark**: A specially formatted string prefix (`__agent_notify__:<user_id>:<agent_name>`) that signals the conversation system to route the response via @-mention. The mark carries the target user's identifier and the originating agent's name.
- **Agent Result**: The text output produced by a built-in agent after completing its task. Injected into the conversation flow along with system instructions telling the LLM to relay the result to the user in natural language.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users receive @-notification of agent results within 5 seconds of agent completion (measured from agent handler return to notification delivery).
- **SC-002**: 100% of agent dispatches result in either a successful notification or a clear error message — no silent failures.
- **SC-003**: Unknown agent names produce an actionable error response within 100ms of the tool call.
- **SC-004**: Adding a new built-in agent requires changes in exactly one file (the agent registry) — the tool description and dispatch logic update automatically.
- **SC-005**: Agent results are delivered correctly both when a conversation is active (injected into existing flow) and when idle (new conversation started).

## Assumptions

- The existing conversation infrastructure (message queues, graph flow, @-mention sending) is stable and will be reused without modification beyond the detection and routing logic.
- Built-in agents are pre-defined and do not need to be dynamically loaded from external sources at runtime.
- The bot always has at least one valid message-sending channel available when agent notifications need to be delivered.
- Agent execution time varies (seconds to minutes) and does not block the main conversation flow.
- The "web_browser" and "generate_video" agent implementations already exist as standalone tools; this feature wraps them behind a unified dispatch interface.
- User identifiers are numeric QQ IDs passed through from the conversation context.
