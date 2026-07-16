# Tasks: Memory System SQLite Refactor

**Input**: Design documents from `specs/027-memory-sqlite-refactor/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- Plugin code: `hatsume/plugins/hatsume-plugin/`
- Tests: `tests/`
- Data: `data/hatsume-plugin/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration changes needed before any implementation

- [ ] T001 Add `MAX_MEMORY_LIMIT=50` and `MEMORY_SIX_HOUR_WINDOW=21600` to `hatsume/plugins/hatsume-plugin/config.py`, remove `MEMORY_TOP_K` and `BM25_RECALL_K`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: SQLite database layer that ALL user stories depend on for persistence

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T002 [P] Create `tests/test_memory_db.py` with tests for: init_db creates tables, insert+load roundtrip, delete_expired, query_by_user_ids with time window, query_all_except, load_all returns None for empty DB, migrate_from_json
- [ ] T003 Create `hatsume/plugins/hatsume-plugin/memory/db.py` with: `init_db()`, `insert_memory()`, `delete_expired_memories()`, `load_all_memories()`, `query_by_user_ids()`, `query_all_except()`, `migrate_from_json()`
- [ ] T004 [P] Update `hatsume/plugins/hatsume-plugin/memory/__init__.py` to export db functions alongside store/retrieval/tokenizer

**Checkpoint**: Database layer ready — memories can be stored and loaded from SQLite. Run `python -m pytest tests/test_memory_db.py -xvs` to verify.

---

## Phase 3: User Story 1 - Efficient Memory Recording During Conversation (Priority: P1) 🎯 MVP

**Goal**: chat_agent outputs `[memoryrecord: {"content": "...", "people": [...]}]` inline; system parses, strips, and persists — eliminating the separate LLM recording call.

**Independent Test**: Trigger a conversation where a user shares a memorable fact. Verify the bot's reply contains a `[memoryrecord: ...]` tag, the tag is stripped from visible output, and the memory is persisted to SQLite.

### Implementation for User Story 1

- [ ] T005 [P] [US1] Update `hatsume/plugins/hatsume-plugin/prompts.py`: add `# 记忆记录` section to `role_sys_prompt` with inline recording instructions; remove `MEMORY_RECORDING_PROMPT` constant; update test mock in `tests/test_graph_nodes.py` to remove `MEMORY_RECORDING_PROMPT`
- [ ] T006 [P] [US1] Update `hatsume/plugins/hatsume-plugin/graph/tools.py`: remove `write_memory` tool function (lines 169-210) and its imports (`resolve_active_memory_people`); update `query_memory()` signature to accept `user_ids: list[int] | None = None` parameter and pass through to `query_mems()`
- [ ] T007 [US1] Update `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`: add `MEMORY_RECORD_PATTERN` regex, `extract_user_ids_from_content()` function; after face tag extraction, parse `[memoryrecord: {...}]` from `ai_text`, strip tags from `ai_text_clean`, call `add_mem()` for each parsed record after sending reply
- [ ] T008 [US1] Remove recording transcript infrastructure from `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`: delete `_memory_record_transcript`, `_memory_record_source_map`, `reset_memory_record_context()`, `append_memory_record_sources()`, and their usage in `ai_node()` (transcript append calls)
- [ ] T009 [US1] Simplify `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py`: remove `mem_record_agent` creation, `MEMORY_RECORDING_PROMPT` import, `write_memory` import, all memory recording logic; keep only queue cleanup, skill reset, and `[CONVERSATION END]` send; update `tests/test_graph_nodes.py` finish tests accordingly

**Checkpoint**: Inline memory recording works end-to-end. Run `python -m pytest tests/test_graph_nodes.py tests/test_tools.py -xvs -k "not (shell|html|image|timer|agent|skill)"` to verify.

---

## Phase 4: User Story 2 - Contextual Memory Retrieval (Priority: P1)

**Goal**: Two-phase retrieval: user-specific memories (6h window) first, then supplemental fill to MAX_MEMORY_LIMIT=50.

**Independent Test**: Create test memories with varying user associations and timestamps, call `query_mems()` with user_ids, verify ordering and count.

### Implementation for User Story 2

- [ ] T010 [US2] Update `hatsume/plugins/hatsume-plugin/memory/retrieval.py`: replace `query_mems()` with two-phase algorithm — Phase 1 uses `db.query_by_user_ids()` for user-specific 6h window memories scored by BM25+embedding; Phase 2 uses `db.query_all_except()` to fill remaining slots up to `max_limit`; add `_score_memory_rows()` helper; import `db as _db`
- [ ] T011 [US2] Update memory retrieval in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`: change `_MEMORY_TOTAL_LIMIT` from 15 to 50; pass `user_ids=extract_user_ids_from_content(last_content)` to `query_memory()` calls; use updated `query_memory()` signature
- [ ] T012 [US2] Update `tests/test_memory_utils.py`: replace `test_query_mems_prioritizes_sender_related_memories_up_to_thirty_percent` (uses old `preferred_user_id` parameter) with new test using `user_ids` parameter and SQLite db stubbing; remove `test_resolve_active_memory_people_merges_source_people_without_guessing` (function removed)

**Checkpoint**: Two-phase retrieval works. Run `python -m pytest tests/test_memory_utils.py -xvs -k "query_mems"` to verify.

---

## Phase 5: User Story 3 - Persistent Storage with Fast Startup (Priority: P2)

**Goal**: Store memories in SQLite with tokenized corpus and embedding vectors; load on startup without rebuilding indices.

**Independent Test**: Start bot with 100 stored memories, verify no embedding API calls during startup loading.

### Implementation for User Story 3

- [ ] T013 [US3] Refactor `hatsume/plugins/hatsume-plugin/memory/store.py`: remove JSON file I/O (`save_mem_list()`, `_get_memory_data_file()`), `active_memory_sources` mechanism (`set_active_memory_sources()`, `clear_active_memory_sources()`, `resolve_active_memory_people()`, `active_memory_sources` dict); delegate persistence to db.py; add `_get_db()` lazy connection; update `add_mem()` to insert into SQLite + update in-memory structures; update `init_tokenized_corpus()` daily job to use `db.delete_expired_memories()` + `db.load_all_memories()`
- [ ] T014 [US3] Add `init_memory_system()` to `hatsume/plugins/hatsume-plugin/memory/store.py`: on first call, check for JSON→SQLite migration (if `memory.json` exists and DB empty, call `db.migrate_from_json()` then rename JSON to `.bak`); load all memories via `db.load_all_memories()` into in-memory structures; rebuild BM25; call from plugin startup in `hatsume/plugins/hatsume-plugin/__init__.py`
- [ ] T015 [US3] Update `tests/test_memory_utils.py` `load_memory_modules()` helper: add `db` module stub; update config mock with `MAX_MEMORY_LIMIT` and `MEMORY_DB_PATH`; add `_get_db` stub to store module; replace JSON-based test (`test_init_tokenized_corpus_migrates_old_memory_records_with_empty_people`) with SQLite-backed test; ensure `test_add_mem_*` tests pass with new SQLite-backed store

**Checkpoint**: SQLite persistence with fast startup works. Run `python -m pytest tests/test_memory_utils.py tests/test_memory_db.py -xvs` to verify.

---

## Phase 6: User Story 4 - Expired Memory Cleanup (Priority: P3)

**Goal**: Daily maintenance job deletes expired memories from SQLite and reloads in-memory indices.

**Independent Test**: Create memories with old timestamps, trigger maintenance job, verify only expired memories removed.

### Implementation for User Story 4

- [ ] T016 [US4] Verify daily maintenance in `hatsume/plugins/hatsume-plugin/memory/store.py`: `init_tokenized_corpus()` correctly calls `db.delete_expired_memories()`, reloads via `db.load_all_memories()`, and rebuilds BM25; expired memories permanently deleted from SQLite
- [ ] T017 [US4] Verify `tests/test_memory_utils.py` daily maintenance test (`test_init_tokenized_corpus_expires_old_memories_from_db`) passes with updated SQLite-backed store

**Checkpoint**: Expired memory cleanup works correctly with SQLite backend.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Integration testing, cleanup, documentation

- [ ] T018 [P] Run full test suite and fix any regressions: `python -m pytest tests/test_memory_db.py tests/test_memory_utils.py tests/test_graph_nodes.py tests/test_tools.py -xvs`
- [ ] T019 [P] Search for stale references to removed symbols: `rg "write_memory|MEMORY_RECORDING_PROMPT|save_mem_list|active_memory_sources|_memory_record_transcript|resolve_active_memory_people|MEMORY_TOP_K|BM25_RECALL_K" hatsume/ --include="*.py"` — fix any remaining references outside migration code

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001) — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational (Phase 2) completion — required for MVP
- **US2 (Phase 4)**: Depends on Foundational (Phase 2) completion — can run parallel to US1
- **US3 (Phase 5)**: Depends on US1 + US2 (uses db.py from Foundational, modified store.py patterns)
- **US4 (Phase 6)**: Depends on US3 (needs refactored store.py)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — No dependencies on other stories
- **US2 (P1)**: Can start after Phase 2 — No dependencies on US1 (different files)
- **US3 (P2)**: Can start after Phase 2 — Modifies store.py which US1/US2 also touch; best done after US1+US2 merge
- **US4 (P3)**: Depends on US3 store.py refactor

### Within Each User Story

- Config/prompts before implementation
- Implementation before test updates
- Core changes before removing old code

### Parallel Opportunities

- T002 + T004 can run in parallel (different files: test vs __init__)
- T005 + T006 can run in parallel (prompts.py vs tools.py — different files)
- US1 and US2 can start in parallel after Foundational phase (different primary files)

---

## Parallel Example: User Story 1

```bash
# Launch prompts and tools changes in parallel:
Task: "Update prompts.py for inline memory recording (T005)"
Task: "Remove write_memory tool from tools.py (T006)"

# Then launch ai_node changes sequentially (depends on prompts + tools):
Task: "Parse [memoryrecord:...] in ai_node (T007)"
Task: "Remove recording transcript vars from ai_node (T008)"
Task: "Simplify finish.py (T009)"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002-T004) — SQLite backend ready
3. Complete Phase 3: User Story 1 (T005-T009) — Inline memory recording works
4. Complete Phase 4: User Story 2 (T010-T012) — Two-phase retrieval works
5. **STOP and VALIDATE**: Memory can be recorded and retrieved end-to-end
6. Deploy if ready (JSON→SQLite migration runs automatically)

### Incremental Delivery

1. Setup + Foundational → SQLite foundation ready
2. Add US1 + US2 → Inline recording + retrieval → MVP deployable!
3. Add US3 → Fast startup + migration → Performance win
4. Add US4 → Daily maintenance verified
5. Polish → Final cleanup and test pass

### Single Developer Strategy

Execute phases sequentially (1 → 2 → 3 → 4 → 5 → 6 → 7). Within each phase, execute [P] tasks in parallel where possible.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Use `git add . && git commit` after each task per project CLAUDE.md rules
- Key risk: store.py is modified by both US1 and US3 — coordinate carefully
- Migration path: `memory.json` → `memory.db` on first startup, JSON renamed to `.bak`
