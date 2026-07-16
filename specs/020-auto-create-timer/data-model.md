# Data Model: Auto Create Timer

**Feature**: 020-auto-create-timer
**Date**: 2026-06-29

## Entity: Timer Task (`timer_tasks`)

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique task identifier |
| group_id | INTEGER | NOT NULL | Target QQ group (0 for auto_create) |
| user_id | INTEGER | NOT NULL | Creator QQ user (0 for auto_create) |
| prompt | TEXT | NOT NULL | Task prompt/instructions |
| created_at | REAL | NOT NULL | Unix timestamp of creation |
| updated_at | REAL | NOT NULL | Unix timestamp of last update |
| task_type | TEXT | NOT NULL, DEFAULT 'normal' | 'normal' or 'auto_create' |

### State Transitions

```
[Created] ──trigger fires──> [Executed] (marked via trigger.fired)
     │
     └──upsert_auto_create()──> [Deleted] (CASCADE: triggers deleted too)
```

### Validation Rules

- `prompt`: 1–500 characters, non-whitespace
- `task_type`: one of `'normal'`, `'auto_create'`
- `group_id`: 0 for auto_create, real group ID for normal
- `user_id`: 0 for auto_create, real user ID for normal

### Uniqueness

- At most 1 row where `task_type = 'auto_create'` (enforced at application layer by `upsert_auto_create()`)

## Entity: Timer Trigger (`timer_triggers`)

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | Unique trigger identifier |
| task_id | INTEGER | NOT NULL, FK → timer_tasks(id) ON DELETE CASCADE | Parent task |
| trigger_at | REAL | NOT NULL | Unix timestamp of scheduled fire time |
| fired | INTEGER | NOT NULL, DEFAULT 0 | 0 = pending, 1 = fired |
| job_id | TEXT | | APScheduler job identifier (e.g., `timer_42`) |

### State Transitions

```
[Pending] ──trigger fires──> [Fired]
(fired=0)                    (fired=1)
```

### Indexing

- Partial index on `(trigger_at) WHERE fired = 0` for fast pending trigger queries

### For Auto-Create

- Exactly 1 pending trigger at any time (via task singleton)
- Trigger is fire-and-forget: marked fired immediately on execution, reschedule is independent

## Relationship Diagram

```
timer_tasks (1) ──────< (N) timer_triggers
   │                            │
   │ task_type                  │ fired=0 → pending
   │ = 'normal'                 │ fired=1 → done
   │ = 'auto_create'            │
   │                            │
   └─ group_id, user_id         └─ trigger_at (Unix ts)
```

## Auto-Create Lifecycle

```
Bot Startup
    │
    ▼
refresh_auto_create()
    ├── DELETE FROM timer_tasks WHERE task_type = 'auto_create'  (CASCADE deletes triggers)
    ├── INSERT new task (group_id=0, user_id=0, task_type='auto_create', prompt=AUTO_CREATE_PROMPT)
    ├── INSERT new trigger (trigger_at = tomorrow 7AM-10PM random)
    └── Register APScheduler job

Timer Fires
    │
    ▼
_execute_auto_create()
    ├── mark_trigger_fired(trigger_id)     # This trigger done
    ├── inject_timer(user_id=0, ...)        # Fire creative task into graph
    └── reschedule_auto_create()            # Create tomorrow's task (new DELETE+INSERT cycle)
```
