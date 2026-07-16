# Tasks: Background Shell Agent

**Input**: Design documents from `/specs/021-background-shell-agent/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅

**Tests**: Included per TDD workflow — tests written first, verified to fail, then implementation.

**Organization**: Tasks grouped by user story for independent implementation. US2 and US3 extend the same handler code as US1.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths in descriptions

---

## Phase 1: Setup — Decision Prompt

**Purpose**: System prompt constant that all subsequent phases depend on

- [ ] T001 Add `BACKGROUND_SHELL_DECISION_PROMPT` constant to `hatsume/plugins/hatsume-plugin/prompts.py` (append ~40 lines at end of file)

**Checkpoint**: Decision prompt available; all other tasks can reference it

---

## Phase 2: Foundational — Background Process Infrastructure

**Purpose**: Core infra functions that MUST be complete before any agent handler logic

**⚠️ CRITICAL**: No user story implementation can begin until this phase is complete

- [ ] T002 [P] Add `import tempfile` to imports in `hatsume/plugins/hatsume-plugin/infra.py`
- [ ] T003 Add `_background_procs` dict and `read_background_output()` function to `hatsume/plugins/hatsume-plugin/infra.py`
- [ ] T004 [P] Add `start_background_cmd()` function to `hatsume/plugins/hatsume-plugin/infra.py`
- [ ] T005 [P] Add `kill_background_cmd()` function to `hatsume/plugins/hatsume-plugin/infra.py`

**Checkpoint**: All infra functions in place — agent handler can now spawn/poll/kill background processes

---

## Phase 3: User Story 1 — Run an Interactive Auth Command (Priority: P1) 🎯 MVP

**Goal**: User asks bot to run an interactive CLI command (e.g., `gh auth login`). Bot spawns process in background, polls for output, relays auth URL to user mid-execution, detects completion, notifies user.

**Independent Test**: Mock a command that outputs a URL then exits. Verify: (1) agent spawns process, (2) URL output triggers NOTIFY injection, (3) final DONE notifies user.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T006 [P] [US1] Write `test_background_shell_agent.py` — test agent registration (`background_shell` in `get_agent_list()`, handler callable) in `tests/test_background_shell_agent.py`
- [ ] T007 [P] [US1] Write `TestBackgroundShellParseTask` — test task parsing (valid JSON, parse failure, empty cmd) in `tests/test_background_shell_agent.py`
- [ ] T008 [P] [US1] Write `test_notify_injects_mid_progress` — NOTIFY decision triggers `inject_agent_notification` while agent stays alive in `tests/test_background_shell_agent.py`
- [ ] T009 [P] [US1] Write `test_done_decision_stops_loop` — DONE decision breaks loop and returns final result in `tests/test_background_shell_agent.py`

### Implementation for User Story 1

- [ ] T010 [US1] Implement `_run_background_shell()` handler — task parse step (code model JSON extraction) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T011 [US1] Implement process spawn + poll loop skeleton (Popen, sleep, read_output, timeout check) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T012 [US1] Implement decision loop — call code model with `BACKGROUND_SHELL_DECISION_PROMPT`, parse DONE/NOTIFY responses in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T013 [US1] Implement NOTIFY mid-progress injection (build notify_msg with NOTIFY_MARK + agent name + task, call `inject_agent_notification`) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T014 [US1] Implement final result formatting (DONE path: success message + full output + elapsed time) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T015 [US1] Register `background_shell` agent via `register_agent()` at module level in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T016 [US1] Run US1 tests to verify pass: `pytest tests/test_background_shell_agent.py -v` — expected 5+ PASS

**Checkpoint**: Auth flow works end-to-end — NOTIFY injects URL, DONE reports success. MVP ready.

---

## Phase 4: User Story 2 — Monitor a Long-Running Command (Priority: P2)

**Goal**: User asks bot to run a time-consuming command. Agent polls without notifying user (routine output), handles timeout gracefully, terminates on error (KILL).

**Independent Test**: Mock a command where code model returns CONTINUE:1 → CONTINUE:1 → DONE. Verify: (1) loop iterates correctly, (2) timeout kills process, (3) KILL decision terminates.

### Tests for User Story 2

- [ ] T017 [P] [US2] Write `test_continue_decision_loops` — CONTINUE:N causes re-poll after N seconds in `tests/test_background_shell_agent.py`
- [ ] T018 [P] [US2] Write `test_timeout_forces_termination` — elapsed >= total_timeout kills process and reports timeout in `tests/test_background_shell_agent.py`
- [ ] T019 [P] [US2] Write `test_kill_decision_terminates_process` — KILL decision calls kill_background_cmd in `tests/test_background_shell_agent.py`

### Implementation for User Story 2

- [ ] T020 [US2] Implement CONTINUE decision parsing (extract N, update check_interval, continue loop) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T021 [US2] Implement KILL decision handling (kill process, collect remaining output, format error result) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T022 [US2] Implement timeout path (elapsed >= total_timeout → force kill → format timeout result) in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T023 [US2] Implement final result formatting for KILL/TIMEOUT paths in `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T024 [US2] Run US2 tests: `pytest tests/test_background_shell_agent.py -v` — expected 8+ PASS (US1 + US2)

**Checkpoint**: Long-running commands handled — CONTINUE polling, KILL on error, timeout enforcement all work.

---

## Phase 5: User Story 3 — Multiple Agents Running Concurrently (Priority: P3)

**Goal**: Background_shell agent coexists with other agents. Duplicate dispatch is rejected. Agent status visible via `/agents` command.

**Independent Test**: Verify (1) `is_agent_running("background_shell")` blocks duplicate dispatch, (2) agent state shows in `/agents` output, (3) coding_agent and background_shell can run concurrently.

### Tests for User Story 3

- [ ] T025 [P] [US3] Write `test_background_shell_infra.py` — test `read_background_output` (incremental read, empty file, missing file) and `kill_background_cmd` (kill process, cleanup, unknown id) in `tests/test_background_shell_infra.py`

### Implementation for User Story 3

- [ ] T026 [US3] Verify duplicate prevention works — `agent_allocate` → `is_agent_running("background_shell")` check already in place (zero change, validation only)
- [ ] T027 [US3] Run infra tests: `pytest tests/test_background_shell_infra.py -v` — expected 7 PASS
- [ ] T028 [US3] Verify agent appears in `/agents` command output (existing `handle_agents` reads `_AGENT_STATES` set by agent handler — zero change, validation only)

**Checkpoint**: All three user stories work. Agent coexists with others, status visible, duplicate dispatch blocked.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integration validation + final cleanup

- [ ] T029 [P] Run full test suite to verify no regressions: `python -m pytest tests/ -v`
- [ ] T030 [P] Verify imports resolve without circular dependencies: `python -c "from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell; from hatsume.plugins.hatsume_plugin.infra import start_background_cmd; from hatsume.plugins.hatsume_plugin.prompts import BACKGROUND_SHELL_DECISION_PROMPT; print('OK')"`
- [ ] T031 [P] Run ruff lint on changed files: `ruff check hatsume/plugins/hatsume-plugin/prompts.py hatsume/plugins/hatsume-plugin/infra.py hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T032 Run quickstart.md smoke test validation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 (decision prompt import) — BLOCKS all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — spawn/read/kill infra must exist
- **Phase 4 (US2)**: Depends on Phase 3 — extends same handler function
- **Phase 5 (US3)**: Depends on Phase 3 — infra tests + concurrency validation
- **Phase 6 (Polish)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Core handler + NOTIFY + DONE. No dependencies on other stories.
- **US2 (P2)**: Extends handler with CONTINUE + KILL + TIMEOUT. Depends on US1 skeleton.
- **US3 (P3)**: Infra tests + concurrency validation. Independent of US2.

### Within Each Phase

- Tests MUST be written and FAIL before implementation
- Infra functions before handler logic
- Parse → Spawn → Poll → Decide → Inject/Complete (pipeline order)

### Parallel Opportunities

- T002-T005 (infra functions) can run in parallel
- T006-T009 (US1 tests) can run in parallel
- T017-T019 (US2 tests) can run in parallel
- T025 (US3 tests) can run in parallel with US2 tasks
- T029-T031 (polish checks) can run in parallel

---

## Implementation Strategy

### MVP First (US1 Only)

1. Phase 1: Add decision prompt constant
2. Phase 2: Add infra functions (spawn, read, kill)
3. Phase 3: Implement US1 — test → handler core → NOTIFY → DONE → register
4. **STOP and VALIDATE**: Run US1 tests, verify auth flow works
5. MVP ready to demo: interactive auth commands work

### Incremental Delivery

1. Phase 1+2 → Foundation ready (prompt + infra)
2. Phase 3 (US1) → Test → Demo (MVP: auth commands work)
3. Phase 4 (US2) → Test → Demo (long-running commands + timeout)
4. Phase 5 (US3) → Test → Demo (concurrency + infra tests)
5. Phase 6 → Final validation → Ship

### Files Affected Summary

| File | Change | Phase |
|------|--------|-------|
| `prompts.py` | +1 constant | Phase 1 |
| `infra.py` | +1 import, +1 dict, +3 functions | Phase 2 |
| `graph/agents.py` | +1 handler (~130 loc), +1 register_agent call | Phase 3-5 |
| `tests/test_background_shell_agent.py` | New file (~250 loc) | Phase 3-4 |
| `tests/test_background_shell_infra.py` | New file (~120 loc) | Phase 5 |

### Files NOT Changed (Zero-Change Reuse)

- `graph/tools.py` — `agent_allocate` dispatches by name
- `graph/nodes/ai.py` — `inject_agent_notification`, `NOTIFY_MARK`
- `handlers/chat.py` — `_start_conv_for_agent` notification callback
- `handlers/commands.py` — `/agents` status display
