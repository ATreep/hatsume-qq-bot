# Tasks: Agent Monitor & Deepseek Provider

**Input**: Design documents from `/specs/018-agent-monitor-deepseek/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: Included — TDD methodology (test first, watch fail, implement, verify pass)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Source**: `hatsume/plugins/hatsume-plugin/`
- **Tests**: `tests/`
- **Config**: `.env.prod` (repository root)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify branch and project readiness

- [x] T001 Verify branch `019-agent-monitor-deepseek` is active and project builds (`python -c "import hatsume.plugins.hatsume_plugin"`)

---

## Phase 2: Foundational — Deepseek Configuration

**Purpose**: Add Deepseek config constants needed by US3. Must complete before `get_code_model()` rewrite.

**⚠️ CRITICAL**: US3 depends on these constants existing in config.py.

- [x] T002 [P] Add Deepseek constants (`DEEPSEEK_BASE_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_V4_PRO`, `get_deepseek_api_key()`) to `hatsume/plugins/hatsume-plugin/config.py` (insert before the "Behavioral constants" section)
- [x] T003 [P] Append `DEEPSEEK_API_KEY=` placeholder to `.env.prod`

**Checkpoint**: Deepseek constants available — US3 can now proceed

---

## Phase 3: User Story 3 — Deepseek Powers Code-Related Tasks (Priority: P2)

**Goal**: `get_code_model()` returns a ChatOpenAI instance configured for Deepseek's official API

**Independent Test**: Call `get_code_model()` and verify model_name is `deepseek-chat`, base_url points to `api.deepseek.com`, and API key is sourced from env var

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T004 [P] [US3] Write `test_deepseek_constants_exist` and `test_deepseek_api_key_reads_env` in `tests/test_deepseek_provider.py`
- [x] T005 [P] [US3] Write `test_get_code_model_returns_deepseek` and `test_get_code_model_does_not_use_volcengine` in `tests/test_deepseek_provider.py`
- [x] T006 [US3] Run tests to verify they FAIL: `python -m pytest tests/test_deepseek_provider.py -v` (expected: ImportError for constants or assertion failure)

### Implementation for User Story 3

- [x] T007 [US3] Rewrite `get_code_model()` in `hatsume/plugins/hatsume-plugin/models.py` to return `ChatOpenAI(base_url=DEEPSEEK_BASE_URL, model=DEEPSEEK_V4_PRO, api_key=get_deepseek_api_key(), temperature=2)`
- [x] T008 [US3] Update imports in `hatsume/plugins/hatsume-plugin/models.py` — add `DEEPSEEK_BASE_URL`, `DEEPSEEK_V4_PRO`, `get_deepseek_api_key` to the `.config` import block
- [x] T009 [US3] Run tests to verify PASS: `python -m pytest tests/test_deepseek_provider.py -v`
- [x] T010 [US3] Run existing tests to confirm no regressions: `python -m pytest tests/test_graph_nodes.py tests/test_tools.py -v`
- [x] T011 [US3] Commit: `git add hatsume/plugins/hatsume-plugin/config.py hatsume/plugins/hatsume-plugin/models.py .env.prod tests/test_deepseek_provider.py && git commit -m "feat: add Deepseek model provider, route get_code_model to deepseek-chat"`

**Checkpoint**: `get_code_model()` returns Deepseek-configured ChatOpenAI. Coding agent and HTML rendering use Deepseek.

---

## Phase 4: User Story 1 — Chat Agent Checks Subagent Status (Priority: P1) 🎯 MVP

**Goal**: Chat agent can query any subagent's current state (idle/running/done) and view results when done

**Independent Test**: Call `check_agent("coding_agent")` and verify response reflects idle/running/done with task/output details

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T012 [P] [US1] Write state tracking tests (`test_set_and_get_agent_state`, `test_is_agent_running`, `test_get_agent_state_unknown`, `test_set_agent_state_preserves_fields`, `test_set_agent_state_records_started_at`) in `tests/test_agent_monitor.py`
- [x] T013 [P] [US1] Write `check_agent` tool tests (`test_check_agent_idle`, `test_check_agent_running`, `test_check_agent_done`, `test_check_agent_unknown`) in `tests/test_agent_monitor.py`
- [x] T014 [US1] Run state tracking tests to verify FAIL: `python -m pytest tests/test_agent_monitor.py -v -k "state or running"` (expected: ImportError for `set_agent_state`)

### Implementation for User Story 1

- [x] T015 [US1] Add `_AGENT_STATES` dict + `set_agent_state()`, `get_agent_state()`, `is_agent_running()` functions to `hatsume/plugins/hatsume-plugin/graph/agents.py` (after AgentHandler type alias, before AGENT_REGISTRY)
- [x] T016 [US1] Run state tracking tests to verify PASS: `python -m pytest tests/test_agent_monitor.py -v -k "state or running"`
- [x] T017 [US1] Run check_agent tests to verify FAIL: `python -m pytest tests/test_agent_monitor.py -v -k "check_agent"` (expected: ImportError for `check_agent`)
- [x] T018 [US1] Add `check_agent(agent_name: str) -> str` @tool function to `hatsume/plugins/hatsume-plugin/graph/tools.py` (append after `agent_allocate` tool)
- [x] T019 [US1] Import and register `check_agent` in the `chat_agent` tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` (add to import block and `create_agent` tools list)
- [x] T020 [US1] Run check_agent tests to verify PASS: `python -m pytest tests/test_agent_monitor.py -v -k "check_agent"`
- [x] T021 [US1] Run registration test to verify PASS: `python -m pytest tests/test_agent_monitor.py -v -k "importable or registered"`
- [x] T022 [US1] Commit: `git add hatsume/plugins/hatsume-plugin/graph/agents.py hatsume/plugins/hatsume-plugin/graph/tools.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py tests/test_agent_monitor.py && git commit -m "feat: add agent state tracking and check_agent monitoring tool"`

**Checkpoint**: Chat agent can query subagent status via `check_agent`. State transitions work.

---

## Phase 5: User Story 2 — Prevent Duplicate Subagent Allocation (Priority: P1)

**Goal**: `agent_allocate` rejects allocation when the target agent is already running

**Independent Test**: Set agent state to "running", call `agent_allocate`, verify rejection message. Set state to "idle"/"done", verify allocation proceeds.

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T023 [P] [US2] Write allocation guard tests (`test_agent_allocate_rejects_when_running`, `test_agent_allocate_accepts_when_idle`) in `tests/test_agent_monitor.py` (append to existing file)
- [x] T024 [US2] Run tests to verify FAIL: `python -m pytest tests/test_agent_monitor.py -v -k "agent_allocate"` (expected: assertion failure — agent_allocate does not yet check running)

### Implementation for User Story 2

- [x] T025 [US2] Add running check to `agent_allocate` in `hatsume/plugins/hatsume-plugin/graph/tools.py` — after handler existence check, add `from .agents import is_agent_running; if is_agent_running(agent_name): return error`
- [x] T026 [US2] Add state tracking calls inside `_run_and_notify()` inner function — call `set_agent_state(agent_name, status="running", ...)` before handler and `set_agent_state(agent_name, status="done", result=result)` after handler
- [x] T027 [US2] Run tests to verify PASS: `python -m pytest tests/test_agent_monitor.py -v`
- [x] T028 [US2] Run existing tests to confirm no regressions: `python -m pytest tests/test_tools.py tests/test_graph_nodes.py -v`
- [x] T029 [US2] Commit: `git add hatsume/plugins/hatsume-plugin/graph/tools.py tests/test_agent_monitor.py && git commit -m "feat: add agent running guard to prevent duplicate allocation"`

**Checkpoint**: Duplicate agent allocation is 100% prevented. Agents track state from allocation through completion.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Validation, lint, and final integration check

- [x] T030 [P] Run ruff lint check: `ruff check hatsume/plugins/hatsume-plugin/`
- [x] T031 [P] Run full test suite: `python -m pytest tests/ -v`
- [x] T032 Validate quickstart.md steps (verify `DEEPSEEK_API_KEY=` in .env.prod, verify imports work)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — already on feature branch
- **Foundational (Phase 2)**: No dependencies — config constants can be added immediately. BLOCKS US3.
- **US3 (Phase 3)**: Depends on Phase 2 (Deepseek constants). Independent of US1/US2.
- **US1 (Phase 4)**: No Phase dependencies (agent state tracking is self-contained). BLOCKS US2 (US2 reuses agents.py state functions).
- **US2 (Phase 5)**: Depends on US1 (agents.py state functions + tools.py structure). Extends agent_allocate.
- **Polish (Phase 6)**: Depends on all user stories complete.

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 1 — no story dependencies
- **US2 (P1)**: Depends on US1 (shares agents.py state tracking)
- **US3 (P2)**: Depends on Phase 2 (config constants) — otherwise independent

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Run test to verify it fails before writing code
- Implement minimal code to pass
- Run test to verify pass
- Commit after each task group

### Parallel Opportunities

- T002 and T003 (Phase 2) can run in parallel
- T004 and T005 (US3 tests) can run in parallel
- T012 and T013 (US1 tests) can run in parallel
- US3 and US1 can be developed in parallel (independent files)
- T030 and T031 (Phase 6) can run in parallel

---

## Parallel Example: User Story 1 & 3

```bash
# These two phases touch DIFFERENT files and can run in parallel:
# Phase 3 (US3): config.py, models.py, .env.prod, tests/test_deepseek_provider.py
# Phase 4 (US1): agents.py, tools.py, ai.py, tests/test_agent_monitor.py

# Launch US3 tests together:
Task: "test_deepseek_constants_exist in tests/test_deepseek_provider.py"
Task: "test_get_code_model_returns_deepseek in tests/test_deepseek_provider.py"

# Launch US1 tests together:
Task: "state tracking tests in tests/test_agent_monitor.py"
Task: "check_agent tool tests in tests/test_agent_monitor.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (Deepseek config)
3. Complete Phase 3: US3 — Deepseek provider (independent, quick win)
4. Complete Phase 4: US1 — Agent monitoring MVP
5. Complete Phase 5: US2 — Allocation prevention
6. **STOP and VALIDATE**: Both agent features work
7. Complete Phase 6: Polish

### Incremental Delivery

1. Phase 1 + 2 → Config foundation ready
2. Phase 3 → Deepseek provider live (all code tasks use Deepseek)
3. Phase 4 → Agent status query works (MVP for monitoring)
4. Phase 5 → Duplicate allocation prevented (complete agent monitor)
5. Phase 6 → Lint clean, all tests pass

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD RED phase)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
