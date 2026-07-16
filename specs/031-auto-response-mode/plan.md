# Implementation Plan: Auto Response Mode

**Branch**: `031-auto-response-mode` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/031-auto-response-mode/spec.md`

## Summary

Add a self-renewing "auto response" timer that periodically injects a short-topic-reply prompt into the conversation graph. Directly mirrors the existing auto_create architecture: APScheduler triggers execution, prompt is injected via `inject_timer()`, and the timer immediately reschedules itself. New `task_type='auto_response'` row in the existing `timer_tasks` table.

**Technical approach**: Reuse existing auto_create code patterns exactly — store methods, executor functions, debug command, and matcher registration all follow the same structure. No new abstractions or refactoring needed.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, APScheduler (nonebot-plugin-apscheduler), SQLite (stdlib sqlite3)

**Storage**: SQLite — existing `timer_tasks` + `timer_triggers` tables (no migration needed; `task_type` column already exists)

**Testing**: pytest

**Target Platform**: Linux server (NoneBot2 runtime)

**Project Type**: NoneBot2 plugin (bot feature)

**Performance Goals**: Timer fires within 30s of scheduled time; startup recovery completes within 2 minutes

**Constraints**: Singleton timer — at most one `auto_response` task at any time; fire-and-forget rescheduling (no blocking on LLM)

**Scale/Scope**: Single group deployment; 1 timer firing every 1-3 hours

## Constitution Check

*GATE: Constitution template is unpopulated (placeholder only). No gates to verify.*

## Project Structure

### Documentation (this feature)

```text
specs/031-auto-response-mode/
├── spec.md              # Feature specification
├── plan.md              # This file
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

Files touched (all under `hatsume/plugins/hatsume-plugin/`):

```text
hatsume/plugins/hatsume-plugin/
├── config.py                   # +AUTO_RESPONSE_GROUP_ID constant
├── prompts.py                  # +get_auto_response_prompt()
├── __init__.py                 # +autoresponse matcher + import
├── handlers/
│   └── commands.py             # +handle_autoresponse() debug command
└── timer/
    ├── __init__.py             # +refresh_auto_response() call in init_scheduler
    ├── store.py                # +upsert/get/list_auto_response methods
    └── executor.py             # +trigger_gen, execute, reschedule, refresh + route

tests/
└── test_auto_response.py       # New test file
```

**Structure Decision**: Follow existing project layout. All changes are additions within existing files, following the auto_create pattern. Single new test file mirrors `test_auto_create.py`.

## Complexity Tracking

No violations. Feature reuses existing patterns without introducing new abstractions.
