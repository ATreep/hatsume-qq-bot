# Tasks: Auto Create Timer

**Input**: Design documents from `/specs/020-auto-create-timer/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Tests included per TDD approach mandated by project guidelines.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths in every description

## Path Conventions

Project root: `/path/to/hatsume`
Plugin source: `hatsume/plugins/hatsume-plugin/`
Tests: `tests/`

---

## Phase 1: Foundational (DB Schema + Config)

**Purpose**: Shared infrastructure that all user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T001 Add `task_type` column migration to `timer_tasks` table in `hatsume/plugins/hatsume-plugin/timer/store.py` — wrap `ALTER TABLE timer_tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'normal'` in try/except sqlite3.OperationalError inside `init_db()`, after the CREATE INDEX statement and before `self._conn.commit()`
- [ ] T002 Write failing tests for auto-create store methods — add `TestAutoCreateTask` class to `tests/test_timer_store.py` with: `test_upsert_auto_create_creates_task`, `test_upsert_auto_create_ensures_singleton`, `test_upsert_auto_create_cascades_triggers`, `test_get_auto_create_returns_none_when_empty`, `test_get_auto_create_returns_task`, `test_list_auto_create_triggers`
- [ ] T003 Run store tests to verify they FAIL: `pytest tests/test_timer_store.py::TestAutoCreateTask -v`
- [ ] T004 Implement `upsert_auto_create(self, trigger_at: float, prompt: str | None = None) -> int` in `hatsume/plugins/hatsume-plugin/timer/store.py` — DELETE all rows WHERE task_type='auto_create', INSERT new task with group_id=0, user_id=0, task_type='auto_create', create single trigger with job_id
- [ ] T005 Implement `get_auto_create(self) -> dict | None` and `list_auto_create_triggers(self) -> list[dict]` in `hatsume/plugins/hatsume-plugin/timer/store.py`
- [ ] T006 Run store tests to verify PASS: `pytest tests/test_timer_store.py::TestAutoCreateTask -v`
- [ ] T007 Remove auto-respond constants and add auto-create constants in `hatsume/plugins/hatsume-plugin/config.py` — delete `AUTO_REPLY_CURRENT_MSG_COUNT`, `AUTO_REPLY_HISTORY_MSG_COUNT`, `AUTO_RESPONSE_PROBABILITY`; add `AUTO_CREATE_GROUP_ID`, `AUTO_CREATE_TIME_START=7`, `AUTO_CREATE_TIME_END=22`, `AUTO_CREATE_PROMPT` (detailed creative prompt with 7 activity suggestions, motivation/results/call-to-action output requirements)
- [ ] T008 Run ruff: `ruff check hatsume/plugins/hatsume-plugin/config.py hatsume/plugins/hatsume-plugin/timer/store.py` — expected no errors

**Checkpoint**: DB schema ready, config constants defined. User stories can begin.

---

## Phase 2: User Story 3 — Remove Auto-Respond (Priority: P1) 🎯

**Goal**: Bot stops spontaneously responding to idle group chat; only responds when @-mentioned or during scheduled creative time.

**Independent Test**: Send 50+ messages in a group without @-mentioning the bot. Verify NO auto-response is generated. Then @-mention the bot and verify it still responds normally.

### Tests for US3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T009 [P] [US3] Update `test_tasks_schema_columns` in `tests/test_timer_store.py` to assert `task_type` column exists: add `assert columns["task_type"] == "TEXT"` after `assert columns["updated_at"] == "REAL"`
- [ ] T010 Run updated schema test: `pytest tests/test_timer_store.py::TestInitDb::test_tasks_schema_columns -v` — expected PASS (T001 already added the column)

### Implementation for US3

- [ ] T011 [US3] Remove `AUTO_RESPONSE_PROBABILITY` import and `random` import from `hatsume/plugins/hatsume-plugin/state.py` — update the `.config` import block to remove `AUTO_RESPONSE_PROBABILITY`; delete `import random` line
- [ ] T012 [US3] Remove `has_respond_recently: bool = False` field from `ConversationState` in `hatsume/plugins/hatsume-plugin/state.py`
- [ ] T013 [US3] Remove `should_auto_respond()` method from `ConversationState` in `hatsume/plugins/hatsume-plugin/state.py`
- [ ] T014 [US3] Remove `AUTO_REPLY_CURRENT_MSG_COUNT` and `AUTO_REPLY_HISTORY_MSG_COUNT` from config import in `hatsume/plugins/hatsume-plugin/handlers/chat.py`
- [ ] T015 [US3] Replace auto-respond branch in `user_chat_handle()` in `hatsume/plugins/hatsume-plugin/handlers/chat.py` — replace the entire `if len(conv_state.idle_queue) >= CONTEXT_QUEUE_LEN:` block with: flush to auxiliary (call `conv_state.flush_idle_to_auxiliary()`) then return
- [ ] T016 [US3] Run ruff: `ruff check hatsume/plugins/hatsume-plugin/state.py hatsume/plugins/hatsume-plugin/handlers/chat.py` — expected no errors

**Checkpoint**: Auto-respond fully removed. Bot only responds to @-mentions.

---

## Phase 3: User Story 1 — Auto-Create Timer Core (Priority: P1) 🎯 MVP

**Goal**: Bot autonomously performs a creative task daily at a random time between 7AM-10PM, posts results to the target group without @-mentioning anyone, and self-reschedules.

**Independent Test**: Trigger via `/autocreate` debug command (added in Phase 4) or wait for scheduled fire. Verify creative output appears in target group. Verify a new task is scheduled for tomorrow.

### Tests for US1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T017 [P] [US1] Create `tests/test_auto_create.py` with `TestRandomNextTrigger` class — tests: `test_returns_tomorrow`, `test_time_in_range`, `test_random_distribution` (100 samples). Use importlib module loading pattern matching existing test files (`tests/test_timer_store.py`).
- [ ] T018 Run auto-create tests to verify FAIL: `pytest tests/test_auto_create.py -v` — expected FAIL (functions not yet defined)

### Implementation for US1

- [ ] T019 [US1] Add imports to `hatsume/plugins/hatsume-plugin/timer/executor.py` — add `import random`, `from datetime import datetime, timezone, timedelta`, and `from ..config import AUTO_CREATE_GROUP_ID, AUTO_CREATE_TIME_START, AUTO_CREATE_TIME_END`
- [ ] T020 [US1] Implement `_random_next_trigger() -> float` in `hatsume/plugins/hatsume-plugin/timer/executor.py` — generate tomorrow's date in UTC+8, random hour [7,21], random minute [0,59], return Unix timestamp
- [ ] T021 Run trigger tests to verify PASS: `pytest tests/test_auto_create.py::TestRandomNextTrigger -v`
- [ ] T022 [US1] Implement `_execute_auto_create(task, store)`, `reschedule_auto_create(store)`, `refresh_auto_create(store)` in `hatsume/plugins/hatsume-plugin/timer/executor.py` — `_execute_auto_create` calls `inject_timer(user_id=0, group_id=AUTO_CREATE_GROUP_ID, ...)` then `reschedule_auto_create`; `reschedule_auto_create` calls `_random_next_trigger()` + `store.upsert_auto_create()` + `register_job()`; `refresh_auto_create` purges old tasks then calls `reschedule_auto_create`
- [ ] T023 [US1] Add task_type branch in `_execute_timer()` in `hatsume/plugins/hatsume-plugin/timer/executor.py` — after the `task is None` check, add: `if task.get("task_type") == "auto_create": store.mark_trigger_fired(trigger_id); await _execute_auto_create(task, store); return`
- [ ] T024 [US1] Wire startup refresh in `hatsume/plugins/hatsume-plugin/timer/__init__.py` — update `init_scheduler()` to import and call `await refresh_auto_create(store)` after `await reload_all_triggers(store)`
- [ ] T025 [US1] Handle `user_id=0` in `inject_timer()` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — when `user_id == 0`: use auto-create message format (no user lookup, no @-mention text), skip `chat_peers.add()`. When `user_id != 0`: existing behavior unchanged.
- [ ] T026 [US1] Verify `detect_timer_notification()` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` handles `__timer__:0` correctly — check that parsing `user_id=0` doesn't break detection
- [ ] T027 [US1] Run ruff: `ruff check hatsume/plugins/hatsume-plugin/timer/ hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — expected no errors

**Checkpoint**: Auto-create timer fully functional — fires daily, posts to group, self-reschedules.

---

## Phase 4: User Story 2 — Engaging Output & Debug Command (Priority: P2)

**Goal**: Bot output includes motivation, results, and call-to-action. `/autocreate` debug command available for testing.

**Independent Test**: Run `/autocreate` in the configured debug group. Inspect output — verify all 3 required elements present. Verify no DB modification occurred.

### Implementation for US2

- [ ] T028 [US2] Add `handle_autocreate(bot, event, matcher)` to `hatsume/plugins/hatsume-plugin/handlers/commands.py` — import `AUTO_CREATE_PROMPT` and `inject_timer`, call `inject_timer(user_id=0, group_id=TARGET_GROUP_ID, timer_prompt=AUTO_CREATE_PROMPT, start_conversation_cb=None)`, finish with confirmation message "🎨 Auto create 已触发（调试模式，数据库未修改）"
- [ ] T029 [US2] Register `/autocreate` command in `hatsume/plugins/hatsume-plugin/__init__.py` — import `handle_autocreate` from commands, create `autocreate_cmd = on_command("autocreate", priority=10, block=True)`, add handler calling `handle_autocreate(bot, event, autocreate_cmd)`
- [ ] T030 [US2] Verify `AUTO_CREATE_PROMPT` in `hatsume/plugins/hatsume-plugin/config.py` includes all 3 output requirements: motivation explanation, results presentation, call-to-action with examples (no `/赞我` reference)
- [ ] T031 [US2] Run ruff: `ruff check hatsume/plugins/hatsume-plugin/handlers/commands.py hatsume/plugins/hatsume-plugin/__init__.py` — expected no errors

**Checkpoint**: Debug command operational. Creative output template complete.

---

## Phase 5: Polish & Verification

**Purpose**: Fix existing tests, run full suite, verify complete removal.

- [ ] T032 Remove auto-respond stubs from `tests/test_chat_send.py` — delete `config_mod.AUTO_REPLY_CURRENT_MSG_COUNT = 10`, `config_mod.AUTO_REPLY_HISTORY_MSG_COUNT = 20`, `config_mod.AUTO_RESPONSE_PROBABILITY = 0.5`
- [ ] T033 Remove auto-respond stubs from `tests/test_conversation.py` — delete `mod.AUTO_REPLY_CURRENT_MSG_COUNT = 10`, `mod.AUTO_REPLY_HISTORY_MSG_COUNT = 20`
- [ ] T034 Verify zero auto-respond references remain: `grep -rn "AUTO_REPLY\|AUTO_RESPONSE\|should_auto_respond\|has_respond_recently" hatsume/ tests/` — expected no results
- [ ] T035 Run full test suite: `python -m pytest tests/ -v` — expected ALL tests PASS
- [ ] T036 Run full lint: `ruff check hatsume/plugins/hatsume-plugin/` — expected no errors
- [ ] T037 Verify auto-create constants: `grep -n "AUTO_CREATE" hatsume/plugins/hatsume-plugin/config.py` — expected 4 constants visible
- [ ] T038 Final commit of all changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — can start immediately. BLOCKS all user stories.
- **US3 (Phase 2)**: Depends on Phase 1. No dependency on US1 or US2.
- **US1 (Phase 3)**: Depends on Phase 1. Independent of US3 (different files, no conflicts).
- **US2 (Phase 4)**: Depends on US1 (needs `inject_timer` user_id=0 support and `AUTO_CREATE_*` config).
- **Polish (Phase 5)**: Depends on all prior phases complete.

### User Story Dependencies

- **US3 (P1)**: Can be implemented in parallel with US1 (different files)
- **US1 (P1)**: Can be implemented in parallel with US3
- **US2 (P2)**: Depends on US1 completion

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Store methods before executor logic
- Executor logic before startup wiring
- Core logic before debug command

### Parallel Opportunities

- T002, T007 can run in parallel (different files)
- US3 (Phase 2) and US1 (Phase 3) can be implemented in parallel by different developers
- T032, T033 can run in parallel (different files)

---

## Implementation Strategy

### MVP First (US3 + US1)

1. Complete Phase 1: Foundational (DB + config)
2. Complete Phase 2: US3 (auto-respond removal)
3. Complete Phase 3: US1 (auto-create timer core)
4. **STOP and VALIDATE**: Auto-create task exists after startup, fires on schedule
5. At this point, the bot has autonomous daily creative behavior — MVP achieved

### Single Developer Strategy (Recommended)

Execute sequentially: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
Each phase commits independently. Stop at any checkpoint to validate.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- All code follows existing patterns: print-style logging, async/await, snake_case, type annotations
- Commit after each phase completion
- New test files follow existing importlib-based module loading pattern (see `tests/test_timer_store.py`)
