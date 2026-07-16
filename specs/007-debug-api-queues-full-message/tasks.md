# Tasks: Debug API Queue Message Full Detail

**Input**: Design documents from `/specs/007-debug-api-queues-full-message/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Test updates are included — the existing test file (`tests/test_debug_api.py`) must match the new response schema.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

This is a single Python project — paths are relative to repo root.

---

## Phase 1: Foundational

**Purpose**: No new setup needed — the debug API server, queue infrastructure, and test harness already exist from spec 005.

**Checkpoint**: Foundation ready — all infrastructure is already in place.

---

## Phase 2: User Story 1 - Core message parsing (Priority: P1) 🎯 MVP

**Goal**: Parse source entry `text` as JSON and return full `message_to_json` fields (`type`, `time`, `user: {id, name}`, `content`, `reply_to`, `depth`) plus `source_id`.

**Independent Test**: Send a message to the bot, call `GET /debug/api/queues`, verify response includes `type`, `time`, `user.id`, `user.name`, `content`, `source_id`.

### Implementation for User Story 1

- [ ] T001 [US1] Rewrite message extraction in `collect_queues()` to parse `text` field as JSON at `hatsume/plugins/hatsume-plugin/debug.py:113-154`
- [ ] T002 [US1] Append `source_id` field from source entry to the parsed message dict in `hatsume/plugins/hatsume-plugin/debug.py`
- [ ] T003 [US1] Remove old `_truncate()` usage, `content_preview`, and standalone `user_name` from message objects in `hatsume/plugins/hatsume-plugin/debug.py`
- [ ] T004 [US1] Update `test_queue_message_has_required_fields` in `tests/test_debug_api.py:243-263` to assert new fields (`type`, `time`, `user.id`, `user.name`, `content`, `source_id`)
- [ ] T005 [US1] Update other queue-related test assertions in `tests/test_debug_api.py` (test_queues_endpoint_returns_200, test_queues_respects_limit_param, test_queue_snapshot_structure) to match new message format

**Checkpoint**: Core parsing works — regular messages show full detail. `GET /debug/api/queues` returns 200 with new fields.

---

## Phase 3: User Story 2 - Forward message nested expansion (Priority: P2)

**Goal**: Forward messages (`type: "forward"`) are returned with their `messages` array fully expanded, each sub-message containing `type`, `time`, `user`, `content`.

**Independent Test**: Add a forward-format source entry to the test queue, call `GET /debug/api/queues`, verify `type: "forward"` and `messages` array with sub-message fields.

### Implementation for User Story 2

- [ ] T006 [US2] Add test for forward message structure in `tests/test_debug_api.py` — inject a source entry with `text` containing `build_forward_json()` output and verify `type: "forward"` and nested `messages` array
- [ ] T007 [US2] Verify forward message expansion passes by running `pytest tests/test_debug_api.py -k "queues" -v`

**Checkpoint**: Forward messages are fully inspectable — nested `messages` array visible in response.

---

## Phase 4: User Story 3 - JSON parse failure fallback (Priority: P3)

**Goal**: Malformed `text` fields do not break the endpoint; fallback returns raw text as `content` with defaults.

**Independent Test**: Inject a source entry with non-JSON `text`, call `GET /debug/api/queues`, verify 200 response with fallback structure.

### Implementation for User Story 3

- [ ] T008 [US3] Add `try/except json.JSONDecodeError` fallback in `collect_queues()` returning `{"type": "message", "time": "", "user": {"id": 0, "name": "unknown"}, "content": raw_text}` in `hatsume/plugins/hatsume-plugin/debug.py`
- [ ] T009 [US3] Add test for JSON parse failure fallback in `tests/test_debug_api.py` — inject source entry with `"text": "not valid json"` and verify 200 response with fallback defaults
- [ ] T010 [US3] Add test for mixed valid/malformed queue in `tests/test_debug_api.py` — 5 entries, 1 malformed, verify all 5 returned

**Checkpoint**: Graceful degradation works — malformed entries never cause 500 errors.

---

## Phase 5: Polish & Documentation

**Purpose**: Update contract documentation and run final validation.

- [ ] T011 Update Section 5 (`GET /debug/api/queues`) QueueMessage schema in `docs/debug-api-contract.md:162-209` — replace old `QueueMessage` interface with new fields, update JSON example
- [ ] T012 Run full test suite: `pytest tests/test_debug_api.py -v` — all tests pass
- [ ] T013 Run `pytest tests/test_debug_api.py::TestAllEndpointsReturn200 -v` — all 7 endpoints still return 200
- [ ] T014 Run `pytest tests/test_debug_api.py::TestJsonEscaping -v` — JSON escaping still works with new format

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Foundational)**: No dependencies — already in place
- **US1 (P1)**: Can start immediately — modifies existing `collect_queues()`
- **US2 (P2)**: Depends on US1 (forward expansion is handled automatically by JSON parsing, but test needs the new structure in place)
- **US3 (P3)**: Depends on US1 (fallback wraps the JSON parse logic added in T001)
- **Polish (Phase 5)**: Depends on all user stories

### Within Each User Story

- US1: T001 → T002 → T003 → (T004, T005) ← T004/T005 can be parallel
- US2: T006 → T007
- US3: T008 → (T009, T010) ← T009/T010 can be parallel
- Polish: T011 → (T012, T013, T014) ← all can be parallel after T011

### Parallel Opportunities

- T004 and T005 within US1 can run in parallel (different test methods)
- T009 and T010 within US3 can run in parallel (different test methods)
- T012, T013, T014 in Polish can run in parallel (independent test classes)

---

## Implementation Strategy

### MVP First (US1 Only)

1. T001: Rewrite `collect_queues()` to parse `text` as JSON
2. T002-T003: Add `source_id`, remove old fields
3. T004-T005: Update tests
4. Run `pytest tests/test_debug_api.py -v` — verify all pass
5. MVP is ready: core message detail visible

### Full Feature

1. Complete MVP (US1)
2. T006-T007: Forward message tests (parsing is automatic, just verify)
3. T008-T010: Add fallback + tests
4. T011: Update contract doc
5. T012-T014: Full validation

---

## Notes

- US1 is the critical path — the JSON parsing change in T001 automatically handles forward messages (US2) since `build_forward_json()` produces the same JSON structure with `type: "forward"`
- The `_truncate()` helper can be removed if no other collector uses it, but keep it if it's still used by `collect_state()` or others
- All message queues (non-source) still return `"messages": []` as before — no change per FR-007
