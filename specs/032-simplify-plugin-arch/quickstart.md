# Quickstart: Simplify Plugin Architecture

**Feature**: 032-simplify-plugin-arch
**Date**: 2026-07-15

## For Developers: Navigating the Refactored Codebase

### Where is the code now?

| If you're looking for... | It used to be in... | It's now in... |
|---|---|---|
| Conversation orchestration | `handlers/chat.py` | `handlers/dialogue.py` (section 3) |
| Message parsing/pipeline | `handlers/pipeline.py` | `handlers/dialogue.py` (section 2) |
| Forward message parsing | `handlers/forward.py` | `handlers/dialogue.py` (section 1) |
| Command handlers (shell, video, timer, etc.) | `handlers/commands.py` | `handlers/tools.py` (section 2) |
| Poke/戳一戳 handler | `handlers/poke.py` | `handlers/tools.py` (section 1) |
| Likes/点赞 | `handlers/likes.py` | `handlers/social.py` |
| Memory CRUD & persistence | `memory/db.py` | `memory/engine.py` (section 1) |
| Memory storage & BM25 index | `memory/store.py` | `memory/engine.py` (section 2) |
| Memory hybrid retrieval | `memory/retrieval.py` | `memory/engine.py` (section 3) |
| Tokenizer | `memory/tokenizer.py` | `memory/tokenizer.py` (unchanged) |

### Import changes

```python
# OLD → NEW
from .handlers.chat import start_chat       → from .handlers.dialogue import start_chat
from .handlers.commands import handle_shell  → from .handlers.tools import handle_shell
from .handlers.likes import handle_like      → from .handlers.social import handle_like
from .handlers.poke import handle_poke       → from .handlers.tools import handle_poke
from .memory.store import get_mem_list       → from .memory.engine import get_mem_list
from .memory.retrieval import query_mems     → from .memory.engine import query_mems
```

### What was removed?

- **22 dead constants** from `config.py` (unused API keys, base URLs, model names, memory constants, shell constants, skill path)
- **6 dead TypedDicts** from `state.py` (PersonEntry, MemoryRecord, SourceEntry, TextContent, ImageContent, ContentPart)
- **11 dead functions** across prompts.py (4), models.py (1), timer/ (3), infra.py (1), graph/nodes.py (1), memory/store.py (1)
- **6 dead state paths**: `last_image_time`, `_last_capture_html_demand`, `_update_image_time`, `_get_human_sources`, `deduplicate_return` branch, `get_pending_triggers`
- **2 redundant patterns consolidated**: `_start_conv_for_agent` + `_start_conv_for_timer` → `_start_conv_for_trigger`

### Verification

```bash
# Run the full test suite
python -m pytest tests/ -xvs

# Lint check
ruff check hatsume/plugins/hatsume-plugin/
```
