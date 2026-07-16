# Feature Specification: Debug API Queue Message Full Detail

**Feature Branch**: `007-debug-api-queues-full-message`

**Created**: 2026-06-05

**Status**: Draft

**Input**: User description: "Change debug API GET /debug/api/queues and @debug-api-contract.md. You should return the full message content, sending time, sender nickname and qqid, and so on, referring to message_to_json."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View full message details in queue snapshot (Priority: P1)

As a developer debugging the Hatsume bot, I want to see the complete message content, sending time, sender nickname, and sender QQ ID for each message in the queue snapshots, so that I can trace what the bot is processing without guessing from 30-character text previews.

**Why this priority**: This is the core enhancement — the entire reason for this change. The current minimal preview provides insufficient information for effective debugging.

**Independent Test**: Can be fully tested by sending a message to the bot and then calling `GET /debug/api/queues` to verify the response contains full `type`, `time`, `user: {id, name}`, `content`, and `source_id` fields.

**Acceptance Scenarios**:

1. **Given** a message from user "小明" (QQ ID 111) saying "今天天气真好啊适合出去玩" at time "2026-06-05 22:30:00" is in the idle source queue, **When** a developer calls `GET /debug/api/queues`, **Then** the response includes a message object with `"source_id": "m...", "type": "message", "time": "2026-06-05 22:30:00", "user": {"id": 111, "name": "小明"}, "content": "今天天气真好啊适合出去玩"`.
2. **Given** the message has no reply-to context, **When** the developer views the queue, **Then** the `reply_to` field is `null` (not absent from the response).

---

### User Story 2 - View forwarded message content with nested structure (Priority: P2)

As a developer, I want to see the full nested structure of forwarded (合并转发) messages in the queue, so that I can inspect multi-message forward content that the bot is processing.

**Why this priority**: Forward messages are a critical data type that the bot handles, and debugging them requires visibility into the nested message array.

**Independent Test**: Can be tested by triggering a forward message, then calling `GET /debug/api/queues` and verifying the message has `"type": "forward"` and a `messages` array with nested message objects containing `type`, `time`, `user`, and `content`.

**Acceptance Scenarios**:

1. **Given** a forward message containing 3 sub-messages from different users is in the idle source queue, **When** a developer calls `GET /debug/api/queues`, **Then** the message object has `"type": "forward"` and a `"messages"` array where each element has `type`, `time`, `user: {id, name}`, `content` fields.
2. **Given** a forward message where some sub-messages include reply-to context, **When** the developer views the queue, **Then** those sub-messages include `reply_to` with the referenced message's user and content.

---

### User Story 3 - Graceful degradation on malformed data (Priority: P3)

As a developer, I want the debug API to remain functional even if the stored `text` field in a source entry is not valid JSON, so that a single malformed entry does not break the entire queue endpoint.

**Why this priority**: Resilience is important for a debug tool, but malformed `text` fields should be rare since they come from a controlled `json.dumps()` call path.

**Independent Test**: Can be tested by injecting a source entry with non-JSON `text`, calling `GET /debug/api/queues`, and verifying a 200 response with the raw text in the `content` field and sensible defaults for other fields.

**Acceptance Scenarios**:

1. **Given** a source entry has `"text": "not valid json"`, **When** a developer calls `GET /debug/api/queues`, **Then** the response returns 200 and the malformed entry appears as `{"source_id": "m...", "type": "message", "time": "", "user": {"id": 0, "name": "unknown"}, "content": "not valid json"}`.
2. **Given** a queue has 5 entries and 1 has malformed `text`, **When** the developer calls `GET /debug/api/queues`, **Then** all 5 entries are returned — the 4 valid ones with full detail and the 1 malformed one with fallback — and the overall status is 200.

---

### Edge Cases

- What happens when `text` field is missing entirely from a source entry? → Fallback: empty string as `content`.
- What happens when `text` is valid JSON but not in `message_to_json` format (e.g., a different JSON object)? → The parsed object is returned as-is with `source_id` appended; any missing expected fields (`type`, `time`, `user`) simply won't appear.
- What happens when a source queue is empty? → `"messages": []` as before; no change.
- What happens with the `limit` parameter? → Same behavior as before: controls how many entries per source queue are returned, applied before parsing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `/debug/api/queues` endpoint MUST return each message object with a `source_id` field containing the source entry's identifier.
- **FR-002**: The endpoint MUST parse the `text` field of each source entry as JSON and return the parsed fields (`type`, `time`, `user`, `content`, `reply_to`, `depth`) in the message object.
- **FR-003**: For messages of type `"forward"`, the endpoint MUST include the nested `messages` array with each sub-message fully expanded.
- **FR-004**: When the `text` field cannot be parsed as JSON, the endpoint MUST fall back to returning the raw text in the `content` field with `"type": "message"`, `"time": ""`, and `"user": {"id": 0, "name": "unknown"}`.
- **FR-005**: The endpoint MUST remove the old `content_preview` field and standalone `user_name` field — user identity is provided via the `user: {id, name}` object.
- **FR-006**: The existing `limit` query parameter behavior MUST be preserved (controls entries per source queue).
- **FR-007**: The 8-queue snapshot structure (4 message queues + 4 source queues) MUST remain unchanged.
- **FR-008**: The `docs/debug-api-contract.md` document MUST be updated to reflect the new QueueMessage schema, including updated TypeScript interfaces, JSON examples, and field descriptions.
- **FR-009**: Existing test cases in `tests/test_debug_api.py` MUST be updated to validate the new message fields and pass against the new response format.

### Key Entities

- **QueueMessage**: A single message in a queue snapshot. Key attributes: `source_id` (queue-level identifier from the source entry), plus all fields from the parsed `message_to_json`/`build_forward_json` output — `type` ("message" or "forward"), `time` (formatted timestamp), `user` (object with `id` and `name`), `content` (for regular messages), `messages` (for forward messages), `reply_to` (optional reply context), and `depth` (optional nesting depth).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Developers can identify the sender's nickname, QQ ID, and exact message sending time for any message in the queue without consulting any other data source.
- **SC-002**: Forward message content is fully inspectable — all nested sub-messages display with their own sender, time, and content.
- **SC-003**: A single malformed entry in a queue does not cause the `/debug/api/queues` endpoint to return an error response.
- **SC-004**: All 7 existing test assertions in `test_debug_api.py` that reference queue message fields pass after the schema change.

## Assumptions

- The `text` field in source entries is always a JSON string produced by `json.dumps(message_to_json(...))` or `json.dumps(build_forward_json(...))` — this is guaranteed by the current pipeline code.
- The debug API has no external consumers that depend on the old `content_preview` or standalone `user_name` fields — this is an internal developer tool.
- The `limit` parameter and 8-queue structure are not being changed — only the internal message representation is enhanced.
