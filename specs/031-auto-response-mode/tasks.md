# Tasks: Auto Response Mode

**Input**: Design documents from `specs/031-auto-response-mode/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Test tasks included — the feature spec and plan reference pytest tests following existing `test_auto_create.py` patterns.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Project is a NoneBot2 plugin. Source under `hatsume/plugins/hatsume-plugin/`, tests under `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No setup needed — project already initialized with all dependencies. Skip to Foundational phase.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented — config constant, prompt function, and store methods that all stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T001 [P] Add `AUTO_RESPONSE_GROUP_ID` constant in `hatsume/plugins/hatsume-plugin/config.py` (after line 130, mirroring `AUTO_CREATE_GROUP_ID` and using the configured target group)
- [x] T002 [P] Add `get_auto_response_prompt()` function in `hatsume/plugins/hatsume-plugin/prompts.py` (after `get_auto_create_prompt()`, 5 Chinese wording variations, returns `str`)
- [x] T003 Add `upsert_auto_response()`, `get_auto_response()`, `list_auto_response_triggers()` methods to `TimerStore` class in `hatsume/plugins/hatsume-plugin/timer/store.py` (after `list_auto_create_triggers()` at line 227, mirroring auto_create store pattern)

**Checkpoint**: Foundation ready — config, prompt, and store methods exist. User story implementation can now begin.

---

## Phase 3: User Story 1 - Periodic Lightweight Community Engagement (Priority: P1) 🎯 MVP

**Goal**: The bot periodically (every 1-3h) picks a topic from recent chat history and sends a short ≤30-char reply to keep the group lively. Timer self-renews via fire-and-forget.

**Independent Test**: Start bot, wait 1-3h, observe a short topical reply in the target group. Verify another timer is immediately scheduled. Check logs for `💬 [auto_response]` tags.

### Implementation for User Story 1

- [x] T004 [US1] Add `_random_response_trigger()` function in `hatsume/plugins/hatsume-plugin/timer/executor.py` (after `_random_next_trigger()` at line 96; returns random timestamp in `[now+1h, now+3h]`, no time-window restriction)
- [x] T005 [US1] Add `_execute_auto_response()`, `reschedule_auto_response()`, and `refresh_auto_response()` functions in `hatsume/plugins/hatsume-plugin/timer/executor.py` (after `reschedule_auto_create()` at line 148; injects prompt via `inject_timer(user_id=0, is_auto_create=False)`, marks trigger fired, reschedules immediately)
- [x] T006 [US1] Add `auto_response` routing in `_execute_timer()` in `hatsume/plugins/hatsume-plugin/timer/executor.py` (after auto_create routing block at line 255; checks `task.get("task_type") == "auto_response"`, marks fired, calls `_execute_auto_response()`)
- [x] T007 [US1] Verify syntax: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/timer/executor.py').read()); print('OK')"` → `OK`

**Checkpoint**: Core auto-response timer functional — fires, injects prompt, reschedules itself. Test by observing logs or using manual trigger.

---

## Phase 4: User Story 2 - System Resilience Across Restarts (Priority: P2)

**Goal**: Auto-response timer recovers after bot restart — re-registers pending trigger or creates fresh one.

**Independent Test**: Create an auto_response task, restart bot, verify the pending timer re-registers OR a fresh one is created. Check logs for `💬 [auto_response] Startup:`.

### Implementation for User Story 2

- [x] T008 [US2] Call `refresh_auto_response()` in `init_scheduler()` in `hatsume/plugins/hatsume-plugin/timer/__init__.py` (after commented-out auto_create refresh at line 39; imports `refresh_auto_response` from executor)
- [x] T009 [US2] Verify syntax: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/timer/__init__.py').read()); print('OK')"` → `OK`

**Checkpoint**: Bot restart recovery functional — auto_response timer survives restarts.

---

## Phase 5: User Story 3 - Admin Debug Trigger (Priority: P3)

**Goal**: Admin can manually trigger auto-response via `/autoresponse` command without affecting the scheduled timer or database.

**Independent Test**: Admin sends `/autoresponse` in a group, bot immediately injects prompt and sends a short reply. Non-admin sends `/autoresponse`, command is ignored.

### Implementation for User Story 3

- [x] T010 [US3] Add `handle_autoresponse()` function in `hatsume/plugins/hatsume-plugin/handlers/commands.py` (after `handle_autocreate()` at line 373; mirrors autocreate debug pattern — supports `prod` arg for production group, custom prompt arg, injects via `inject_timer(user_id=0, start_conversation_cb=None)`)
- [x] T011 [US3] Register `autoresponse_cmd` matcher and handler in `hatsume/plugins/hatsume-plugin/__init__.py` (import `handle_autoresponse`, add `on_command("autoresponse", admin-only)` at line 100, add handler decorator at line 181; mirror autocreate registration)
- [x] T012 [US3] Verify syntax: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/__init__.py').read()); print('OK')"` → `OK`

**Checkpoint**: Admin debug command functional — `/autoresponse` works for testing without affecting the scheduled timer.

---

## Phase 6: Tests

**Purpose**: Verify trigger generation bounds and store CRUD operations.

- [x] T013 [P] Create `tests/test_auto_response.py` (mirrors `test_auto_create.py` pattern; stub-heavy module loading; `TestRandomResponseTrigger` class: 3 tests — valid horizon, random distribution over 100 samples, no time-window restriction over 500 samples; `TestAutoResponseStore` class: 4 tests — upsert creates single task, upsert replaces old, get returns None when empty, list triggers filters fired)
- [x] T014 Run all tests: `python -m pytest tests/test_auto_response.py -xvs` → All pass
- [x] T015 Run full test suite to verify no regressions: `python -m pytest tests/ -xvs` → All existing tests still pass

**Checkpoint**: All tests pass, no regressions in existing functionality.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 2 (Foundational)**: No dependencies — can start immediately. Blocks all user stories.
- **Phase 3 (US1)**: Depends on Phase 2 completion.
- **Phase 4 (US2)**: Depends on Phase 3 (US1) — needs `refresh_auto_response()` defined in T005.
- **Phase 5 (US3)**: Depends on Phase 2 (config + prompt) — can run in parallel with US1.
- **Phase 6 (Tests)**: Depends on Phase 2-5 completion (all code must exist).

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2). No dependencies on other stories.
- **User Story 2 (P2)**: Depends on US1 (`refresh_auto_response()` defined in US1's executor additions).
- **User Story 3 (P3)**: Can start after Foundational (Phase 2). Independent of US1/US2 (only uses config + prompt).

### Within Each User Story

- Executor functions before routing (T004-T005 before T006)
- Handler function before matcher registration (T010 before T011)
- Implementation before syntax verification (each group)

### Parallel Opportunities

- T001 and T002 can run in parallel (different files)
- T004 and T010 could run in parallel if staffed (different files, both after Phase 2)
- T013 is independent of all other tasks (test file)

---

## Parallel Example: Foundational Phase

```bash
# Launch foundational tasks in parallel:
Task: "T001 Add AUTO_RESPONSE_GROUP_ID in config.py"
Task: "T002 Add get_auto_response_prompt() in prompts.py"
# Then:
Task: "T003 Add store methods in timer/store.py" (after T001, T002)
```

## Parallel Example: After Foundational

```bash
# These can run in parallel after Phase 2:
Task: "T004-T006 US1 executor + routing" (group A)
Task: "T010-T011 US3 debug command + matcher" (group B)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: Foundational (T001-T003) — config + prompt + store
2. Complete Phase 3: User Story 1 (T004-T007) — executor + routing
3. **STOP and VALIDATE**: Manually create auto_response task in DB and verify timer fires
4. Deploy if ready — this delivers the core feature

### Incremental Delivery

1. Foundational → Config and prompt ready
2. Add User Story 1 → Core timer working (MVP!)
3. Add User Story 2 → Startup recovery → Deploy
4. Add User Story 3 → Debug command → Deploy
5. Add Tests → Quality gate → Final deploy

### Single Developer Strategy (Recommended)

Execute tasks sequentially in order T001 → T015. Each task is 2-5 minutes. Total: ~30-45 minutes for full implementation.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- All new code mirrors existing auto_create patterns exactly
- `inject_timer()` is NOT modified — reused as-is
- No database migration needed — `task_type` column already exists
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
