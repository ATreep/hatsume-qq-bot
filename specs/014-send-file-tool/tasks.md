# Tasks: Send File from Ubuntu Container

**Input**: Design documents from `specs/014-send-file-tool/`

**Tests**: Included (TDD workflow)

**Status**: ✅ All tasks complete (implemented 2026-06-25, commit `458f58f`)

## Phase 1: Setup (Configuration)

- [x] T001 Add SEND_FILE constants in `hatsume/plugins/hatsume-plugin/config.py`
- [x] T002 Verify constants import correctly

## Phase 2: Foundational (Core Module)

- [x] T003 Create `hatsume/plugins/hatsume-plugin/file_transfer.py` with validate_container_path(), get_container_file_size(), is_container_path_a_file(), is_container_running(), _copy_from_container(), send_file_to_chat()
- [x] T004 [P] Write path validation tests in `tests/test_file_transfer.py` (TestValidateContainerPath: 8 tests)
- [x] T005 [P] Write size check tests in `tests/test_file_transfer.py` (TestGetContainerFileSize: 4 tests)
- [x] T006 [P] Write file type check tests in `tests/test_file_transfer.py` (TestIsContainerPathAFile: 2 tests)
- [x] T007 Run foundational tests → ALL PASS

## Phase 3: User Story 1 & 3 - Send File + Security (P1)

**Goal**: Extract and send files from `/work/` with path security

- [x] T008 [US1] Add send_file @tool to `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [x] T009 [US1] Import send_file in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [x] T010 [US1] Register send_file in create_agent() tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [x] T011 [P] [US1] Write integration test (test_send_file_success) in `tests/test_file_transfer.py`
- [x] T012 [P] [US1] Write tool registration tests in `tests/test_file_transfer.py`
- [x] T013 [US3] Write traversal rejection tests in `tests/test_file_transfer.py` (4 traversal + 1 integration)

## Phase 4: User Story 2 + 4 + 5 - Display Name, Oversize, Prompt Rules (P2)

- [x] T014 [US2] Write display_name override test (test_display_name_override) in `tests/test_file_transfer.py`
- [x] T015 [US4] Write oversize rejection test (test_oversize_file_returns_error) in `tests/test_file_transfer.py`
- [x] T016 [US5] Add send_file usage rules to `hatsume/plugins/hatsume-plugin/prompts.py`
- [x] T017 [US5] Write file_not_found error test in `tests/test_file_transfer.py`

## Phase 5: Polish

- [x] T018 Run full suite: `pytest tests/test_file_transfer.py -v` → 18/18 PASS
- [x] T019 Commit all changes

## Implementation Summary

| Metric | Value |
|--------|-------|
| Total tasks | 19 |
| Files created | 2 |
| Files modified | 4 |
| Tests | 18/18 PASS |
| Commit | `458f58f` |
