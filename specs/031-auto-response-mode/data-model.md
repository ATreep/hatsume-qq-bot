# Data Model: Auto Response Mode

**Feature**: Auto Response Mode
**Date**: 2026-07-13

## Entities

### Auto Response Task (`timer_tasks` row)

Existing table, new rows with `task_type = 'auto_response'`.

| Field | Type | Value | Notes |
|-------|------|-------|-------|
| `id` | INTEGER PK | auto | |
| `group_id` | INTEGER | 0 | Storage placeholder; actual target from config |
| `user_id` | INTEGER | 0 | No user association |
| `prompt` | TEXT | From `get_auto_response_prompt()` | Randomly chosen wording variation |
| `created_at` | REAL | `time.time()` | Unix timestamp |
| `updated_at` | REAL | `time.time()` | Unix timestamp |
| `task_type` | TEXT | `'auto_response'` | Distinguishes from `'normal'` and `'auto_create'` |

**Uniqueness rule**: At most one `task_type = 'auto_response'` row. Enforced by `upsert_auto_response()` which DELETE-all-then-INSERT.

### Auto Response Trigger (`timer_triggers` row)

Existing table, one unfired trigger per auto_response task.

| Field | Type | Value | Notes |
|-------|------|-------|-------|
| `id` | INTEGER PK | auto | |
| `task_id` | INTEGER FK | → `timer_tasks.id` | CASCADE on delete |
| `trigger_at` | REAL | Random [now+1h, now+3h] | Unix timestamp |
| `fired` | INTEGER | 0 | Set to 1 when timer executes |
| `job_id` | TEXT | `"timer_{trigger_id}"` | APScheduler job identifier |

### Lifecycle / State Transitions

```
[No task exists]
    │
    ▼ refresh_auto_response() or first reschedule
[Task created, Trigger pending (fired=0)]
    │
    ▼ APScheduler fires → _execute_auto_response()
[Trigger fired (fired=1)] + [New Task created with new Trigger]
    │
    ▼ (self-renewing loop continues)
```

## Validation Rules

- `trigger_at` must be in the future when created
- Exactly one unfired trigger per auto_response task at any time
- `task_type` must be exactly `'auto_response'` for these rows
