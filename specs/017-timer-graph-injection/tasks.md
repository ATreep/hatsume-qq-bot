# Tasks: Timer Graph Injection

**Input**: Design documents from `/specs/017-timer-graph-injection/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: TDD — tests written before implementation per `superpowers:test-driven-development`.

**Organization**: Tasks grouped by user story for independent implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths in all descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Goal**: Create test file and verify project is ready for changes

- [x] T001 Create test file with stubs at `tests/test_timer_injection.py` — include `MockMessage`, `MockState`, `_load_ai_module()` helper, and placeholder test classes
- [x] T002 Verify test file loads successfully: `python -m pytest tests/test_timer_injection.py -v` (expected: tests collected but FAIL since functions not yet defined)

---

## Phase 2: Foundational — TIMER_MARK Detection & Injection (Blocks US1, US2, US3)

**Goal**: Add `TIMER_MARK`, `detect_timer_notification()`, and `inject_timer()` to `graph/nodes/ai.py`. These are shared by all three user stories.

- [x] T003 [P] Write failing tests for `detect_timer_notification` in `tests/test_timer_injection.py` (test_detects_string_content, test_detects_list_content, test_returns_none_for_regular_message, test_returns_none_for_agent_notify)
- [x] T004 Write failing tests for `inject_timer` in `tests/test_timer_injection.py` (test_injects_into_human_queue_when_chatting, test_calls_start_conversation_cb_when_not_chatting, test_no_callback_when_not_chatting_no_cb)
- [x] T005 [P] Run tests to verify they fail: `python -m pytest tests/test_timer_injection.py -v` (expected: FAIL)
- [x] T006 Add `TIMER_MARK = "__timer__"` constant after line 47 in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [x] T007 Add `detect_timer_notification(state) -> int | None` function after line 74 in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — scan last message content for `__timer__:` prefix, extract user_id via `split(":", 1)`
- [x] T008 Add `inject_timer(user_id, timer_prompt, context, start_conversation_cb=None)` function after line 110 in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — build marked message, append to human_queue if chatting, call cb if not
- [x] T009 Run tests to verify they pass: `python -m pytest tests/test_timer_injection.py -v` (expected: ALL PASS)
- [x] T010 Commit: `git add tests/test_timer_injection.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py && git commit -m "feat: add TIMER_MARK, detect_timer_notification, inject_timer to ai.py"`

---

## Phase 3: User Story 1 — Timer Fires During Active Chat (Priority: P1) 🎯 MVP

**Goal**: Timer injects into active conversation's human_queue and the AI responds with @-mention.

**Independent Test**: Set a 1-minute timer while bot is actively chatting → verify response within same conversation flow with @-mention.

- [x] T011 [US1] Add `detect_timer_notification` import in `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py` line 15: change import to `from .ai import detect_agent_notification, detect_timer_notification`
- [x] T012 [US1] Add timer check in `chat_end_detect_node` in `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py` after line 23: `if detect_timer_notification(state) is not None: return {"messages": []}`
- [x] T013 [P] [US1] Run existing tests to verify no regression: `python -m pytest tests/test_graph_nodes.py -v` (expected: ALL PASS)
- [x] T014 [US1] Add `timer_uid = detect_timer_notification(state)` after line 213 in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` (ai_node function)
- [x] T015 [US1] Add `timer_uid` @-mention branch in ai_node response section (after line 269) in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — when timer_uid is not None, use `ai_answer_with_at` to @-mention timer creator
- [x] T016 [US1] Run tests: `python -m pytest tests/test_timer_injection.py -v` (expected: ALL PASS)
- [x] T017 Commit: `git add hatsume/plugins/hatsume-plugin/graph/nodes/detect.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py && git commit -m "feat: wire timer detection into detect_node and ai_node @mention"`

---

## Phase 4: User Story 2 — Timer Fires When Bot Is Idle (Priority: P2)

**Goal**: Timer starts a new conversation when no conversation is active.

**Independent Test**: Bot idle → set 1-min timer → verify bot starts new conversation and @-mentions creator.

- [x] T018 [US2] Add `_start_conv_for_timer(user_id, notify_msg)` function after `_start_conv_for_agent` in `hatsume/plugins/hatsume-plugin/handlers/chat.py` — mirrors `_start_conv_for_agent` exactly: sets ai_cb, activates chat, spawns new conversation
- [x] T019 [US2] Register `_start_conv_for_timer` with executor: add `from ..timer.executor import set_timer_conv_callback` and `set_timer_conv_callback(_start_conv_for_timer)` after line 72 in `hatsume/plugins/hatsume-plugin/handlers/chat.py`
- [x] T020 [US2] Run existing tests: `python -m pytest tests/test_conversation.py tests/test_timer_injection.py -v` (expected: ALL PASS)
- [x] T021 Commit: `git add hatsume/plugins/hatsume-plugin/handlers/chat.py && git commit -m "feat: add _start_conv_for_timer callback and wiring"`

---

## Phase 5: User Story 3 — Timer Integrates With Existing Conversation Flow (Priority: P3)

**Goal**: Replace standalone agent with graph injection. Multiple timers and agent_allocate coexist without conflict.

**Independent Test**: Set multiple timers (1 min apart) → all delivered in order. Timer + agent_allocate → both complete without interference.

- [x] T022 [US3] Remove `_run_timer_agent`, `_save_tools_globals`, `_restore_tools_globals` (lines 242-347) from `hatsume/plugins/hatsume-plugin/timer/executor.py`
- [x] T023 [US3] Add `_timer_start_conv_cb`, `set_timer_conv_callback(cb)`, and `_inject_timer_to_graph(user_id, group_id, sys_prompt, task_prompt, context_msgs)` after `_fetch_recent_messages` in `hatsume/plugins/hatsume-plugin/timer/executor.py`
- [x] T024 [US3] Update `_execute_timer` in `hatsume/plugins/hatsume-plugin/timer/executor.py` — replace lines 170-208 (old agent call + delivery) with: build system prompt → `await _inject_timer_to_graph(...)` → `store.mark_trigger_fired(trigger_id)`
- [x] T025 [P] [US3] Add round-trip test in `tests/test_timer_injection.py`: `TestTimerInjectionRoundTrip.test_inject_timer_to_graph_builds_correct_context` — verifies full message format with timer mark, context, and task prompt
- [x] T026 [US3] Run all tests: `python -m pytest tests/test_timer_injection.py tests/test_timer_store.py tests/test_graph_nodes.py tests/test_conversation.py -v` (expected: ALL PASS)
- [x] T027 Ruff lint: `ruff check hatsume/plugins/hatsume-plugin/timer/executor.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [x] T028 Commit: `git add hatsume/plugins/hatsume-plugin/timer/executor.py tests/test_timer_injection.py && git commit -m "feat: replace _run_timer_agent with _inject_timer_to_graph"`

---

## Phase 6: Polish & Export

**Goal**: Update module exports and final verification.

- [x] T029 [P] Update `hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py` to export `detect_timer_notification`, `inject_timer`, `TIMER_MARK`
- [x] T030 Final test run: `python -m pytest tests/test_timer_injection.py tests/test_timer_store.py tests/test_graph_nodes.py tests/test_conversation.py -v`
- [x] T031 Final commit: `git add . && git commit -m "feat: export timer detection/injection from graph.nodes, complete timer graph injection"`

---

## Dependencies

```
Phase 1 (Setup: T001-T002)
  ↓
Phase 2 (Foundational: T003-T010) ← blocks ALL user stories
  ↓
  ├─ Phase 3 (US1: T011-T017) ← no dependency on US2 or US3
  ├─ Phase 4 (US2: T018-T021) ← depends on Phase 2 only
  └─ Phase 5 (US3: T022-T028) ← depends on Phase 2, Phase 4 (needs callback)
  ↓
Phase 6 (Polish: T029-T031) ← depends on all phases
```

## Parallel Opportunities

| Task Group | Parallel Tasks |
|------------|---------------|
| Phase 2 tests | T003 (detect tests) and T004 (inject tests) can be written simultaneously |
| US1 + US2 | After Phase 2, US1 (T011-T017) and US2 (T018-T021) can run in parallel |
| US3 integration test | T025 can be written in parallel with T022-T024 |

## MVP Scope

**User Story 1 only** (Phases 1 + 2 + 3): Timer fires during active chat → injection works. This delivers the core value of replacing the standalone agent with graph injection when a conversation is already running. Phases 4-6 can follow incrementally.

## Implementation Strategy

1. **MVP First** (Phases 1-3): Deliver core timer injection into active conversations
2. **Incremental** (Phase 4): Add idle-case conversation start
3. **Complete** (Phase 5): Remove standalone agent, integrate fully
4. **Polish** (Phase 6): Export, lint, final verification

Each phase produces independently testable, committable code.
