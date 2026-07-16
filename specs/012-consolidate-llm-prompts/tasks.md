# Tasks: Consolidate LLM Prompts

**Input**: Design documents from `specs/012-consolidate-llm-prompts/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Not requested — existing test suite serves as regression safety net. No new tests needed for pure refactoring.

**Organization**: Tasks are grouped by work units. Since this is a pure refactoring, all work centers on relocating prompts to one file, then updating consumers.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Project root: `hatsume/plugins/hatsume-plugin/`
- All paths relative to repository root

---

## Phase 1: Core — Add All Prompts to `prompts.py`

**Purpose**: Centralize all 15 prompt definitions into the single source of truth. This phase BLOCKS all consumer file updates.

- [ ] T001 Add 8 prompt constants and 11 builder functions to `hatsume/plugins/hatsume-plugin/prompts.py` — append after `build_skill_prompt()`, organized in 4 sections: Graph Node Prompts (AUXILIARY_COMPACTION_PROMPT, FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX/SUFFIX, build_face_emotion_classifier_prompt, CHAT_END_DETECT_PROMPT, MEMORY_RECORDING_PROMPT, build_memory_context_prompt), Tool Prompts (WEB_BROWSER_AGENT_PROMPT, HTML_GENERATION_PROMPT, build_web_result_rephrase_prompt, build_video_failure_prompt, build_video_success_prompt), Feature Prompts (NIGHT_COMIC_STORY_PROMPT, build_night_comic_image_prompt, build_like_failure_prompt, build_like_success_prompt), Timer Prompts (build_timer_system_prompt, build_timer_context_prompt, build_timer_task_prompt)

- [ ] T002 Verify prompts.py syntax: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/prompts.py').read()); print('Syntax OK')"`

**Checkpoint**: All prompts defined in one file — consumer updates can now begin in parallel

---

## Phase 2: Update Graph Node Consumers

**Purpose**: Replace inline prompts in LangGraph nodes with imports from prompts.py. Covers US1 (all prompts findable in one place) and US2 (prompt changes don't require touching business logic).

### User Story 1 & 2 — AI Node (Priority: P1) 🎯

**Goal**: Replace 3 inline prompts in ai.py with imports

**Independent Test**: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/graph/nodes/ai.py').read()); print('Syntax OK')"`

- [ ] T003 [P] [US1] Update imports in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` — add AUXILIARY_COMPACTION_PROMPT, build_face_emotion_classifier_prompt, build_memory_context_prompt to existing `from ...prompts import` line

- [ ] T004 [P] [US1] Replace auxiliary compaction SystemMessage (lines 83-87) in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` with `SystemMessage(AUXILIARY_COMPACTION_PROMPT)`

- [ ] T005 [P] [US1] Replace memory context HumanMessage (lines 178-182) in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` with `HumanMessage(build_memory_context_prompt(memory_summary))`

- [ ] T006 [P] [US1] Replace face emotion classifier system_prompt (lines 248-257) in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` with `system_prompt=build_face_emotion_classifier_prompt(list(face_dict.keys()))`

- [ ] T007 Verify ai.py syntax: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/graph/nodes/ai.py').read()); print('Syntax OK')"`

### User Story 1 & 2 — Detect Node (Priority: P1)

**Goal**: Replace 1 inline prompt in detect.py with import

**Independent Test**: Same syntax check pattern

- [ ] T008 [P] [US1] Add `from ...prompts import CHAT_END_DETECT_PROMPT` to `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py` and replace inline SystemMessage (lines 51-92) with `SystemMessage(CHAT_END_DETECT_PROMPT)`

- [ ] T009 Verify detect.py syntax

### User Story 1 & 2 — Finish Node (Priority: P1)

**Goal**: Replace 1 inline prompt in finish.py with import

**Independent Test**: Same syntax check pattern

- [ ] T010 [P] [US1] Add `from ...prompts import MEMORY_RECORDING_PROMPT` to `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py` and replace inline system_prompt (lines 52-68) with `system_prompt=MEMORY_RECORDING_PROMPT`

- [ ] T011 Verify finish.py syntax

**Checkpoint**: All graph node prompts consolidated — 3 files updated

---

## Phase 3: Update Tool & Handler Consumers

**Purpose**: Replace inline prompts in tools and handler files with imports. All tasks in this phase can run in parallel (different files, no inter-dependencies).

### User Story 1 & 2 — Tools (Priority: P1)

**Goal**: Replace 5 inline prompts in tools.py with imports

- [ ] T012 [P] [US1] Add module-level imports to `hatsume/plugins/hatsume-plugin/graph/tools.py`: HTML_GENERATION_PROMPT, WEB_BROWSER_AGENT_PROMPT, build_video_failure_prompt, build_video_success_prompt, build_web_result_rephrase_prompt

- [ ] T013 [P] [US1] Replace video failure prompt (line 382) in `hatsume/plugins/hatsume-plugin/graph/tools.py` with `build_video_failure_prompt(prompt)`

- [ ] T014 [P] [US1] Replace video success prompt (lines 386-390) in `hatsume/plugins/hatsume-plugin/graph/tools.py` with `build_video_success_prompt(prompt, audio_note)`

- [ ] T015 [P] [US1] Replace web browser agent system_prompt (lines 448-456) in `hatsume/plugins/hatsume-plugin/graph/tools.py` with `system_prompt=WEB_BROWSER_AGENT_PROMPT`

- [ ] T016 [P] [US1] Replace web result rephrase HumanMessage (lines 480-484) in `hatsume/plugins/hatsume-plugin/graph/tools.py` with `HumanMessage(build_web_result_rephrase_prompt(demand))`

- [ ] T017 [P] [US1] Delete `_HTML_GENERATION_SYSTEM_PROMPT` variable (lines 499-505) in `hatsume/plugins/hatsume-plugin/graph/tools.py` and replace its usage in `capture_html_shot()` with `HTML_GENERATION_PROMPT`

- [ ] T018 Verify tools.py syntax

### User Story 1 & 2 — Night Comic (Priority: P1)

**Goal**: Replace 2 inline prompts in night_comic.py with imports

- [ ] T019 [P] [US1] Add import `from ..prompts import NIGHT_COMIC_STORY_PROMPT, build_night_comic_image_prompt` to `hatsume/plugins/hatsume-plugin/handlers/night_comic.py`

- [ ] T020 [P] [US1] Replace story generation SystemMessage (lines 114-119) in `hatsume/plugins/hatsume-plugin/handlers/night_comic.py` with `SystemMessage(NIGHT_COMIC_STORY_PROMPT)`

- [ ] T021 [P] [US1] Replace image generation prompt (lines 133-142) in `hatsume/plugins/hatsume-plugin/handlers/night_comic.py` with `build_night_comic_image_prompt(story, user_tuples[0][1], user_tuples[1][1], img_style)`

- [ ] T022 Verify night_comic.py syntax

### User Story 1 & 2 — Likes (Priority: P1)

**Goal**: Replace 2 inline prompts in likes.py with imports

- [ ] T023 [P] [US1] Update import in `hatsume/plugins/hatsume-plugin/handlers/likes.py`: change `from ..prompts import role_sys_prompt` to `from ..prompts import build_like_failure_prompt, build_like_success_prompt, role_sys_prompt`

- [ ] T024 [P] [US1] Replace like failure HumanMessage (lines 85-89) in `hatsume/plugins/hatsume-plugin/handlers/likes.py` with `HumanMessage(build_like_failure_prompt(user_name))`

- [ ] T025 [P] [US1] Replace like success HumanMessage (lines 103-109) in `hatsume/plugins/hatsume-plugin/handlers/likes.py` with `HumanMessage(build_like_success_prompt(user_name, like_time, _get_like_times(event.get_user_id())))`

- [ ] T026 Verify likes.py syntax

### User Story 1 & 2 — Timer (Priority: P1)

**Goal**: Replace 3 inline prompts in executor.py with imports

- [ ] T027 [P] [US1] Update import in `hatsume/plugins/hatsume-plugin/timer/executor.py`: change `from ..prompts import role_sys_prompt` to `from ..prompts import build_timer_context_prompt, build_timer_system_prompt, build_timer_task_prompt, role_sys_prompt`

- [ ] T028 [P] [US1] Replace timer system prompt builder (lines 168-174) in `hatsume/plugins/hatsume-plugin/timer/executor.py` with `build_timer_system_prompt(creator_info, group_id, prompt)`

- [ ] T029 [P] [US1] Replace timer context HumanMessage (lines 302-303) in `hatsume/plugins/hatsume-plugin/timer/executor.py` with `HumanMessage(build_timer_context_prompt(ctx_text))`

- [ ] T030 [P] [US1] Replace timer task HumanMessage (line 305) in `hatsume/plugins/hatsume-plugin/timer/executor.py` with `HumanMessage(build_timer_task_prompt(task_prompt))`

- [ ] T031 Verify executor.py syntax

**Checkpoint**: All consumer files updated — 7 files total, all prompts relocated

---

## Phase 4: Verification & Polish

**Purpose**: Run full regression validation. Covers US3 (no behavioral changes).

- [ ] T032 [US3] Run full test suite: `python -m pytest tests/ -xvs`

- [ ] T033 [US3] Run ruff lint: `ruff check hatsume/plugins/hatsume-plugin/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Core)**: No dependencies — must complete FIRST, blocks all consumer updates
- **Phase 2 (Graph Nodes)**: Depends on Phase 1 — T003-T011 can run in parallel within Phase 2
- **Phase 3 (Tools & Handlers)**: Depends on Phase 1 — T012-T031 can all run in parallel with each other and with Phase 2
- **Phase 4 (Verification)**: Depends on Phases 1-3 completion

### User Story Dependencies

All 3 user stories are P1 and implemented simultaneously across Phases 1-3:
- **US1** (findability): Satisfied by Phase 1 — all prompts in one file
- **US2** (maintainability): Satisfied by Phases 2-3 — imports replace inlines
- **US3** (no regressions): Verified in Phase 4 — tests pass, lint clean

### Parallel Opportunities

- T003-T006 (ai.py edits) can run sequentially but the ai.py file itself is independent of other nodes
- T008, T010 (detect.py, finish.py) can run in parallel with T003-T006
- T012-T018 (tools.py) can run in parallel with all Phase 2 tasks
- T019-T022 (night_comic.py) can run in parallel with all other Phase 2-3 tasks
- T023-T026 (likes.py) can run in parallel with all other Phase 2-3 tasks
- T027-T031 (executor.py) can run in parallel with all other Phase 2-3 tasks

---

## Parallel Example: Phase 2-3 Consumer Updates

```bash
# All consumer files are independent once prompts.py is done (Phase 1):
# Launch ai.py updates (T003-T007)
# Launch detect.py update (T008-T009)
# Launch finish.py update (T010-T011)
# Launch tools.py updates (T012-T018)
# Launch night_comic.py updates (T019-T022)
# Launch likes.py updates (T023-T026)
# Launch executor.py updates (T027-T031)
```

---

## Implementation Strategy

### MVP First (Phase 1 Only)

1. Complete Phase 1: Add all prompts to prompts.py
2. **STOP and VALIDATE**: Verify syntax, check all prompts are present
3. At this point US1 (findability) is satisfied — all prompts in one file

### Incremental Delivery

1. Phase 1 → prompts.py enriched → US1 done
2. Phase 2 → graph nodes updated → US2 progressing
3. Phase 3 → tools & handlers updated → US2 done
4. Phase 4 → validation → US3 confirmed
5. Each phase delivers measurable progress

---

## Notes

- [P] tasks = different files, no dependencies — 80% of tasks are [P]
- Pure refactoring — no test changes needed (existing tests verify US3)
- `role_sys_prompt` and `build_skill_prompt()` remain unchanged in prompts.py
- Internal control signals (`__end__`, etc.) stay in their current locations
- Skill files (`data/hatsume-plugin/skills/*.md`) are out of scope
