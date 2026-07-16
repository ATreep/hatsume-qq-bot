# Research: Timer Module

**Feature**: 008-timer-module | **Date**: 2026-06-07

## Decision: SQLite via sqlite3 stdlib

**Rationale**: Python 3.12+ ships with sqlite3. No extra dependencies. Sufficient for hundreds of timer tasks. Existing plugin data is stored as JSON files; SQLite adds ACID transactions and efficient indexed queries (critical for startup: `WHERE fired=0 AND trigger_at > ?`).

**Alternatives considered**:
- JSON file (existing pattern): No query support, manual deduplication, concurrency risks with multiple writers
- aiosqlite: Async wrapper, but adds dependency. sqlite3 is synchronous, fast enough for timer CRUD, and asyncio single-thread means no blocking concern

## Decision: APScheduler DateTrigger for each trigger time

**Rationale**: `nonebot_plugin_apscheduler` already used in the project (night_comic, memory maintenance). DateTrigger fires exactly once at the specified time. Each trigger row gets its own APScheduler job, registered by `job_id = f"timer_{trigger_id}"`.

**Alternatives considered**:
- asyncio.create_task + asyncio.sleep: No persistence, lost on restart
- CronTrigger with end_date: Over-complicated for one-shot triggers within 7-day window
- Custom event loop timer: Reinventing APScheduler

## Decision: Multiprocessing not needed

**Rationale**: Python asyncio is single-threaded, single-process. The timer executor runs as a separate asyncio task, interleaving at await points. This matches the existing pattern (e.g., `generate_video` background task in tools.py).

## Decision: Global state isolation via save/restore

**Rationale**: `graph/tools.py` uses module-level globals (`_tool_call_counts`, `_ai_answer`, etc.). Timer agent needs independent state. Since asyncio is single-threaded, a simple save-before/restore-after pattern works: save all globals, set timer-specific values, run agent, restore. No locks needed.

**Alternatives considered**:
- Context variables (contextvars): Would require refactoring all of tools.py
- Thread-local storage: Not applicable (single-threaded asyncio)
- Separate tool instances: Would duplicate tool definitions

## Decision: get_group_member_name() for username lookup

**Rationale**: Already used by `night_comic.py`. Returns real-time group member name. If user left group, lookup fails → cleanup path triggered.

## Decision: get_bot().get_group_msg_history() for recent messages

**Rationale**: OneBot V11 API provides message history. Not currently used in the codebase, but is a standard OneBot API. Falls back to empty context if unavailable.

**Alternatives considered**:
- Tracking messages in ConversationState.idle_queue: Only works for messages received while graph is running; misses messages between triggers
- Storing recent messages separately: Duplicates existing message pipeline
