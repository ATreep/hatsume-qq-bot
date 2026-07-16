# Tasks: Agent Notification Detection Skip

**Input**: Design documents from `specs/016-agent-notify-detect-skip/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, quickstart.md

**Tests**: Included — 4 unit tests per spec requirements and TDD methodology.

**Organization**: Tasks are grouped by dependency order. Since User Story 2 (extract function) is a prerequisite for User Story 1 (detect node skip), foundational tasks come first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

---

## Phase 1: Foundational — Extract Reusable Function

**Purpose**: Create `detect_agent_notification()` that both user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T001 [US2] Extract `detect_agent_notification(state: MessagesState) -> int | None` function in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — insert after `NOTIFY_MARK` constant definition (after line 47), a pure function that scans `state["messages"][-1].content` for NOTIFY_MARK prefix and returns the notified user_id or None

- [ ] T002 [US2] Export `detect_agent_notification` from `hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py` — add to the import block from `.ai` (line 3-19)

**Checkpoint**: `detect_agent_notification` function exists and is importable from the nodes package.

---

## Phase 2: User Story 1 — Agent Result Arrives During Active Conversation (Priority: P1) 🎯 MVP

**Goal**: When an agent notification (`__agent_notify__`) is present in the last message, `chat_end_detect_node` skips LLM-based end-detection and routes directly to `chat_llm`.

**Independent Test**: Simulate conversation state with NOTIFY_MARK in last message → `chat_end_detect_node` returns `{"messages": []}` without invoking any model.

### Implementation for User Story 1

- [ ] T003 [US1] Import `detect_agent_notification` in `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py` — add `from .ai import detect_agent_notification` to imports (line 14 area)

- [ ] T004 [US1] Add early-return guard in `chat_end_detect_node` in `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py` — insert after `print("Enter chat_end_detect_node")` (line 18): if `detect_agent_notification(state) is not None`, return `{"messages": []}`

**Checkpoint**: Agent notifications always route to chat_llm. Normal detection logic unchanged for non-notification messages.

---

## Phase 3: User Story 2 — Agent Detection Logic is Reusable Across Nodes (Priority: P2)

**Goal**: `ai_node` uses the extracted `detect_agent_notification()` instead of inline detection code, eliminating duplication.

**Independent Test**: Call `detect_agent_notification(state)` directly with list content, string content, and no-mark messages → verify correct uid/None returns.

### Implementation for User Story 2

- [ ] T005 [US2] Refactor `ai_node` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — replace inline NOTIFY_MARK detection block (lines 184-201: `last_content_in`, the isinstance/list/elif loop) with `notified_uid = detect_agent_notification(state)` (preserve the `notified_uid` variable name and the comment line)

**Checkpoint**: ai_node behavior unchanged — agent notifications still correctly extract user_id and trigger at-reply.

---

## Phase 4: Tests & Polish

**Purpose**: Validate correctness, prevent regressions.

- [ ] T006 [P] [US2] Write test `test_detect_agent_notification_returns_uid_for_notify_mark_in_list_content` in `tests/test_graph_nodes.py` — state with list-type content containing NOTIFY_MARK prefix, assert returns correct user_id

- [ ] T007 [P] [US2] Write test `test_detect_agent_notification_returns_uid_for_notify_mark_in_string_content` in `tests/test_graph_nodes.py` — state with string-type content containing NOTIFY_MARK prefix, assert returns correct user_id

- [ ] T008 [P] [US2] Write test `test_detect_agent_notification_returns_none_when_no_notify_mark` in `tests/test_graph_nodes.py` — state with normal text message, assert returns None

- [ ] T009 [US1] Write test `test_chat_end_detect_node_skips_detection_when_notify_mark_present` in `tests/test_graph_nodes.py` — 4 messages including one with NOTIFY_MARK prefix, assert `chat_end_detect_node` returns `{"messages": []}` without model invocation

- [ ] T010 Run new tests: `python -m pytest tests/test_graph_nodes.py -k "test_detect_agent_notification or test_chat_end_detect_node_skips" -xvs`

- [ ] T011 Run full test suite for regressions: `python -m pytest tests/ -xvs`

**Checkpoint**: All 4 new tests pass. Zero regressions in existing test suite.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — can start immediately. BLOCKS all user stories.
- **User Story 1 (Phase 2)**: Depends on Phase 1 (T001, T002) — needs the function to exist and be importable.
- **User Story 2 (Phase 3)**: Depends on Phase 1 (T001) — needs the function to exist. Independent of Phase 2.
- **Tests (Phase 4)**: Depends on Phases 2 and 3 being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Phase 1. Independent of User Story 2.
- **User Story 2 (P2)**: Can start after Phase 1. Independent of User Story 1.

### Within Each Phase

- T001 → T002 (export depends on function existing)
- T003 → T004 (import before use)
- T006, T007, T008 can run in parallel (different test functions, same file but non-conflicting)
- T009 depends on T004 (detect node guard must exist)
- T010 depends on T006-T009 (all tests must be written)
- T011 depends on T010 (new tests pass before regression run)

### Parallel Opportunities

- Phase 2 and Phase 3 can run in parallel after Phase 1 (different files: detect.py vs ai.py)
- T006, T007, T008 all parallel (different test functions)
- T005 (refactor ai_node) and T003-T004 (detect node changes) are parallel

---

## Parallel Example

```bash
# After Phase 1 completes, launch in parallel:
# Worker A: Phase 2 (User Story 1)
Task: "T003 Import detect_agent_notification in detect.py"
Task: "T004 Add early-return guard in chat_end_detect_node"

# Worker B: Phase 3 (User Story 2)
Task: "T005 Refactor ai_node to use detect_agent_notification()"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (T001-T002)
2. Complete Phase 2: User Story 1 (T003-T004)
3. **STOP and VALIDATE**: Agent notifications survive end-detection
4. Deploy if urgent

### Full Delivery (Recommended)

1. Complete Phase 1: Foundational
2. Complete Phases 2 and 3 in parallel
3. Complete Phase 4: Tests
4. Full test suite pass → done

### Execution Order (Single Developer)

T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011

**Total**: 11 tasks, estimated 15-20 minutes for a single developer.

---

## Notes

- No new files created — all changes in existing files
- `detect_agent_notification()` is a pure function with no side effects — easy to test
- The existing test harness (`_load_nodes_module()` + `MockMessage`) already stubs all external dependencies
- Commit after each phase for clean history
