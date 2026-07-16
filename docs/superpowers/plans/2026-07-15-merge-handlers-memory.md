# Merge handlers/ & memory/ + dead code elimination — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce handlers/ (7→4 files) and memory/ (5→3 files), remove ~300 lines of dead code, consolidate 2 redundant patterns, resolve 1 circular dependency. Zero logic changes.

**Architecture:** Pure structural refactor — merge tightly-coupled modules by cohesion, remove unreachable functions/constants/state, rename surviving files with semantic names (dialogue/tools/social/engine). All import sites and test stubs updated to new module paths.

**Tech Stack:** Python 3.12+, NoneBot2, LangGraph, SQLite, pytest, ruff

## Global Constraints

- Zero logic changes — no behavior modification anywhere
- All 280 tests must pass after the refactor
- `ruff check` clean
- Files merged by appending content in section order (dependencies before consumers)
- Tests restored from git HEAD before any code changes
- Commit after each completed phase

---

### Task 1: Restore tests from git HEAD

**Files:**
- Create: `tests/` directory and all 25 files restored from git

**Interfaces:**
- Produces: Full test suite at `tests/` with all 280 test functions

- [ ] **Step 1: Restore tests from git**

```bash
cd /path/to/hatsume && git checkout HEAD -- tests/
```

- [ ] **Step 2: Verify tests are restored**

```bash
ls tests/ | wc -l
```
Expected: at least 20 files.

- [ ] **Step 3: Quick sanity — tests exist but may not run (deps may be missing)**

```bash
python -m pytest tests/ --collect-only 2>&1 | tail -5
```
Expected: collection stats show ~280 tests (import-time failures for missing deps are expected at this stage).

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume && git add tests/ && git commit -m "chore: restore tests/ from HEAD for refactor validation"
```

---

### Task 2: Remove dead constants from config.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py`

**Interfaces:**
- Consumes: (none — these are dead constants with zero consumers)
- Produces: Clean config.py with 53 alive constants (was 74)

- [ ] **Step 1: Remove the 22 dead constants + commented-out line**

Apply these removals in `config.py`:

```
# Remove line 28: DEEPSEEK_API_KEY
# Remove line 29: NV_API_KEY
# Remove line 38: OPENCODE_GO_BASE_URL
# Remove line 40: CCSWITCH_ROUTE_URL
# Remove line 41: DEEPSEEK_BASE_URL
# Remove line 47: DOUBAO_1_6_LITE
# Remove line 50: DOUBAO_2_PRO
# Remove line 51: DOUBAO_2_1_PRO
# Remove line 52: DOUBAO_CODE
# Remove line 53: DEEPSEEK_V4_FLASH
# Remove line 55: SEEDREAM_4_0
# Remove line 56: SEEDREAM_4_5
# Remove line 60: KIMI_2_6
# Remove line 61: GEMINI_3_1_FLASH_LITE
# Remove line 62: MINIMAX_3
# Remove line 65: DEEPSEEK_V4_PRO
# Remove lines 80-82: ADVANCE_MODEL_NAME, LITE_MODEL_NAME, MINI_MODEL_NAME
# Remove line 133: # AUTO_CREATE_GROUP_ID: int = TARGET_GROUP_ID (commented-out line)
# Remove line 142: MEMORY_SIX_HOUR_WINDOW
# Remove line 146: PEOPLE_PRIORITY_RATIO
# Remove line 155: SHELL_MAX_OUTPUT
# Remove line 168: CODING_AGENT_SKILL_PATH
```

- [ ] **Step 2: Remove the "ocgo" case from get_base_url()**

Remove lines 94-95 (`case "ocgo": return OPENCODE_GO_BASE_URL`) from `get_base_url()`.

- [ ] **Step 3: Remove the "ocgo" case from get_api_key()**

Remove lines 109-110 (`case "ocgo": return lambda: OPENCODE_API_KEY`) from `get_api_key()`.

- [ ] **Step 4: Remove "ocgo" from Provider literal type**

Change line 78 from:
```python
PROVIDER: Literal["volc", "volc_plan", "ocgo", "kege"] = "kege"
```
to:
```python
PROVIDER: Literal["volc", "volc_plan", "kege"] = "kege"
```

And update `get_base_url` signature (line 85) and `get_api_key` signature (line 100) similarly.

- [ ] **Step 5: Verify no imports broken**

```bash
python -c "from hatsume.plugins.hatsume_plugin.config import *; print('OK')" 2>&1
```

- [ ] **Step 6: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/config.py && git commit -m "refactor: remove 22 dead constants and ocgo provider from config.py"
```

---

### Task 3: Remove dead TypedDicts and state from state.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/state.py`

**Interfaces:**
- Consumes: (none — dead types, dead field)
- Produces: state.py with only ConversationState

- [ ] **Step 1: Remove dead TypedDict types (lines 17-47)**

Remove everything between `# ---- Type definitions ----` and `# ---- Conversation state ----`:
```python
# Remove lines 17-47:
#   class PersonEntry(TypedDict) ...
#   class MemoryRecord(TypedDict) ...
#   class SourceEntry(TypedDict) ...
#   class TextContent(TypedDict) ...
#   class ImageContent(TypedDict) ...
#   ContentPart = Union[TextContent, ImageContent]
```

Also remove the `TypedDict, Union` imports from line 8 if no longer used (keep `Any, Callable, Coroutine`).

- [ ] **Step 2: Remove dead `last_image_time` field**

Remove line 69: `last_image_time: float = 0`

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/state.py && git commit -m "refactor: remove dead TypedDicts and last_image_time from state.py"
```

---

### Task 4: Remove dead functions from prompts.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py`

**Interfaces:**
- Consumes: (none — all dead)
- Produces: Clean prompts.py

- [ ] **Step 1: Remove build_video_failure_prompt and build_video_success_prompt**

Remove lines 274-287 (both video prompt functions, including their docstrings and blank lines).

- [ ] **Step 2: Remove build_timer_context_prompt and build_timer_task_prompt**

Remove lines 371-378 (both timer prompt functions).

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/prompts.py && git commit -m "refactor: remove 4 dead prompt builder functions"
```

---

### Task 5: Remove dead function from models.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/models.py`

**Interfaces:**
- Consumes: (none — dead)
- Produces: models.py without unreachable gpt-image path

- [ ] **Step 1: Remove generate_image_for_gpt_image**

Remove lines 222-281 (the entire `generate_image_for_gpt_image` function, ~60 lines).

- [ ] **Step 2: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/models.py && git commit -m "refactor: remove dead generate_image_for_gpt_image function"
```

---

### Task 6: Remove dead methods from timer/store.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/store.py`

**Interfaces:**
- Consumes: (none — dead)
- Produces: TimerStore without dead query methods and dead code branch

- [ ] **Step 1: Remove get_auto_response()**

Remove lines 271-281 (the entire `get_auto_response` method).

- [ ] **Step 2: Remove get_pending_triggers()**

Remove lines 304-313 (the entire `get_pending_triggers` method).

- [ ] **Step 3: Remove deduplicate_return branch from validate_trigger_times**

In `validate_trigger_times` (line 327), change:
```python
def validate_trigger_times(
    self, trigger_times: list[float], now: float | None = None,
    deduplicate_return: bool = False,
) -> list[str] | tuple[list[float], list[str]]:
```
to:
```python
def validate_trigger_times(
    self, trigger_times: list[float], now: float | None = None,
) -> list[str]:
```

And remove lines 352-353:
```python
        if deduplicate_return:
            return clean_times, errors
```
Change line 354 from `return errors` to just `return errors` (already there but check the return type).

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/timer/store.py && git commit -m "refactor: remove dead timer query methods and deduplicate_return branch"
```

---

### Task 7: Remove dead function from timer/executor.py + cleanup timer/__init__.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py`
- Modify: `hatsume/plugins/hatsume-plugin/timer/__init__.py`

**Interfaces:**
- Consumes: (none — dead function + commented-out call site)
- Produces: Clean timer module

- [ ] **Step 1: Remove refresh_auto_create from executor.py**

Remove lines 249-282 (the entire `refresh_auto_create` function, ~34 lines).

- [ ] **Step 2: Clean up commented-out call in timer/__init__.py**

Remove line 38: `# await refresh_auto_create(store)`

Also remove the `refresh_auto_create` from the docstring in `init_scheduler` if referenced.

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/timer/executor.py hatsume/plugins/hatsume-plugin/timer/__init__.py && git commit -m "refactor: remove dead refresh_auto_create and commented-out call site"
```

---

### Task 8: Remove dead functions from infra.py and graph/nodes.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py`
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes.py`

**Interfaces:**
- Consumes: (none — dead)
- Produces: Clean modules

- [ ] **Step 1: Remove render_html_to_image from infra.py**

Remove lines 179-186 (the entire `render_html_to_image` function).

- [ ] **Step 2: Remove _get_human_sources from graph/nodes.py**

Remove lines 418-419:
```python
def _get_human_sources() -> list[dict]:
    return _state.human_source_queue if _state else []
```

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/infra.py hatsume/plugins/hatsume-plugin/graph/nodes.py && git commit -m "refactor: remove dead render_html_to_image and _get_human_sources"
```

---

### Task 9: Remove dead state from graph/tools.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

**Interfaces:**
- Consumes: (none — dead)
- Produces: Clean tools.py module-level state

- [ ] **Step 1: Remove _last_capture_html_demand**

Remove line 78: `_last_capture_html_demand: str = ""`

- [ ] **Step 2: Remove _update_image_time from configure_tool_callbacks**

Remove `_update_image_time` from the `global` declaration on line 130:
Change:
```python
    global _is_image_rate_limited, _update_image_time
```
to:
```python
    global _is_image_rate_limited
```

- [ ] **Step 3: Remove _update_image_time default on line 81**

Remove `_update_image_time: Callable[[], None] = lambda: None` (line 81 if it exists, or check exact line).

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/graph/tools.py && git commit -m "refactor: remove dead _last_capture_html_demand and _update_image_time state"
```

---

### Task 10: Remove memory_has_user and clean memory/__init__.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/store.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`

**Interfaces:**
- Consumes: (none — dead function; dead re-export facade)
- Produces: Clean memory package ready for merge

- [ ] **Step 1: Remove memory_has_user from memory/store.py**

Remove lines 89-94 (the entire `memory_has_user` function).

- [ ] **Step 2: Replace memory/__init__.py with thin facade (pre-merge)**

```python
"""Memory package: storage, retrieval, and tokenization."""
from .engine import init_db, insert_memory, delete_expired_memories, load_all_memories
from .engine import query_by_user_ids, query_all_except, migrate_from_json
from .engine import get_mem_list, add_mem, init_tokenized_corpus, init_memory_system
from .engine import normalize_people, normalize_memory_object
from .engine import query_mems, ensure_embedding_model, rebuild_bm25, rebuild_embedding_vectors
from .tokenizer import tokenize_with_pos
```

(Note: `engine.py` doesn't exist yet — this is forward-looking. For now, just remove the `memory_has_user` re-export and the db/store/retrieval re-exports will be updated in the memory merge task.)

Actually, just remove `memory_has_user` re-export from __init__.py for now.

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/memory/store.py hatsume/plugins/hatsume-plugin/memory/__init__.py && git commit -m "refactor: remove dead memory_has_user function"
```

---

### Task 11: Consolidate _start_conv_for_agent + _start_conv_for_timer

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py`

**Interfaces:**
- Produces: Single `_start_conv_for_trigger` replacing two 95%-identical functions (~40 lines saved)

- [ ] **Step 1: Replace both functions with unified version**

Replace `_start_conv_for_agent` (lines 36-75) and `_start_conv_for_timer` (lines 78-112) with:

```python
def _start_conv_for_trigger(
    user_id: int, group_id: int, notify_msg: str, *, trigger_type: str = "agent"
) -> None:
    """Start a new conversation for an external trigger (agent/timer) when not chatting.

    Uses bot.send_group_msg() to target the specific group directly.
    trigger_type: "agent" | "timer" — controls whether user_id=None is allowed.
    """
    from nonebot import get_bot
    from ..graph.tools import configure_tool_callbacks as configure_tools

    bot = get_bot()

    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = mask_secret_keys(str(msg))
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")

    conv_state.ai_answer = _send_to_group
    conv_state.ai_answer_with_at = _send_to_group

    if user_id != 0:
        conv_state.activate_chat(f"group_{group_id}_{user_id}")

    effective_user_id = user_id if user_id != 0 else None
    # agent triggers use user_id=None when user_id==0 (no specific user to notify)
    if trigger_type == "agent" and user_id == 0:
        effective_user_id = None

    asyncio.create_task(
        start_new_conversation(
            conv_state, _send_to_group, configure_tools,
            user_id=effective_user_id,
            messages=[{"type": "text", "text": notify_msg}],
        )
    )
```

- [ ] **Step 2: Update callers**

Two call sites in `graph/nodes.py` reference `_start_conv_for_agent` and `_start_conv_for_timer`. Find and update them:

In `graph/nodes.py`, search for `_start_conv_for_agent` and `_start_conv_for_timer` and replace with `_start_conv_for_trigger` with appropriate `trigger_type=` kwarg.

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/handlers/chat.py hatsume/plugins/hatsume-plugin/graph/nodes.py && git commit -m "refactor: merge _start_conv_for_agent and _start_conv_for_timer into _start_conv_for_trigger"
```

---

### Task 12: Merge handlers/ — create dialogue.py, tools.py, rename likes→social.py

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`
- Create: `hatsume/plugins/hatsume-plugin/handlers/tools.py`
- Create: `hatsume/plugins/hatsume-plugin/handlers/social.py` (from likes.py)
- Delete: `hatsume/plugins/hatsume-plugin/handlers/chat.py`
- Delete: `hatsume/plugins/hatsume-plugin/handlers/pipeline.py`
- Delete: `hatsume/plugins/hatsume-plugin/handlers/forward.py`
- Delete: `hatsume/plugins/hatsume-plugin/handlers/commands.py`
- Delete: `hatsume/plugins/hatsume-plugin/handlers/poke.py`
- Delete: `hatsume/plugins/hatsume-plugin/handlers/likes.py`

**Interfaces:**
- Consumes: Contents of chat.py, pipeline.py, forward.py, commands.py, poke.py, likes.py
- Produces: dialogue.py, tools.py, social.py — same public exports under new module names

- [ ] **Step 1: Create dialogue.py**

Concatenate in order: forward.py → pipeline.py → chat.py, separated by `# ----` dividers. Update internal imports:
- Remove `from .pipeline import get_human_message` (now same file)
- Remove `from .forward import (...)` (now same file) — pipeline's forward import
- Keep `from .commands import _wire_conv_state` → change to `from .tools import _wire_conv_state`

```bash
cd /path/to/hatsume/hatsume/plugins/hatsume-plugin/handlers
# Build dialogue.py from the three source files
cat forward.py > dialogue.py
echo -e "\n# ---- Message Pipeline ----\n" >> dialogue.py
tail -n +4 pipeline.py >> dialogue.py  # skip pipeline's docstring and future-import
echo -e "\n# ---- Conversation Orchestration ----\n" >> dialogue.py
tail -n +4 chat.py >> dialogue.py  # skip chat's docstring and future-import
```

Then edit dialogue.py to fix imports:
1. Add `from __future__ import annotations` at top (only once)
2. Remove `from .pipeline import get_human_message` (it's now in the same file)
3. Remove `from .forward import (...)` (it's now in the same file)
4. Change `from .commands import _wire_conv_state` to `from .tools import _wire_conv_state`

- [ ] **Step 2: Create tools.py**

Concatenate poke.py → commands.py:
```bash
cd /path/to/hatsume/hatsume/plugins/hatsume-plugin/handlers
echo '"""Command and event handlers: shell, video, img, timer, skills, membersearch, agents, poke."""' > tools.py
echo "" >> tools.py
echo "from __future__ import annotations" >> tools.py
echo "" >> tools.py
echo "# ---- Poke Handler ----" >> tools.py
tail -n +4 poke.py >> tools.py  # skip poke's docstring and future-import
echo -e "\n# ---- Command Handlers ----\n" >> tools.py
tail -n +4 commands.py >> tools.py  # skip commands' docstring and future-import
```

- [ ] **Step 3: Rename likes.py → social.py**

```bash
cd /path/to/hatsume/hatsume/plugins/hatsume-plugin/handlers
cp likes.py social.py
# Edit social.py's docstring to say "Like/follow social features"
```

- [ ] **Step 4: Delete old files**

```bash
cd /path/to/hatsume/hatsume/plugins/hatsume-plugin/handlers
rm chat.py pipeline.py forward.py commands.py poke.py likes.py
```

- [ ] **Step 5: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/handlers/ && git commit -m "refactor: merge handlers/ — dialogue+tools+social (7→4 files)"
```

---

### Task 13: Merge memory/ — create engine.py

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Delete: `hatsume/plugins/hatsume-plugin/memory/db.py`
- Delete: `hatsume/plugins/hatsume-plugin/memory/store.py`
- Delete: `hatsume/plugins/hatsume-plugin/memory/retrieval.py`

**Interfaces:**
- Consumes: Contents of db.py, store.py, retrieval.py
- Produces: engine.py with db+store+retrieval merged in section order

- [ ] **Step 1: Create engine.py**

Concatenate in order: db.py → store.py → retrieval.py:
```bash
cd /path/to/hatsume/hatsume/plugins/hatsume-plugin/memory
cat db.py > engine.py
echo -e "\n# ---- Storage & Indexing ----\n" >> engine.py
tail -n +4 store.py >> engine.py
echo -e "\n# ---- Hybrid Retrieval ----\n" >> engine.py
tail -n +4 retrieval.py >> engine.py
```

- [ ] **Step 2: Fix internal imports**

In engine.py:
1. Remove `from . import db as _db` (store section) — same file now
2. Remove `from .tokenizer import tokenize_with_pos` (store section) — becomes `from tokenizer import tokenize_with_pos` OR keep as package-relative `from .tokenizer import tokenize_with_pos`
3. Remove `from . import db as _db` (retrieval section) — same file now
4. Remove `from . import store as _store` (retrieval section) — same file now
5. Remove `from . import tokenizer as _tokenizer` (retrieval section) — becomes `from .tokenizer import tokenize_with_pos`
6. Remove `from .store import normalize_memory_object` (inside `migrate_from_json` in db section) — now same-file function, just call it directly
7. Keep `from ..config import ...` references
8. Ensure only one `from __future__ import annotations` at top

- [ ] **Step 3: Delete old files**

```bash
cd /path/to/hatsume/hatsume/plugins/hatsume-plugin/memory
rm db.py store.py retrieval.py
```

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/memory/ && git commit -m "refactor: merge memory/ — engine.py (db+store+retrieval, 5→3 files)"
```

---

### Task 14: Update all production import sites

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes.py`
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`

**Interfaces:**
- Consumes: All existing public APIs under new module paths
- Produces: All 11 import sites updated

- [ ] **Step 1: Update __init__.py imports**

Change lines 14-18:
```python
from .handlers.dialogue import start_chat, user_chat_handle
from .handlers.tools import handle_shell, handle_generate_video, handle_timer, handle_list_skills, handle_membersearch, handle_resetsandbox, handle_clear, handle_agents, handle_autocreate, handle_autoresponse, handle_poke
from .handlers.social import handle_like, handle_likerank
from .memory.engine import init_memory_system, init_tokenized_corpus
```

- [ ] **Step 2: Update graph/nodes.py imports**

Search for lazy imports inside functions in nodes.py and update:
- `from ..handlers.chat import conv_state, start_new_conversation` → `from ..handlers.dialogue import conv_state, start_new_conversation`
- `from ..memory.store import add_mem` → `from ..memory.engine import add_mem`

Also update `_start_conv_for_agent` → `_start_conv_for_trigger` references (from Task 11).

- [ ] **Step 3: Update graph/tools.py imports**

Lines 22-23:
```python
from ..memory.engine import get_mem_list
from ..memory.engine import query_mems
```

- [ ] **Step 4: Update memory/__init__.py**

```python
"""Memory package: storage, retrieval, and tokenization."""
from .engine import init_db, insert_memory, delete_expired_memories, load_all_memories
from .engine import query_by_user_ids, query_all_except, migrate_from_json
from .engine import get_mem_list, add_mem, init_tokenized_corpus, init_memory_system
from .engine import normalize_people, normalize_memory_object
from .engine import query_mems, ensure_embedding_model, rebuild_bm25, rebuild_embedding_vectors
from .tokenizer import tokenize_with_pos
```

- [ ] **Step 5: Verify no stale references remain**

```bash
cd /path/to/hatsume && grep -rn "handlers\.chat\|handlers\.pipeline\|handlers\.forward\|handlers\.commands\|handlers\.poke\|memory\.db\|memory\.store\|memory\.retrieval" hatsume/plugins/hatsume-plugin/ --include="*.py" | grep -v __pycache__ | grep -v "\.git"
```
Expected: zero results (except possibly in comments/docstrings).

- [ ] **Step 6: Commit**

```bash
cd /path/to/hatsume && git add hatsume/plugins/hatsume-plugin/ && git commit -m "refactor: update all production import sites to new module names"
```

---

### Task 15: Rewrite test stubs to new module paths

**Files:**
- Modify: All 25 test files in `tests/` that contain `sys.modules["..."]` stubs for renamed modules

**Interfaces:**
- Consumes: Test stub paths referencing old module names
- Produces: Updated test stubs referencing new module names

- [ ] **Step 1: Global search-and-replace for module path strings**

Run these replacements across all test files:

```bash
cd /path/to/hatsume/tests

# memory module renames
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.memory\.store/hatsume.plugins.hatsume-plugin.memory.engine/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.memory\.retrieval/hatsume.plugins.hatsume-plugin.memory.engine/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.memory\.db/hatsume.plugins.hatsume-plugin.memory.engine/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.memory\.store/hatsume.plugins.hatsume_plugin.memory.engine/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.memory\.retrieval/hatsume.plugins.hatsume_plugin.memory.engine/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.memory\.db/hatsume.plugins.hatsume_plugin.memory.engine/g' {} +

# handler module renames
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.handlers\.chat/hatsume.plugins.hatsume-plugin.handlers.dialogue/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.handlers\.commands/hatsume.plugins.hatsume-plugin.handlers.tools/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.handlers\.chat/hatsume.plugins.hatsume_plugin.handlers.dialogue/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.handlers\.commands/hatsume.plugins.hatsume_plugin.handlers.tools/g' {} +

# pipeline → dialogue
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.handlers\.pipeline/hatsume.plugins.hatsume-plugin.handlers.dialogue/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.handlers\.pipeline/hatsume.plugins.hatsume_plugin.handlers.dialogue/g' {} +

# forward → dialogue
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.handlers\.forward/hatsume.plugins.hatsume-plugin.handlers.dialogue/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.handlers\.forward/hatsume.plugins.hatsume_plugin.handlers.dialogue/g' {} +

# poke → tools
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume-plugin\.handlers\.poke/hatsume.plugins.hatsume-plugin.handlers.tools/g' {} +
find . -name "*.py" -exec sed -i '' 's/hatsume\.plugins\.hatsume_plugin\.handlers\.poke/hatsume.plugins.hatsume_plugin.handlers.tools/g' {} +
```

- [ ] **Step 2: Manual audit for special cases**

The `test_forward.py` file loads the forward module directly via `spec_from_file_location`. The forward parsing code is now in dialogue.py — update the spec/source path if needed, or update the test to import from dialogue instead.

The `test_conversation.py` and `test_agents_command.py` may need manual adjustment for multi-module stub merging (where separate stubs for pipeline+forward+chat now all point to dialogue, merge them into one stub).

- [ ] **Step 3: Clean up already-dead stub references**

Remove references to these non-existent modules:
- `hatsume.plugins.hatsume_plugin.graph.nodes.ai` (already consolidated into graph/nodes.py)
- `hatsume.plugins.hatsume-plugin.file_transfer` (already moved to handlers/commands.py)
- `handlers/conversation.py` (already merged into chat.py)

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume && git add tests/ && git commit -m "refactor: update test stubs to new merged module paths"
```

---

### Task 16: Run full test suite & fix issues

**Files:**
- Modify: Whatever needs fixing to get tests green

**Interfaces:**
- Consumes: All merged modules + updated tests
- Produces: All 280 tests passing

- [ ] **Step 1: Run the full test suite**

```bash
cd /path/to/hatsume && python -m pytest tests/ -x --tb=short 2>&1
```

- [ ] **Step 2: Fix any failing tests**

For each failure:
1. Read the error
2. Identify the root cause (stale import, missing stub, merge artifact)
3. Fix the code or test
4. Re-run the specific test to verify

- [ ] **Step 3: Run ruff**

```bash
cd /path/to/hatsume && ruff check hatsume/plugins/hatsume-plugin/ --select F,E,W 2>&1
```

Fix any lint errors.

- [ ] **Step 4: Final verification**

```bash
cd /path/to/hatsume && python -m pytest tests/ -xvs 2>&1 | tail -20
```

Expected: `passed` with count close to 280.

- [ ] **Step 5: Final commit**

```bash
cd /path/to/hatsume && git add . && git commit -m "refactor: finalize merge + dead code elimination, all tests passing"
```

---

## Task Dependency Graph

```
Task 1 (restore tests)
  │
  ├── Task 2 (dead config.py constants)
  ├── Task 3 (dead state.py types)
  ├── Task 4 (dead prompts.py functions)
  ├── Task 5 (dead models.py function)
  ├── Task 6 (dead timer/store.py methods)
  ├── Task 7 (dead timer/executor.py function)
  ├── Task 8 (dead infra.py + nodes.py functions)
  ├── Task 9 (dead tools.py state)
  └── Task 10 (dead memory_has_user)
         │
         ├── Task 11 (consolidate _start_conv triggers)
         │      └── Task 12 (merge handlers/)
         └── Task 13 (merge memory/)
                │
                ├── Task 14 (update production imports)
                │      └── Task 15 (rewrite test stubs)
                │             └── Task 16 (run tests + fix)
                └── (dependency chain continues)
```

Tasks 2-10 are independent and can run in parallel.
Tasks 11-12-14-15-16 form a serial chain (each depends on the previous).
Task 13 depends on Task 10 only; can run after Task 10 alongside Tasks 11-12.
