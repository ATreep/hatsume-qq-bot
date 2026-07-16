# Tasks: Agent Dispatch Context

**Input**: Design documents from `/specs/028-agent-dispatch-context/`

**Tests**: Test tasks included — the project uses TDD and existing test coverage must be maintained.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Core state infrastructure that all user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T001 Add `get_agent_context()` helper function in `hatsume/plugins/hatsume-plugin/graph/agents.py` — returns the `context` field from latest agent instance state, or `""` if absent

**Checkpoint**: Context retrieval infrastructure ready

---

## Phase 2: User Story 1 - Chat Agent Dispatches Subagent with Context (Priority: P1) 🎯 MVP

**Goal**: Chat agent records conversation context when dispatching a subagent, context is stored in agent state and embedded in completion notifications

**Independent Test**: Trigger a subagent dispatch with known context → verify context appears in the injected notification message

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T002 [P] [US1] Write test `test_get_agent_context_returns_stored_context` in `tests/test_agent_dispatch.py` — verifies `get_agent_context()` reads back stored context
- [ ] T003 [P] [US1] Write test `test_get_agent_context_returns_empty_for_missing` in `tests/test_agent_dispatch.py` — verifies empty string for nonexistent agent
- [ ] T004 [P] [US1] Write test `test_get_agent_context_returns_empty_when_no_context_field` in `tests/test_agent_dispatch.py` — verifies backward compatibility when state lacks context field
- [ ] T005 [US1] Run tests to verify they FAIL: `python -m pytest tests/test_agent_dispatch.py -xvs -k "test_get_agent_context"`

### Implementation for User Story 1

- [ ] T006 [US1] Add `context: str = ""` parameter to `inject_agent_notification()` signature and embed context in notify_msg in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — format: `📋 派发背景：{context}` between SYSTEM header and task section, omitted when context is empty
- [ ] T007 [US1] Rename `agent_allocate` → `agent_dispatch` in `hatsume/plugins/hatsume-plugin/graph/tools.py` — update function name, tool description, print statement. Add `context: str` parameter (required, no default). Store context in `add_agent_instance()` call inside `_run_and_notify()`. Pass context to `inject_agent_notification()`
- [ ] T008 [US1] Update import and tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — change `agent_allocate` → `agent_dispatch` in the import block (line 37) and chat_agent tools list (line 514)
- [ ] T009 [US1] Run all related tests to verify PASS: `python -m pytest tests/test_agent_dispatch.py tests/test_graph_nodes.py -xvs`

**Checkpoint**: User Story 1 fully functional — context flows from dispatch → state → injection

---

## Phase 3: User Story 2 - Tool Renamed for Semantic Clarity (Priority: P2)

**Goal**: Zero references to `agent_allocate` remain in active project source files

**Independent Test**: `grep -rn "agent_allocate" hatsume/ tests/ CLAUDE.md` returns zero results

### Implementation for User Story 2

- [ ] T010 [P] [US2] Update prompt text in `hatsume/plugins/hatsume-plugin/prompts.py` — change `agent_allocate` → `agent_dispatch` in the agent state prompt string (line 164)
- [ ] T011 [P] [US2] Update docstring in `hatsume/plugins/hatsume-plugin/graph/agents.py` — change module docstring from `agent_allocate` → `agent_dispatch` (line 1)
- [ ] T012 [P] [US2] Update comment in `hatsume/plugins/hatsume-plugin/timer/executor.py` — change `agent_allocate` → `agent_dispatch` in comment (line 305)
- [ ] T013 [P] [US2] Rename test file `tests/test_agent_allocate.py` → `tests/test_agent_dispatch.py` and update all internal references (`agent_allocate` → `agent_dispatch`)
- [ ] T014 [P] [US2] Update test references in `tests/test_graph_nodes.py` (line 304: `tools_mod.agent_allocate` → `tools_mod.agent_dispatch`)
- [ ] T015 [P] [US2] Update test references in `tests/test_timer_injection.py` (line 139: `"agent_allocate"` → `"agent_dispatch"`)
- [ ] T016 [P] [US2] Update comment in `tests/test_background_shell_agent.py` (line 3: `test_agent_allocate.py` → `test_agent_dispatch.py`)
- [ ] T017 [P] [US2] Update any `agent_allocate` references in `CLAUDE.md` (if present)
- [ ] T018 [US2] Verify zero remaining references: `grep -rn "agent_allocate" hatsume/ tests/ CLAUDE.md | grep -v ".git/"` → expected empty

**Checkpoint**: Global rename complete — `agent_dispatch` is the canonical name

---

## Phase 4: User Story 3 - Conversation Continuity After Agent Completion (Priority: P3)

**Goal**: Run full test suite and lint to confirm everything works end-to-end

**Independent Test**: `python -m pytest tests/ -xvs` passes, `ruff check` passes

### Implementation for User Story 3

- [ ] T019 [US3] Run full test suite: `python -m pytest tests/ -xvs` — fix any failures
- [ ] T020 [US3] Run ruff lint: `ruff check hatsume/plugins/hatsume-plugin/` — fix any issues
- [ ] T021 [US3] Final grep verification: confirm zero `agent_allocate` references in active source and zero regressions in agent dispatch flow

**Checkpoint**: All user stories verified, ready to commit

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final quality checks and documentation

- [ ] T022 Commit all changes with conventional commit message
- [ ] T023 Run quickstart.md validation steps

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately
- **User Story 1 (Phase 2)**: Depends on Phase 1 — BLOCKS US2 and US3
- **User Story 2 (Phase 3)**: Depends on Phase 2 completion (needs `agent_dispatch` to exist before rename sweep)
- **User Story 3 (Phase 4)**: Depends on Phase 2 + 3 completion
- **Polish (Phase 5)**: Depends on all phases

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Phase 1 — core implementation
- **User Story 2 (P2)**: Depends on US1 — rename must happen on the already-renamed tool
- **User Story 3 (P3)**: Depends on US1 + US2 — verification of complete feature

### Within Each User Story

- Tests (T002-T005) MUST be written and FAIL before implementation (T006-T009)
- Implementation before rename sweep (US1 before US2)
- All tasks before verification (US3)

### Parallel Opportunities

- T002, T003, T004 (US1 tests) can run in parallel — different test functions
- T010-T017 (US2 rename tasks) can all run in parallel — different files
- T019, T020 (US3 verification) can run in parallel — independent checks

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (T001)
2. Complete Phase 2: User Story 1 (T002-T009)
3. **STOP and VALIDATE**: Verify context flows end-to-end
4. The feature is functional at this point — rename can follow

### Full Delivery

1. Foundational → US1 (MVP) → US2 (rename) → US3 (verify) → Polish
2. Each phase adds value incrementally

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Context is a required `str` parameter on `agent_dispatch` — no default value
- Empty context omits the `📋 派发背景：` line entirely
- Historical spec docs (`specs/024-agent-allocate-*`) are intentionally NOT renamed
- Commit after each task or logical group
