# Feature Specification: Auto Response Mode

**Feature Branch**: `031-auto-response-mode`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "Referring auto create mode, create an auto response mode. Create a special `auto response` timer automatically when starting and finishing an old `auto response` timer. When this timer triggered, inject a prompt into humanqueue: (SYSTEM)从聊天记录与最近的历史记录中挑选一个话题进行一句话回复，不超过30字。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Periodic Lightweight Community Engagement (Priority: P1)

The bot automatically, on a recurring random interval (1–3 hours), picks a topic from recent group chat history and sends a short one-sentence reply (≤30 Chinese characters) to keep the group lively. Group members see natural, varied interjections that feel spontaneous rather than mechanical.

**Why this priority**: This is the core feature — without it nothing else matters. Delivers the primary user value: automated, low-effort community engagement that doesn't feel robotic.

**Independent Test**: Can be fully tested by observing the bot send a short topical reply in the target group within a 1–3 hour window, then send another one within the next 1–3 hour window, and verifying the replies are contextually relevant to recent chat history.

**Acceptance Scenarios**:

1. **Given** the bot is running and the auto-response timer is active, **When** the timer fires (random interval 1–3 hours), **Then** the bot reads recent chat history, picks a topic, and sends a one-sentence reply of ≤30 Chinese characters to the configured group.
2. **Given** a timer just fired and injected its prompt, **When** the injection is complete, **Then** a new timer is immediately scheduled with a random delay of 1–3 hours, ensuring continuous periodic engagement.
3. **Given** the timer fires at any hour of the day (including late night/early morning), **When** the trigger time arrives, **Then** the bot always executes the prompt — there is no time-of-day restriction.

---

### User Story 2 - System Resilience Across Restarts (Priority: P2)

If the bot restarts (crash, update, maintenance), the auto-response timer recovers automatically. A pending timer that hasn't fired yet is re-registered and fires at its original scheduled time. If no pending timer exists (the old one already fired), a fresh one is created immediately.

**Why this priority**: Without recovery, every restart breaks the engagement loop until an admin manually intervenes. This ensures the feature is reliable in production.

**Independent Test**: Can be tested by creating an auto-response timer, restarting the bot, and verifying either the existing pending timer resumes or a new one is created.

**Acceptance Scenarios**:

1. **Given** a pending auto-response timer exists in the database (not yet fired), **When** the bot restarts, **Then** the timer's APScheduler job is re-registered and fires at its originally scheduled time.
2. **Given** no pending auto-response timer exists (fired or never created), **When** the bot restarts, **Then** a fresh auto-response timer is created with a random 1–3 hour trigger time.

---

### User Story 3 - Admin Debug Trigger (Priority: P3)

An admin can manually trigger an auto-response execution for testing purposes via a `/autoresponse` command, without waiting for the next scheduled timer. The command injects the prompt immediately into the current group without modifying the database or affecting the scheduled timer.

**Why this priority**: Nice-to-have for debugging and demonstration. The feature works without it, but it's valuable for verification.

**Independent Test**: Admin sends `/autoresponse` in a group and observes the bot immediately inject the auto-response prompt and generate a short reply.

**Acceptance Scenarios**:

1. **Given** an admin sends `/autoresponse` in a group, **When** the command is processed, **Then** the auto-response prompt is immediately injected into the conversation graph for that group, without creating or modifying any database records.
2. **Given** a non-admin sends `/autoresponse`, **When** the command is processed, **Then** the command is ignored (no action taken).

---

### Edge Cases

- **What happens when the bot restarts with an expired pending trigger?** A fresh timer is created (the old expired trigger is cleaned up).
- **What happens if two auto-response tasks somehow exist?** The upsert operation deletes all old rows before creating a new one, guaranteeing at most one.
- **What happens when the LLM is unavailable when the timer fires?** The prompt is injected into the message queue; the graph handles unavailability through its normal error handling. The timer reschedules regardless.
- **What happens when a conversation is already active when the timer fires?** The prompt is appended to the human queue and processed after the current conversation turn completes.
- **What happens when no conversation is active?** A new conversation is started automatically.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST maintain exactly one auto-response timer at all times (singleton per deployment).
- **FR-002**: System MUST automatically create a new auto-response timer with a random delay of 1–3 hours immediately after the current timer fires (self-renewing).
- **FR-003**: System MUST inject a prompt into the conversation graph when the timer fires, instructing the LLM to pick a topic from recent chat history and reply in one sentence of ≤30 Chinese characters.
- **FR-004**: System MUST vary the prompt wording slightly across executions to avoid mechanically identical outputs.
- **FR-005**: System MUST operate the auto-response timer 24 hours a day with no time-of-day restrictions.
- **FR-006**: System MUST target a configurable group ID for auto-response messages, separate from the auto-create group configuration.
- **FR-007**: System MUST recover the auto-response timer on startup: re-register a pending timer's job, or create a fresh timer if none is pending.
- **FR-008**: System MUST provide an admin-only `/autoresponse` debug command that immediately injects the auto-response prompt without affecting the scheduled timer or database.
- **FR-009**: System MUST NOT @-mention any user when delivering auto-response messages (the message is from the bot itself, not on behalf of a user).
- **FR-010**: System MUST use a fire-and-forget rescheduling pattern — the next timer is created immediately upon trigger, without waiting for the LLM to finish processing.

### Key Entities *(include if feature involves data)*

- **Auto Response Task**: A special timer task with type `auto_response`. Has no user association (user_id=0, group_id=0 for storage, actual target group from config). Contains a prompt and a single pending trigger. Exactly one exists at any time.
- **Auto Response Trigger**: A single pending trigger associated with the auto-response task. Has a future `trigger_at` timestamp and a `fired` flag. Replaced (old deleted, new created) on each reschedule cycle.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The bot sends an auto-response message in the target group within 3.5 hours of the feature being enabled (first trigger window).
- **SC-002**: Subsequent auto-response messages appear at intervals between 1 and 3 hours from the previous message.
- **SC-003**: After a bot restart, auto-response functionality resumes within 2 minutes (scheduler recovery window) without manual intervention.
- **SC-004**: Auto-response messages are contextually relevant to recent chat history (topic is picked from actual recent messages, not random/generic).
- **SC-005**: The admin `/autoresponse` command triggers a response within 30 seconds of invocation.

## Assumptions

- The target group for auto-response is the same community that already uses the bot's other features (auto-create, timers, chat). The group ID is configured by the operator.
- The LLM has access to recent chat history through the existing conversation graph and message queue system, which provides sufficient context for topic selection.
- The existing APScheduler infrastructure (nonebot-plugin-apscheduler) is available and functioning — this feature adds a new scheduled task type to it.
- The existing `timer_tasks` database table with its `task_type` column supports adding a new type value without schema changes.
- The auto-response timer follows the same fire-and-forget rescheduling pattern as the existing auto-create timer, which has proven reliable in production.
- No user-facing on/off toggle is needed beyond the admin debug command — the feature runs continuously once deployed.
