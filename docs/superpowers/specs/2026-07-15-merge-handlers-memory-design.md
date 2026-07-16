# Design: Merge handlers/ & memory/ modules + dead code elimination

**Date**: 2026-07-15
**Status**: Approved
**Author**: Claude Opus 4.8
**Scope**: `hatsume/plugins/hatsume-plugin/handlers/` and `hatsume/plugins/hatsume-plugin/memory/`

## 1. Motivation

The `handlers/` and `memory/` packages have accreted files that, after multiple refactors, no longer carry their weight as separate modules:

- `handlers/pipeline.py` and `handlers/forward.py` are only imported by `chat.py` — they form a spine with no other consumers.
- `handlers/poke.py` is a 31-line event handler with no reason to be its own file.
- `memory/db.py`, `memory/store.py`, and `memory/retrieval.py` are tightly coupled (store↔retrieval even has a circular import resolved by lazy import), sharing the same consumers.
- `config.py` has 21 dead constants (30% of definitions).
- Multiple dead functions, unused TypedDicts, and duplicate logic blocks exist across the codebase.

**Goal**: Reduce module count by ~42% in the affected packages, remove ~300 lines of dead code, resolve one circular import, and give surviving files clean semantic names — with zero logic changes.

## 2. Target Architecture

### 2a. handlers/ — before → after

```
Before (7 files):                    After (4 files):
├── __init__.py   (1 line)     →    ├── __init__.py   (thin facade)
├── chat.py       (317 loc)    →    ├── dialogue.py   (≈720 loc)  chat + pipeline + forward
├── pipeline.py   (243 loc)    →    ├── tools.py      (≈432 loc)  commands + poke
├── forward.py    (159 loc)    →    ├── social.py     (83 loc)    likes renamed
├── commands.py   (401 loc)    →
├── poke.py       (31 loc)     →
└── likes.py      (83 loc)     →
```

### 2b. memory/ — before → after

```
Before (5 files):                    After (3 files):
├── __init__.py   (8 loc)      →    ├── __init__.py   (thin facade)
├── db.py         (166 loc)    →    ├── engine.py     (≈600 loc)  db + store + retrieval
├── store.py      (234 loc)    →    ├── tokenizer.py  (27 loc)    unchanged
├── retrieval.py  (198 loc)    →
└── tokenizer.py  (27 loc)     →
```

**Net**: 12 files → 7 files (-42%). All surviving names are semantic (`dialogue`, `tools`, `social`, `engine`).

### 2c. Full dependency graph (post-merge)

```
config.py ──────────────────────────────────────────── (constants, 0 internal deps)
    │
    ├── state.py ───────────────────────────────────── (ConversationState only)
    ├── models.py ──────────────────────────────────── (LLM/embedding/image factories)
    ├── infra.py ───────────────────────────────────── (Docker sandbox)
    ├── utils/ ─────────────────────────────────────── (QQ msg format, MD→image)
    ├── skills/ ────────────────────────────────────── (remote skill install)
    ├── timer/ ─────────────────────────────────────── (scheduled tasks)
    │
    ├── memory/engine.py ───── (SQLite + BM25 + retrieval merged, no circular deps)
    │   └── memory/tokenizer.py (jieba, pure leaf)
    │
    ├── graph/
    │   ├── builder.py ─── StateGraph definition
    │   ├── nodes.py ───── human→detect→ai→finish
    │   ├── agents.py ──── coding_agent registry
    │   └── tools.py ───── 18 LLM tool definitions
    │
    └── handlers/
        ├── dialogue.py ── conversation orchestration, message pipeline, forward parsing
        ├── tools.py ───── shell, video, img, timer, membersearch, agents, poke
        └── social.py ──── likes, likerank
```

**Circular dependencies**: 1 eliminated (memory store↔retrieval → single engine.py). 4 remain in `graph/` (untouched by this refactor, all resolved by lazy imports).

## 3. Merge Strategy

### 3a. `handlers/chat.py` + `pipeline.py` + `forward.py` → `dialogue.py`

**Rationale**: `chat.py` imports `pipeline.get_human_message` and `pipeline` imports `forward` for parsing. The three form a strict spine — no other module imports pipeline or forward. Merging them eliminates two intra-package cross-imports.

**Section order** in `dialogue.py`:
1. `# ---- Forward Message Parsing ----` (from forward.py, 159 loc)
2. `# ---- Message Pipeline ----` (from pipeline.py, 243 loc)
3. `# ---- Conversation Orchestration ----` (from chat.py, 317 loc)

The ordering puts imports-first dependency leaves before their consumers.

### 3b. `handlers/commands.py` + `poke.py` → `tools.py`

**Rationale**: Both are command/event-triggered handlers. poke is 31 lines — too small for its own file. No cross-imports between them.

**Section order**:
1. `# ---- Poke Handler ----` (from poke.py, 31 loc)
2. `# ---- Command Handlers ----` (from commands.py, 401 loc)

### 3c. `handlers/likes.py` → `social.py`

Pure rename for semantic clarity. No content changes.

### 3d. `memory/db.py` + `store.py` + `retrieval.py` → `engine.py`

**Rationale**: The three modules share a tight dependency cluster — `retrieval` imports from both `db` and `store`, `store` imports from `db` and `tokenizer`, and `db` has a lazy import of `store.normalize_memory_object` to avoid a static circular import. Merging eliminates the circular import entirely and keeps the 600-line module in a single, coherent file.

**Section order**:
1. `# ---- Database Layer (SQLite) ----` (from db.py, 166 loc) — must come first: defines `init_db()`, CRUD, embedding persistence
2. `# ---- Storage & Indexing ----` (from store.py, 234 loc) — BM25 index, scheduler hooks, memory lifecycle
3. `# ---- Hybrid Retrieval ----` (from retrieval.py, 198 loc) — BM25 + embedding vector fusion

**Critical**: After the merge, `db.py`'s lazy import of `normalize_memory_object` from `store` becomes a same-file function call. Remove the `from .store import normalize_memory_object` line inside `migrate_from_json()`.

## 4. Import Rewrite Map

### 4a. Production imports

| File | Old import | New import |
|------|-----------|-----------|
| `__init__.py:14` | `from .handlers.chat import start_chat, user_chat_handle` | `from .handlers.dialogue import ...` |
| `__init__.py:15` | `from .handlers.commands import handle_shell, handle_generate_video, handle_timer, handle_list_skills, handle_membersearch, handle_resetsandbox, handle_clear, handle_agents, handle_autocreate, handle_autoresponse` | `from .handlers.tools import ...` |
| `__init__.py:16` | `from .handlers.likes import handle_like, handle_likerank` | `from .handlers.social import ...` |
| `__init__.py:17` | `from .handlers.poke import handle_poke` | (merged into tools.py, import from there) |
| `__init__.py:18` | `from .memory.store import init_memory_system, init_tokenized_corpus` | `from .memory.engine import ...` |
| `graph/nodes.py:318` | `from ..handlers.chat import conv_state, start_new_conversation` | `from ..handlers.dialogue import ...` |
| `graph/nodes.py:653` | `from ..memory.store import add_mem` | `from ..memory.engine import add_mem` |
| `graph/tools.py:22` | `from ..memory.store import get_mem_list` | `from ..memory.engine import get_mem_list` |
| `graph/tools.py:23` | `from ..memory.retrieval import query_mems` | `from ..memory.engine import query_mems` |
| `memory/__init__.py` | `from .db import ...`, `from .store import ...`, `from .retrieval import ...`, `from .tokenizer import ...` | `from .engine import ...`, `from .tokenizer import ...` |
| `memory/store.py:144` | `from .store import normalize_memory_object` (lazy import inside `db.py`) | Remove — same-file function now |

### 4b. Test stub rewrites

Tests use `sys.modules["hatsume.plugins.hatsume-plugin.module.name"]` to stub module paths. 78 unique stub keys were identified across 25 test files. The following rewrites are needed:

| Old stub path | New stub path | Affected tests |
|---|---|---|
| `...memory.store` | `...memory.engine` | test_agent_dispatch, test_conversation, test_graph_nodes, test_membersearch, test_random_acg_photo, test_tools, test_memory_utils |
| `...memory.retrieval` | `...memory.engine` | test_conversation, test_graph_nodes, test_membersearch, test_random_acg_photo, test_memory_utils |
| `...memory.db` | `...memory.engine` | test_memory_db, test_memory_utils |
| `...handlers.chat` | `...handlers.dialogue` | test_agents_command, test_conversation |
| `...handlers.pipeline` | (absorbed into dialogue) | test_conversation, test_omni_model |
| `...handlers.forward` | (absorbed into dialogue) | test_forward |
| `...handlers.commands` | `...handlers.tools` | test_agents_command, test_membersearch |
| `...handlers.poke` | (absorbed into tools) | (no test directly stubs poke) |

**Three already-dead references** found in tests (from prior un-cleaned-up refactors):
- `...graph.nodes.ai` → already consolidated into `graph/nodes.py`
- `...file_transfer` → logic already moved to `handlers/commands.py`
- `handlers/conversation.py` → already merged into `chat.py`

These should be cleaned up during the test rewrite pass.

## 5. Dead Code Removal

### 5A. Dead functions (11 items, ~120 lines)

| # | File | Lines | Function | Reason dead |
|---|------|-------|----------|-------------|
| 1-2 | `prompts.py` | 371-378 | `build_timer_context_prompt`, `build_timer_task_prompt` | Old timer agent path; replaced by `inject_timer()` |
| 3-4 | `prompts.py` | 274, 282 | `build_video_failure_prompt`, `build_video_success_prompt` | Video tool builds messages inline |
| 5 | `models.py` | 222-281 | `generate_image_for_gpt_image()` (~60 loc) | Never imported by any consumer |
| 6 | `timer/store.py` | 271 | `TimerStore.get_auto_response()` | Never called |
| 7 | `timer/store.py` | 304 | `TimerStore.get_pending_triggers()` | Never called |
| 8 | `timer/executor.py` | 249-282 | `refresh_auto_create()` (34 loc) | Call site commented out in `timer/__init__.py:38` |
| 9 | `memory/store.py` | 89-94 | `memory_has_user()` | Re-exported with `# noqa: F401` but never called |
| 10 | `infra.py` | 179-186 | `render_html_to_image()` | Never imported; rendering via `utils/md_to_image.py` |
| 11 | `graph/nodes.py` | 418-419 | `_get_human_sources()` | Never called |

### 5B. Dead TypedDicts (6 types, ~30 lines)

Remove from `state.py` lines 20-47: `PersonEntry`, `MemoryRecord`, `SourceEntry`, `TextContent`, `ImageContent`, `ContentPart`. Only `ConversationState` is imported from `state.py`.

### 5C. Dead constants (22 items, ~40 lines)

Remove from `config.py`:
- `DEEPSEEK_API_KEY`, `NV_API_KEY` (lines 28-29) — unused API keys
- `CCSWITCH_ROUTE_URL`, `DEEPSEEK_BASE_URL` (lines 40-41) — unused base URLs
- `DOUBAO_1_6_LITE`, `DOUBAO_2_PRO`, `DOUBAO_2_1_PRO`, `DOUBAO_CODE`, `DEEPSEEK_V4_FLASH`, `SEEDREAM_4_0`, `SEEDREAM_4_5`, `KIMI_2_6`, `GEMINI_3_1_FLASH_LITE`, `MINIMAX_3`, `DEEPSEEK_V4_PRO` (lines 47-65) — unused model name constants
- `ADVANCE_MODEL_NAME`, `LITE_MODEL_NAME`, `MINI_MODEL_NAME` (lines 80-82) — bypassed by `models.py`
- `MEMORY_SIX_HOUR_WINDOW`, `PEOPLE_PRIORITY_RATIO` (lines 142, 146) — unused memory constants
- `SHELL_MAX_OUTPUT` (line 155) — unused docker constant
- `CODING_AGENT_SKILL_PATH` (line 168) — unused skill constant
- `OPENCODE_GO_BASE_URL` (line 38) and the `"ocgo"` case in `get_base_url()` — zero callers

### 5D. Dead state & code paths (6 items, ~50 lines)

| # | File | Item | Action |
|---|------|------|--------|
| 1 | `state.py:69` | `last_image_time: float = 0` | Remove — never read/written; image rate-limiting was never wired |
| 2 | `graph/tools.py:130` | `global _update_image_time` in `configure_tool_callbacks` | Remove — never assigned |
| 3 | `graph/tools.py:78` | `_last_capture_html_demand` | Remove — never read/written |
| 4 | `timer/store.py:329-354` | `deduplicate_return=True` branch in `validate_trigger_times()` | Remove dead branch |
| 5 | `memory/__init__.py` | All 8 lines of re-exports from deleted submodules | Replace with thin re-export facade: `from .engine import ...`, `from .tokenizer import ...` |
| 6 | `config.py:133` | Commented-out `# AUTO_CREATE_GROUP_ID: int = TARGET_GROUP_ID` | Remove |

### 5E. Redundant code consolidation (2 items, ~60 lines duplicated)

| # | Files | Issue | Action |
|---|-------|-------|--------|
| 1 | `dialogue.py` (ex-chat:36-112) | `_start_conv_for_agent` and `_start_conv_for_timer` are 95% identical | Merge into single `_start_conv_for_trigger(trigger_type, user_id, group_id, msg)` |
| 2 | `tools.py` (ex-commands:86-128) vs `graph/tools.py:682-733` | Duplicate timer list formatting (~40 lines) | Extract shared formatting function; LLM tool delegates to it |

## 6. Edge Cases & Risk Mitigation

### 6a. `_wire_conv_state` shared-state pattern

`dialogue.py` creates `conv_state = ConversationState()` at module level then calls `_wire_conv_state(conv_state)` from `tools.py`. This pattern is unchanged by the merge — only the import name moves from `.commands` to `.tools`. Zero logic change.

### 6b. Module import ordering

`dialogue.py` must order its merged sections: forward → pipeline → chat (dependencies before consumers). `engine.py` must order: db → store → retrieval. Same-file function definitions must appear before their call sites.

### 6c. `memory/db.py` lazy import resolution

`migrate_from_json()` in db.py currently does `from .store import normalize_memory_object` inside the function body (lazy import) to avoid a static circular dependency with `store`. After merging into `engine.py`, `normalize_memory_object` is defined in the same file — remove this now-unnecessary import line.

### 6d. Test file restoration

`tests/` is deleted from the working tree but tracked in git HEAD. Recovery steps:
1. `git checkout HEAD -- tests/` — restore all 25 files
2. Rewrite all `sys.modules["..."]` stubs (78 unique keys) to new module paths
3. Merge multi-module stubs (e.g., separate `memory.store` + `memory.retrieval` stubs → single `memory.engine` stub)
4. Clean up 3 already-dead stub references from prior un-cleaned-up refactors

### 6e. Hyphen vs underscore in test stubs

9 test files register `hatsume.plugins.hatsume_plugin` (underscore) as an alias for `hatsume-plugin` (hyphen). Both forms must be audited and updated consistently.

## 7. Implementation Order

1. Restore `tests/` from git HEAD
2. Remove dead code from `config.py`, `state.py`, `prompts.py`, `models.py`, `timer/`, `infra.py`, `graph/nodes.py`, `graph/tools.py`, `memory/store.py`
3. Consolidate redundant code (merge `_start_conv_for_agent`+`_start_conv_for_timer`, extract shared timer formatter)
4. Merge `handlers/`: create `dialogue.py`, `tools.py`, rename `likes.py` → `social.py`, delete `pipeline.py`/`forward.py`/`commands.py`/`poke.py`/`chat.py`
5. Merge `memory/`: create `engine.py`, keep `tokenizer.py`, update `__init__.py`
6. Update all production import sites (11 locations)
7. Rewrite all test stubs to new module paths
8. Run test suite: `python -m pytest tests/ -xvs`
9. Fix any stub/import issues found by tests
10. `git add .` and commit

## 8. Verification Criteria

- [ ] `python -m pytest tests/ -xvs` passes with all 280 tests green
- [ ] `ruff check hatsume/plugins/hatsume-plugin/` produces no new errors
- [ ] `from .handlers.dialogue import start_chat, user_chat_handle, start_new_conversation` works
- [ ] `from .handlers.tools import handle_shell, handle_poke, ...` works
- [ ] `from .handlers.social import handle_like, handle_likerank` works
- [ ] `from .memory.engine import get_mem_list, add_mem, query_mems, init_db` works
- [ ] `from .memory.tokenizer import tokenize_with_pos` works
- [ ] All `sys.modules["..."]` stubs in tests reference valid module paths
- [ ] Zero references to deleted files (`handlers.chat`, `handlers.pipeline`, `handlers.forward`, `handlers.commands`, `handlers.poke`, `memory.db`, `memory.store`, `memory.retrieval`) remain in the codebase
