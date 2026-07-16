# Feature Specification: Timer Graph Injection

**Feature Branch**: `017-timer-graph-injection`

**Created**: 2026-06-28

**Status**: Draft

**Input**: User description: "Update the timer trigger logic when the timer is on time. Do not create a new chat agent, but inject the timer prompt into the human queue. You can refer to the logic of Agent Allocate."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Timer Fires During Active Chat (Priority: P1)

A group member sets a timer ("remind me to drink water in 10 minutes"). When the timer fires, if the bot is already engaged in a conversation in that group, the timer prompt is immediately injected into the ongoing conversation. The bot seamlessly processes the timer alongside whatever is being discussed, responding to the timer creator naturally within the flow of conversation.

**Why this priority**: This is the primary change — replacing the standalone agent with graph injection. Timer responses must feel like natural conversation, not a separate bot response.

**Independent Test**: Set a short timer (1 minute) while the bot is actively chatting. Verify the bot responds to the timer within the same conversation flow, @-mentioning the creator, and the conversation continues normally afterward.

**Acceptance Scenarios**:

1. **Given** a group chat with an active bot conversation (bot is `is_chatting`), **When** a timer fires for user A with the prompt "remind me to stand up", **Then** the timer message is injected into the current conversation queue, and the bot responds within the ongoing conversation, @-mentioning user A.
2. **Given** a group chat with an active bot conversation, **When** a timer fires, **Then** the conversation does NOT end before the timer is processed — the bot continues the conversation after delivering the timer response.
3. **Given** a group chat with an active bot conversation, **When** a timer fires, **Then** the bot's response includes relevant context (who set the timer, recent chat context, the timer prompt) delivered in the bot's natural conversational style.

---

### User Story 2 - Timer Fires When Bot Is Idle (Priority: P2)

A group member sets a timer. When the timer fires and the bot is NOT currently engaged in any conversation in that group, the bot starts a new conversation to deliver the timer prompt. The timer creator is @-mentioned, and the conversation remains open for follow-up interaction.

**Why this priority**: This handles the idle case — timers must still work even when no conversation is happening. This mirrors the existing agent notification pattern (agent_allocate → start new conversation).

**Independent Test**: Wait for the bot to be idle in a group (no active conversation), set a 1-minute timer, and verify the bot starts a new conversation, @-mentions the creator, and remains available for follow-up.

**Acceptance Scenarios**:

1. **Given** no active bot conversation in the group (`is_chatting` is False), **When** a timer fires for user B with prompt "check the weather", **Then** the bot starts a new conversation, processes the timer prompt, and @-mentions user B in the response.
2. **Given** no active bot conversation, **When** the timer conversation finishes, **Then** the bot returns to idle state, ready for normal interactions.

---

### User Story 3 - Timer Integrates With Existing Conversation Flow (Priority: P3)

The timer injection system integrates seamlessly with the existing conversation management. Timer notifications share the same detection and routing infrastructure as agent notifications, ensuring consistent behavior. Multiple timers can fire in sequence without conflict, and timer messages are properly identified so the conversation never terminates prematurely when a timer is pending.

**Why this priority**: This is the infrastructure glue — ensuring timer injection doesn't break existing systems or create edge-case bugs.

**Independent Test**: Set multiple timers (1 min apart) and verify all are delivered in sequence. Set a timer during an agent_allocate session and verify both complete without interference.

**Acceptance Scenarios**:

1. **Given** multiple timers fire in quick succession, **When** the bot processes them, **Then** each timer is delivered in order, each with the correct @-mention for its respective creator.
2. **Given** a timer fires during a conversation, **When** the conversation would normally end (detect_node returns "yes"), **Then** the timer notification prevents premature ending, ensuring the timer is processed.
3. **Given** an agent_allocate and a timer both fire during the same conversation, **When** both are injected into the message queue, **Then** both are processed correctly without interference — each using its own notification mark.

---

### Edge Cases

- What happens when the timer creator cannot be found (e.g., user left the group)? The bot still delivers the timer message, but without an @-mention — just the plain text response.
- What happens when the timer fires but the group is unreachable? The timer is marked as fired and the error is logged; no message is delivered.
- What happens when a timer fires exactly during the `/clear` command which ends a conversation? The clear command ends the current conversation first; if a timer fires right after, it starts a fresh conversation.
- What happens when no timer callback is registered? The injection function logs an error and does not crash; the timer is still marked as fired.
- What happens with very long timer prompts (near the 500-char limit)? The full prompt is included in the injected message; no truncation needed since the graph handles arbitrary-length messages.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When a timer fires, the system MUST build a marked notification message containing the timer prompt, creator identity, system context, and recent chat history.
- **FR-002**: When a timer fires AND a conversation is currently active, the system MUST inject the timer message directly into the active conversation's message queue and register the timer creator as a conversation participant.
- **FR-003**: When a timer fires AND no conversation is active, the system MUST start a new conversation to deliver the timer prompt, mirroring the existing agent notification conversation start pattern.
- **FR-004**: The conversation end detection system MUST recognize timer-marked messages and route them to the response generation node — never ending the conversation when a timer notification is pending — using the same routing logic as agent notification messages.
- **FR-005**: The response generation node MUST detect timer marks in messages and, when present, deliver the bot's response with an @-mention directed at the timer creator.
- **FR-006**: The system MUST mark the timer trigger as "fired" after the injection call completes — timer delivery is handled asynchronously by the conversation graph.
- **FR-007**: The system MUST NOT create a standalone chat agent for timer execution. Timer prompts flow through the existing conversation graph using the same agent and tool set as normal conversations.
- **FR-008**: Timer injection MUST NOT interfere with agent notification injection — both use separate message identification prefixes and are detected independently.

### Key Entities

- **Timer Message**: A specially marked message containing the timer creator's user ID, system context, recent chat history, and the timer prompt. Used by the detection and response nodes to route and @-mention correctly. Distinct from agent notification messages.
- **Timer Conversation Callback**: A registered callback function that creates a new conversation when a timer fires and no conversation is active. Mirrors the existing agent notification callback pattern.
- **Timer Trigger Record**: Existing database record in timer_triggers — unchanged. Still holds trigger time, fired status, and job identifier. The only change is what happens after the trigger fires.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Timer responses are delivered within the existing conversation flow — users cannot distinguish timer responses from normal bot responses in terms of conversational style and continuity.
- **SC-002**: A timer that fires during an active conversation does not cause the conversation to end prematurely — the bot continues the conversation after delivering the timer response.
- **SC-003**: Timers that fire when no conversation is active start a new conversation and deliver the timer prompt within 30 seconds of the scheduled trigger time.
- **SC-004**: Concurrent timers (multiple timers firing within the same minute) are all delivered in sequence without message loss or crashes.
- **SC-005**: The codebase change removes at least 80 lines of standalone agent code and replaces it with 40 or fewer lines of graph injection code, eliminating the fragile tool isolation pattern.

## Assumptions

- The existing APScheduler integration continues to trigger timer jobs reliably — only the execution path after triggering changes.
- The timer storage layer and its schema remain unchanged.
- The conversation state and its message queues already support the injection pattern, as proven by the existing agent notification flow.
- Recent chat context (last 5 messages) continues to be fetched before injection, providing the same contextual richness as the current standalone agent.
- The timer system prompt builder remains functional and is included in the injected context.
- The same APScheduler misfire tolerance (5 minutes) applies — timers within the tolerance window are compensated on startup.
