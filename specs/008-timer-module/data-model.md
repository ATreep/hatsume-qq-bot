# Data Model: Timer Module

**Feature**: 008-timer-module | **Date**: 2026-06-07

## Entity-Relationship

```
TimerTask (1) ────< (N) TimerTrigger
```

- One task has many triggers (expanded from recurring patterns like "every day 7am")
- Cascade delete: deleting a task removes all its triggers + cancels all its APScheduler jobs

## TimerTask

| Field | Type | Constraint | Description |
|-------|------|-----------|-------------|
| `id` | INTEGER | PK, AUTOINCREMENT | Task unique ID |
| `group_id` | INTEGER | NOT NULL | QQ group ID where task was created |
| `user_id` | INTEGER | NOT NULL | Creator's QQ ID (looked up at trigger time) |
| `prompt` | TEXT | NOT NULL, max 500 chars | Task content prompt for chat_agent |
| `created_at` | REAL | NOT NULL | Unix timestamp of creation |
| `updated_at` | REAL | NOT NULL | Unix timestamp of last update |

### Lifecycle States

1. **Active**: Has at least one unfired trigger in the future
2. **Completed**: All triggers fired, no future triggers → displayed as "已完成" in list
3. **Deleted**: Removed by user or auto-cleanup (creator left group)

## TimerTrigger

| Field | Type | Constraint | Description |
|-------|------|-----------|-------------|
| `id` | INTEGER | PK, AUTOINCREMENT | Trigger unique ID |
| `task_id` | INTEGER | FK → TimerTask(id) ON DELETE CASCADE | Parent task |
| `trigger_at` | REAL | NOT NULL | Unix timestamp of trigger time |
| `fired` | INTEGER | NOT NULL DEFAULT 0 | 0 = pending, 1 = fired |
| `job_id` | TEXT | NULLABLE | APScheduler job ID (format: `timer_{id}`) |

### Lifecycle States

1. **Pending**: `fired=0`, `trigger_at > now`, `job_id` is set
2. **Fired**: `fired=1`, `job_id` may be cleared
3. **Expired (not fired)**: `fired=0`, `trigger_at < now - tolerance` → marked fired on startup
4. **Missed (in tolerance)**: `fired=0`, `now - tolerance <= trigger_at <= now` → executed on startup recovery

## Indexes

```sql
CREATE INDEX idx_triggers_pending ON timer_triggers(trigger_at) WHERE fired = 0;
```

Used for startup reload: `SELECT * FROM timer_triggers WHERE fired = 0 AND trigger_at > ?`

## Validation Rules

- `trigger_at` must be > current time at creation (FR-015)
- `trigger_at` must be <= current time + 30 days (FR-004, FR-015)
- `prompt` must not be empty (implied)
- `prompt` max 500 characters (edge case in spec)
- Duplicate `trigger_at` values within the same `create_timer` call are deduplicated
- `create_timer` allows at most 10 unique triggers in any rolling 24-hour window (FR-019); this rule is not enforced by TimerStore or `/timer update`
