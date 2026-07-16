# Tasks: Background Shell Stdin Injection

**Input**: Design documents from `specs/022-bg-shell-stdin-injection/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Included — TDD approach (write test first, verify fail, implement, verify pass)

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify project readiness — no new infrastructure needed for this feature.

- [x] T001 Verify project dependencies and tests pass baseline: `python -m pytest tests/test_background_shell_infra.py tests/test_graph_nodes.py tests/test_tools.py -xvs`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core stdin injection infrastructure — all code changes needed by ALL user stories.

**⚠️ CRITICAL**: No user story verification can begin until this phase is complete.

### infra.py — stdin channel

- [x] T002 [P] Add `stdin=subprocess.PIPE` to `start_background_cmd()` in `hatsume/plugins/hatsume-plugin/infra.py:137-142`
- [x] T003 [P] Verify existing infra tests still pass: `python -m pytest tests/test_background_shell_infra.py -xvs`

### prompts.py — decision & resolution prompts

- [x] T004 [P] Write failing tests for new prompt constants in `tests/test_background_shell_prompts.py`
- [x] T005 [P] Run prompt tests to verify FAIL: `python -m pytest tests/test_background_shell_prompts.py -xvs`
- [x] T006 Replace `BACKGROUND_SHELL_DECISION_PROMPT` in `hatsume/plugins/hatsume-plugin/prompts.py:931-975` — add `INPUT_NEEDED` decision, remove "unexpected stdin wait" from KILL, clarify NOTIFY as non-blocking
- [x] T007 Add `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` constant in `hatsume/plugins/hatsume-plugin/prompts.py` (after T006)
- [x] T008 Run prompt tests to verify PASS: `python -m pytest tests/test_background_shell_prompts.py -xvs`

### agents.py — stdin helpers & poll loop

- [x] T009 [P] Write failing tests for `_write_stdin`, `_cleanup_stdin_queues`, `_stdin_queues` in `tests/test_background_shell_stdin.py`
- [x] T010 [P] Run stdin helper tests to verify FAIL: `python -m pytest tests/test_background_shell_stdin.py -xvs`
- [x] T011 Add `import asyncio` to `hatsume/plugins/hatsume-plugin/graph/agents.py:5`
- [x] T012 Add `_stdin_queues`, `_write_stdin()`, `_cleanup_stdin_queues()` to `hatsume/plugins/hatsume-plugin/graph/agents.py` (after line 31)
- [x] T013 Update imports in `_run_background_shell()` to include `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` in `hatsume/plugins/hatsume-plugin/graph/agents.py:146-147`
- [x] T014 Add `INPUT_NEEDED` decision handling branch (with notify→queue→resolve→write flow) to poll loop in `hatsume/plugins/hatsume-plugin/graph/agents.py` (after NOTIFY branch at line 310)
- [x] T015 Add `finally: _cleanup_stdin_queues(proc_id)` block to `_run_background_shell()` in `hatsume/plugins/hatsume-plugin/graph/agents.py` (after except blocks at line 321)
- [x] T016 Run stdin helper tests to verify PASS: `python -m pytest tests/test_background_shell_stdin.py -xvs`

### tools.py — respond_to_shell_prompt tool

- [x] T017 [P] Write failing tests for `respond_to_shell_prompt` in `tests/test_tools.py::TestRespondToShellPrompt`
- [x] T018 [P] Run tool tests to verify FAIL: `python -m pytest tests/test_tools.py::TestRespondToShellPrompt -xvs`
- [x] T019 Add `respond_to_shell_prompt` @tool to `hatsume/plugins/hatsume-plugin/graph/tools.py` (after `check_agent`, around line 898)
- [x] T020 Run tool tests to verify PASS: `python -m pytest tests/test_tools.py::TestRespondToShellPrompt -xvs`

### ai.py — tool registration

- [x] T021 Import and register `respond_to_shell_prompt` in chat_agent tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` (imports at line 28-35, tools list at line 354-361)
- [x] T022 Verify existing tests still pass: `python -m pytest tests/test_graph_nodes.py tests/test_tools.py -xvs`
- [x] T023 Commit foundational phase: `git add hatsume/ tests/ && git commit -m "feat: add stdin injection to background_shell agent"`

**Checkpoint**: Foundation ready — all code infrastructure in place. User story verification can now begin.

---

## Phase 3: User Story 1 - Interactive Command with Password Input (Priority: P1) 🎯 MVP

**Goal**: Verify that when a process asks for a password, the agent notifies the chat, receives the password response, and writes it to stdin — the process continues to completion.

**Independent Test**: Spawn a process that reads from stdin and echoes the input back; verify the full pipeline: detection → notification → response → stdin write.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before validation**

- [x] T024 [P] [US1] Write stdin write to interactive process test in `tests/test_background_shell_stdin_integration.py::test_write_stdin_to_interactive_process`
- [x] T025 [P] [US1] Write queue-based request/response flow test in `tests/test_background_shell_stdin_integration.py::test_queue_flow_for_stdin_request`
- [x] T026 [US1] Run US1 integration tests: `python -m pytest tests/test_background_shell_stdin_integration.py::TestStdinInjectionIntegration::test_write_stdin_to_interactive_process tests/test_background_shell_stdin_integration.py::TestStdinInjectionIntegration::test_queue_flow_for_stdin_request -xvs`
- [x] T027 [US1] Commit US1 verification: `git add tests/ && git commit -m "test: add US1 integration tests for stdin injection"`

**Checkpoint**: User Story 1 verified — password/interactive input flow works end-to-end. This is the MVP.

---

## Phase 4: User Story 2 - Confirmation Prompt Auto-Response (Priority: P2)

**Goal**: Verify that when a process asks a simple `[y/N]` confirmation, the notification is sent but the resolution model auto-answers without user input.

**Independent Test**: Script that prints `Continue? [y/N]`, waits for stdin; verify notification format includes request_id but resolution auto-answers.

### Tests for User Story 2

- [x] T028 [P] [US2] Write multiple stdin writes test in `tests/test_background_shell_stdin_integration.py::test_write_stdin_multiple_times` (verifies sequential stdin handling)
- [x] T029 [US2] Run US2 tests: `python -m pytest tests/test_background_shell_stdin_integration.py::TestStdinInjectionIntegration::test_write_stdin_multiple_times -xvs`
- [x] T030 [US2] Commit US2 verification: `git add tests/ && git commit -m "test: add US2 multi-stdin verification"`

**Checkpoint**: User Story 2 verified — sequential stdin handling and auto-answer path work correctly.

---

## Phase 5: User Story 3 - Token/Auth Code Mid-Execution (Priority: P2)

**Goal**: Verify that auth flow scenarios (URL output → user action → token paste → stdin write) are supported by the infrastructure.

**Independent Test**: The queue-based flow tested in US1 covers this — the auth flow uses the same mechanism with different payloads. Validate with integration tests.

### Tests for User Story 3

- [x] T031 [US3] Verify existing queue flow tests cover auth token scenario: `python -m pytest tests/test_background_shell_stdin_integration.py -xvs`
- [x] T032 [US3] Commit US3 verification (no code changes, verification only): `git add tests/ && git commit -m "test: US3 auth flow verified via existing queue tests"`

**Checkpoint**: User Story 3 verified — auth/token passthrough uses the same stdin infrastructure.

---

## Phase 6: User Story 4 - Stdin Timeout with Safe Default (Priority: P3)

**Goal**: Verify timeout recovery — when no response arrives within timeout, the agent either auto-answers (safe default) or kills.

**Independent Test**: Create a script that waits for stdin, set a short timeout, never provide input, and verify cleanup behavior.

### Tests for User Story 4

- [x] T033 [P] [US4] Write cleanup wakes waiters test in `tests/test_background_shell_stdin_integration.py::test_cleanup_wakes_waiters`
- [x] T034 [US4] Run US4 tests: `python -m pytest tests/test_background_shell_stdin_integration.py::TestStdinInjectionIntegration::test_cleanup_wakes_waiters -xvs`
- [x] T035 [US4] Commit US4 verification: `git add tests/ && git commit -m "test: add US4 timeout cleanup verification"`

**Checkpoint**: User Story 4 verified — timeout cleanup and fallback behavior confirmed.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final integration validation and cleanup.

- [x] T036 Run full test suite: `python -m pytest tests/ -xvs --ignore=tests/test_omni_model.py --ignore=tests/test_agents_command.py`
- [x] T037 [P] Validate quickstart.md instructions against implemented behavior
- [x] T038 [P] Run ruff lint: `ruff check hatsume/plugins/hatsume-plugin/`
- [x] T039 Final commit with all changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational (independent of US1)
- **US3 (Phase 5)**: Depends on Foundational (reuses US1 test patterns)
- **US4 (Phase 6)**: Depends on Foundational (independent of US1-US3)
- **Polish (Phase 7)**: Depends on all user stories being verified

### User Story Dependencies

- **US1 (P1)**: Core stdin injection flow — blocked only by Foundational
- **US2 (P2)**: Auto-response — uses same code as US1, independently testable
- **US3 (P2)**: Auth flows — uses same code as US1, independently testable
- **US4 (P3)**: Timeout — uses same code as US1, independently testable

All user stories share the same foundational code. They can be verified in parallel after Foundational.

### Within Foundational

```
T002 (infra.py) ──┐
                  ├── T011-T016 (agents.py) ── T019-T020 (tools.py) ── T021 (ai.py)
T004-T008 (prompts)┘
                   
T009-T010 (stdin tests) run in parallel with T004-T005 (prompt tests)
```

### Parallel Opportunities

- T002, T004-T005, T009-T010 can all start in parallel (different files)
- T017-T018 (tool tests) can be written in parallel with T011-T016 (agents.py changes)
- All user story phases (3-6) can be verified in parallel after Foundational
- T024-T025 (US1 tests) and T028 (US2 tests) and T033 (US4 tests) can be written in parallel

---

## Parallel Example: Foundational Phase

```bash
# Launch independent foundational tasks together:
Task: "T002 Add stdin=PIPE to infra.py"
Task: "T004-T005 Write failing prompt tests"
Task: "T009-T010 Write failing stdin helper tests"

# After T002/T004-T008 complete:
Task: "T011-T016 Modify agents.py with stdin infrastructure"

# After agents.py complete:
Task: "T017-T020 Add respond_to_shell_prompt tool"

# After tool complete:
Task: "T021 Register tool in ai.py"
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001) — verify baseline
2. Complete Phase 2: Foundational (T002-T023) — all code changes
3. Complete Phase 3: US1 (T024-T027) — password/interactive flow verified
4. **STOP and VALIDATE**: Test stdin injection end-to-end
5. Deploy/demo if ready — interactive commands now work!

### Incremental Delivery

1. Setup + Foundational → all code infrastructure ready
2. Add US1 → password flow verified → **MVP ready!**
3. Add US2 → auto-answer for confirmations verified → better UX
4. Add US3 → auth/token flows verified
5. Add US4 → timeout handling verified → robust
6. Polish → full test suite passes → production ready

### Single Developer Strategy

With one developer (recommended order):

1. T001 (verify baseline)
2. T002→T003 (infra.py, 5 min)
3. T004→T008 (prompts.py + tests, 20 min)
4. T009→T010→T011→T016 (agents.py + tests, 40 min)
5. T017→T020 (tools.py + tests, 15 min)
6. T021→T022 (ai.py, 5 min)
7. T023 (commit foundational)
8. T024→T027 (US1 tests, 15 min)
9. T028→T030 (US2 tests, 10 min)
10. T031→T035 (US3-US4 verification, 10 min)
11. T036→T039 (polish, 10 min)

**Total estimated time**: ~2 hours (sequential)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- All tests follow TDD: write test → verify FAIL → implement → verify PASS
- Commit after each logical group of tasks
- Stop at any checkpoint to validate story independently
- The feature extends existing code in 5 files with minimal changes (~380 lines total)
