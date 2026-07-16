# Implementation Plan: Timer Module

**Branch**: `008-timer-module` | **Date**: 2026-06-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-timer-module/spec.md`

## Summary

Add a timer module to the hatsume QQ bot. Users create timer tasks via natural language chat (LLM `create_timer` tool call) or explicit `/timer` commands. Tasks persist in SQLite with support for multiple trigger times per task (future 7-day limit). On trigger, an independent chat_agent instance executes the task prompt with isolated state, recent group message context, and sends results to the group @-mentioning the creator. Startup recovery reloads pending triggers from the database, with a 5-minute tolerance window for missed triggers.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, nonebot-plugin-apscheduler (existing), sqlite3 (stdlib), langchain_core, langchain.agents.create_agent

**Storage**: SQLite (single file `timer.db` in plugin data directory via `nonebot_plugin_localstore`)

**Testing**: pytest

**Target Platform**: Linux/macOS server running NoneBot2

**Project Type**: NoneBot2 plugin (existing plugin: `hatsume-plugin`)

**Performance Goals**: Timer trigger-to-message latency < 60s; startup reload < 30s

**Constraints**: Timer chat_agent runs in independent asyncio task, must not block main graph agent. Global tool state isolated via save/restore pattern.

**Scale/Scope**: Tens of timer tasks per group, hundreds total across the bot's lifetime

## Constitution Check

*GATE: N/A — Project constitution is a placeholder template with no defined principles.*

## Project Structure

### Documentation (this feature)

```text
specs/008-timer-module/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── timer-api.md     # Timer tool & command contracts
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── timer/
│   ├── __init__.py           # Public interface: init_scheduler(), get_store()
│   ├── store.py              # TimerStore class: SQLite CRUD operations
│   └── executor.py           # Job management + independent chat_agent execution
├── __init__.py               # [+ /timer command matcher, + init_scheduler() call]
├── config.py                 # [+ TIMER_MAX_FUTURE_DAYS, TIMER_TOLERANCE_MINUTES]
├── debug.py                  # [+ GET /debug/api/timers endpoint]
├── graph/
│   ├── tools.py              # [+ create_timer, list_timers, delete_timer tools, + _current_group_id]
│   └── builder.py            # [+ pass group_id to configure_tool_callbacks]
├── handlers/
│   └── commands.py           # [+ handle_timer() function]

tests/
├── test_timer_store.py       # SQLite CRUD unit tests
├── test_timer_executor.py    # Execution logic + job management tests
├── test_timer_tools.py       # LLM tool parameter validation tests
└── test_timer_commands.py    # /timer command parsing & output tests
```

**Structure Decision**: Follows existing project modular pattern. New `timer/` sub-package mirrors `memory/` structure. Tools added alongside existing tools in `graph/tools.py`. Commands added to existing handler per pattern in `__init__.py`.

## Complexity Tracking

> No constitution violations to justify.
