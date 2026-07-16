# Research: Auto Create Timer

**Feature**: 020-auto-create-timer
**Date**: 2026-06-29

## Decisions

### 1. Task Type Discrimination

**Decision**: Add `task_type TEXT NOT NULL DEFAULT 'normal'` column to `timer_tasks` table.

**Rationale**: Clean semantic distinction between `'normal'` and `'auto_create'` tasks. Extensible for future task types. Better than magic-number sentinels (group_id=-1, user_id=-1) which are fragile and non-obvious.

**Alternatives considered**:
- Magic numbers: rejected — semantically opaque, easy to break
- Separate table: rejected — duplicates trigger management logic

### 2. Singleton Enforcement

**Decision**: Application-level enforcement via `upsert_auto_create()` that DELETE-then-INSERT.

**Rationale**: SQLite lacks stored procedures. A UNIQUE constraint on `task_type` would prevent multiple types ever, which is overly restrictive. The DELETE-then-INSERT pattern is atomic within a single SQLite transaction.

**Alternatives considered**:
- UNIQUE constraint on task_type: rejected — prevents multiple 'normal' tasks
- Database trigger: rejected — SQLite triggers add complexity without benefit

### 3. Reschedule Timing

**Decision**: Fire-and-forget — reschedule immediately after graph injection, don't wait for LLM completion.

**Rationale**: Robustness. If the LLM execution hangs or errors, tomorrow's task is still scheduled. The reschedule takes <1ms (DB write + APScheduler registration) vs waiting potentially minutes for LLM completion.

**Alternatives considered**:
- Wait for graph completion callback: rejected — complex, failure-prone
- Polling: rejected — wastes resources

### 4. Random Trigger Time Generation

**Decision**: `random.randint(hour=7..21, minute=0..59)` for tomorrow's date, UTC+8 timezone.

**Rationale**: Simple uniform distribution across the allowed window. Avoids midnight edge cases. The 15-hour window (07:00-22:00) provides sufficient randomness.

**Alternatives considered**:
- Weighted distribution favoring midday: rejected — unnecessary complexity
- Fixed time: rejected — defeats purpose of variety

### 5. Auto-Create Graph Injection

**Decision**: Reuse existing `inject_timer()` in `graph/nodes/ai.py` with `user_id=0` sentinel.

**Rationale**: Leverages existing conversation graph infrastructure. The `user_id=0` triggers a special message format without @-mention. No new graph nodes needed.

**Alternatives considered**:
- Separate graph path: rejected — duplicates infrastructure
- New LLM agent outside graph: rejected — loses access to conversation context and tools

### 6. Schema Migration Safety

**Decision**: `ALTER TABLE ... ADD COLUMN` wrapped in `try/except sqlite3.OperationalError`.

**Rationale**: SQLite doesn't support `IF NOT EXISTS` for `ALTER TABLE`. The try/except handles both the column-already-exists case and any unexpected errors gracefully. The `DEFAULT 'normal'` ensures backward compatibility.

**Alternatives considered**:
- Check `PRAGMA table_info` first: rejected — same outcome, more code
- Fresh schema: rejected — would lose existing data

### 7. Debug Command Isolation

**Decision**: `/autocreate` injects directly to the configured `TARGET_GROUP_ID`, with no DB write.

**Rationale**: Debug mode must not interfere with the scheduled auto-create lifecycle. Using a separate group prevents test output from polluting the production group. No DB modification keeps the singleton invariant intact.

**Alternatives considered**:
- Trigger the scheduled task early: rejected — would require reschedule logic
- Write to DB with immediate trigger time: rejected — risks singleton violation
