# Feature Specification: Auto Create Timer

**Feature Branch**: `020-auto-create-timer`

**Created**: 2026-06-29

**Status**: Draft

**Input**: User description: "Remove the auto respond feature and add a special 'auto create' timer task. This timer task autonomously executes creative tasks using all available bot capabilities (viewing GitHub trending repos, creating repos, painting pictures, starring repos from conversations, etc.). The special timer self-renews daily at a random time between 7:00 AM and 10:00 PM. Only one special timer task exists at any time. On bot startup or after the special timer fires, the old task is removed and a new one is created for the next day."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bot autonomously performs daily creative tasks (Priority: P1)

As a group member, I want the bot to autonomously do something creative and interesting each day, so the group feels lively and I get exposed to new ideas, repositories, and artwork without anyone needing to prompt the bot.

**Why this priority**: This is the core feature — the autonomous creative timer is the entire reason for this change. Without it, the bot just reacts to user commands; with it, the bot has its own "personality" and initiative.

**Independent Test**: Can be fully tested by triggering the `/autocreate` debug command and observing the bot's creative output in the debug group. Delivers value by demonstrating the bot's autonomous creative capability.

**Acceptance Scenarios**:

1. **Given** the bot is running and no auto-create task exists, **When** the bot starts up, **Then** exactly one auto-create timer task is scheduled for a random time tomorrow between 7:00 AM and 10:00 PM.
2. **Given** an auto-create timer fires at its scheduled time, **When** the timer triggers, **Then** the bot executes a creative task (using its available capabilities), posts the results to the configured group without @-mentioning any specific user, and immediately schedules a new auto-create task for a random time the next day.
3. **Given** a group member uses the `/autocreate` command, **When** the command executes, **Then** the bot immediately performs a creative task and posts the result to the debug group, without modifying the scheduled timer database.

---

### User Story 2 - Bot output is engaging and interactive (Priority: P2)

As a group member, I want the bot's creative output to be interesting, personal, and invite interaction, so I feel connected to the bot and want to engage with its creations.

**Why this priority**: The quality of the bot's output determines whether group members actually engage with the feature. A bot that just dumps information is boring; a bot that shares its motivation and invites interaction creates community.

**Independent Test**: Inspect the bot's creative output after an auto-create trigger. Verify it includes: (1) why the bot chose this task, (2) a clear presentation of what was created, and (3) a call-to-action inviting group members to interact.

**Acceptance Scenarios**:

1. **Given** the bot completes a creative task, **When** it posts the result, **Then** the output includes an explanation of why it chose that particular task (motivation).
2. **Given** the bot posts a creative result, **When** viewing the output, **Then** the result is clearly presented (repository link, image description, research summary, etc.).
3. **Given** the bot posts a creative result, **When** reading the output, **Then** it includes an invitation for group members to interact (e.g., star a repo, share their thoughts, join a discussion).

---

### User Story 3 - Bot no longer auto-responds to idle chat (Priority: P1)

As a group member, I want the bot to stop spontaneously responding to group chatter when nobody @-mentions it, so the bot only speaks when explicitly addressed or during its scheduled creative time.

**Why this priority**: Removing the auto-respond feature is a prerequisite for the new behavior model. The old auto-respond could feel intrusive; replacing it with scheduled creative output gives the bot a more deliberate and charming presence.

**Independent Test**: Send multiple messages in the group without @-mentioning the bot. Verify that the bot does NOT spontaneously start a conversation, even when the idle message queue fills up. (The idle queue still gets flushed to auxiliary storage, but no auto-response is generated.)

**Acceptance Scenarios**:

1. **Given** the bot is running and no one has @-mentioned it, **When** 50+ messages accumulate in the group without any @-mention, **Then** the bot does NOT send any message to the group (no auto-response).
2. **Given** the bot is running, **When** someone @-mentions the bot, **Then** the bot responds normally (manual triggering still works).

---

### Edge Cases

- What happens if the bot restarts multiple times in a day? → Each restart deletes the old auto-create task and creates a fresh one for tomorrow. No duplicate tasks accumulate.
- What happens if the auto-create timer fires while the bot is already engaged in a conversation? → The creative task is injected into the conversation queue and processed when the current conversation finishes.
- What happens if the LLM execution fails (API error, timeout)? → The timer trigger is marked as fired, and the reschedule for tomorrow already happened (fire-and-forget pattern). The next day's task is not affected.
- What happens if someone runs `/autocreate` while a scheduled auto-create is pending? → The debug command fires immediately in the debug group. The scheduled task remains unchanged and will still fire at its planned time.
- What happens if the database already has timer tasks from a previous version (before this feature)? → Existing tasks are assigned a default type of "normal" and are unaffected. The first startup purges any "auto_create" type rows and creates exactly one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST maintain exactly one special auto-create timer task at all times while running.
- **FR-002**: System MUST, on startup, delete any existing auto-create timer tasks and create a fresh one scheduled for a random time the next day between 7:00 AM and 10:00 PM (local time).
- **FR-003**: System MUST, immediately after an auto-create timer fires, delete the old task and create a new one scheduled for a random time the next day between 7:00 AM and 10:00 PM.
- **FR-004**: System MUST distinguish auto-create timer tasks from user-created timer tasks in persistent storage.
- **FR-005**: System MUST execute auto-create tasks without @-mentioning or notifying any specific user.
- **FR-006**: System MUST post auto-create execution results to the configured target group.
- **FR-007**: System MUST provide a `/autocreate` debug command that immediately triggers a creative execution to a designated debug group without modifying the timer database.
- **FR-008**: System MUST remove the automatic idle-chat response behavior — the bot must not spontaneously start conversations based on accumulated group messages.
- **FR-009**: System MUST still respond normally when explicitly @-mentioned by users.
- **FR-010**: The auto-create prompt MUST instruct the bot to: (a) explain its motivation for the chosen creative task, (b) present the results clearly, and (c) invite group members to interact with the creation.
- **FR-011**: The auto-create prompt MUST suggest a diverse range of possible creative activities including but not limited to: exploring trending repositories, forking and modifying repositories, generating AI artwork, starring repositories mentioned in conversations, and researching interesting technical topics.

### Key Entities

- **Timer Task**: Represents a scheduled action. Has a type (normal or auto_create), associated group, optional associated user, prompt content, and creation/update timestamps. Auto-create tasks have no associated user.
- **Timer Trigger**: Represents a specific firing time for a timer task. Has a scheduled timestamp, a fired/unfired status, and a scheduler job reference. Auto-create triggers are fire-and-forget: marked fired immediately upon execution, with reschedule happening independently.
- **Creative Execution**: The result of an auto-create timer firing. The bot autonomously decides what to do, executes it using available capabilities, and produces visible output in the group.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After bot startup, exactly one auto-create task exists in the system, scheduled for tomorrow between 7:00 AM and 10:00 PM.
- **SC-002**: After an auto-create timer fires, a new auto-create task is scheduled for the next day within 5 seconds (the reschedule happens immediately, not waiting for LLM completion).
- **SC-003**: No more than one auto-create task ever exists in the database at any point in time.
- **SC-004**: The bot does not send any unsolicited messages to the group when 50+ messages accumulate without @-mentions (auto-respond is fully removed).
- **SC-005**: The `/autocreate` command produces visible creative output in the debug group within 60 seconds of invocation.
- **SC-006**: 100% of auto-create outputs include all three required elements: motivation, results presentation, and interaction call-to-action.

## Assumptions

- The bot has access to a stable LLM API for generating creative content.
- The configured target group is active and accessible to the bot.
- The debug group exists and is accessible for `/autocreate` testing.
- The APScheduler plugin is installed and functioning.
- The system timezone is UTC+8 (Asia/Shanghai) for trigger time calculation.
- Existing timer tasks created before this feature use a default type of "normal" and are unaffected.
- The bot's available tools (web search, image generation, shell execution) are sufficient for creative task execution.
