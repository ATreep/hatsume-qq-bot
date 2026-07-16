# Auto Response Mode — Design Spec

**Date:** 2026-07-13
**Status:** approved

## Overview

Add an "auto response" mode — a self-renewing periodic timer that periodically injects a short-topic-reply prompt into the conversation graph. Mirrors the existing "auto create" mode's architecture: fire-and-forget timer that reschedules itself immediately upon triggering.

## Motivation

The bot currently has `auto_create` for long-form creative research tasks (every 4-6h). Auto response fills a different niche: lightweight, high-frequency community engagement — picking a topic from recent chat history and replying with a short (~30 char) message to keep the group lively.

## Design

### Approach

Direct reuse of the `auto_create` self-renewing fire-and-forget pattern. Both modes share the same code structure and differ only in parameters.

| Dimension | auto_create | auto_response |
|-----------|-------------|---------------|
| `task_type` | `auto_create` | `auto_response` |
| Group ID | `AUTO_CREATE_GROUP_ID` | `AUTO_RESPONSE_GROUP_ID` (new config var) |
| Interval | random 4-6h | random 1-3h |
| Time window | 7:00-22:00 only | 24h (no restriction) |
| Prompt | Random research task | Fixed core + minor random variations |
| Startup recovery | Supported (commented out) | Supported (enabled) |

### Files to Change

| File | Change |
|------|--------|
| `config.py` | Add `AUTO_RESPONSE_GROUP_ID` constant |
| `prompts.py` | Add `get_auto_response_prompt()` |
| `timer/store.py` | Add `upsert_auto_response()`, `get_auto_response()`, `list_auto_response_triggers()` |
| `timer/executor.py` | Add `_random_response_trigger()`, `_execute_auto_response()`, `reschedule_auto_response()`, `refresh_auto_response()` |
| `timer/__init__.py` | Call `refresh_auto_response()` in `init_scheduler()` |
| `handlers/commands.py` | Add `/autoresponse` debug command |
| `__init__.py` | Register `autoresponse` matcher (admin only) |

### Components

#### 1. Config (`config.py`)
```python
AUTO_RESPONSE_GROUP_ID: int = TARGET_GROUP_ID  # same target as auto_create
```

#### 2. Prompt (`prompts.py`)
```python
def get_auto_response_prompt() -> str:
    """Core: pick a topic from chat history, reply in ≤30 chars."""
    # Fixed core with minor random variation in wording
    variations = [
        "(SYSTEM)从聊天记录与最近的历史记录中挑选一个话题进行一句话回复，不超过30字。",
        "(SYSTEM)看看最近的聊天记录，选一个有意思的话题，用一句话回复，别超过30个字。",
        "(SYSTEM)浏览最近的群聊内容，找一个话题进行简短的一句话回复（30字以内）。",
    ]
    return random.choice(variations)
```

#### 3. Store (`timer/store.py`)

Three new methods, mirroring auto_create:

- **`upsert_auto_response(trigger_at, prompt=None)`** — Delete all old `auto_response` tasks, create one new. Guarantees at most one `auto_response` row. Returns `task_id`.
- **`get_auto_response()`** — Get current auto_response task with pending trigger, or None.
- **`list_auto_response_triggers()`** — List unfired triggers for auto_response tasks.

#### 4. Executor (`timer/executor.py`)

Four new functions, mirroring auto_create:

- **`_random_response_trigger()`** — Random timestamp in `[now+1h, now+3h]`. No time-window restriction (24h).
- **`_execute_auto_response(task, store)`** — Injects prompt via `inject_timer(user_id=0, is_auto_create=False)`, marks trigger fired, calls `reschedule_auto_response()`.
- **`reschedule_auto_response(store)`** — Delete old + create new with random trigger, register APScheduler job.
- **`refresh_auto_response(store)`** — Startup recovery: re-register pending trigger or create fresh one.

#### 5. Scheduler Init (`timer/__init__.py`)

Add `await refresh_auto_response(store)` call in `init_scheduler()`, alongside the existing (commented-out) auto_create refresh.

#### 6. Debug Command (`handlers/commands.py`)

`handle_autoresponse()` — mirrors `handle_autocreate()`: immediately inject the prompt into the graph without touching the DB. Admin-only via matcher.

### Data Flow

```
APScheduler triggers _execute_wrapper()
  → _execute_timer()
    → task_type == 'auto_response' → _execute_auto_response()
      → inject_timer(user_id=0, prompt=get_auto_response_prompt(), is_auto_create=False)
        → if _state.is_chatting: human_queue.append()
        → else: start_conversation_cb()
      → store.mark_trigger_fired(trigger_id)
      → reschedule_auto_response(store)   # fire-and-forget — no waiting for LLM
```

### inject_timer Behavior

No changes needed to `inject_timer()`. With `user_id=0` and `is_auto_create=False`:
- Log tag: `"timer (no user)"`
- No @-mention in the message
- Appends to `human_queue` if chatting, otherwise starts new conversation

### Error Handling

- Store operations use existing SQLite patterns (WAL mode, foreign keys)
- APScheduler job registration uses `replace_existing=True` to avoid duplicates
- If inject_timer fails, the trigger is still marked fired and rescheduling proceeds (same as auto_create)

### Testing

New test file `tests/test_auto_response.py` covering:
- `_random_response_trigger()` returns timestamp in [now+1h, now+3h]
- Random distribution across 100 samples
- Store CRUD: upsert, get, list triggers
- Executor lifecycle: execute → reschedule → refresh

### Edge Cases

| Scenario | Handling |
|----------|----------|
| Bot restarts with pending trigger | `refresh_auto_response()` re-registers APScheduler job |
| Bot restarts with expired trigger | Creates fresh trigger (same as auto_create) |
| Two auto_response tasks somehow exist | `upsert_auto_response()` deletes all old rows first |
| LLM not available when timer fires | Timer injects into queue; graph handles failure normally |
| Chat is already active | Injects into `human_queue`, waits for current turn to finish |

### Non-Goals

- Per-group auto response (single global instance, same as auto_create)
- User-facing `/autoresponse on/off` toggle (debug command only, admin-only)
- Different prompts per time of day (single prompt pool)
