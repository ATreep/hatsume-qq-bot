# Data Model: Agent State Prompt Injection

**Feature**: 026-agent-state-injection
**Date**: 2026-07-05

## Entities

### Agent Instance (existing, no changes)

Stored in `_AGENT_STATES: dict[str, list[dict]]` in `graph/agents.py`.

| Field | Type | Description |
|-------|------|-------------|
| `instance_id` | `str` | Unique ID, format `{name}_{uuid_hex_8}` |
| `name` | `str` | Agent type name (e.g., `"coding_agent"`, `"background_shell"`) |
| `status` | `"running"` \| `"done"` \| `"idle"` | Current lifecycle state |
| `task` | `str` | Natural language task description |
| `user_id` | `int` | QQ user ID to notify on completion |
| `started_at` | `float` | Unix timestamp when execution began |
| `result` | `str` (optional) | Output text when status is `"done"` |

### Lifecycle

```
[created] → status="running" → status="done"
                                   ↓
                              result populated
                              notification injected
```

### Prompt Injection Data

The `build_agent_state_prompt()` function filters `_AGENT_STATES` to only instances with `status == "running"` and extracts:

| Output Field | Source Field | Transform |
|---|---|---|
| name | `inst["name"]` | None |
| task | `inst["task"]` | Truncate to 200 chars |
| elapsed | `inst["started_at"]` | `int(time.time() - started_at)` seconds |

Empty string returned when no running instances exist.
