# Implementation Plan: Auto Create Timer

**Branch**: `020-auto-create-timer` | **Date**: 2026-06-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/020-auto-create-timer/spec.md`

## Summary

Remove the auto-respond feature and add a self-renewing "auto create" special timer task. The special timer autonomously executes creative LLM tasks daily at a random time between 7:00 AM and 10:00 PM, posts results to the target QQ group without @-mentioning any user, and immediately reschedules itself for the next day. A `/autocreate` command enables ad-hoc debugging without database modification.

## Technical Context

**Language/Version**: Python 3.12+ (with `from __future__ import annotations`)

**Primary Dependencies**: NoneBot2, nonebot-adapter-onebot, nonebot-plugin-apscheduler, LangChain, LangGraph, volcenginesdkarkruntime

**Storage**: SQLite (via sqlite3 module), single DB file at `data/hatsume-plugin/timer_db/timer.db`

**Testing**: pytest (with importlib-based module loading for NoneBot dependency isolation)

**Target Platform**: Python server process (Linux/macOS), accessed via QQ group chat through OneBot V11

**Project Type**: NoneBot2 plugin (single-plugin Python project)

**Performance Goals**: Reschedule within 5s of trigger fire; `/autocreate` output visible within 60s

**Constraints**: Must not break existing timer functionality; existing tests must continue to pass; ruff lint compliance

**Scale/Scope**: 1 auto-create task at any time; ~10 files modified; ~3 files created (tests + config additions)

## Constitution Check

*GATE: Constitution template is unpopulated — no gates to enforce. Proceed.*

## Project Structure

### Documentation (this feature)

```text
specs/020-auto-create-timer/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── __init__.py              # Modify: register autocreate_cmd matcher
├── config.py                # Modify: remove auto-reply, add auto-create constants
├── state.py                 # Modify: remove auto-respond fields/methods
├── handlers/
│   ├── chat.py              # Modify: remove auto-respond branch
│   └── commands.py          # Modify: add handle_autocreate()
├── graph/nodes/
│   └── ai.py                # Modify: handle user_id=0 in inject_timer
└── timer/
    ├── __init__.py           # Modify: call refresh_auto_create() on startup
    ├── store.py              # Modify: add task_type column + auto-create methods
    └── executor.py           # Modify: add auto-create execution + lifecycle

tests/
├── test_auto_create.py       # New: random trigger + execution tests
├── test_timer_store.py       # Modify: add TestAutoCreateTask + update schema test
├── test_chat_send.py         # Modify: remove auto-respond stubs
└── test_conversation.py      # Modify: remove auto-respond stubs
```

**Structure Decision**: Single project structure following existing plugin layout. All timer changes stay within `timer/` module. New tests follow existing `tests/` patterns with importlib-based module loading.

## Complexity Tracking

No constitution violations — no entries needed.
