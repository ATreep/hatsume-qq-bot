# Quickstart: Auto Create Timer

**Feature**: 020-auto-create-timer
**Date**: 2026-06-29

## Feature Overview

The bot now has an autonomous "auto create" timer that fires once daily at a random time between 7:00 AM and 10:00 PM. When it fires, the bot autonomously chooses and executes a creative task (exploring GitHub trending, generating artwork, forking repos, etc.) and posts the result to the target group.

## Testing

### Run all tests

```bash
python -m pytest tests/ -v
```

### Run auto-create specific tests

```bash
# Store methods (singleton, cascade, get)
pytest tests/test_timer_store.py::TestAutoCreateTask -v

# Random trigger generation
pytest tests/test_auto_create.py::TestRandomNextTrigger -v
```

### Manual testing via /autocreate command

In the configured debug QQ group (`TARGET_GROUP_ID`), send:
```
/autocreate
```
This immediately triggers a creative execution without modifying the database. The bot should produce creative output in the group within 60 seconds.

### Verify auto-respond removal

Send 50+ messages in any group without @-mentioning the bot. The bot should NOT spontaneously respond.

Send a message @-mentioning the bot. The bot should respond normally.

## Key Files

| File | What Changed |
|------|-------------|
| `config.py` | Removed `AUTO_REPLY_*`, `AUTO_RESPONSE_*`; added `AUTO_CREATE_*` constants |
| `state.py` | Removed `should_auto_respond()`, `has_respond_recently` |
| `handlers/chat.py` | Removed auto-respond branch |
| `timer/store.py` | Added `task_type` column, `upsert_auto_create()`, `get_auto_create()`, `list_auto_create_triggers()` |
| `timer/executor.py` | Added `_random_next_trigger()`, `_execute_auto_create()`, `reschedule_auto_create()`, `refresh_auto_create()` |
| `timer/__init__.py` | Calls `refresh_auto_create()` on startup |
| `graph/nodes/ai.py` | Handles `user_id=0` in `inject_timer()` |
| `__init__.py` | Registered `/autocreate` command |
| `handlers/commands.py` | Added `handle_autocreate()` |

## Verification Checklist

- [ ] `pytest tests/ -v` — all tests pass
- [ ] `ruff check hatsume/plugins/hatsume-plugin/` — no lint errors
- [ ] `/autocreate` in `TARGET_GROUP_ID` produces creative output
- [ ] Auto-respond is fully removed (no references to `AUTO_REPLY`, `AUTO_RESPONSE`, `should_auto_respond`, `has_respond_recently`)
- [ ] Auto-create task exists after bot startup
