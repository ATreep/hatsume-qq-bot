# Tasks: 合并转发消息解析与 JSON 化消息格式

**Input**: Design documents from `/specs/001-forward-message-support/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md

**Tests**: Included — the project uses pytest for testing.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

All paths relative to `hatsume/plugins/hatsume-plugin/` unless specified otherwise.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project configuration and baseline changes before feature work begins

- [ ] T001 Add `MAX_FORWARD_DEPTH: int = 3` constant to `hatsume/plugins/hatsume-plugin/config.py`
- [ ] T002 [P] Delete `generate_msg_template()` function from `hatsume/plugins/hatsume-plugin/utils.py`
- [ ] T003 [P] Create `message_to_json()` function in `hatsume/plugins/hatsume-plugin/utils.py` — accepts (user_name, user_id, content, msg_time, reply_to=None) and returns a dict with keys: type, time, user{id,name}, content, reply_to

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 Create `hatsume/plugins/hatsume-plugin/handlers/forward.py` with module skeleton: `has_forward_segment()`, `parse_forward_messages()`, `resolve_forward_content()` stubs
- [ ] T005 Implement `has_forward_segment(msg: Message) -> str | None` in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — iterate message segments, return forward_id if found
- [ ] T006 Implement `parse_forward_messages(bot, forward_id, depth=0) -> list[dict]` in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — call `bot.call_api("get_forward_msg", id=forward_id)`, iterate nodes, extract text content, return list of message dicts (flat, no nesting yet)
- [ ] T007 Add error handling to `parse_forward_messages()` in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — API failure returns placeholder message dict `{"user": {...}, "content": "(合并转发消息获取失败)"}`

**Checkpoint**: Foundation ready — forward detection and basic API parsing functional

---

## Phase 3: User Story 1 - 机器人读取单层合并转发消息 (Priority: P1) 🎯 MVP

**Goal**: Robot detects and reads single-layer merged forward messages, presenting content as JSON to LLM with correct sender attribution

**Independent Test**: Send a single-layer forward message (3 messages from 3 different users) in a test group; verify the bot's prompt contains JSON with correct type="forward", user identifies the forwarder, messages array has 3 entries with correct original senders

### Tests for User Story 1

- [ ] T008 [P] [US1] Write unit test for `has_forward_segment()` in `tests/test_forward.py` — test with forward segment present, absent, and multiple segments
- [ ] T009 [P] [US1] Write unit test for `parse_forward_messages()` in `tests/test_forward.py` — mock `bot.call_api`, verify correct JSON output for a flat forward message
- [ ] T010 [P] [US1] Write unit test for `message_to_json()` in `tests/test_pipeline_json.py` — verify output dict structure for plain message and reply message

### Implementation for User Story 1

- [ ] T011 [US1] Update `get_human_message()` in `hatsume/plugins/hatsume-plugin/handlers/pipeline.py` — replace `generate_msg_template()` call with `json.dumps(message_to_json(...), ensure_ascii=False)` for plain text messages
- [ ] T012 [US1] Update `get_human_message()` in `hatsume/plugins/hatsume-plugin/handlers/pipeline.py` — detect forward segments and call `resolve_forward_content()`, embed result as forward JSON in text content
- [ ] T013 [US1] Implement `resolve_forward_content()` in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — combine detection + parsing, return list of message dicts (for US1, flat only)
- [ ] T014 [US1] Update `get_human_message()` in `hatsume/plugins/hatsume-plugin/handlers/pipeline.py` — recursively collect all people from forward messages into `source_entry.people`
- [ ] T015 [US1] Update `get_human_message()` in `hatsume/plugins/hatsume-plugin/handlers/pipeline.py` — handle reply messages with JSON `reply_to` field (replace old template-based reply format)
- [ ] T016 [US1] Update system prompt examples in `hatsume/plugins/hatsume-plugin/prompts.py` — replace all `generate_msg_template()` example calls with JSON format examples (plain message, reply message, forward message)

**Checkpoint**: Single-layer forward messages fully functional. Bot understands forward content with correct sender attribution.

---

## Phase 4: User Story 2 - 机器人正确处理嵌套合并转发 (Priority: P2)

**Goal**: Recursively parse nested forward messages up to depth 3, with depth field tracking and truncation beyond limit

**Independent Test**: Construct a depth-2 nested forward; verify JSON output has correct depth fields and tree structure

### Tests for User Story 2

- [ ] T017 [P] [US2] Write test for nested forward parsing (depth 2) in `tests/test_forward.py` — mock nested API responses, verify depth fields on nested messages
- [ ] T018 [P] [US2] Write test for depth limit truncation (depth 4) in `tests/test_forward.py` — verify placeholder message at depth 4, no further API calls

### Implementation for User Story 2

- [ ] T019 [US2] Update `parse_forward_messages()` in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — add recursive detection: when a node's content contains a forward segment, recursively call `parse_forward_messages(child_id, depth+1)`
- [ ] T020 [US2] Add depth field to nested message dicts in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — each nested message/forward node gets `"depth": <current_depth>` field
- [ ] T021 [US2] Add depth limit enforcement in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — when `depth >= MAX_FORWARD_DEPTH`, return placeholder instead of recursing: `{"user": {...}, "content": "(嵌套层数过多，已省略)", "depth": depth}`
- [ ] T022 [US2] Handle picture segments in forward node content in `hatsume/plugins/hatsume-plugin/handlers/forward.py` — download and base64-encode images found in forward messages (reuse existing pipeline image handling logic or extract to shared helper)
- [ ] T023 [US2] Update source_entry people collection in `hatsume/plugins/hatsume-plugin/handlers/pipeline.py` — ensure people from nested forward nodes are also collected

**Checkpoint**: Nested forward messages up to depth 3 fully parsed. Depth limit enforced with placeholder.

---

## Phase 5: User Story 3 - LLM 以 JSON 格式输出回复 (Priority: P3)

**Goal**: LLM outputs JSON `{"message": "..."}`, parsed by Python before sending to QQ

**Independent Test**: Send a chat message and verify the internal LLM output is parsed as JSON; verify that unparseable output falls back to raw text

### Tests for User Story 3

- [ ] T024 [P] [US3] Write test for JSON output parsing in `tests/test_ai_json_output.py` — test valid `{"message": "..."}` parsing
- [ ] T025 [P] [US3] Write test for JSON parse failure fallback in `tests/test_ai_json_output.py` — test malformed JSON returns original text as message

### Implementation for User Story 3

- [ ] T026 [US3] Update system prompt in `hatsume/plugins/hatsume-plugin/prompts.py` — add LLM output format requirement: must output JSON `{"message": "..."}`, no other text
- [ ] T027 [US3] Add JSON output parsing logic in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — after receiving LLM response, `json.loads()` to extract `message` field
- [ ] T028 [US3] Add fallback for JSON parse failure in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — if `json.loads()` raises, use raw response text as message
- [ ] T029 [US3] Update `_memory_record_transcript` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — use parsed message text instead of raw LLM response for transcript recording

**Checkpoint**: LLM outputs JSON, parsed correctly, fallback works. Full JSON-in/JSON-out pipeline.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integration validation and cleanup

- [ ] T030 [P] Run all existing tests to verify no regressions: `python -m pytest tests/ -v`
- [ ] T031 [P] Update CLAUDE.md message format documentation — replace `generate_msg_template()` reference with JSON format description
- [ ] T032 Run quickstart.md manual validation scenarios
- [ ] T033 Code review: verify all `from __future__ import annotations` present in new files, type hints complete, Chinese strings consistent

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T002, T003) completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2) completion
- **User Story 2 (Phase 4)**: Depends on User Story 1 (Phase 3) — extends `parse_forward_messages()` and `resolve_forward_content()`
- **User Story 3 (Phase 5)**: Depends on Foundational (Phase 2) — independent of US1/US2, can run in parallel with them after Phase 2
- **Polish (Phase 6)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational — no dependencies on other stories
- **User Story 2 (P2)**: Depends on US1 (extends forward.py functions) — MUST follow US1
- **User Story 3 (P3)**: Can start after Foundational — independent of US1/US2

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Forward detection before API parsing
- API parsing before pipeline integration
- Pipeline integration before system prompt update
- Story complete before moving to next priority (for US1 to US2)

### Parallel Opportunities

- T002 and T003 can run in parallel (different files)
- T008, T009, T010 can run in parallel (different test files)
- T017 and T018 can run in parallel (different test functions)
- T024 and T025 can run in parallel (different test functions)
- T030 and T031 can run in parallel (different concerns)
- User Story 3 can run in parallel with User Story 1/2 (independent code paths)

---

## Parallel Example: User Story 1 Tests

```bash
# Launch all tests for User Story 1 together:
Task: "Write unit test for has_forward_segment() in tests/test_forward.py"
Task: "Write unit test for parse_forward_messages() in tests/test_forward.py"
Task: "Write unit test for message_to_json() in tests/test_pipeline_json.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T007)
3. Complete Phase 3: User Story 1 (T008-T016)
4. **STOP and VALIDATE**: Test single-layer forward message in real QQ group
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational -> Foundation ready
2. Add User Story 1 -> Test independently -> Single-layer forward works (MVP!)
3. Add User Story 2 -> Test independently -> Nested forward works
4. Add User Story 3 -> Test independently -> JSON-in/JSON-out complete
5. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001-T007)
2. Once Foundational is done:
   - Developer A: User Story 1 + User Story 2 (sequential, same file)
   - Developer B: User Story 3 (independent: prompts.py + ai.py)
3. Polish phase together

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- US2 builds on US1's forward.py — same developer should handle both
- US3 is independent of US1/US2 — can be developed in parallel
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
