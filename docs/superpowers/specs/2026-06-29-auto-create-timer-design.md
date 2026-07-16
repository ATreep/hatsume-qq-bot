# Auto Create Timer — Design Spec

**Date:** 2026-06-29
**Status:** Approved
**Project:** hatsume QQ Bot (NoneBot2 Plugin)

## Overview

Remove the auto-respond feature and add a new "auto-create" special timer task. This special timer autonomously executes a creative task using all available LLM tools/skills, posts the result to the configured group, and self-reschedules for the next day. A `/autocreate` slash command enables ad-hoc debugging without touching the database.

## Feature Scope

### In Scope

1. **Remove auto respond**: Delete all code related to the idle-queue automatic response mechanism (`should_auto_respond`, `has_respond_recently`, config constants, trigger logic).
2. **Auto-create timer in DB**: Add `task_type` column to `timer_tasks` table. Ensure at most one `auto_create` row exists at any time.
3. **Auto-create execution**: On trigger, inject the auto-create prompt into the conversation graph. Post output to `TARGET_GROUP_ID` without @-mentioning any user.
4. **Self-rescheduling**: Immediately after injection, delete the old auto-create task and create a new one with a random trigger time tomorrow between 07:00–22:00 (UTC+8).
5. **Startup refresh**: On NoneBot startup (`init_scheduler`), purge old auto-create tasks and create a fresh one.
6. **`/autocreate` debug command**: Fire auto-create immediately in `TARGET_GROUP_ID`, no DB modification.

### Out of Scope

- Multiple auto-create tasks
- Per-group auto-create config
- UI/admin panel for auto-create
- Auto-create analytics/history beyond the existing trigger log

## Architecture

```
┌──────────────────────────────────────────────┐
│  Startup: init_scheduler()                    │
│    ├─ reload_all_triggers()   (existing)      │
│    └─ refresh_auto_create()   (NEW)           │
│         ├─ DELETE all task_type='auto_create' │
│         └─ reschedule_auto_create()           │
│              ├─ upsert_auto_create(rand time) │
│              └─ register_job()                │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│  Runtime: APScheduler fires trigger           │
│    └─ _execute_timer(trigger, store)          │
│         ├─ task_type == 'auto_create'?        │
│         │   YES → _execute_auto_create()      │
│         │     ├─ mark_trigger_fired()         │
│         │     ├─ inject_timer(to graph)       │
│         │     └─ reschedule_auto_create()     │
│         │   NO  → existing timer flow         │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│  Debug: /autocreate command                   │
│    └─ handle_autocreate()                     │
│         └─ inject_timer(to graph,            │
│              group=TARGET_GROUP_ID)            │
│         (no DB change, no reschedule)         │
└──────────────────────────────────────────────┘
```

## Database Changes

### Schema Migration

```sql
ALTER TABLE timer_tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'normal';
```

Safe migration via try/except in `init_db()`. Existing rows default to `'normal'`.

### task_type Values

| Value | Meaning |
|-------|---------|
| `normal` | Regular user timer (notifies user) |
| `auto_create` | Autonomous creative timer (no user notification) |

### Auto-create Task Convention

- `group_id = 0`, `user_id = 0` (no real user association)
- `task_type = 'auto_create'`
- `prompt` = `AUTO_CREATE_PROMPT` from config
- Exactly 1 `auto_create` row enforced at application layer via `upsert_auto_create()`

## Config Changes

### Removed Constants

- `AUTO_REPLY_CURRENT_MSG_COUNT`
- `AUTO_REPLY_HISTORY_MSG_COUNT`
- `AUTO_RESPONSE_PROBABILITY`

### New Constants

```python
AUTO_CREATE_GROUP_ID: int = TARGET_GROUP_ID  # configured in the environment
AUTO_CREATE_TIME_START: int = 7    # 7:00 AM UTC+8
AUTO_CREATE_TIME_END: int = 22     # 10:00 PM UTC+8
```

`AUTO_CREATE_PROMPT` — detailed creative prompt (see config.py inline).

## File Change Summary

| File | Action |
|------|--------|
| `config.py` | Remove 3 auto-reply constants; add 3 auto-create constants + prompt |
| `state.py` | Remove `has_respond_recently` field, `should_auto_respond()` method, `AUTO_RESPONSE_PROBABILITY` import |
| `handlers/chat.py` | Remove auto-respond branch, remove `AUTO_REPLY_*` imports |
| `timer/store.py` | Add `task_type` column migration; add `upsert_auto_create()`, `get_auto_create()`, `list_auto_create_triggers()` |
| `timer/executor.py` | Add `_random_next_trigger()`, `_execute_auto_create()`, `reschedule_auto_create()`, `refresh_auto_create()`; branch on `task_type` in `_execute_timer()` |
| `timer/__init__.py` | Call `refresh_auto_create()` in `init_scheduler()` |
| `handlers/commands.py` | Add `handle_autocreate()` |
| `__init__.py` | Register `autocreate_cmd` matcher |
| `graph/nodes/ai.py` | Handle `user_id=0` in inject logic (no @-mention) |

## Timing & Randomization

```python
def _random_next_trigger() -> float:
    """Pick a random time tomorrow between 07:00–22:00 UTC+8.
    Returns Unix timestamp."""
    # hour ∈ [7, 21], minute ∈ [0, 59]
```

## Error Handling

- **APScheduler job fails to register**: Log error, don't crash. Next startup will recover.
- **LLM execution fails**: Already rescheduled for tomorrow — no action needed.
- **Multiple auto_create rows (should not happen)**: `upsert_auto_create()` deletes all before inserting.
- **`/autocreate` in non-group context**: Matcher requires GroupMessageEvent, so N/A.

## Testing

Key invariants:

1. `upsert_auto_create` is idempotent — at most 1 auto_create row
2. `_random_next_trigger` always returns tomorrow 07:00–22:00
3. Auto-respond code is fully removed (grep confirms zero references)
4. Existing timer tests continue to pass
5. `/autocreate` does not write to DB
