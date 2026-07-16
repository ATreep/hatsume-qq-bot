# Tasks: Agent Allocate Deduplication Guard

**Input**: Design documents from `specs/024-agent-allocate-dedup-guard/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Tests**: Included — TDD approach per project workflow.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

## Path Conventions

- **Source**: `hatsume/plugins/hatsume-plugin/graph/`
- **Tests**: `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No setup needed — all infrastructure already exists.

*No tasks — existing codebase has all prerequisites.*

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add import that implementation depends on.

- [x] T001 Add `is_agent_running` to existing agents import in `hatsume/plugins/hatsume-plugin/graph/tools.py:25`

**Checkpoint**: Import available for implementation phase.

---

## Phase 3: User Story 1 - Prevent Accidental Duplicate Agent Allocation (Priority: P1) 🎯 MVP

**Goal**: When the chat LLM tries to allocate an agent whose name already has a running instance, refuse unless `check_agent` was called first in the same turn.

**Independent Test**: Run `python -m pytest tests/test_agent_allocate.py::TestAgentAllocateDedupGuard -xvs` — all 3 tests pass.

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T002 [P] [US1] Write test `test_is_agent_running_detects_running_instance` and guard logic tests in `tests/test_agent_allocate.py` — verifies building blocks
- [x] T003 [P] [US1] Write guard logic test `test_guard_logic_allows_when_checked` in `tests/test_agent_allocate.py` — verifies allow when check_agent was called
- [x] T004 [P] [US1] Write guard logic test `test_guard_logic_allows_when_not_running` in `tests/test_agent_allocate.py` — verifies normal allocation when no duplicate

### Implementation for User Story 1

- [x] T005 [US1] Add dedup guard block in `agent_allocate` function in `hatsume/plugins/hatsume-plugin/graph/tools.py` — refuse if `is_agent_running(agent_name)` AND not `_check_agent_used`
- [x] T006 [US1] Run all tests to verify implementation: zero regressions, all pre-existing failures confirmed

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 2)**: No dependencies — start immediately
- **User Story 1 (Phase 3)**: Depends on Phase 2 (T001 import)

### Within User Story 1

- Tests (T002, T003, T004) MUST be written and FAIL before implementation (T005)
- T005 depends on T001 (import) + tests existing
- T006 is final verification

### Parallel Opportunities

- T002, T003, T004 (all tests) can be written in parallel — they test different scenarios in the same file but are independent assertions

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Write test test_refuses_when_agent_running_and_not_checked"
Task: "Write test test_allows_when_agent_running_and_check_agent_was_called"
Task: "Write test test_allows_when_agent_not_running"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: T001 (add import)
2. Complete Phase 3: Write tests (T002-T004) → verify they FAIL
3. Complete Phase 3: Implement guard (T005) → verify tests PASS
4. Complete Phase 3: Full test suite verification (T006)
5. **STOP and VALIDATE**: All tests pass, MVP complete

---

## Notes

- [P] tasks = different files, no dependencies
- [US1] label maps task to the single user story
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
