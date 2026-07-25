# Timer Compatibility Removal Design

## Goal

Remove all Timer v1 and transitional Timer v2 compatibility state from the
active timer database and runtime. Preserve the current Timer v2 tasks and
their progress while moving the database under the Hatsume plugin data
directory managed by `nonebot_plugin_localstore`.

The final runtime supports only the current Timer v2 schema. It does not detect
old database locations, upgrade old schemas, or import Timer v1 data.

## Scope

The change removes:

- `timer_tasks.truncated`;
- `timer_tasks.effective_until`;
- `timer_tasks.legacy_task_id`;
- the `timer_migrations` table;
- the legacy Timer v1 migration module and command;
- legacy schedule inference and capped-frequency expansion code;
- truncated-schedule notes in timer listings;
- tests and current architecture documentation for removed compatibility paths.

The exact-time creation limit of ten points remains a current product rule and
is not compatibility behavior. Frequency tasks continue to retain at most five
distinct period points while keeping every occurrence through their inclusive
end boundary.

## Final Database Location

`TimerStore` resolves its default path with:

```python
nonebot_plugin_localstore.get_plugin_data_file("timer-v2-db/timer.db")
```

With the repository's `LOCALSTORE_USE_CWD=true` deployment configuration, the
path is:

```text
data/hatsume-plugin/timer-v2-db/timer.db
```

`TimerStore.init_db()` creates the nested `timer-v2-db` parent directory before
opening SQLite. The runtime has no fallback to `data/timer-v2-db/timer.db`.

## Final Schema

The active database contains only `timer_tasks` and
`timer_schedule_points`, plus SQLite's internal tables and the existing indexes.

```text
timer_tasks
  id, group_id, user_id, prompt, task_type, schedule_type
  start_at, end_at, step
  total_occurrences, processed_occurrences
  created_at, updated_at

timer_schedule_points
  id, task_id, period_value, clock_time, exact_at
  first_fire_at, last_fire_at
  planned_occurrences, processed_occurrences, last_processed_at, job_id
```

The existing constraints remain: task and schedule types are checked, progress
cannot exceed planned occurrences, point timestamps agree with planned counts,
point job IDs are unique, and deleting a task cascades to its points.

## One-Time Data Conversion

The repository's current database is converted offline before the runtime code
is switched to the final schema.

1. Confirm no Hatsume process holds the timer database open.
2. Use the SQLite backup API to create a consistent working copy that includes
   committed WAL contents. Leave the old database and its sidecars untouched.
3. In the working copy, expand every frequency task whose old
   `truncated` value is `1`, using its stored boundaries, step, points, and first
   retained occurrence. Preserve task IDs, point IDs, job IDs, processed counts,
   and last-processed timestamps.
4. Rebuild `timer_tasks` with only the final columns and copy all task rows.
5. Drop `timer_migrations` and the old `timer_tasks` table.
6. Run SQLite integrity and foreign-key checks, verify task, point, and progress
   counts, and confirm that no compatibility column or table remains.
7. Place the validated working copy at the localstore destination.
8. Reopen and validate the destination, then remove the old database and its WAL
   and SHM sidecars.

The conversion is an implementation-time operation, not a retained runtime
migration facility. If validation fails, the destination is discarded and the
old database remains untouched.

The current workspace database has five tasks and no row with
`truncated = 1`, but the expansion step remains part of the conversion procedure
so the operation is correct for any pre-conversion contents.

## Runtime Changes

`SchedulePlan` no longer contains `effective_until` or `truncated`. Schedule
builders compute points and total occurrences only. The internal exact-time
helper needed by auto-response and recovery tests remains, but legacy timestamp
pattern inference is removed.

`TimerStore` creates and writes only the final schema, then validates the
application table and column sets. It fails initialization when an incompatible
schema is found instead of accepting extra compatibility state. Task creation
and exact replacement SQL no longer mention compatibility columns. Migration
marker APIs and capped-frequency expansion APIs are deleted.

The legacy `timer/migration.py` module and `scripts/migrate_timer_v2.py` command
are deleted. Startup continues to initialize the database, restore point jobs,
compensate recent missed triggers, refresh auto-response, and register cleanup;
none of those flows perform schema or path migration.

Timer overview output continues to show exact points, frequency rules, total and
processed counts, and the next occurrence. It no longer reports truncation or an
effective retained boundary.

## Failure Handling

Runtime database initialization fails visibly if the localstore path cannot be
resolved or the final schema cannot be opened. It does not silently open an old
path or modify an incompatible schema.

The one-time data conversion uses SQLite transactions and validation before old
files are removed. Source removal happens only after the destination opens
successfully and passes integrity, foreign-key, row-count, and progress checks.

## Tests

Focused tests cover:

- localstore-based default path resolution;
- a fresh database containing exactly the final application tables and columns;
- absence of all removed compatibility columns and tables;
- repeated initialization preserving existing final-schema data;
- unchanged task creation, exact replacement, progress, cleanup, auto-response,
  executor recovery, and timer overview behavior;
- rejection of a database that still contains compatibility schema.

The one-time conversion separately records before-and-after row counts, IDs,
schedule points, and progress during implementation. It is not retained as a
runtime migration API or permanent compatibility test harness.

Tests dedicated only to Timer v1 import, migration markers, legacy cadence
inference, and the removed migration CLI are deleted. After focused Timer tests,
the repository's Ruff, Pyright, and complete Pytest checks must pass without
ignored collection errors, warnings, or type errors.

## Documentation

`AGENTS.md` and `docs/arch.md` are updated to describe the localstore path, final
schema, and current runtime behavior. The prior Timer v2 design and plan remain
as historical decision records; they are not current architecture references.
Runtime database files remain outside the main repository and are not committed.
