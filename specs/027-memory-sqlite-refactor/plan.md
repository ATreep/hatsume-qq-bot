# Implementation Plan: Memory System SQLite Refactor

**Branch**: `027-memory-sqlite-refactor` | **Date**: 2026-07-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/027-memory-sqlite-refactor/spec.md`

## Summary

Refactor the hatsume memory system to use SQLite for persistent storage (storing tokenized corpus and embedding vectors alongside content to eliminate rebuild-on-startup), replace the separate LLM-based memory recording pass with inline `[memoryrecord: {...}]` JSON tags parsed from chat_agent output, and implement two-phase memory retrieval (user-specific within 6-hour window → supplemental fill to MAX_MEMORY_LIMIT=50).

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: nonebot2, langgraph, langchain-openai, numpy, rank_bm25, jieba

**Storage**: SQLite (stdlib `sqlite3`, WAL mode)

**Testing**: pytest

**Target Platform**: Linux server (NoneBot2 + OneBot V11 adapter)

**Project Type**: NoneBot2 Plugin (QQ chat bot)

**Performance Goals**: Memory retrieval <1s for up to 1000 stored memories; startup memory loading without embedding API calls

**Constraints**: Single-process access; WAL mode sufficient for concurrency; embedding vectors are 1024-dimensional float32

**Scale/Scope**: ~1000 memories max (150-day retention); 50 memories retrieved per conversation turn

## Constitution Check

*GATE: No constitution defined — all gates pass by default.*

## Project Structure

### Documentation (this feature)

```text
specs/027-memory-sqlite-refactor/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A — no external interfaces)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── memory/
│   ├── __init__.py       # MODIFY: re-export from db.py
│   ├── db.py             # NEW: SQLite CRUD, schema, migration
│   ├── store.py          # MODIFY: delegate persistence to db.py
│   ├── retrieval.py      # MODIFY: two-phase query_mems()
│   └── tokenizer.py      # UNCHANGED
├── graph/
│   ├── nodes/
│   │   ├── ai.py         # MODIFY: parse [memoryrecord:...], extract_user_ids
│   │   └── finish.py     # MODIFY: remove mem_record_agent
│   └── tools.py          # MODIFY: remove write_memory, update query_memory()
├── config.py             # MODIFY: MAX_MEMORY_LIMIT, remove MEMORY_TOP_K
└── prompts.py            # MODIFY: add 记忆记录, remove MEMORY_RECORDING_PROMPT

tests/
├── test_memory_db.py     # NEW: SQLite layer tests
├── test_memory_utils.py  # MODIFY: update for new query_mems signature
├── test_graph_nodes.py   # MODIFY: update finish tests, remove transcript tests
└── test_tools.py         # MODIFY: remove write_memory tests

data/hatsume-plugin/
├── memory.db             # NEW: SQLite database (replaces memory.json)
└── memory.json.bak       # Created after migration (backup)
```

**Structure Decision**: Single-plugin structure following existing NoneBot2 conventions. New `db.py` is a leaf module within `memory/`; all other changes modify existing files.

## Complexity Tracking

> No violations — constitution is empty.
