# Tasks: Timer Module

**Input**: Design documents from `/specs/008-timer-module/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Not explicitly requested — test tasks omitted. Add via `/speckit-checklist` if needed.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Exact file paths in every description

## Path Conventions

Based on plan.md, source is under `hatsume/plugins/hatsume-plugin/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration constants and timer package skeleton

- [ ] T001 [P] Add timer config constants (`TIMER_MAX_FUTURE_DAYS`, `TIMER_TOLERANCE_MINUTES`) in `hatsume/plugins/hatsume-plugin/config.py`
- [ ] T002 Create empty timer package with `__init__.py` in `hatsume/plugins/hatsume-plugin/timer/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: TimerStore — SQLite database schema and CRUD operations. ALL user stories depend on this.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 Create `TimerStore` class with `init_db()` (schema creation, indexes, foreign key with CASCADE) in `hatsume/plugins/hatsume-plugin/timer/store.py`
- [ ] T004 Implement CRUD methods: `create_task()`, `get_task()`, `delete_task()`, `update_task()`, `list_tasks_by_group()`, `mark_trigger_fired()`, `get_pending_triggers()` in `hatsume/plugins/hatsume-plugin/timer/store.py`
- [ ] T005 Implement validation methods: `validate_trigger_times()` (reject past times, enforce 7-day limit, deduplicate) and `validate_prompt()` (non-empty, max 500 chars) in `hatsume/plugins/hatsume-plugin/timer/store.py`

**Checkpoint**: Foundation ready — SQLite store fully functional, user story implementation can begin

---

## Phase 3: User Story 1 - Create Timer via Natural Language Chat (Priority: P1) 🎯 MVP

**Goal**: Users can create timer tasks by talking to the bot naturally. LLM invokes `create_timer` tool to submit parsed times and prompt.

**Independent Test**: Send "@初芽 明早8点提醒我开会" in a group chat, verify bot responds with confirmation including task ID and trigger times, and task is persisted in SQLite.

### Implementation for User Story 1

- [ ] T006 [US1] Add `_current_group_id` global and update `configure_tool_callbacks()` signature in `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T007 [US1] Implement `create_timer` tool with validation, store integration, and 5 few-shot examples in docstring in `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T008 [US1] Pass `group_id` through `configure_tool_callbacks()` in `hatsume/plugins/hatsume-plugin/graph/builder.py` (extract from event, wire to tools configure call)
- [ ] T009 [US1] Add `create_timer` to the agent's tool list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Checkpoint**: Users can create timer tasks via natural language. Task creation is confirmed and persisted.

---

## Phase 4: User Story 2 - Timer Triggers and Executes Results (Priority: P1) 🎯 MVP

**Goal**: Timers fire at scheduled times, execute independently, and send results to the group @-mentioning the creator. Auto-cleanup if creator left the group.

**Independent Test**: Create a timer 1 minute in the future, wait for trigger, verify group receives @creator message from chat_agent.

### Implementation for User Story 2

- [ ] T010 [US2] Implement job management: `register_job()` (APScheduler DateTrigger), `cancel_task_jobs()`, `add_jobs_for_task()` in `hatsume/plugins/hatsume-plugin/timer/executor.py`
- [ ] T011 [US2] Implement `execute_timer()` with global state save/restore pattern: save tools.py globals → set timer-owned state → run agent → restore in `hatsume/plugins/hatsume-plugin/timer/executor.py`
- [ ] T012 [US2] Implement username lookup via `get_bot().get_group_member_list()` with cleanup path (cancel jobs + delete task) if user not found in `hatsume/plugins/hatsume-plugin/timer/executor.py`
- [ ] T013 [US2] Implement context fetching: get last 5 group messages via `get_bot().get_group_msg_history()` as fallback, build system prompt with creator identity, create independent `create_agent` instance in `hatsume/plugins/hatsume-plugin/timer/executor.py`
- [ ] T014 [US2] Implement result delivery: parse agent output → `MessageSegment.at(user_id)` + result text → `get_bot().send_group_msg()` in `hatsume/plugins/hatsume-plugin/timer/executor.py`

**Checkpoint**: Full timer lifecycle works — create → wait → trigger → execute → deliver. MVP complete.

---

## Phase 5: User Story 4 - Startup Recovery and Fault Tolerance (Priority: P2)

**Goal**: Bot restarts recover all pending timers from SQLite. Missed timers within 5-minute tolerance window are compensated. Expired timers are cleaned up.

**Independent Test**: Create timers, restart bot, verify all pending timers re-register and fire correctly.

### Implementation for User Story 4

- [ ] T015 [US4] Implement `init_scheduler()`: load all `fired=0` triggers from DB, for each register APScheduler job OR compensate-execute (if within tolerance) OR mark expired (if beyond tolerance) in `hatsume/plugins/hatsume-plugin/timer/__init__.py`
- [ ] T016 [US4] Wire `init_scheduler()` call into plugin startup in `hatsume/plugins/hatsume-plugin/__init__.py` (import and call at module level, after NoneBot scheduler is available)

**Checkpoint**: Timer tasks survive bot restarts. Missed timers handled correctly per tolerance window.

---

## Phase 6: User Story 3 - Manage Timer Tasks via Commands (Priority: P2)

**Goal**: Users can list, delete, and update timers with `/timer` slash command. Invalid format shows help.

**Independent Test**: Issue `/timer list`, `/timer delete <id>`, `/timer update <id> ...` in a group, verify correct responses.

### Implementation for User Story 3

- [ ] T017 [US3] Register `timer_cmd = on_command("timer")` matcher in `hatsume/plugins/hatsume-plugin/__init__.py`
- [ ] T018 [US3] Implement `handle_timer()`: parse subcommands (`list`, `delete <id>`, `update <id> <prompt> @ <times>`), dispatch to store operations, format responses with help text on invalid input in `hatsume/plugins/hatsume-plugin/handlers/commands.py`
- [ ] T019 [US3] Implement `update_task()` flow: validate new prompt/times → cancel existing APScheduler jobs → update DB record → create new triggers → register new jobs in `hatsume/plugins/hatsume-plugin/timer/executor.py` (or call existing store + job functions from handler)

**Checkpoint**: All /timer sub-commands functional. Help text displayed on invalid input.

---

## Phase 7: User Story 5 - LLM Tools for Timer Management (Priority: P3)

**Goal**: chat_agent can list and delete timers via tool calls in natural conversation.

**Independent Test**: In chat, say "帮我看看我设了哪些定时任务" and "把那个开会的定时取消了", verify LLM correctly uses tools.

### Implementation for User Story 5

- [ ] T020 [P] [US5] Implement `list_timers` tool using `TimerStore.list_tasks_by_group()` in `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T021 [P] [US5] Implement `delete_timer` tool using `TimerStore.delete_task()` in `hatsume/plugins/hatsume-plugin/graph/tools.py`
- [ ] T022 [US5] Add `list_timers` and `delete_timer` to agent's tool list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Checkpoint**: All three timer LLM tools operational. Natural language timer management works.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Debug API, docs, edge case hardening

- [ ] T023 [P] Add `GET /debug/api/timers` endpoint with TimerStore integration in `hatsume/plugins/hatsume-plugin/debug.py`
- [ ] T024 Edge case hardening: prompt length limit enforcement, duplicate trigger dedup, empty group handling, LLM failure notification in relevant files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001, T002) — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational (T003-T005)
- **US2 (Phase 4)**: Depends on Foundational (T003-T005). Can run parallel with US1.
- **US4 (Phase 5)**: Depends on US2 (T010-T014) for executor functions
- **US3 (Phase 6)**: Depends on Foundational (T003-T005) and US4's T016 (needs init wired). Can run parallel with US1/US2.
- **US5 (Phase 7)**: Depends on Foundational (T003-T005). Can run parallel with US3.
- **Polish (Phase 8)**: Depends on all desired stories

### User Story Dependencies

- **US1 (P1)**: Foundational → independent
- **US2 (P1)**: Foundational → independent (can run parallel with US1)
- **US4 (P2)**: Foundational + US2 → independent
- **US3 (P2)**: Foundational → independent (can run parallel with US1/US2)
- **US5 (P3)**: Foundational → independent (can run parallel with US3)

### Within Each User Story

- Shared globals/config before tool/feature code
- Store operations before executor/command logic
- Tool definition before adding to agent tool list

### Parallel Opportunities

```
Phase 1: T001 | T002 (parallel)
Phase 2: T003 → T004 → T005 (sequential within store.py)
Phase 3: T006 | T007 (parallel), then T008 → T009
Phase 4: T010 → T011 → T012 | T013 → T014 (T012 + T013 parallel)
Phase 5: T015 → T016
Phase 6: T017 → T018 → T019
Phase 7: T020 | T021 (parallel), then T022
Phase 8: T023 | T024 (parallel)
```

### Cross-Phase Parallelism

Once Foundational (Phase 2) completes:
- US1 (Phase 3) + US2 (Phase 4) + US3 (Phase 6) can start in parallel
- US5 (Phase 7) can start after Foundational too

---

## Parallel Example: After Foundational Phase

```bash
# Launch US1 and US2 in parallel (different files):
Task: "T006 add _current_group_id global in graph/tools.py"
Task: "T007 implement create_timer tool in graph/tools.py"
# ---
Task: "T010 implement job management in timer/executor.py"
Task: "T011 implement execute_timer in timer/executor.py"

# Launch US3 in parallel with US5 (different files):
Task: "T017 register /timer matcher in __init__.py"
Task: "T020 implement list_timers tool in graph/tools.py"
Task: "T021 implement delete_timer tool in graph/tools.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Complete Phase 1: Setup (T001-T002)
2. Complete Phase 2: Foundational (T003-T005) **← CRITICAL BLOCKER**
3. Complete Phase 3: US1 (T006-T009) — create via natural language
4. Complete Phase 4: US2 (T010-T014) — trigger & execute
5. **STOP and VALIDATE**: Create a timer → wait for trigger → verify result
6. Deploy MVP

### Incremental Delivery

1. Setup + Foundational → Store ready
2. +US1 → Natural language creation works (can demo create + confirm)
3. +US2 → Full timer lifecycle works (MVP!)
4. +US4 → Survives restarts
5. +US3 → Command management works
6. +US5 → Natural language management works
7. +Polish → Debug API + edge cases

### Suggested MVP Scope

**Phases 1-4** (T001-T014): Users create timers via chat, timers fire and execute results. This is the minimum viable product.

---

## Notes

- [P] tasks modify different files — safe to run in parallel
- [Story] label maps task to spec user story
- T003-T005 are all in `store.py` — sequential execution recommended (same file)
- T010-T014 are all in `executor.py` — sequential execution recommended (same file)
- `tools.py` is modified by T006-T007 (US1) and T020-T021 (US5) — can conflict if run in parallel without coordination
- `__init__.py` is modified by T002 and T017 — T002 just creates empty file, T017 adds matcher
- All timer tools share the same `TimerStore` instance — wire via `timer/__init__.py` public interface
