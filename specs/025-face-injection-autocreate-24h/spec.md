# Feature Specification: Face Emoji Injection + Auto-Create 24h

**Feature Branch**: `025-face-injection-autocreate-24h`

**Created**: 2026-07-02

**Status**: Draft

**Input**: User description: "修改 ai_node 的表情 face 发送机制：不再单独 invoke 新的 model，而是给 chat_agent 的系统提示词注入提示词让 LLM 在输出最后插入 <hatsumeface>情绪名</hatsumeface> 标记来表示表情。程序用正则提取情绪名，随机选对应前缀图片发送，ai_answer 过滤掉标记。另外，移除 auto_create 的时间窗口限制（AUTO_CREATE_TIME_START/END），允许全天任何时间触发。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AI Sends Emotion-Appropriate Face Image (Priority: P1)

As a group chat participant, when I interact with the AI bot 初芽, she occasionally sends a facial expression image (表情) that matches the emotional tone of her reply — without any extra delay from a second LLM call.

**Why this priority**: The face expression feature is core to 初芽's personality expression in chat. Removing the extra LLM call reduces latency and API costs while delivering the same user-visible behavior.

**Independent Test**: Trigger a conversation with the bot in a group chat. When conditions allow (bot has not just sent an image, cooling period has passed), verify that the bot sometimes sends a face image after its text reply, and the face image's emotion category matches one of the available emotion types (开心, 生气, 害羞, etc.).

**Acceptance Scenarios**:

1. **Given** the bot has just replied to a user message and face-sending conditions are met (no image tools used, cooling period passed), **When** the LLM decides to express an emotion by including `<hatsumeface>开心</hatsumeface>` in its reply, **Then** the bot sends a randomly selected "开心" face image after the text reply, and the text shown to users does NOT contain the `<hatsumeface>` tag.

2. **Given** the bot has just replied and face-sending conditions are met, **When** the LLM chooses NOT to include any `<hatsumeface>` tag in its reply, **Then** only the text reply is sent — no face image, no tag visible to users.

3. **Given** the bot just used an image generation tool (generate_image or capture_html_shot) in the current turn, **When** the LLM's reply contains a `<hatsumeface>` tag, **Then** no face image is sent (face-sending is suppressed when an image was already generated).

4. **Given** the bot has sent a face image in the previous turn, **When** the next turn begins and face conditions are re-evaluated, **Then** the cooling counter prevents face injection until at least one turn has passed.

---

### User Story 2 - Bot Keeps Track of Its Past Face Choices (Priority: P2)

As the AI bot, when I include a face tag in my reply, that tag remains in my conversation history (graph state) so I can see what emotion I chose in previous turns. This helps me maintain consistent emotional expression across a conversation.

**Why this priority**: This is an internal behavior that improves long-conversation coherence. Users do not directly see this — they only benefit from more consistent bot behavior.

**Independent Test**: After a turn where the bot included `<hatsumeface>开心</hatsumeface>` in its reply, inspect the AIMessage stored in the graph state. The tag should be present in the message content. In the next turn, the LLM sees this tag in the history.

**Acceptance Scenarios**:

1. **Given** the bot's reply includes `<hatsumeface>害羞</hatsumeface>`, **When** the reply is stored as an AIMessage in the conversation graph state, **Then** the full text including the tag is preserved (not stripped).

2. **Given** the bot has sent a face in a previous turn, **When** the next user message triggers another AI reply, **Then** the LLM can see the previous face tag in the message history.

---

### User Story 3 - Auto-Create Triggers at Any Time of Day (Priority: P3)

As the bot operator, I want the auto-create (自主创作) feature to trigger at random intervals throughout the entire day, without being blocked during nighttime hours (22:00–07:00).

**Why this priority**: The auto-create feature produces creative content for the group. The current time window restriction (07:00–22:00) prevents content generation during hours when some group members are most active (night owls, international members). Removing this restriction allows more flexible scheduling.

**Independent Test**: Observe the auto-create trigger schedule over multiple days. Trigger times should be evenly distributed across all 24 hours, with no clustering or gaps at the old boundary hours.

**Acceptance Scenarios**:

1. **Given** the bot's auto-create timer just fired at 23:30 (previously blocked), **When** the next auto-create trigger is scheduled, **Then** the next trigger time is randomly placed 4–6 hours in the future (around 03:30–05:30), without being clamped or wrapped to a "valid" hour window.

2. **Given** the auto-create fired at 05:00, **When** the next trigger time is calculated, **Then** it falls naturally around 09:00–11:00 (4–6 hours later), without unnecessary hour adjustment.

3. **Given** the auto-create scheduler is restarted (bot reboot), **When** a new auto-create task is created, **Then** the trigger time is set to a random time 4–6 hours from now, regardless of the current hour.

---

### Edge Cases

- **No face files on disk**: If the `data/hatsume-plugin/faces/` directory is empty or missing, the face injection prompt is not appended to the system prompt, and the LLM has no knowledge of the face feature.
- **LLM uses an unknown emotion name**: If the LLM outputs `<hatsumeface>兴奋</hatsumeface>` but "兴奋" does not match any face file prefix, no face image is sent (silent skip).
- **Multiple face tags in one reply**: Only the first `<hatsumeface>...</hatsumeface>` match is used for face selection; all tags are stripped from user-facing text.
- **Malformed tag (unclosed, empty)**: Regex does not match — treated as no tag, normal text sent.
- **Tag appears mid-message vs. at the end**: The tag is extracted and stripped regardless of position; face image is still sent after the text.
- **Auto-create trigger time during DST transition**: The UTC+8 timezone is consistently used; DST does not apply to UTC+8.

## Requirements *(mandatory)*

### Functional Requirements

**Face Injection**

- **FR-001**: The system MUST evaluate face-sending gate conditions (cooling counter, random probability, image-tool usage) BEFORE the main chat agent is created for a turn.
- **FR-002**: When gate conditions pass, the system MUST dynamically scan available face image files, extract emotion names from their prefixes (text before first `_`), and inject a prompt section listing those emotions into the chat agent's system prompt.
- **FR-003**: When gate conditions do NOT pass, the system MUST NOT inject any face-related prompt into the system prompt.
- **FR-004**: The injected prompt MUST instruct the LLM to append `<hatsumeface>emotion_name</hatsumeface>` at the end of its reply when it wants to express an emotion, and to omit the tag entirely when no face is desired.
- **FR-005**: After receiving the LLM's reply, the system MUST extract any `<hatsumeface>` tag via regex and strip all such tags from the text before sending it to users.
- **FR-006**: The system MUST preserve the original text (including face tags) in the AIMessage stored to the conversation graph state.
- **FR-007**: If the extracted emotion name matches a known face file prefix, the system MUST randomly select one image file with that prefix, read it from disk, encode it as base64, and send it as a face image.
- **FR-008**: The face image sending logic (file reading, base64 encoding, MessageSegment construction) MUST remain identical to the current implementation — only the trigger mechanism changes.

**Auto-Create Timer**

- **FR-009**: The auto-create next-trigger calculation MUST generate a random time 4–6 hours in the future without clamping to any specific hour window.
- **FR-010**: The `AUTO_CREATE_TIME_START` and `AUTO_CREATE_TIME_END` configuration constants MUST be removed.

### Key Entities

- **Face Image File**: Stored in `data/hatsume-plugin/faces/` with naming convention `{emotion}_{index}.{ext}`. The emotion prefix (before first `_`) maps to the tag value the LLM outputs.
- **Face Tag**: XML-like marker `<hatsumeface>emotion</hatsumeface>` embedded in the LLM's text reply. Extracted by regex, stripped from user-facing output, preserved in graph state.
- **Auto-Create Trigger**: A scheduled task that fires every 4–6 hours (random interval) to prompt the bot to generate creative content autonomously.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Face images are sent within the same conversation turn as the text reply — no additional LLM round-trip is incurred for face selection.
- **SC-002**: The `<hatsumeface>` tag is never visible to users in group chat messages.
- **SC-003**: Face-sending frequency remains comparable to current behavior (approximately every 2–4 turns when no image tools are used).
- **SC-004**: Auto-create triggers occur at all hours of the day, with no hour-of-day gaps in the trigger time distribution over a 7-day period.
- **SC-005**: All existing tests pass without regression after the changes.

## Assumptions

- The face image file naming convention (`{emotion}_{index}.{ext}`) remains unchanged.
- The gate conditions (cooling counter, 50% random probability, image-tool exclusion) remain unchanged from the current implementation.
- The auto-create random interval (4–6 hours) remains unchanged; only the hour-window clamping is removed.
- The `data/hatsume-plugin/faces/` directory is managed externally (images added/removed by the bot operator); the system only reads from it.
- The regex pattern `<hatsumeface>(.*?)</hatsumeface>` is sufficient for tag extraction — no nested tags or attributes are expected.
