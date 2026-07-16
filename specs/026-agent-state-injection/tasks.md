# Tasks: Agent State Prompt Injection

**Input**: Design documents from `/specs/026-agent-state-injection/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, quickstart.md

**Tests**: Test updates are required — existing tests must be updated to remove `check_agent` and dedup guard references.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Source: `hatsume/plugins/hatsume-plugin/`
- Tests: `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify starting state — all existing tests pass before changes

- [x] T001 Verify all existing tests pass before making changes — run `python -m pytest tests/ -xvs` and confirm zero failures

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the new `build_agent_state_prompt()` function — this is the foundation US2 and US3 depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 [P] Add `build_agent_state_prompt()` function in `hatsume/plugins/hatsume-plugin/prompts.py` after `build_skill_prompt()` (after line 124). Function signature: `def build_agent_state_prompt() -> str`. Returns markdown section listing running agents from `get_running_instances()`, or empty string. Use lazy import for `get_running_instances` inside the function body. Format: `"\n# 后台 Agent 状态\n\n以下 Agent 正在后台执行任务。...\n\n- **{name}**: {task[:200]}，已运行 {elapsed}s\n"` (see data-model.md for field mapping)

- [x] T003 Verify `build_agent_state_prompt()` imports and returns empty string — run `python -c "from hatsume.plugins.hatsume_plugin.prompts import build_agent_state_prompt; assert build_agent_state_prompt() == ''; print('OK')"`

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - LLM Passively Sees Running Agent States (Priority: P1) 🎯 MVP

**Goal**: Agent state information is injected into the chat_agent system prompt every turn, eliminating the need for a `check_agent` tool call.

**Independent Test**: Verify that `build_agent_state_prompt()` returns a non-empty string when agents are running, and that it's called in `ai_node()`.

### Implementation for User Story 1

- [x] T004 [US1] Add `build_agent_state_prompt` to the imports in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — add it to the `from ...prompts import (...)` block (line 21-27), keeping alphabetical order

- [x] T005 [US1] Inject agent state prompt into system prompt in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — after the skill injection block (after line 385), add: `agent_prompt = build_agent_state_prompt()` / `if agent_prompt: sys_prompt += agent_prompt` / `print("[agents] Injected agent state info into system prompt")`

- [x] T006 [US1] Run existing tests to verify no regression from prompt injection — `python -m pytest tests/ -xvs`

**Checkpoint**: Agent states are now injected into system prompt every turn. US1 is independently functional.

---

## Phase 4: User Story 2 - Agent Allocation No Longer Blocked by Dedup Gate (Priority: P2)

**Goal**: `agent_allocate` accepts allocations for already-running agents without requiring a prior `check_agent` call.

**Independent Test**: Verify that calling `agent_allocate` for an agent that already has a running instance returns a success message (the dedup gate is absent).

### Implementation for User Story 2

- [x] T007 [US2] Remove the dedup gate from `agent_allocate` in `hatsume/plugins/hatsume-plugin/graph/tools.py` — delete lines 881-886 (the `if is_agent_running(agent_name) and not _check_agent_used:` block with its return statement)

- [x] T008 [US2] Remove `_check_agent_used` global and its reset in `hatsume/plugins/hatsume-plugin/graph/tools.py`:
  - Delete line 80 (`_check_agent_used: bool = False`)
  - Update `reset_capture_flag()` (lines 132-136): remove `_check_agent_used` from the `global` statement and delete `_check_agent_used = False`

- [x] T009 [US2] Run existing tests to verify no regression from gate removal — `python -m pytest tests/ -xvs`

**Checkpoint**: `agent_allocate` no longer blocks duplicate allocations. US2 is independently functional.

---

## Phase 5: User Story 3 - Code Simplification (Priority: P3)

**Goal**: `check_agent` tool and all its references are fully removed. Test files are cleaned up.

**Independent Test**: `grep -r "check_agent\|_check_agent_used" hatsume/ tests/` returns no results. Full test suite passes.

### Test Updates (write/update first, ensure they align with removed code)

- [x] T010 [US3] Remove `tools_mod.check_agent = None` stub line from `tests/test_graph_nodes.py` (line 310)

- [x] T011 [US3] Remove the entire `TestAgentAllocateDedupGuard` class from `tests/test_agent_allocate.py` (lines 146-311, containing 5 test methods: `test_is_agent_running_detects_running_instance`, `test_is_agent_running_returns_false_when_idle`, `test_guard_logic_refuses_when_running_and_not_checked`, `test_guard_logic_allows_when_checked`, `test_guard_logic_allows_when_not_running`)

### Implementation for User Story 3

- [x] T012 [US3] Remove `check_agent` tool function from `hatsume/plugins/hatsume-plugin/graph/tools.py` — delete the entire function (lines 926-988, the `@tool` decorated `async def check_agent() -> str:`)

- [x] T013 [US3] Remove `check_agent` from the import and tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`:
  - Line 35: remove `check_agent,` from the `from ..tools import (...)` block
  - Line 421: remove `check_agent,` from the `create_agent(...)` tools list argument

**Checkpoint**: `check_agent` is fully removed. US3 is independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Full verification — integration tests, import chain, and cleanup check

- [x] T014 [P] Verify `check_agent` and `_check_agent_used` are absent from the codebase — `grep -r "check_agent\|_check_agent_used" hatsume/ tests/` returns no output

- [x] T015 [P] Verify full import chain — `python -c "from hatsume.plugins.hatsume_plugin.prompts import build_agent_state_prompt; from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate, reset_capture_flag; from hatsume.plugins.hatsume_plugin.graph.agents import get_running_instances; import inspect; assert '_check_agent_used' not in inspect.getsource(reset_capture_flag); print('All assertions passed')"`

- [x] T016 Run full test suite — `python -m pytest tests/ -xvs` — all tests must pass with zero failures

- [x] T017 Commit all changes with descriptive message

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — verify baseline
- **Foundational (Phase 2)**: Can start immediately — adds new function
- **US1 (Phase 3)**: Depends on Phase 2 (`build_agent_state_prompt` must exist)
- **US2 (Phase 4)**: Depends on Phase 2 (removes gate that references `_check_agent_used`)
- **US3 (Phase 5)**: Depends on US2 (removes `_check_agent_used` flag that the gate used; removes `check_agent` tool itself)
- **Polish (Phase 6)**: Depends on US1+US2+US3 complete

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational — injects agent states into prompt. No other story dependencies.
- **US2 (P2)**: Depends on Foundational — removes the dedup gate. Can be done in parallel with US1.
- **US3 (P3)**: Depends on US2 (removes `_check_agent_used` which US2 stopped using). Can start after US2 tasks are done.

### Within Each User Story

- Test updates before implementation changes (for US3)
- T010, T011 can run in parallel (different test files)
- T012 must run after T011 (to confirm test expectations align)
- T010, T011 also safe to run early — they just delete test code

### Parallel Opportunities

- T002, T003: sequential (verify after write)
- T004, T005: sequential (import before use)
- T007, T008: sequential within US2 (remove gate first, then flag)
- T010, T011: **parallel** (different files)
- T012, T013: **parallel** (different files, after tests updated)
- T014, T015: **parallel** (different verification commands)
- US1 (Phase 3) and US2 (Phase 4): **parallel** — different sections of different files

---

## Parallel Example: Phase 3+4 (US1 and US2 in parallel)

```bash
# US1 tasks (sequential within story):
Task: "T004 Add build_agent_state_prompt to imports in ai.py"
Task: "T005 Inject agent state prompt in ai.py"
Task: "T006 Run tests to verify US1"

# US2 tasks (sequential within story, can run alongside US1):
Task: "T007 Remove dedup gate from agent_allocate in tools.py"
Task: "T008 Remove _check_agent_used global from tools.py"
Task: "T009 Run tests to verify US2"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002-T003)
3. Complete Phase 3: US1 (T004-T006)
4. **STOP and VALIDATE**: Verify agent states appear in system prompt
5. Continue to US2/US3 if desired

### Recommended Delivery (All Stories)

Since this is a tightly-scoped refactoring, all 3 user stories should be delivered together:

1. T001 → T002-T003 → T004-T006 (US1) +
2. T007-T009 (US2, can parallel with US1)
3. T010-T011 → T012-T013 (US3, after US2)
4. T014-T017 (Polish & verify)

### Parallel Team Strategy

With multiple developers:
- Developer A: US1 (T004-T006)
- Developer B: US2 (T007-T009)
- Developer C: US3 test updates (T010-T011), then T012-T013 after US2 done

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- `is_agent_running()` utility in `agents.py` is retained (not removed)
