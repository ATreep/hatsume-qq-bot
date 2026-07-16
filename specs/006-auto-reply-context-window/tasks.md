# Tasks: 自动回复上下文窗口优化

**Input**: Design documents from `/specs/006-auto-reply-context-window/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: No new test files required (logic-only change to existing flow). Verification via manual testing per quickstart.md.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Changes confined to existing NoneBot2 plugin:
- `hatsume/plugins/hatsume-plugin/config.py`
- `hatsume/plugins/hatsume-plugin/handlers/chat.py`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No new project setup needed — this is a minimal change to an existing project. Configuration constants are the only "infrastructure" and serve as Phase 2.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add configurable constants that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until config constants are in place

- [x] T001 Add `AUTO_REPLY_CURRENT_MSG_COUNT = 10` and `AUTO_REPLY_HISTORY_MSG_COUNT = 20` constants in `hatsume/plugins/hatsume-plugin/config.py` (Behavioral Constants section, near `CONTEXT_QUEUE_LEN`)

**Checkpoint**: Config constants ready — user story implementation can now begin

---

## Phase 3: User Story 1 + 2 - 自动回复聚焦最近话题 & AI获得完整背景 (Priority: P1) 🎯 MVP

**Goal**: Modify auto-reply message assembly to split context into "当前聊天记录" (last 10 msgs) and "历史聊天记录" (up to 20 prior msgs), so the bot replies to recent topics while AI retains full background.

**Independent Test**: Trigger auto-reply with 30 messages in queue; verify AI receives "## 当前聊天记录：" (10 msgs) + "## 历史聊天记录：" (up to 20 msgs) markers, and reply focuses on recent topics.

**Note**: US1 and US2 are implemented as a single code change — the message split simultaneously achieves both "focus on recent" (US1) and "background context" (US2).

### Implementation for User Story 1 + 2

- [x] T002 [US1] Import `append_auxiliary_message` and new config constants in `hatsume/plugins/hatsume-plugin/handlers/chat.py` (add to existing import block from `..graph.nodes` and `..config`)
- [x] T003 [US1] Implement message split logic in `user_chat_handle()` auto-reply path in `hatsume/plugins/hatsume-plugin/handlers/chat.py`: split `messages[CONTEXT_QUEUE_OVERLAP_LEN:]` into history (first part) and current (last `AUTO_REPLY_CURRENT_MSG_COUNT`), append history to auxiliary queue via `append_auxiliary_message()`, pass only current to `start_new_conversation()`
- [x] T004 [US1] Verify edge case handling in split logic: when total messages ≤ N (all go to current), when total < N+M (current = N, remaining = history), per FR-007 in `hatsume/plugins/hatsume-plugin/handlers/chat.py`

**Checkpoint**: US1 + US2 fully functional — auto-reply now splits context with markers. This is the MVP.

---

## Phase 4: User Story 3 - 低活跃群聊不触发对过时内容的回复 (Priority: P2)

**Goal**: In low-activity groups where messages span hours, the split ensures only recent messages appear in "current chat", preventing stale-topic replies.

**Independent Test**: Simulate messages spanning 5+ hours; verify auto-reply "当前聊天记录" contains only the most recent 10 messages, not earlier ones.

**Note**: US3 is largely a consequence of US1+US2 implementation — the message split inherently prevents stale-topic replies. This phase focuses on manual verification.

### Implementation for User Story 3

- [x] T005 [US3] Manual verification: simulate low-activity scenario (30 messages over 5+ hours), confirm auto-reply context shows only recent 10 as "当前聊天记录" per quickstart.md verification steps
- [x] T006 [US3] Verify the `has_respond_recently` toggle still works correctly after the split logic change (no regression in auto-reply triggering cadence)

**Checkpoint**: US3 verified — low-activity scenarios no longer produce stale replies. All user stories complete.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T007 Run existing pytest suite to verify no regressions: `cd /path/to/hatsume && python -m pytest tests/ -v`
- [x] T008 Verify @-triggered conversation flow is unaffected (smoke test: @bot with a message, confirm normal reply behavior)
- [x] T009 Code review: confirm history/current split has no overlap (FR-005), sources arrays stay aligned with messages, no off-by-one errors

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: N/A — existing project
- **Foundational (Phase 2)**: No dependencies — T001 can start immediately
- **User Stories 1+2 (Phase 3)**: Depends on Phase 2 (T001) — needs config constants
- **User Story 3 (Phase 4)**: Depends on Phase 3 — verification of split behavior
- **Polish (Phase 5)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 + US2 (P1)**: Both served by same code change in T002-T004. No separation needed.
- **US3 (P2)**: Depends on US1+US2 completion. Verification-only phase.

### Within Each Phase

- T002 → T003 → T004 (sequential: import → logic → edge cases)
- T005, T006 can run in parallel (both are verification tasks)
- T007, T008, T009 can run in parallel (independent checks)

### Parallel Opportunities

```
Phase 2:  T001 (single task, no parallelism needed)
Phase 3:  T002 → T003 → T004 (sequential dependency chain)
Phase 4:  T005, T006 (parallel — different verification concerns)
Phase 5:  T007, T008, T009 (parallel — different test suites)
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only — Phase 2 + 3)

1. Complete T001: Add config constants
2. Complete T002-T004: Implement message split + edge cases
3. **STOP and VALIDATE**: Trigger auto-reply, verify "## 当前聊天记录：" / "## 历史聊天记录：" markers
4. Deploy if ready — this already solves the core problem

### Full Delivery

1. MVP (Phase 2 + 3) → Deploy
2. Add Phase 4 verification → Confirm low-activity fix
3. Add Phase 5 polish → Regression tests, code review
4. All user stories independently verified

### Single Developer Strategy

Estimated time: 30-60 minutes total
1. T001 (5 min) — add 2 lines to config.py
2. T002-T004 (15 min) — modify ~15 lines in chat.py
3. T005-T006 (10 min) — manual verification
4. T007-T009 (10 min) — tests + review

---

## Notes

- Only 2 files modified, ~20 lines total — minimal risk of regression
- The existing `human_node` pattern (`## 历史聊天记录：` / `## 当前聊天记录：`) is reused without modification
- `append_auxiliary_message()` already handles the compression (>80 messages) case — no new edge cases introduced
- @-triggered conversation flow is untouched — zero risk of breaking it
- Commit after each task or logical group
