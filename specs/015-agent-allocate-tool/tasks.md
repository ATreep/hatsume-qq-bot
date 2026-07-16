# Tasks: Agent Allocate Tool

**Input**: Design documents from `/specs/015-agent-allocate-tool/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Tests are included per TDD methodology (write-first, fail, then implement).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Plugin source**: `hatsume/plugins/hatsume-plugin/`
- **Tests**: `tests/` at repository root
- **Graph nodes**: `hatsume/plugins/hatsume-plugin/graph/`
- **Handlers**: `hatsume/plugins/hatsume-plugin/handlers/`

---

## Phase 1: Setup

**Purpose**: Verify prerequisites and create new files that don't exist yet

- [ ] T001 Verify all existing tests pass with `python -m pytest tests/ -xvs`
- [ ] T002 Verify current branch is `015-agent-allocate-tool` with `git branch --show-current`

---

## Phase 2: Foundational — Agent Registry

**Purpose**: Create the agent registry infrastructure. All user stories depend on this.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 [P] Write test for agent registry functions (register_agent, get_agent_list, get_agent_handler) in `tests/test_agent_allocate.py`
- [ ] T004 Verify test fails with `python -m pytest tests/test_agent_allocate.py::TestAgentRegistry -xvs`
- [ ] T005 Create `hatsume/plugins/hatsume-plugin/graph/agents.py` with AGENT_REGISTRY dict, register_agent(), get_agent_list(), get_agent_handler()
- [ ] T006 Verify test passes with `python -m pytest tests/test_agent_allocate.py::TestAgentRegistry -xvs`
- [ ] T007 Commit: `git add graph/agents.py tests/test_agent_allocate.py && git commit -m "feat: add agent registry infrastructure"`

**Checkpoint**: Registry infrastructure ready — agent implementations can now be added

---

## Phase 3: User Story 1 - Dispatch a Built-in Agent (Priority: P1) 🎯 MVP

**Goal**: End-to-end flow: LLM calls agent_allocate tool → agent runs in background → result injected into conversation → user gets @-notification

**Independent Test**: Trigger tool dispatch for web_browser agent, verify background execution, confirm @-notification with agent result

### Agent Handler Implementations

- [ ] T008 [P] [US1] Write test for built-in agent registration (web_browser + generate_video must be in registry) in `tests/test_agent_allocate.py`
- [ ] T009 [P] [US1] Verify test fails with `python -m pytest tests/test_agent_allocate.py::TestBuiltinAgents -xvs`
- [ ] T010 [US1] Implement _run_web_browser_agent(task, user_id) in `hatsume/plugins/hatsume-plugin/graph/agents.py` (mirrors existing web_browser tool logic)
- [ ] T011 [P] [US1] Implement _run_video_agent(task, user_id) in `hatsume/plugins/hatsume-plugin/graph/agents.py` (mirrors existing generate_video tool logic)
- [ ] T012 [US1] Register both agents with register_agent() at module bottom of `hatsume/plugins/hatsume-plugin/graph/agents.py`
- [ ] T013 [US1] Verify test passes with `python -m pytest tests/test_agent_allocate.py::TestBuiltinAgents -xvs`
- [ ] T014 [US1] Run full test suite `python -m pytest tests/ -xvs` to check no regressions
- [ ] T015 Commit: `git add graph/agents.py tests/test_agent_allocate.py && git commit -m "feat: add built-in agent handlers for web_browser and generate_video"`

### agent_allocate Tool

- [ ] T016 [P] [US1] Write test for agent_allocate tool (unknown agent → error, known agent → confirmation) in `tests/test_agent_allocate.py`
- [ ] T017 [US1] Verify test fails with `python -m pytest tests/test_agent_allocate.py::TestAgentAllocateTool -xvs`
- [ ] T018 [US1] Add imports (get_agent_list, get_agent_handler) and _AGENT_LIST_STR to `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T019 [US1] Add configure_agent_notification_callback() function in `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T020 [US1] Add agent_allocate tool with f-string description injection in `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T021 [US1] Verify test passes with `python -m pytest tests/test_agent_allocate.py::TestAgentAllocateTool -xvs`
- [ ] T022 Commit: `git add graph/tools.py tests/test_agent_allocate.py && git commit -m "feat: add agent_allocate tool with dynamic agent list description"`

### Notification Injection + Mark Detection

- [ ] T023 [P] [US1] Write test for NOTIFY_MARK detection (extract uid from str, extract uid from list, no mark → None) in `tests/test_agent_allocate.py`
- [ ] T024 [P] [US1] Write test for inject_agent_notification message format in `tests/test_agent_allocate.py`
- [ ] T025 [US1] Verify tests fail with `python -m pytest tests/test_agent_allocate.py::TestNotifyMarkDetection -xvs` and `python -m pytest tests/test_agent_allocate.py::TestInjectAgentNotification -xvs`
- [ ] T026 [US1] Add NOTIFY_MARK constant and inject_agent_notification() function in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T027 [US1] Verify tests pass with `python -m pytest tests/test_agent_allocate.py::TestNotifyMarkDetection TestInjectAgentNotification -xvs`
- [ ] T028 Commit: `git add graph/nodes/ai.py tests/test_agent_allocate.py && git commit -m "feat: add NOTIFY_MARK constant and inject_agent_notification function"`

### ai_node NOTIFY_MARK Detection & @-Routing

- [ ] T029 [US1] In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, add reverse-scan of last_content for NOTIFY_MARK before chat_agent invocation
- [ ] T030 [US1] In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, route message via ai_answer_with_at when notified_uid is detected; otherwise use standard ai_answer
- [ ] T031 [US1] Run full test suite `python -m pytest tests/ -xvs` to check no regressions
- [ ] T032 Commit: `git add graph/nodes/ai.py && git commit -m "feat: detect NOTIFY_MARK in ai_node and route to ai_answer_with_at"`

### Tool Registration & Exports

- [ ] T033 [US1] Import agent_allocate in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` and add to create_agent tools list
- [ ] T034 [US1] Export NOTIFY_MARK and inject_agent_notification from `hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py`
- [ ] T035 [US1] Verify imports resolve: `python -c "from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate; print('OK')"`
- [ ] T036 Commit: `git add graph/nodes/ai.py graph/nodes/__init__.py && git commit -m "feat: register agent_allocate tool in ai_node and export from nodes"`

### Callback Wiring in chat.py

- [ ] T037 [US1] In `hatsume/plugins/hatsume-plugin/handlers/chat.py`, add _last_user_chat_matcher module-level variable and _start_conv_for_agent() callback function
- [ ] T038 [US1] Register callback via configure_agent_notification_callback() at module bottom of `hatsume/plugins/hatsume-plugin/handlers/chat.py`
- [ ] T039 [US1] Store user_chat_matcher in _last_user_chat_matcher at start of user_chat_handle()
- [ ] T040 [US1] Run full test suite `python -m pytest tests/ -xvs` to check no regressions
- [ ] T041 [US1] Run ruff lint: `python -m ruff check hatsume/plugins/hatsume-plugin/`
- [ ] T042 Commit: `git add handlers/chat.py && git commit -m "feat: wire agent notification callback in chat.py"`

**Checkpoint**: User Story 1 complete — agent_allocate tool is fully functional end-to-end

---

## Phase 4: User Story 2 - Discover Available Agents (Priority: P2)

**Goal**: Agent list in tool description stays synchronized with registry, enabling LLM to correctly match user requests to agents

**Independent Test**: Inspect agent_allocate.description and verify it contains all registered agent names and descriptions

- [ ] T043 [US2] Verify _AGENT_LIST_STR in `hatsume/plugins/hatsume-plugin/graph/tools.py` is populated from get_agent_list() at module level
- [ ] T044 [US2] Verify agent_allocate.description f-string includes agent list by running: `python -c "from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate; print(agent_allocate.description)"`
- [ ] T045 [US2] Verify adding a new agent to registry automatically appears in description (add test agent, check description, remove test agent)
- [ ] T046 Commit: `git add tests/test_agent_allocate.py && git commit -m "feat: verify dynamic agent list in tool description"`

**Checkpoint**: User Story 2 complete — agent discoverability works automatically

---

## Phase 5: User Story 3 - Handle Agent Errors Gracefully (Priority: P3)

**Goal**: Failed agents still notify the user with an error message instead of silent failures

**Independent Test**: Dispatch an agent configured to fail and verify user receives error notification

- [ ] T047 [P] [US3] Write test verifying that inject_agent_notification is called with failure message when handler raises exception, in `tests/test_agent_allocate.py`
- [ ] T048 [US3] Verify test fails
- [ ] T049 [US3] Verify try/except in agent_allocate._run_and_notify() catches exceptions, sets result to failure message, and still calls inject_agent_notification()
- [ ] T050 [US3] Verify test passes
- [ ] T051 [US3] Run full test suite `python -m pytest tests/ -xvs`
- [ ] T052 Commit: `git add tests/test_agent_allocate.py && git commit -m "test: verify graceful error handling in agent dispatch"`

**Checkpoint**: User Story 3 complete — all error paths handled gracefully

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integration verification and cleanup

- [ ] T053 [P] Run full test suite: `python -m pytest tests/ -xvs`
- [ ] T054 [P] Run ruff lint on all changed files
- [ ] T055 Verify imports resolve from quickstart.md verification section
- [ ] T056 Commit any remaining changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational — core end-to-end flow
- **User Story 2 (Phase 4)**: Depends on US1 (tool must exist to verify description)
- **User Story 3 (Phase 5)**: Depends on US1 (notification injection must exist)
- **Polish (Phase 6)**: Depends on all user stories complete

### Within User Story 1

- T008-T015 (Agent Handlers): Before T016-T022 (Tool), before T023-T028 (Notification), before T029-T036 (Routes), before T037-T042 (Callback)
- All [P] tasks within a group can run in parallel

### Parallel Opportunities

- T003, T008, T016, T023-T024 can be written as test stubs in parallel (different test classes)
- T010 and T011 (web_browser handler + video handler) can run in parallel
- US2 (Phase 4) and US3 (Phase 5) can run in parallel after US1 completes
- T053 and T054 can run in parallel (test suite + lint)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (agent registry)
3. Complete Phase 3: User Story 1 (full dispatch + notify)
4. **STOP and VALIDATE**: Test end-to-end flow
5. Phase 4 (US2) and Phase 5 (US3) are quick validations

### Incremental Delivery

1. Setup + Foundational → Registry ready
2. Add US1 → Full end-to-end agent dispatch flow (MVP!)
3. Add US2 → Auto-discovery of agents in tool description
4. Add US3 → Graceful error handling verified
5. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files or independent test classes, no sequential dependencies
- [Story] label maps task to specific user story from spec.md
- Each commit is a logical group (test + implementation + pass)
- TDD: write test first, verify it fails, implement, verify it passes
- Stop at any checkpoint to validate independently
- All file paths are relative to project root
