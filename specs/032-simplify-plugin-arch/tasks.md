# Tasks: Simplify Plugin Architecture

**Input**: Design documents from `/specs/032-simplify-plugin-arch/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: Test suite exists (280 tests). Tests are restored from git HEAD in Phase 1 and used for validation throughout. No new tests needed — this is a pure refactor with zero logic changes.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US4, US5)
- Include exact file paths in descriptions

## Path Conventions

All paths relative to: `hatsume/plugins/hatsume-plugin/`

Tests at: `tests/` (restored from git HEAD in Phase 1)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Restore test suite from git HEAD

- [ ] T001 Restore tests/ directory from git HEAD via `git checkout HEAD -- tests/` and verify 25 files are restored

---

## Phase 2: Dead Code Removal (User Story 4, Priority: P2)

**Purpose**: Remove ~300 lines of dead code. All tasks in this phase are independent and can run in parallel.

**Independent Test**: `grep` for each removed constant/function name finds zero references; `ruff check` clean.

### Dead Constants (config.py)

- [ ] T002 [P] [US4] Remove 22 dead constants + commented-out line from `hatsume/plugins/hatsume-plugin/config.py` — remove DEEPSEEK_API_KEY (L28), NV_API_KEY (L29), OPENCODE_GO_BASE_URL (L38), CCSWITCH_ROUTE_URL (L40), DEEPSEEK_BASE_URL (L41), DOUBAO_1_6_LITE (L47), DOUBAO_2_PRO (L50), DOUBAO_2_1_PRO (L51), DOUBAO_CODE (L52), DEEPSEEK_V4_FLASH (L53), SEEDREAM_4_0 (L55), SEEDREAM_4_5 (L56), KIMI_2_6 (L60), GEMINI_3_1_FLASH_LITE (L61), MINIMAX_3 (L62), DEEPSEEK_V4_PRO (L65), ADVANCE_MODEL_NAME/LITE_MODEL_NAME/MINI_MODEL_NAME (L80-82), commented-out AUTO_CREATE_GROUP_ID (L133), MEMORY_SIX_HOUR_WINDOW (L142), PEOPLE_PRIORITY_RATIO (L146), SHELL_MAX_OUTPUT (L155), CODING_AGENT_SKILL_PATH (L168). Also remove `"ocgo"` case from `get_base_url()` and `get_api_key()`, and remove `"ocgo"` from the Provider Literal type.

### Dead Types & State

- [ ] T003 [P] [US4] Remove 6 dead TypedDicts (PersonEntry, MemoryRecord, SourceEntry, TextContent, ImageContent, ContentPart) and dead `last_image_time` field from `hatsume/plugins/hatsume-plugin/state.py`; clean up unused imports (TypedDict, Union)

- [ ] T004 [P] [US4] Remove dead state from `hatsume/plugins/hatsume-plugin/graph/tools.py`: remove `_last_capture_html_demand` (L78), remove `_update_image_time` from global declaration in `configure_tool_callbacks` (L130)

### Dead Functions

- [ ] T005 [P] [US4] Remove 4 dead prompt builder functions from `hatsume/plugins/hatsume-plugin/prompts.py`: `build_video_failure_prompt` (L274), `build_video_success_prompt` (L282), `build_timer_context_prompt` (L371), `build_timer_task_prompt` (L376)

- [ ] T006 [P] [US4] Remove dead `generate_image_for_gpt_image()` function (~60 lines) from `hatsume/plugins/hatsume-plugin/models.py` (L222-281)

- [ ] T007 [P] [US4] Remove dead `render_html_to_image()` function from `hatsume/plugins/hatsume-plugin/infra.py` (L179-186)

- [ ] T008 [P] [US4] Remove dead `_get_human_sources()` function from `hatsume/plugins/hatsume-plugin/graph/nodes.py` (L418-419)

- [ ] T009 [P] [US4] Remove dead `memory_has_user()` function from `hatsume/plugins/hatsume-plugin/memory/store.py` (L89-94) and its re-export from `memory/__init__.py`

- [ ] T010 [P] [US4] Remove 3 dead timer items from `hatsume/plugins/hatsume-plugin/timer/`: `get_auto_response()` (store.py L271-281), `get_pending_triggers()` (store.py L304-313), `deduplicate_return` branch from `validate_trigger_times()` (store.py L329-354); remove `refresh_auto_create()` (executor.py L249-282) and commented-out call site (timer/__init__.py L38)

- [ ] T011 Commit dead code removal with message: `refactor: remove ~300 lines of dead code across 10 files`

---

## Phase 3: Handlers Merge (User Stories 1 & 2, Priority: P1) 🎯 MVP

**Purpose**: Merge handlers/ from 7 files to 4 files with semantic names.

**Independent Test**: Import `start_chat` from `handlers.dialogue`, `handle_shell` from `handlers.tools`, `handle_like` from `handlers.social` — all function signatures unchanged.

- [ ] T012 [US1] Create `hatsume/plugins/hatsume-plugin/handlers/dialogue.py` by merging forward.py (section 1) + pipeline.py (section 2) + chat.py (section 3) in order. Remove intra-file cross-imports (`from .pipeline import get_human_message`, `from .forward import ...`). Change `from .commands import _wire_conv_state` to `from .tools import _wire_conv_state`.

- [ ] T013 [P] [US2] Create `hatsume/plugins/hatsume-plugin/handlers/tools.py` by merging poke.py (section 1) + commands.py (section 2). All existing exports preserved unchanged.

- [ ] T014 [P] [US2] Rename `hatsume/plugins/hatsume-plugin/handlers/likes.py` → `social.py` with updated docstring. No content changes.

- [ ] T015 [US1] Delete old handler files: `chat.py`, `pipeline.py`, `forward.py`, `commands.py`, `poke.py`, `likes.py` from `hatsume/plugins/hatsume-plugin/handlers/`

- [ ] T016 [US1] Update handlers `__init__.py` to re-export from new module paths (see data-model.md for full list)

- [ ] T017 Commit handlers merge with message: `refactor: merge handlers/ 7→4 files (dialogue+tools+social)`

---

## Phase 4: Memory Merge (User Story 3, Priority: P1)

**Purpose**: Merge memory/ from 5 files to 3 files, eliminate circular import.

**Independent Test**: Call `query_mems("test")`, `add_mem(...)`, `init_db()` — all from `memory.engine` with identical behavior.

- [ ] T018 [US3] Create `hatsume/plugins/hatsume-plugin/memory/engine.py` by merging db.py (section 1) + store.py (section 2) + retrieval.py (section 3) in order. Remove all `from . import db/store/retrieval as _*` imports. Remove lazy `from .store import normalize_memory_object` inside `migrate_from_json()`. Keep `from .tokenizer import tokenize_with_pos` for the tokenizer dependency.

- [ ] T019 [US3] Delete old memory files: `db.py`, `store.py`, `retrieval.py` from `hatsume/plugins/hatsume-plugin/memory/`

- [ ] T020 [US3] Update `memory/__init__.py` to re-export all public functions from `engine.py` and `tokenizer.py` (see data-model.md for full list)

- [ ] T021 Commit memory merge with message: `refactor: merge memory/ 5→3 files (engine.py, eliminate circular import)`

---

## Phase 5: Consolidate Redundant Code (User Story 5, Priority: P3)

**Purpose**: Eliminate duplicate logic patterns.

**Independent Test**: Trigger both agent notification and timer notification — both produce identical conversation-start behavior.

- [ ] T022 [US5] Replace `_start_conv_for_agent` and `_start_conv_for_timer` in `hatsume/plugins/hatsume-plugin/handlers/dialogue.py` with a single `_start_conv_for_trigger(user_id, group_id, notify_msg, *, trigger_type)` function. Update callers in `graph/nodes.py`.

- [ ] T023 Commit redundancy consolidation with message: `refactor: merge duplicate _start_conv functions into _start_conv_for_trigger`

---

## Phase 6: Import & Test Update

**Purpose**: Update all production imports and test stubs, verify correctness.

- [ ] T024 Update all 11 production import sites across 4 files:
  - `__init__.py`: 5 import lines → new module paths
  - `graph/nodes.py`: `handlers.chat` → `handlers.dialogue`; `memory.store` → `memory.engine`
  - `graph/tools.py`: `memory.store` → `memory.engine`; `memory.retrieval` → `memory.engine`
  - (See plan.md and data-model.md for exact before→after mappings)

- [ ] T025 Update all `sys.modules["..."]` test stubs across ~25 test files:
  - `memory.store` → `memory.engine`
  - `memory.retrieval` → `memory.engine`
  - `memory.db` → `memory.engine`
  - `handlers.chat` → `handlers.dialogue`
  - `handlers.pipeline` → `handlers.dialogue`
  - `handlers.forward` → `handlers.dialogue`
  - `handlers.commands` → `handlers.tools`
  - `handlers.poke` → `handlers.tools`
  - Both hyphen (`hatsume-plugin`) and underscore (`hatsume_plugin`) forms

- [ ] T026 Clean up 3 already-dead test stub references (graph.nodes.ai, file_transfer, handlers.conversation)

- [ ] T027 Commit import/test updates with message: `refactor: update all imports and test stubs to new module paths`

---

## Phase 7: Verification & Polish

**Purpose**: Ensure everything works, lint clean, finalize.

- [ ] T028 Run full test suite: `python -m pytest tests/ -x --tb=short` — expect all 280 tests pass. Fix any failures iteratively.

- [ ] T029 Run ruff check: `ruff check hatsume/plugins/hatsume-plugin/ --select F,E,W` — fix any new lint errors.

- [ ] T030 Verify zero stale references remain: `grep -rn "handlers\.chat\|handlers\.pipeline\|handlers\.forward\|handlers\.commands\|memory\.db\|memory\.store\|memory\.retrieval" hatsume/plugins/hatsume-plugin/ --include="*.py" | grep -v __pycache__` — expect zero results.

- [ ] T031 Final commit with `git add .` per project convention: `refactor: finalize simplify-plugin-arch — 12→7 files, -300 dead lines, all tests green`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Dead Code, US4)**: Depends on Phase 1 (tests restored). All 9 tasks (T002-T010) are [P] — run in parallel.
- **Phase 3 (Handlers Merge, US1+US2)**: Depends on Phase 2 (dead code in handlers files removed first)
- **Phase 4 (Memory Merge, US3)**: Depends on Phase 2 (dead code in memory files removed first). Can run parallel to Phase 3.
- **Phase 5 (Consolidation, US5)**: Depends on Phase 3 (chat.py is now in dialogue.py)
- **Phase 6 (Import Update)**: Depends on Phases 3, 4, 5 (new module names exist)
- **Phase 7 (Verification)**: Depends on Phase 6

### Parallel Opportunities

- **Phase 2**: All 9 dead-code tasks (T002-T010) target different files — FULLY PARALLEL
- **Phase 3 vs Phase 4**: Handlers merge and memory merge are INDEPENDENT — can run in parallel
- **Phase 3 internal**: T012 (dialogue.py), T013 (tools.py), T014 (social.py) target different files — PARALLEL

### User Story Dependencies

- **US4 (Dead Code)**: Foundation — must complete first. No dependencies on other stories.
- **US1+US2 (Handlers Merge)**: Depends on US4. Independent of US3.
- **US3 (Memory Merge)**: Depends on US4. Independent of US1+US2.
- **US5 (Redundancy)**: Depends on US1+US2 (needs dialogue.py)

---

## Parallel Example: Phase 2 (Dead Code)

```bash
# Launch all 9 dead-code tasks simultaneously:
Task: "Remove 22 dead constants from config.py"
Task: "Remove dead TypedDicts + last_image_time from state.py"
Task: "Remove dead state from graph/tools.py"
Task: "Remove 4 dead prompt functions from prompts.py"
Task: "Remove dead generate_image_for_gpt_image from models.py"
Task: "Remove dead render_html_to_image from infra.py"
Task: "Remove dead _get_human_sources from graph/nodes.py"
Task: "Remove dead memory_has_user from memory/store.py"
Task: "Remove dead timer methods + refresh_auto_create"
```

---

## Implementation Strategy

### MVP First (Phase 1 + 2 + 3 + 6 + 7)

1. Complete Phase 1: Restore tests
2. Complete Phase 2: Remove all dead code (parallel, fast)
3. Complete Phase 3: Merge handlers (the core architectural change)
4. Complete Phase 6: Update imports & tests
5. Complete Phase 7: Verify — all tests pass, lint clean
6. **STOP**: This is a deployable increment — cleaner handlers, all dead code gone

### Full Delivery

1. MVP above → handlers simplified ✅
2. Add Phase 4: Merge memory → memory simplified, circular import gone ✅
3. Add Phase 5: Consolidate redundancy → cleaner code ✅
4. Final Phase 7 verification → all green ✅

---

## Notes

- [P] tasks = different files, no dependencies — run in parallel
- [Story] label maps task to specific user story for traceability
- This is a pure refactor — no new tests needed, no behavior changes
- The companion plan at `docs/superpowers/plans/2026-07-15-merge-handlers-memory.md` has detailed edit instructions for each task
- Commit after each phase (as shown)
- Stop at any checkpoint to validate the phase independently
