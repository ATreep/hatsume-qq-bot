# Timer V2 Native Scheduling Design

## Goal

Replace the legacy finite timestamp-list timer interface with four explicit timer
creation modes backed by native APScheduler triggers, move persistence to
`data/timer-v2-db/timer.db`, provide a one-shot manual migration for unfinished
legacy tasks, expose complete schedule information through `list_timers`, and
remove finished tasks every day at 03:00 China Standard Time.

## Confirmed Product Decisions

- Timer creation is exposed through exactly four tools: daily, weekly, monthly,
  and exact-time.
- Daily, weekly, and monthly tasks have inclusive start and end timestamps and a
  positive integer interval step.
- Daily time points are strict `HH:MM:SS` strings.
- Weekly time points pair an ISO weekday (`1` for Monday through `7` for Sunday)
  with a strict `HH:MM:SS` string.
- Monthly time points pair a day of month (`1` through `31`) with a strict
  `HH:MM:SS` string.
- Each frequency task accepts one to five complete schedule points per period.
- Each exact-time task accepts one to ten timezone-bearing ISO 8601 timestamps.
- Frequency tasks have no task-wide occurrence-count limit. Their inclusive
  `end_at` boundary is the only end-of-schedule bound.
- The legacy 30-day future horizon is removed. Exact-time and per-period point
  limits remain, but frequency occurrence totals are not truncated.
- The old `get_timer` tool and function are removed. `list_timers` is the single
  read surface and includes complete frequency or exact-trigger details.
- `delete_timer` remains and cancels every APScheduler job owned by the task.
- The existing internal `auto_response` timer remains supported but is not part
  of the four user-facing creation modes.

## Tool Contracts

### Daily

```python
create_daily_timer(
    user_id: int,
    prompt: str,
    start_at: str,
    end_at: str,
    time_points: list[str],
    step: int = 1,
) -> str
```

`start_at` and `end_at` are timezone-bearing ISO 8601 timestamps. `time_points`
contains one to five exact `HH:MM:SS` values. The schedule is anchored to the
calendar date containing `start_at`; `step=2` means every second calendar day.
An occurrence is retained only when its complete timestamp is inside the
inclusive range.

### Weekly

```python
create_weekly_timer(
    user_id: int,
    prompt: str,
    start_at: str,
    end_at: str,
    time_points: list[WeeklyTimePoint],
    step: int = 1,
) -> str
```

```python
class WeeklyTimePoint(TypedDict):
    weekday: int
    time: str
```

The week containing `start_at` is interval week zero. Only weeks whose offset
from that week is divisible by `step` are active. Each time point is a complete
weekday and clock-time pair, and there may be at most five pairs.

### Monthly

```python
create_monthly_timer(
    user_id: int,
    prompt: str,
    start_at: str,
    end_at: str,
    time_points: list[MonthlyTimePoint],
    step: int = 1,
) -> str
```

```python
class MonthlyTimePoint(TypedDict):
    day: int
    time: str
```

The month containing `start_at` is interval month zero. Only months whose offset
from that month is divisible by `step` are active. A point whose day does not
exist in an active month is skipped; it is not moved to the month's final day.

### Exact Time

```python
create_at_timer(
    user_id: int,
    prompt: str,
    trigger_times: list[str],
) -> str
```

`trigger_times` contains one to ten timezone-bearing ISO 8601 timestamps. The
timestamps may be irregular. The raw input list must not exceed ten entries,
duplicate instants are rejected, and all retained instants must be in the future.

### Shared Validation

The tool docstrings and executable validation enforce the same rules:

- The current group must be known.
- The prompt must be nonblank and no longer than 500 characters.
- Start and end timestamps must include a UTC offset, and start must not be after
  end.
- Clock strings must match `HH:MM:SS` exactly and represent a real clock time.
- `step` must be a positive integer.
- Weekly weekdays and monthly days must be in their documented ranges.
- Tool input schemas use strict integers for `step`, `weekday`, and `day`, so
  JSON booleans are rejected instead of being coerced to `1`.
- Frequency point collections contain one to five complete points and may not
  contain duplicates.
- Exact-time collections contain one to ten future instants and may not contain
  duplicates.
- A frequency range must produce at least one future occurrence.

All timestamps are normalized to China Standard Time (`UTC+08:00`) for calendar
calculations and display. A timezone-bearing input that represents the same
instant in another offset remains valid.

## Scheduling Model

The v2 implementation uses native APScheduler triggers rather than persisting
every future occurrence:

- Daily points use `IntervalTrigger(days=step)`.
- Weekly points use `IntervalTrigger(weeks=step)`.
- Monthly points use `CalendarIntervalTrigger(months=step)`.
- Exact timestamps use `DateTrigger`.

When a frequency point has only one retained occurrence remaining, it uses a
native `DateTrigger` for that final instant. The recurrence interval is no
longer semantically relevant in this state, and this avoids asking APScheduler
to calculate an unreachable next date for very large valid steps.

Each complete schedule point owns one APScheduler job. Daily and weekly first-run
dates are calculated from the task's anchor period. Monthly first-run dates are
calculated by advancing through active months until the requested day exists.
Every native trigger has an explicit first and last fire boundary.
Job registration also sets `next_run_time` explicitly to the persisted next
occurrence so crossing that instant during registration enters normal misfire
handling instead of silently advancing to the following interval.

Creation calculates each frequency point independently. It records only that
point's first occurrence, last occurrence, and planned count inside the requested
range, then sums point counts for the task total. It never constructs or stores a
task-wide tuple containing every occurrence. Daily and weekly counts use calendar
arithmetic; monthly calculation advances only through the applicable stepped
months so invalid month days can be skipped. Small tests and legacy
classification may explicitly merge point sequences on demand, but normal task
creation remains bounded in memory by the number of requested points.

APScheduler job identifiers are derived from schedule-point IDs, not task IDs,
so a task with several points can be registered and cancelled independently.
Jobs use China Standard Time, replacement on restart, the existing misfire grace
window, and no silent coalescing of distinct due occurrences.

## Persistence

The default database path is exactly:

```text
data/timer-v2-db/timer.db
```

The path is resolved from the repository/application root rather than the legacy
`nonebot_plugin_localstore` timer directory.

### `timer_tasks`

The task table stores:

- identity, group, user, prompt, creation time, and update time;
- internal `task_type` (`normal` or `auto_response`);
- schedule mode (`daily`, `weekly`, `monthly`, or `at`);
- requested inclusive start and end instants for frequency tasks;
- positive step for frequency tasks;
- requested end and last actual scheduled instant;
- total planned occurrences and total processed occurrences;
- optional unique legacy task ID for migration traceability.

### `timer_schedule_points`

Each point stores:

- its owning task ID with cascading deletion;
- weekday or day-of-month when the mode needs one;
- exact `HH:MM:SS` clock text for frequency points;
- exact timestamp for exact-time points;
- nullable first and last planned timestamps;
- planned and processed occurrence counts;
- last processed scheduled timestamp;
- stable APScheduler job ID.

Indexes cover group task listing, incomplete tasks, and task-owned points. SQLite
foreign keys and WAL remain enabled. Writes use parameters, explicit
transactions, and commits.

Every requested frequency definition is persisted for exact listing. A point
that has no future occurrence inside the requested range is descriptive: it has
a planned count of zero and null first/last timestamps, never owns a scheduled
job, and does not affect task progress totals.

The store owns task and point CRUD, atomic progress updates, incomplete-task
queries, and cleanup queries. Schedule calculation and classification remain in
a pure timer schedule module so they can be tested without SQLite or NoneBot.

## Execution and Recovery

When a native job fires, its point ID identifies the task and the next unprocessed
scheduled occurrence. Normal timer delivery continues through the existing graph
injection path. After the attempt finishes, including an injection failure, the
store advances both point and task progress for that scheduled occurrence. This
matches the existing behavior that a failed delivery attempt is still considered
fired.

On startup, recovery handles every incomplete point:

1. Derive scheduled occurrences after the last processed position and no later
   than the current time.
2. Mark occurrences older than the configured tolerance as processed and
   expired.
3. Dispatch the most recent missed occurrence when it is inside the tolerance
   window, preserving the existing compensation behavior.
4. Register a native job when the point still has future retained occurrences.
5. Leave fully processed tasks for the daily cleanup job.

The progress update is idempotent for a scheduled occurrence. Repeated startup
recovery must not count or inject the same occurrence twice.

`auto_response` continues to use a single internal exact-time task. Startup may
regenerate it when necessary, and it remains excluded from group timer listings
and normal completed-task cleanup.

## Daily Cleanup

Startup registers one APScheduler cron job with a stable ID, replacement enabled,
and timezone `UTC+08:00`. It runs every day at `03:00:00`.

The cleanup selects normal tasks whose processed count equals their planned
count, defensively cancels any remaining point jobs, and deletes the tasks. Point
rows are removed through SQLite cascading deletion. Active tasks and the internal
`auto_response` task are untouched. Repeated cleanup is harmless.

## Legacy Migration

The legacy source is:

```text
data/hatsume-plugin/timer_db/timer.db
```

Migration is never imported, checked, or executed by Bot startup. `get_store()`
only initializes the v2 schema, while `init_scheduler()` only restores v2
schedules, maintains the internal auto-response task, and registers cleanup.

Development completion uses the standalone command
`scripts/migrate_timer_v2.py`. Its defaults are the legacy source above and
`data/timer-v2-db/timer.db`; `--source` and `--destination` override them for
testing and recovery. The command validates that the source is a regular file
before creating or opening the destination. It then initializes and always closes
its destination store, invokes the reusable migration module exactly once, and
prints one JSON object containing `migrated_tasks`, `skipped_tasks`, and
`already_applied`, plus `expanded_frequency_tasks` for the v2 cap-removal
upgrade. A missing source or migration failure exits nonzero without a success
object. The command may be rerun safely after success.

The manual command copies the legacy database and any WAL into a private
temporary directory, then opens only that snapshot with a read-only URI. SQLite
never opens or writes the source database, WAL, or SHM files. All destination
changes run in one transaction. A migration marker and unique legacy task ID make
retries idempotent. A failed migration rolls back the destination and must be
retried manually after the cause is corrected.

Only legacy `normal` tasks with at least one unfired trigger are eligible.
Completed tasks, `auto_create`, and `auto_response` records are not copied. The
internal auto-response lifecycle creates a fresh v2 record.

For each eligible task, migration sorts and deduplicates pending timestamps and
uses both prompt wording and timestamp cadence:

1. Build daily, weekly, and monthly candidates from local calendar positions,
   clock times, and constant period gaps.
2. Use explicit prompt wording such as daily, weekly, weekday names, monthly, or
   day-of-month language to resolve patterns that fit more than one mode.
3. Without a decisive prompt hint, prefer monthly for stable month/day patterns,
   weekly for stable weekday/week-gap patterns, and daily for stable day-gap
   patterns.
4. Fall back to exact-time when no recurrence candidate represents the pending
   timestamps without inventing occurrences.

Frequency migration keeps the earliest five distinct period points and the full
frequency sequence through the inferred end boundary. Exact-time fallback keeps
the earliest ten pending timestamps. Migrated tasks begin with zero processed v2
occurrences and retain the legacy task ID as their public task ID when it does not
conflict.

The same manual command upgrades frequency tasks previously persisted with
`truncated=1`. For each such task it rebuilds point counts through the stored
`end_at`, using the earliest persisted first occurrence as the historical cutoff.
It verifies that every existing nonempty point keeps the same first occurrence,
then updates only planned counts, last occurrences, task total,
`effective_until`, and `truncated`. Point IDs, job IDs, processed counts, and last
processed timestamps remain unchanged. The upgrade runs in a destination
transaction, is idempotent, and never runs from Bot startup. The compatibility
columns `effective_until` and `truncated` remain in the schema; frequency tasks
end with `truncated=0`, while exact-time legacy fallback may still use
`truncated=1` for its ten-timestamp limit.

## Listing and Deletion

`list_timers` remains grouped into unfinished and finished normal tasks until the
03:00 cleanup removes finished rows. Every frequency entry includes:

- task ID, target user, and complete prompt;
- mode and interval step;
- requested inclusive range;
- every exact period point using `HH:MM:SS`;
- planned and processed counts;
- next pending occurrence, or `none` when complete.

Weekly points display localized weekday labels. Monthly points display the day of
month. Exact-time entries list every retained timestamp with its completed or
pending status. This replaces the removed `get_timer` detail surface.

`delete_timer` verifies group ownership, cancels all point jobs, deletes the task
and its points, and returns the existing user-facing confirmation style.

The `/timer update <id> <prompt> @ <timestamps>` command remains available for
backward compatibility. It replaces the selected task with an exact-time
schedule, applies the same one-to-ten timestamp validation as `create_at_timer`,
cancels the old native jobs before replacement, and registers the new date jobs
after the transaction commits. `/timer list` reuses the same detailed overview as
`list_timers` so the command and chat tool cannot drift. `/timer list` with no
argument lists the current group for any caller. `/timer list <group_id>` accepts
one positive integer and lets only the configured administrator inspect a
different group; specifying the current group remains available to ordinary
members. The overview helper accepts the target group explicitly and never
changes the process-global current-group context during cross-group inspection.

## Tool Registry and Prompt Integration

The old `create_timer` and `get_timer` functions are removed. `CHAT_TOOLS`
registers the four new creation tools once each, followed by `list_timers` and
`delete_timer`. Test stubs and graph integrations are updated to match that exact
surface. System-prompt timer overview injection continues to call the shared
`get_timer_overview` helper behind `list_timers`; the helper itself is not a chat
tool.

## Error Handling

Tool input errors return concise Chinese messages and perform no database or
scheduler mutation. Bot startup database errors identify only the v2 destination
and close the unready store; they never mention or access the legacy database.
The manual migration command reports source and destination paths while excluding
prompt contents from exception output, closes the destination on every path, and
returns a nonzero status for operational failures. Scheduler registration
failures do not discard the persisted task; startup recovery can retry them.
Cancellation treats an already absent APScheduler job as success.

## Test Strategy

Focused offline tests cover:

- strict clock parsing, inclusive boundaries, every interval mode, invalid month
  dates, deduplication, point limits, exact-time limits, and frequency plans with
  more than 50 occurrences;
- bounded-memory frequency plan construction and on-demand occurrence expansion;
- v2 schema creation, repeated initialization, CRUD, atomic progress, and
  completed-task cleanup;
- read-only and idempotent legacy migration for daily, weekly, monthly, irregular,
  finished, oversized-period, oversized-occurrence, and internal task fixtures;
- proof that legacy database, WAL, and SHM bytes remain unchanged after migration;
- proof that Bot startup neither imports nor calls the migration module;
- standalone migration command defaults, explicit paths, structured success and
  already-applied output, missing-source failure, exception propagation, and
  destination cleanup;
- manual expansion of previously capped frequency tasks with stable point IDs,
  progress preservation, rollback, and idempotency;
- native interval, calendar-interval, date, and 03:00 cron registration;
- restart compensation, expiration, progress idempotency, cancellation, and
  cleanup;
- all four creation tool docs and executable limits;
- complete frequency and exact-time output in `list_timers`;
- current-group `/timer list`, administrator-only explicit-group listing,
  invalid-group rejection, exact-time update, and delete compatibility;
- removal of `create_timer` and `get_timer` from code, tool registration, graph
  stubs, and architecture documentation;
- continued auto-response behavior through the v2 store.

After focused timer tests pass, verification runs the repository-required Ruff,
Pyright, and complete pytest commands. Tests remain offline and use temporary
SQLite databases; they never initialize or modify either runtime timer database.

## Documentation

`docs/arch.md` will be updated with the four-tool interface, v2 schema, native
scheduler lifecycle, explicit one-shot migration command, recovery behavior,
cleanup job, new module ownership, and removal of `get_timer`. Repository
instructions remain in `AGENTS.md`; no `CLAUDE.md` is created.
