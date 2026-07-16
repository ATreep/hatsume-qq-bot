# Tasks: Skill Create Tool

**Input**: Design documents from `/specs/013-skill-create-tool/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Included — TDD approach per design spec.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Project follows existing NoneBot2 plugin structure:
- Source: `hatsume/plugins/hatsume-plugin/`
- Tests: `tests/`

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: `SkillManager.save_skill()` method that US1 and US2 both depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T001 Write tests for `SkillManager.save_skill()` in `tests/test_skill_create.py` — test_save_new_skill_returns_created, test_save_existing_skill_overwrites, test_save_skill_clears_cache, test_save_skill_write_failure_returns_error
- [ ] T002 Run tests to verify they fail: `python -m pytest tests/test_skill_create.py -xvs` (expected: FAIL — AttributeError: 'SkillManager' object has no attribute 'save_skill')
- [ ] T003 Implement `save_skill(name, content)` method in `hatsume/plugins/hatsume-plugin/skills/manager.py` — after `remove_skill`, before `reset_conversation`
- [ ] T004 Run tests to verify they pass: `python -m pytest tests/test_skill_create.py -xvs` (expected: 4 PASS)
- [ ] T005 Commit: `git add tests/test_skill_create.py hatsume/plugins/hatsume-plugin/skills/manager.py && git commit -m "feat: add SkillManager.save_skill() method"`

**Checkpoint**: Foundation ready — `save_skill()` works, user story implementation can begin

---

## Phase 2: User Story 1 - Create New Skill from Content (Priority: P1) 🎯 MVP

**Goal**: LLM can call `skill_create(content)` with valid frontmatter and a skill file is saved to disk

**Independent Test**: Call `skill_create(content)` with valid content containing `name` + `description` in frontmatter; verify file exists on disk and success message returned

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T006 [P] [US1] Add tool-level test `test_valid_content_returns_success` in `tests/test_skill_create.py`

### Implementation for User Story 1

- [ ] T007 [US1] Add `@tool skill_create(content: str) -> str` in `hatsume/plugins/hatsume-plugin/graph/tools.py` — after `skill_download`, before `membersearch`. Parse frontmatter via `SkillManager.parse_frontmatter_text()`, validate name + description, delegate to `mgr.save_skill()`.
- [ ] T008 [US1] Run US1 test to verify it passes: `python -m pytest tests/test_skill_create.py::TestSkillCreateTool::test_valid_content_returns_success -xvs` (expected: PASS)
- [ ] T009 [US1] Import `skill_create` and add to chat agent tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — add to import block and `create_agent` tools list after `skill_download`
- [ ] T010 [US1] Verify import works: `python -c "from hatsume.plugins.hatsume_plugin.graph.tools import skill_create; print('OK:', skill_create.name)"` (expected: `OK: skill_create`)
- [ ] T011 [US1] Commit: `git add tests/test_skill_create.py hatsume/plugins/hatsume-plugin/graph/tools.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py && git commit -m "feat: add skill_create tool for chat agent"`

**Checkpoint**: User Story 1 functional — LLM can create new skills via `skill_create`

---

## Phase 3: User Story 2 - Overwrite Existing Skill (Priority: P1)

**Goal**: Calling `skill_create` with same `name` overwrites existing file and returns overwrite warning

**Independent Test**: Call `skill_create` twice with same `name` but different content; verify second call returns overwrite message and file contains new content

### Implementation for User Story 2

> **NOTE**: The `save_skill()` method already supports overwrite (implemented in T003). US2 needs no new code — only additional test verification.

- [ ] T012 [US2] Verify overwrite behavior with existing test `test_save_existing_skill_overwrites`: `python -m pytest tests/test_skill_create.py::TestSaveSkill::test_save_existing_skill_overwrites -xvs` (expected: PASS — already passing from T004)

**Checkpoint**: User Story 2 verified — overwrite works correctly via existing `save_skill()` logic

---

## Phase 4: User Story 3 - Validation of Required Fields (Priority: P2)

**Goal**: Invalid content (missing frontmatter, missing name, missing description) returns descriptive errors

**Independent Test**: Provide content with missing frontmatter, missing name, and missing description; verify each returns appropriate error message

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T013 [P] [US3] Add test `test_missing_name_returns_error` in `tests/test_skill_create.py`
- [ ] T014 [P] [US3] Add test `test_missing_description_returns_error` in `tests/test_skill_create.py`
- [ ] T015 [P] [US3] Add test `test_no_frontmatter_returns_error` in `tests/test_skill_create.py`

### Implementation for User Story 3

> **NOTE**: Validation logic is built into `skill_create` tool (implemented in T007). US3 verification confirms error messages are correct.

- [ ] T016 [US3] Run all skill_create tests: `python -m pytest tests/test_skill_create.py -xvs` (expected: all 8 tests PASS)
- [ ] T017 [US3] Run existing skill manager tests to verify no regression: `python -m pytest tests/test_skill_manager.py -xvs` (expected: all existing tests PASS)
- [ ] T018 [US3] Commit any remaining changes

**Checkpoint**: All 3 user stories functional — create, overwrite, and validation all work

---

## Phase 5: Polish & Integration Verification

**Purpose**: Final verification that everything works together

- [ ] T019 Run full test suite for feature: `python -m pytest tests/test_skill_create.py tests/test_skill_manager.py tests/test_tools.py tests/test_graph_nodes.py -xvs` (expected: all tests PASS)
- [ ] T020 Commit final changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — can start immediately
- **User Story 1 (Phase 2)**: Depends on Foundational (T003 — `save_skill()` exists)
- **User Story 2 (Phase 3)**: No code dependencies (overwrite is built into `save_skill()` from T003); only test verification
- **User Story 3 (Phase 4)**: Depends on US1 (T007 — `skill_create` tool exists with validation)
- **Polish (Phase 5)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Depends on Foundational — No dependencies on other stories
- **User Story 2 (P2)**: Depends on Foundational — Independently testable
- **User Story 3 (P3)**: Depends on US1 — Validation is in the `skill_create` tool

### Parallel Opportunities

- T013, T014, T015 (US3 tests) can all run in parallel
- US1 and US2 can be verified in parallel after Foundational phase completes

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (`save_skill()` + its tests)
2. Complete Phase 2: User Story 1 (`skill_create` tool + registration)
3. **STOP and VALIDATE**: Verify `skill_create` can create a new skill
4. Deploy/demo if ready

### Incremental Delivery

1. Complete Foundational → `save_skill()` ready
2. Add User Story 1 → `skill_create` works for new files (MVP!)
3. Verify User Story 2 → Overwrite works (already built in)
4. Add User Story 3 → Validation errors are clear

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
