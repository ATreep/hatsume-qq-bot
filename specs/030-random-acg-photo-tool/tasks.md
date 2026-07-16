# Tasks: Random ACG Photo Tool

**Input**: Design documents from `/specs/030-random-acg-photo-tool/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: Included — TDD approach (tests written first, fail, then implement)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

- Plugin source: `hatsume/plugins/hatsume-plugin/`
- Tools: `hatsume/plugins/hatsume-plugin/graph/tools.py`
- AI node: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- Tests: `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify prerequisites — this feature adds to an existing project with no new dependencies.

- [x] T001 Verify project runs and existing tests pass: `python -m pytest tests/ -x --timeout=60`
- [x] T002 Verify Photos.app "ACG" album exists and is accessible on the host Mac

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None — this feature has zero new infrastructure. Existing `tools.py`, `ai.py`, `infra.py` (`ensure_container_running`), and `config.py` (`CONTAINER_NAME`) are reused as-is.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

*(No tasks — foundational components already exist in the codebase.)*

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Request a Random ACG Photo (Priority: P1) 🎯 MVP

**Goal**: Group chat member asks for a random ACG image → bot retrieves one from Apple Photos "ACG" album → sends it to the chat.

**Independent Test**: Send "来张二次元图" in group chat → bot replies with an image from the ACG album.

### Tests for User Story 1 (TDD — write FIRST, ensure they FAIL)

- [x] T003 [P] [US1] Write test `test_tool_exists` in `tests/test_random_acg_photo.py` — verifies `random_acg_photo` is a callable on the tools module
- [x] T004 [P] [US1] Write test `test_success_returns_sandbox_path` in `tests/test_random_acg_photo.py` — mocks subprocess/osascript/docker cp, verifies returned path matches `/tmp/apple_photo_export_*.jpg`
- [x] T005 [P] [US1] Write test `test_empty_album_returns_error` in `tests/test_random_acg_photo.py` — mocks osascript returning ALBUM_EMPTY, verifies Chinese error string
- [x] T006 Run tests to confirm they FAIL: `python -m pytest tests/test_random_acg_photo.py -xvs`
  Expected: `AttributeError: module ... has no attribute 'random_acg_photo'`

### Implementation for User Story 1

- [x] T007 [US1] Add `random_acg_photo` async tool function in `hatsume/plugins/hatsume-plugin/graph/tools.py` — uses `osascript` to export random photo from "ACG" album, `docker cp` to sandbox, returns sandbox path with timestamped filename
- [x] T008 [US1] Run tests to verify they PASS: `python -m pytest tests/test_random_acg_photo.py -xvs`
  Expected: 3 passed (T003, T004, T005) + 1 still failing (T009 from US2 not written yet)

**Checkpoint**: US1 core functionality working — tool returns valid sandbox paths. Error handling (US2) comes next.

---

## Phase 4: User Story 2 — Graceful Error Handling (Priority: P2)

**Goal**: When Photos.app is unavailable, album is missing, album is empty, or sandbox is down, the tool returns descriptive Chinese error messages.

**Independent Test**: Close Photos.app → trigger tool → verify Chinese error about Photos not running. Rename album → trigger → verify album-not-found error.

### Tests for User Story 2 (TDD — write FIRST, ensure they FAIL)

- [x] T009 [P] [US2] Write test `test_photos_app_not_running_returns_error` in `tests/test_random_acg_photo.py` — mocks osascript failure (returncode=1, stderr about app not running), verifies Chinese error with "无法访问 Photos"
- [x] T010 [P] [US2] Write test `test_docker_cp_failure_returns_error` in `tests/test_random_acg_photo.py` — mocks successful osascript but failed docker cp, verifies Chinese error with "❌"
- [x] T011 Run new tests to confirm they FAIL: `python -m pytest tests/test_random_acg_photo.py -xvs -k "photos_app_not_running or docker_cp_failure"`
  Expected: FAIL (error handling not yet implemented, tool returns unexpected output)

### Implementation for User Story 2

- [x] T012 [US2] Ensure error handling in `random_acg_photo` in `hatsume/plugins/hatsume-plugin/graph/tools.py` covers: osascript non-zero returncode → Photos not running error, ALBUM_NOT_FOUND → album missing error, ALBUM_EMPTY → empty album error, docker cp failure → sandbox unavailable error
- [x] T013 [US2] Run all tests to verify PASS: `python -m pytest tests/test_random_acg_photo.py -xvs`
  Expected: ALL 5 tests pass

**Checkpoint**: Error handling complete — tool gracefully handles all four error conditions.

---

## Phase 5: Register Tool in AI Node

**Purpose**: Make `random_acg_photo` available to the LLM by adding it to the chat_agent tools list.

**Independent Test**: LLM can invoke `random_acg_photo` during conversation (integration test in production).

- [x] T014 Import `random_acg_photo` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — add to existing tools import block (line 31-38)
- [x] T015 Add `random_acg_photo` to `chat_agent` tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` (line 512-518)
- [x] T016 Run full test suite to verify no regressions: `python -m pytest tests/ -x --timeout=60`

**Checkpoint**: Tool fully integrated — LLM can see and invoke `random_acg_photo`.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T017 [P] Run ruff lint: `ruff check hatsume/plugins/hatsume-plugin/graph/tools.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [x] T018 [P] Verify quickstart.md test scenarios match implementation
- [ ] T019 Manual integration test: run bot, trigger ACG photo request, verify photo is sent

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — verify existing state
- **Phase 2 (Foundational)**: Nothing needed — existing codebase provides all infrastructure
- **Phase 3 (US1)**: Can start immediately after Phase 1
- **Phase 4 (US2)**: Depends on US1 implementation (T007) — error handling is in the same function
- **Phase 5 (Register)**: Depends on US1+US2 complete (tool function must exist before import)
- **Phase 6 (Polish)**: Depends on all prior phases

### User Story Dependencies

- **User Story 1 (P1)**: Independent — no other story needed
- **User Story 2 (P2)**: Builds on US1 (same function, adds error branches) — technically separable via function structure but naturally sequential

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Tests → Implementation → Verify pass → Next story

### Parallel Opportunities

- T003, T004, T005 can be written in parallel (all go in the same test file)
- T009, T010 can be written in parallel
- T017, T018 can run in parallel (different tools)
- Phase 5 could be done in parallel with US2 error handling (separate files: tools.py vs ai.py)

---

## Implementation Strategy

### MVP First (US1 + US2)

1. T001-T002: Verify environment
2. T003-T006: Write failing tests for US1
3. T007-T008: Implement US1, verify tests pass
4. T009-T011: Write failing tests for US2
5. T012-T013: Implement US2, verify all pass
6. T014-T016: Register in ai.py, verify no regressions
7. T017-T019: Polish and manual verification

**STOP and VALIDATE** after T008 (US1 working) and T013 (US2 working).

---

## Notes

- This is a ~60-line addition to an existing codebase — no new files for source code, only 1 new test file
- All tool error messages follow the `❌ 错误：<description>` convention from existing tools
- Zero new Python dependencies — uses `subprocess`, `os`, `shutil`, `datetime` (all stdlib)
- Tests mock all external processes (osascript, docker cp) — no Photos.app or Docker needed for `pytest`
- [P] tasks = different files or independent concerns, no dependencies
- Commit after each phase or logical group
