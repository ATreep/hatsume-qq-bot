# Tasks: Face Emoji Injection + Auto-Create 24h

**Input**: Design documents from `specs/025-face-injection-autocreate-24h/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md

**Tests**: Tests are included — the feature spec and project CLAUDE.md mandate TDD and test coverage.

**Organization**: Tasks grouped by user story for independent implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Verify prerequisites, no new scaffolding needed

- [ ] T001 Verify all existing tests pass before changes: `python -m pytest tests/ -xvs`

---

## Phase 2: Foundational — Face Injection Prompt Builder (Blocks US1, US2)

**Purpose**: The `build_face_injection_prompt()` function that both US1 and US2 depend on

**⚠️ CRITICAL**: US1 and US2 cannot start until this phase is complete

- [ ] T002 Remove `FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX`, `FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX`, and `build_face_emotion_classifier_prompt()` in `hatsume/plugins/hatsume-plugin/prompts.py`
- [ ] T003 Add `build_face_injection_prompt(emotions: list[str]) -> str` in `hatsume/plugins/hatsume-plugin/prompts.py` — returns empty string if emotions empty, otherwise returns `# 表情发送` section with dynamic emotion list
- [ ] T004 Verify syntax: `python -c "from hatsume.plugins.hatsume_plugin.prompts import build_face_injection_prompt; print(build_face_injection_prompt(['开心','生气']))"`

**Checkpoint**: Face injection prompt builder ready — US1 and US2 can proceed

---

## Phase 3: User Story 1 — AI Sends Emotion-Appropriate Face Image (Priority: P1) 🎯 MVP

**Goal**: When gate conditions pass, the LLM can express emotion via `<hatsumeface>` tag in its reply, and the system sends a matching face image. No second LLM call.

**Independent Test**: Trigger conversation in a group chat, verify `[face]` log lines appear and face images are sent after text replies when conditions allow.

### Tests for User Story 1

- [ ] T005 [P] [US1] Update mock: replace `build_face_emotion_classifier_prompt` with `build_face_injection_prompt` in `tests/test_graph_nodes.py:246`
- [ ] T006 [P] [US1] Rewrite `test_generate_image_used_skips_maybe_send_face` → `test_generate_image_used_skips_face_injection` in `tests/test_graph_nodes.py` — verify `# 表情发送` NOT in sys_prompt when `_generate_image_used=True`
- [ ] T007 [P] [US1] Rewrite `test_face_can_be_called_when_both_flags_false` → `test_face_injection_when_flags_false` in `tests/test_graph_nodes.py` — verify `# 表情发送` IS in sys_prompt when both flags are False

### Implementation for User Story 1

- [ ] T008 [US1] Update imports in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`: replace `build_face_emotion_classifier_prompt` with `build_face_injection_prompt`, add `import re`
- [ ] T009 [US1] Add `FACE_TAG_PATTERN = re.compile(r"<hatsumeface>(.*?)</hatsumeface>")` after `TIMER_MARK` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T010 [US1] Move gate check BEFORE `create_agent`: import `_cap_used`/`_gen_used`, check conditions, scan face files, inject face prompt into `sys_prompt` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T011 [US1] Add tag extraction after `ai_text`: regex search `FACE_TAG_PATTERN`, set `face_emotion` and `ai_text_clean` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T012 [US1] Send `ai_text_clean` (tag stripped) to user via `ai_answer`, preserve `ai_text` (with tag) in `AIMessage` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T013 [US1] Replace old gate + `_maybe_send_face` call with inline face sending: if `face_emotion` matches `_face_dict`, read file, base64-encode, send via `MessageSegment.image` in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T014 [US1] Remove `_maybe_send_face()` function entirely from `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [ ] T015 [US1] Run face tests: `pytest tests/test_graph_nodes.py -k "face" -xvs` — all 3 must PASS
- [ ] T016 [US1] Run full test suite: `python -m pytest tests/ -xvs` — no regressions

**Checkpoint**: US1 complete — face images sent via inline injection, no separate agent call

---

## Phase 4: User Story 2 — Bot Keeps Track of Past Face Choices (Priority: P2)

**Goal**: Face tags remain in AIMessage (graph state) so the LLM sees past face choices in conversation history.

**Independent Test**: Inspect AIMessage content after a face turn — verify tag is present. Users never see the tag.

### Tests for User Story 2

- [ ] T017 [P] [US2] Add `test_face_tag_stripped_from_user_text_preserved_in_aimessage` in `tests/test_graph_nodes.py` — verify tag in AIMessage, tag NOT in user-facing send

### Implementation for User Story 2

> **Note**: US2 behavior is already implemented by US1 code (T012 sends clean text to user, returns original `ai_text` in AIMessage). This phase adds the explicit test.

- [ ] T018 [US2] Verify the `return {"messages": [AIMessage(ai_text)]}` line in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` uses `ai_text` (not `ai_text_clean`)
- [ ] T019 [US2] Run test: `pytest tests/test_graph_nodes.py -k "face_tag_stripped" -xvs` — PASS

**Checkpoint**: US2 complete — face tags preserved in graph state, stripped from user output

---

## Phase 5: User Story 3 — Auto-Create Triggers at Any Time (Priority: P3)

**Goal**: Auto-create fires at any hour of the day, no time window restriction.

**Independent Test**: Check `/timer autocreate` output — next trigger should be 4-6 hours from now regardless of current hour.

### Implementation for User Story 3

- [ ] T020 [US3] Remove `AUTO_CREATE_TIME_START` and `AUTO_CREATE_TIME_END` from `hatsume/plugins/hatsume-plugin/config.py:117-118`
- [ ] T021 [US3] Remove `AUTO_CREATE_TIME_START` and `AUTO_CREATE_TIME_END` from config import in `hatsume/plugins/hatsume-plugin/timer/executor.py:15-17`
- [ ] T022 [US3] Simplify `_random_next_trigger()` in `hatsume/plugins/hatsume-plugin/timer/executor.py:93-138` — remove hour clamping, just return `now + random(4h, 6h)` timestamp
- [ ] T023 [US3] Update `reschedule_auto_create()` docstring in `hatsume/plugins/hatsume-plugin/timer/executor.py:170-172` — remove "clamped to the valid daily window"
- [ ] T024 [US3] Verify syntax: `python -c "from hatsume.plugins.hatsume_plugin.timer.executor import _random_next_trigger; print(_random_next_trigger())"`
- [ ] T025 [US3] Run full test suite: `python -m pytest tests/ -xvs` — no regressions

**Checkpoint**: US3 complete — auto-create fires at any hour

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation across all stories

- [ ] T026 Run full test suite: `python -m pytest tests/ -xvs` — all tests PASS
- [ ] T027 Verify auto-create time calculation: `python -c "import random; from hatsume.plugins.hatsume_plugin.timer.executor import _random_next_trigger; print(_random_next_trigger())"` — prints a valid future timestamp
- [ ] T028 [P] Run ruff lint check: verify no lint errors introduced

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS US1, US2
- **US1 (Phase 3)**: Depends on Foundational — MVP face injection
- **US2 (Phase 4)**: Depends on US1 (shares same code, adds test)
- **US3 (Phase 5)**: Depends on Setup only — INDEPENDENT of US1/US2, can run in parallel
- **Polish (Phase 6)**: Depends on all user stories

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — no other story dependencies
- **US2 (P2)**: After US1 (adds test for US1 behavior)
- **US3 (P3)**: After Phase 1 — completely independent of US1/US2

### Parallel Opportunities

- US3 (T020-T025) can run in PARALLEL with US1+US2 (T005-T019) — different files, no shared state
- Within US1: T005, T006, T007 (tests) can run in parallel before implementation

---

## Implementation Strategy

### MVP First (US1 Only + US3)

1. Complete Phase 1: Setup → T001 ✅
2. Complete Phase 2: Foundational → T002-T004 ✅
3. Complete Phase 3: US1 → T005-T016 ✅ (face injection MVP)
4. Complete Phase 5: US3 → T020-T025 ✅ (auto-create 24h, independent)
5. **STOP and VALIDATE**: Run full test suite
6. Deploy if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → Test → MVP: Face injection working
3. Add US2 → Test → Tag preservation verified
4. Add US3 → Test → Auto-create 24h enabled
5. Polish → Full validation
