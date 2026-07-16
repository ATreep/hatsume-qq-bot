# Implementation Plan: Face Emoji Injection + Auto-Create 24h

**Branch**: `025-face-injection-autocreate-24h` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/025-face-injection-autocreate-24h/spec.md`

## Summary

Two independent changes: (1) Replace the separate `face_choice_agent` LLM call with inline prompt injection into `chat_agent` so face emotion selection happens in the same LLM invocation. (2) Remove the auto-create time window (`AUTO_CREATE_TIME_START`/`END`) so auto-create can fire at any hour.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, LangGraph, LangChain, `re` (stdlib)

**Storage**: Face image files in `data/hatsume-plugin/faces/` (filesystem); auto-create timer in SQLite (`timer_db/`)

**Testing**: pytest

**Target Platform**: Linux server (NoneBot2 bot)

**Project Type**: QQ chatbot plugin (NoneBot2)

**Performance Goals**: Remove one LLM round-trip per face send (latency improvement of ~1-3s per face event)

**Constraints**: Do NOT change gate conditions, face file format, or auto-create interval (4-6h)

**Scale/Scope**: 4 files changed, ~50 lines removed, ~60 lines added

## Constitution Check

*GATE: No gates defined (constitution template not yet populated). Proceeding.*

## Project Structure

### Documentation (this feature)

```text
specs/025-face-injection-autocreate-24h/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── config.py                    # Remove AUTO_CREATE_TIME_START/END
├── prompts.py                   # build_face_injection_prompt() replaces classifier
├── graph/nodes/ai.py            # Gate before create_agent, tag extraction, inline face send
└── timer/executor.py            # Simplify _random_next_trigger()

tests/
└── test_graph_nodes.py          # Updated face tests
```

**Structure Decision**: No new files created. All changes are modifications to existing files following established project conventions.

## Complexity Tracking

No violations. Both changes reduce complexity (removing separate agent call, removing time-window logic).
