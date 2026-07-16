# Feature Specification: Agent Notification Detection Skip

**Feature Branch**: `016-agent-notify-detect-skip`

**Created**: 2026-06-26

**Status**: Draft

**Input**: User description: "When chat_agent uses agent_allocate to spawn a new agent, do not execute chat_end_detect_node logic when this agent inject result to human_queue. In chat_end_detect_node, use a reusable function to detect agent notification mark in the last message to judge if there is a NOTIFY_MARK, if so, just response 'no'."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent Result Arrives During Active Conversation (Priority: P1)

When a user has an active conversation with the bot and a previously-dispatched agent (via agent_allocate) completes its task, the agent's result is injected into the conversation queue. The conversation must continue so the bot can relay the agent's result to the user — the chat end-detection logic must not terminate the conversation when an agent notification is waiting.

**Why this priority**: This is the core bug — without this fix, agent results can be silently lost when the detect node ends the conversation before the LLM processes the notification. Every agent_allocate invocation is affected.

**Independent Test**: Can be tested by simulating a conversation state where the last message contains an agent notification mark (`__agent_notify__`), verifying that the chat end-detection node returns "no" (continue) instead of running LLM-based detection.

**Acceptance Scenarios**:

1. **Given** an active conversation with 5+ messages, **When** the last message in the conversation state contains a `__agent_notify__:12345:web_browser` prefix, **Then** the chat end-detection node immediately returns "continue" without invoking any LLM model.
2. **Given** an active conversation with 5+ messages, **When** the last message is a normal user message without any agent notification mark, **Then** the chat end-detection node runs its normal LLM-based detection logic as before.

---

### User Story 2 - Agent Detection Logic is Reusable Across Nodes (Priority: P2)

The NOTIFY_MARK detection logic (scanning the last message for `__agent_notify__`) currently exists inline within the AI response node. This logic should be extracted into a standalone, reusable function that can be called from both the AI node and the chat end-detection node.

**Why this priority**: This is a code quality and maintainability requirement. It prevents duplication and ensures consistent behavior between the two nodes that need to detect agent notifications. Without this, future changes to the notification format could cause inconsistencies.

**Independent Test**: Can be tested by calling the extracted function directly with various message states (list content, string content, no notification mark) and verifying correct return values.

**Acceptance Scenarios**:

1. **Given** a conversation state where the last message content is a list containing a text part starting with `__agent_notify__:67890:generate_video`, **When** `detect_agent_notification(state)` is called, **Then** it returns the integer user ID `67890`.
2. **Given** a conversation state where the last message content is a plain string starting with `__agent_notify__:11111:web_browser`, **When** `detect_agent_notification(state)` is called, **Then** it returns the integer user ID `11111`.
3. **Given** a conversation state where the last message is a normal text message without any notification mark, **When** `detect_agent_notification(state)` is called, **Then** it returns `None`.

---

### Edge Cases

- What happens when the last message content is a non-text type (e.g., an image)? The detection function must return `None` gracefully — no crash, no false positive.
- What happens when `__agent_notify__` appears mid-message rather than at the start? It should be ignored — only the prefix position triggers recognition.
- What happens when the detection function returns `None` in the detect node? The existing detection logic runs unchanged — no regression.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a reusable function `detect_agent_notification` that scans the last message in a conversation state for the `__agent_notify__` notification mark prefix.
- **FR-002**: `detect_agent_notification` MUST return the notified user ID (integer) when a notification mark is found, or `None` when no mark is present.
- **FR-003**: `detect_agent_notification` MUST handle both list-type message content (list of content parts) and string-type message content.
- **FR-004**: The chat end-detection node MUST call `detect_agent_notification` on the current state before running any LLM-based detection logic.
- **FR-005**: When `detect_agent_notification` returns a non-None value, the chat end-detection node MUST immediately return "continue" (do not end the conversation).
- **FR-006**: The AI response node MUST use the same `detect_agent_notification` function to detect agent notifications, replacing its inline detection logic.
- **FR-007**: `detect_agent_notification` MUST be exported from the graph nodes package for external access.

### Key Entities

- **Agent Notification Mark (`__agent_notify__`)**: A prefix string embedded in message content to indicate that the message contains an agent's completed result. Format: `__agent_notify__:<user_id>:<agent_name>` followed by the result text.
- **Conversation State (`MessagesState`)**: LangGraph's message-based state dictionary containing an ordered list of messages exchanged between human and AI during a conversation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When an agent notification arrives during an active conversation, the conversation always continues to the AI response node (100% of cases, up from the current <100% due to random detection).
- **SC-002**: The AI node's agent notification detection behavior is unchanged after refactoring to use the extracted function — all existing agent notification flows work identically.
- **SC-003**: No regression in existing chat end-detection behavior for non-notification messages — the normal detection logic remains intact.
- **SC-004**: Unit tests achieve full coverage of the new `detect_agent_notification` function including both content types and the None case.

## Assumptions

- The `NOTIFY_MARK` constant (`__agent_notify__`) and its format remain unchanged.
- Agent notifications are always injected as the most recent message in the conversation state (via human_queue → human_node).
- The existing LangGraph graph structure (human → detect → chat_llm → human) remains unchanged.
- The test infrastructure (`_load_nodes_module()` with `MockMessage`) supports testing the new function and detect node behavior.
