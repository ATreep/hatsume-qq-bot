# Tasks: Auto-Stop Docker Container When Idle

**Input**: Design documents from `/specs/023-auto-stop-container/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Included — this feature follows TDD (tests written first, verified to fail, then implementation).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Source: `hatsume/plugins/hatsume-plugin/infra.py`
- Tests: `tests/test_container_lifecycle.py` (new file)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify prerequisites — project already initialized, no new scaffolding needed.

- [x] T001 Verify Docker is available and `hatsume/plugins/hatsume-plugin/virtual/launch_image.sh` exists

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core refcount state and helper functions that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests for Foundational

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T002 [P] Write test class `TestAcquireSubprocess` (4 tests: increments, cancels timer, skips done task) in `tests/test_container_lifecycle.py`
- [x] T003 [P] Write test class `TestReleaseSubprocess` (4 tests: decrements, clamps at zero, starts timer on zero, no timer on positive) in `tests/test_container_lifecycle.py`
- [x] T004 [P] Write test class `TestDelayedStopContainer` (2 tests: stops after grace, skips if refcount increased) in `tests/test_container_lifecycle.py`

### Implementation for Foundational

- [x] T005 Add imports (`asyncio`, `threading`) and module-level state (`_subprocess_refcount`, `_subprocess_refcount_lock`, `_stop_timer_task`, `_STOP_GRACE_SECONDS`) to `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T006 Implement `_acquire_subprocess()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T007 Implement `_release_subprocess()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T008 Implement `_delayed_stop_container()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T009 Run foundational tests: `pytest tests/test_container_lifecycle.py -v -k "TestAcquireSubprocess or TestReleaseSubprocess or TestDelayedStopContainer"` — verify all 10 tests PASS

**Checkpoint**: Foundation ready — helper functions exist and pass all tests. User story implementation can now begin.

---

## Phase 3: User Story 1 — Container Automatically Stops After Inactivity (Priority: P1) 🎯 MVP

**Goal**: When `run_cmd()` completes and no other subprocesses are active, the container auto-stops after 5 minutes.

**Independent Test**: Run a synchronous shell command, wait for the grace period, verify `stop_container()` is called. Also verify refcount is released on timeout and HALT errors.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T010 [P] [US1] Write test class `TestRunCmdRefcount` (3 tests: releases on success, releases on timeout, releases on HALT) in `tests/test_container_lifecycle.py`

### Implementation for User Story 1

- [x] T011 [US1] Integrate `_acquire_subprocess()` / `_release_subprocess()` with try/finally into `run_cmd()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T012 [US1] Run US1 tests: `pytest tests/test_container_lifecycle.py::TestRunCmdRefcount -v` — verify all 3 tests PASS

**Checkpoint**: User Story 1 complete — synchronous commands trigger auto-stop after grace period. Independently testable.

---

## Phase 4: User Story 2 — Active Commands Prevent Premature Shutdown (Priority: P2)

**Goal**: Multiple concurrent subprocesses keep the container running. The grace timer only starts when ALL finish. A new subprocess during the grace period cancels the timer.

**Independent Test**: Start a background process (refcount=1), kill it (refcount=0, timer starts). Verify timer creation and refcount lifecycle.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T013 [P] [US2] Write test class `TestKillBackgroundCmdRefcount` (2 tests: releases refcount on kill, skips release for unknown proc_id) in `tests/test_container_lifecycle.py`

### Implementation for User Story 2

- [x] T014 [US2] Integrate `_acquire_subprocess()` into `start_background_cmd()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T015 [US2] Integrate `_release_subprocess()` into `kill_background_cmd()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T016 [US2] Run US2 tests: `pytest tests/test_container_lifecycle.py::TestKillBackgroundCmdRefcount -v` — verify all 2 tests PASS

**Checkpoint**: User Stories 1 AND 2 both work — background processes are tracked, refcount prevents premature shutdown.

---

## Phase 5: User Story 3 — Manual Cleanup Still Works (Priority: P3)

**Goal**: `/resetsandbox` cancels any pending auto-stop timer and removes the container immediately.

**Independent Test**: Create a pending timer, call `cleanup_persistent_container()`, verify timer is cancelled and container removed.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T017 [P] [US3] Write test class `TestCleanupCancelsTimer` (2 tests: cancels pending timer, works with no timer) in `tests/test_container_lifecycle.py`

### Implementation for User Story 3

- [x] T018 [US3] Integrate timer cancellation into `cleanup_persistent_container()` in `hatsume/plugins/hatsume-plugin/infra.py`
- [x] T019 [US3] Run US3 tests: `pytest tests/test_container_lifecycle.py::TestCleanupCancelsTimer -v` — verify all 2 tests PASS

**Checkpoint**: All user stories complete — manual cleanup coexists with auto-stop.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification, regression testing, and quality gates.

- [x] T020 Run all new tests: `pytest tests/test_container_lifecycle.py -v` — verify all 15 tests PASS
- [x] T021 Run existing regression tests: `pytest tests/test_background_shell_infra.py tests/test_background_shell_agent.py tests/test_graph_nodes.py -v` — verify all PASS
- [x] T022 Run ruff lint: `ruff check hatsume/plugins/hatsume-plugin/infra.py` — verify no errors
- [x] T023 Verify quickstart.md instructions work correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — can start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 - P1)**: Depends on Phase 2
- **Phase 4 (US2 - P2)**: Depends on Phase 2 (can run in parallel with Phase 3)
- **Phase 5 (US3 - P3)**: Depends on Phase 2 (can run in parallel with Phase 3/4)
- **Phase 6 (Polish)**: Depends on Phase 3, 4, 5 all complete

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies on other stories — can start after Phase 2
- **User Story 2 (P2)**: No dependencies on other stories — can start after Phase 2
- **User Story 3 (P3)**: No dependencies on other stories — can start after Phase 2

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation after test verification
- Story complete before moving to next priority (if sequential)

### Parallel Opportunities

- T002, T003, T004 (Phase 2 tests) can run in parallel
- T010 (US1 test) can run in parallel with T013 (US2 test) and T017 (US3 test)
- Phase 3, 4, 5 implementation can run in parallel (different code sections)
- T020, T021, T022, T023 (Polish) can all run in parallel

---

## Parallel Example: All User Story Tests

```bash
# Write all test files concurrently (Phase 2-5 tests):
Task: "T002-T004: Foundational tests in tests/test_container_lifecycle.py"
Task: "T010: US1 tests in tests/test_container_lifecycle.py"
Task: "T013: US2 tests in tests/test_container_lifecycle.py"
Task: "T017: US3 tests in tests/test_container_lifecycle.py"

# Note: All tests are in the same file, so write them sequentially within the file,
# but the test classes are independent and can be designed in parallel.
```

---

## Implementation Strategy

### MVP First (User Story 1 + Foundational)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: `pytest tests/test_container_lifecycle.py -v` — 13 tests should pass
5. Deploy — synchronous commands now trigger auto-stop

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test → Deploy (MVP! sync commands auto-stop works)
3. Add User Story 2 → Test → Deploy (background processes tracked)
4. Add User Story 3 → Test → Deploy (manual cleanup coexists)
5. Polish → Final verification

### Single Developer Strategy

Execute phases sequentially: 1 → 2 → 3 → 4 → 5 → 6. Tests first within each phase, then implementation.

---

## Notes

- [P] tasks = different test classes or independent code sections
- [Story] label maps task to specific user story for traceability
- Each user story is independently testable after its phase completes
- Tests must FAIL before implementation (TDD red-green-refactor)
- All tests are in a single new file: `tests/test_container_lifecycle.py`
- Commit after each task or logical group
- Total: 23 tasks across 6 phases
