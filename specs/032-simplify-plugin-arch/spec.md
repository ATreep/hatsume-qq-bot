# Feature Specification: Simplify Plugin Architecture

**Feature Branch**: `032-simplify-plugin-arch`

**Created**: 2026-07-15

**Status**: Draft

**Input**: User description: "Simplify the architecture of hatsume/plugins/hatsume-plugin/: merge handlers/ modules (chat+pipeline+forward→dialogue.py, commands+poke→tools.py, likes→social.py), merge memory/ modules (db+store+retrieval→engine.py), remove ~300 lines of dead code (22 dead constants, 11 dead functions, 6 dead TypedDicts, 6 dead state paths, 2 redundant patterns), update all imports + test stubs to new module paths. Zero logic changes. Pass all 280 tests."

## User Scenarios & Testing

### User Story 1 - Developer navigates to find handler code (Priority: P1)

A developer needs to locate the conversation orchestration logic. Previously it was spread across 3 files (chat.py, pipeline.py, forward.py) in a tightly-coupled spine. After this change, all conversation orchestration — message parsing, forward message handling, debouncing, and graph coordination — lives in a single, clearly-named file: `dialogue.py`.

**Why this priority**: This is the primary architectural improvement — reducing cognitive load when navigating the codebase. The handler spine is the most-frequently-modified area of the plugin.

**Independent Test**: Open `handlers/dialogue.py` and verify it contains all three sections (forward parsing, message pipeline, conversation orchestration) separated by `# ----` dividers, with zero imports from deleted files.

**Acceptance Scenarios**:

1. **Given** the plugin is loaded, **When** a developer searches for `from .pipeline import get_human_message`, **Then** zero results are found (the import no longer exists — the function is in dialogue.py).
2. **Given** a chat message arrives, **When** the conversation pipeline processes it, **Then** the behavior is identical to before the merge (same message assembly, same debouncing, same context trimming).
3. **Given** a forwarded message arrives, **When** the forward parser processes it, **Then** it correctly resolves nested forwards up to the configured depth.

---

### User Story 2 - Developer finds a command handler quickly (Priority: P1)

A developer needs to add a new command. Previously, poke handling lived in its own 31-line file (`poke.py`) and commands lived in `commands.py`. After this change, all trigger-based handlers (shell, video, timer, skills, membersearch, agents, poke) live in a single `tools.py`, while social/gamification features (likes, likerank) live in `social.py`.

**Why this priority**: Reduces module count from 7 to 4 in the handlers package; every surviving file has a semantic name that describes its role rather than its history.

**Independent Test**: Import `handle_poke` from `handlers.tools` and verify it returns the same ACG photo response behavior.

**Acceptance Scenarios**:

1. **Given** someone pokes the bot, **When** the poke notice fires, **Then** the bot replies with a random ACG photo (behavior unchanged).
2. **Given** a `/ccsh` command, **When** the admin runs it, **Then** the shell executes in the Docker sandbox exactly as before.
3. **Given** a `赞我` full-match message, **When** the like handler fires, **Then** the QQ profile like is sent and the count is tracked.

---

### User Story 3 - Developer queries or stores memory (Priority: P1)

A developer needs to understand the memory system. Previously it was 3 tightly-coupled files (`db.py`, `store.py`, `retrieval.py`) with a circular import between store and retrieval resolved by a lazy import inside a function. After this change, the entire memory engine lives in `engine.py` with zero circular dependencies.

**Why this priority**: Eliminates a known circular import; reduces memory package from 5 to 3 files; all memory operations (CRUD, BM25 indexing, hybrid retrieval) are co-located.

**Independent Test**: Call `query_mems("test query")` and verify it returns scored results using the same BM25 + embedding hybrid algorithm as before.

**Acceptance Scenarios**:

1. **Given** the memory system initializes, **When** the plugin starts, **Then** the SQLite database is created/migrated and existing memories are loaded into the BM25 index.
2. **Given** a new memory is stored, **When** `add_mem()` is called, **Then** the memory is persisted to SQLite with its embedding vector and the BM25 index is updated.
3. **Given** a memory query, **When** `query_mems()` is called, **Then** results are scored using the same BM25 weight (0.5) and embedding weight (0.5) as before, ranked by combined score.

---

### User Story 4 - Dead code no longer distracts (Priority: P2)

A developer reading `config.py` or `state.py` no longer sees 22 unused constants, 6 unused TypedDict definitions, or a never-read `last_image_time` field. Dead functions in `prompts.py`, `models.py`, `timer/`, `infra.py`, and `graph/` are removed, reducing the codebase by approximately 300 lines.

**Why this priority**: Dead code is noise — it misleads developers into thinking features exist when they don't, and creates maintenance burden (dead constants still get imported, dead functions still get linted). This cleanup makes the codebase honest about what's actually alive.

**Independent Test**: Run `grep` for each removed constant/function name across the entire codebase and verify zero references exist.

**Acceptance Scenarios**:

1. **Given** a developer searches for `DEEPSEEK_API_KEY` in the codebase, **When** the grep completes, **Then** zero results are found (it was dead and has been removed).
2. **Given** the test suite runs, **When** all 280 tests execute, **Then** zero tests fail due to missing imports or removed code.
3. **Given** `ruff check` runs, **When** the linter scans the plugin, **Then** zero new errors are introduced (the code is as clean or cleaner than before).

---

### User Story 5 - Redundant code is consolidated (Priority: P3)

Two 95%-identical functions (`_start_conv_for_agent` and `_start_conv_for_timer`) are merged into a single `_start_conv_for_trigger` function. Duplicate timer-listing logic between `commands.py` and `tools.py` is deduplicated.

**Why this priority**: Redundancy is a maintenance hazard — fixing a bug in one copy means remembering to fix the other. Lower priority because the functions already work correctly; this is hygiene.

**Independent Test**: Trigger both an agent notification and a timer notification; verify both produce the same conversation-start behavior as before.

**Acceptance Scenarios**:

1. **Given** an agent notification fires, **When** no conversation is active, **Then** a new conversation starts via `_start_conv_for_trigger(trigger_type="agent")`.
2. **Given** a timer fires, **When** no conversation is active, **Then** a new conversation starts via `_start_conv_for_trigger(trigger_type="timer")`.

---

### Edge Cases

- **Module import ordering**: Merged files must order sections so dependencies appear before consumers (forward → pipeline → chat in dialogue.py; db → store → retrieval in engine.py). A section that calls a function defined in a later section will cause a `NameError` at import time.
- **_wire_conv_state wiring**: `chat.py` creates `conv_state` then calls `commands._wire_conv_state(conv_state)` to share rate-limiting state. After the merge, this becomes `tools._wire_conv_state(conv_state)` — the import name changes but the shared object and call pattern are unchanged.
- **Lazy import elimination**: `db.py`'s `migrate_from_json()` has a lazy `from .store import normalize_memory_object` to avoid a static circular import. After merging into `engine.py`, this import becomes unnecessary (the function is in the same file) and must be removed to avoid a self-import error.
- **Test stubs with hyphen/underscore**: 9 test files register `hatsume.plugins.hatsume_plugin` (underscore) as a package alias. Both the hyphen and underscore forms must be updated consistently to new module paths.
- **Already-dead test references**: 3 test files reference module paths that were already removed in prior refactors (`graph.nodes.ai`, `file_transfer`, `handlers.conversation`). These should be cleaned up during the test rewrite pass rather than carried forward.

## Requirements

### Functional Requirements

- **FR-001**: The handlers package MUST contain exactly 4 files: `__init__.py`, `dialogue.py`, `tools.py`, `social.py`.
- **FR-002**: The memory package MUST contain exactly 3 files: `__init__.py`, `engine.py`, `tokenizer.py`.
- **FR-003**: `dialogue.py` MUST export `start_chat`, `user_chat_handle`, `start_new_conversation`, `conv_state`, and `get_human_message` with identical signatures to their pre-merge versions.
- **FR-004**: `tools.py` MUST export `handle_shell`, `handle_generate_video`, `handle_timer`, `handle_list_skills`, `handle_membersearch`, `handle_resetsandbox`, `handle_clear`, `handle_agents`, `handle_autocreate`, `handle_autoresponse`, `handle_poke`, and `_wire_conv_state`.
- **FR-005**: `social.py` MUST export `handle_like` and `handle_likerank`.
- **FR-006**: `engine.py` MUST export all previously-public functions from `db.py`, `store.py`, and `retrieval.py` with identical signatures: `init_db`, `insert_memory`, `delete_expired_memories`, `load_all_memories`, `query_by_user_ids`, `query_all_except`, `migrate_from_json`, `get_mem_list`, `add_mem`, `init_tokenized_corpus`, `init_memory_system`, `normalize_people`, `normalize_memory_object`, `query_mems`, `ensure_embedding_model`, `rebuild_bm25`, `rebuild_embedding_vectors`.
- **FR-007**: All 11 production import sites (in `__init__.py`, `graph/nodes.py`, `graph/tools.py`, `memory/__init__.py`) MUST be updated to reference the new module paths.
- **FR-008**: All 78 unique `sys.modules["..."]` stub keys across 25 test files MUST be updated to reference the new module paths.
- **FR-009**: The 22 dead constants in `config.py` MUST be removed, including the `"ocgo"` provider case from `get_base_url()` and `get_api_key()`.
- **FR-010**: The 11 dead functions (across `prompts.py`, `models.py`, `timer/store.py`, `timer/executor.py`, `infra.py`, `graph/nodes.py`, `memory/store.py`) MUST be removed.
- **FR-011**: The 6 dead TypedDict types and the `last_image_time` field from `state.py` MUST be removed.
- **FR-012**: The `_start_conv_for_agent` and `_start_conv_for_timer` functions in chat.py MUST be consolidated into a single `_start_conv_for_trigger` function with a `trigger_type` parameter.
- **FR-013**: The full test suite (~280 tests) MUST pass after all changes.
- **FR-014**: Zero logic or behavior changes are permitted — the refactor is purely structural.
- **FR-015**: `ruff check` MUST produce no new errors compared to the pre-refactor baseline.

### Key Entities

- **Module**: A Python file within the plugin package. This refactor reduces the count from 12 to 7 in the two affected packages. Each surviving module has a semantic name (dialogue, tools, social, engine) describing its responsibility.
- **Import path**: A dotted Python module reference (e.g., `hatsume.plugins.hatsume-plugin.handlers.chat`). The refactor updates 11 production import paths and ~78 test stub paths.
- **Test stub**: A `sys.modules` entry that mock-replaces a module for test isolation. Each stub references a module by its fully-qualified Python path string.

## Success Criteria

- **SC-001**: The handlers package contains 4 files (was 7) — a 43% reduction in module count.
- **SC-002**: The memory package contains 3 files (was 5) — a 40% reduction in module count.
- **SC-003**: The codebase contains approximately 300 fewer lines of dead or redundant code.
- **SC-004**: All 280 existing tests pass with zero modifications to test logic (only module path strings in stubs are updated).
- **SC-005**: Zero references to deleted module paths (`handlers.chat`, `handlers.pipeline`, `handlers.forward`, `handlers.commands`, `handlers.poke`, `memory.db`, `memory.store`, `memory.retrieval`) remain in any Python file.
- **SC-006**: The memory engine's circular import (store↔retrieval) is eliminated — `engine.py` has no lazy imports or circular dependencies.
- **SC-007**: A developer unfamiliar with the refactor can locate the conversation orchestration code by reading file names alone (`dialogue.py` for conversation flow, `tools.py` for command handlers, `social.py` for likes, `engine.py` for memory).

## Assumptions

- The 280 tests in `tests/` (currently deleted from the working tree but tracked in git HEAD) can be restored via `git checkout HEAD -- tests/` and will run successfully after stub path updates.
- The Python import system resolves renamed modules correctly after all import sites and `sys.modules` stubs are updated — no `importlib` machinery or `__path__` manipulation is needed.
- The existing test infrastructure (pytest, mock, `unittest.mock`) is sufficient to validate the refactor without adding new test dependencies.
- The `_wire_conv_state` pattern is the only shared mutable state between handler modules that crosses the merge boundary.
- All dead code identified in the audit is genuinely unreachable — no external consumers exist outside the plugin package.
- The `ruff` configuration in `pyproject.toml` is sufficient and does not need modification for the refactor.
