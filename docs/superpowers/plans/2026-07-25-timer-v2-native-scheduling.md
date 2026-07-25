# Timer V2 Native Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace legacy timestamp-expanded timers with four validated creation modes, native APScheduler recurrence, v2 SQLite persistence, an explicit one-shot unfinished-task migration command, detailed listing, and daily completed-task cleanup.

**Architecture:** A pure schedule module parses and calculates finite daily, weekly, monthly, and exact plans. SQLite stores task definitions and per-point progress, while APScheduler owns one native job per point and startup only rebuilds runtime jobs from v2 state. A standalone repository script reuses the read-only migration module after development; Bot startup never imports or executes legacy migration code.

**Tech Stack:** Python 3.12, SQLite, APScheduler 3.11, NoneBot2, LangChain tools, pytest, Ruff, Pyright.

**Repository constraint:** Do not create commits unless the user explicitly asks. The commit steps normally required by the planning workflow are intentionally replaced with status and diff checks.

---

## File Structure

- Create `hatsume/plugins/hatsume-plugin/timer/schedule.py`: schedule value objects, strict parsing, occurrence calculation, 50-occurrence allocation, next-occurrence derivation, and legacy frequency classification.
- Create `hatsume/plugins/hatsume-plugin/timer/migration.py`: read-only, idempotent v1-to-v2 migration orchestration.
- Create `scripts/migrate_timer_v2.py`: explicit CLI for one-shot migration with default and override paths.
- Replace `hatsume/plugins/hatsume-plugin/timer/store.py`: v2 schema, task/point CRUD, progress, exact replacement, cleanup, and internal auto-response persistence.
- Replace `hatsume/plugins/hatsume-plugin/timer/executor.py`: native job construction, cancellation, execution, recovery, auto-response, and 03:00 cleanup registration.
- Modify `hatsume/plugins/hatsume-plugin/timer/__init__.py`: initialize only v2 storage, then recover and register lifecycle jobs without legacy access.
- Modify `hatsume/plugins/hatsume-plugin/graph/tools.py`: four creation tools, shared validation flow, detailed listing, delete, and registry changes.
- Modify `hatsume/plugins/hatsume-plugin/handlers/tools.py`: detailed shared `/timer list`, exact-time `/timer update`, and v2 job registration.
- Modify `hatsume/plugins/hatsume-plugin/config.py`: remove obsolete 30-day and rolling-window limits; define timer-v2 limits in one place.
- Create `tests/test_timer_schedule.py`: pure scheduling and classification coverage.
- Replace `tests/test_timer_store.py`: v2 persistence and progress coverage.
- Create `tests/test_timer_migration.py`: source-preserving migration coverage.
- Create `tests/test_timer_migration_cli.py`: standalone command behavior and isolation coverage.
- Create `tests/test_timer_executor.py`: native trigger, recovery, and cleanup coverage.
- Modify `tests/test_auto_response.py`, `tests/test_tools.py`, `tests/test_graph_nodes.py`, `tests/test_timer_injection.py`, and `tests/test_membersearch.py`: new store/tool interfaces and removed tools.
- Modify `docs/arch.md`: v2 data model, tools, lifecycle, migration, cleanup, and module index.

### Task 1: Pure Schedule Plans and Limits

**Files:**
- Create: `tests/test_timer_schedule.py`
- Create: `hatsume/plugins/hatsume-plugin/timer/schedule.py`
- Modify: `hatsume/plugins/hatsume-plugin/config.py`

- [x] **Step 1: Write failing parsing and daily schedule tests**

Create tests that load `timer/schedule.py` through the existing importlib package pattern and assert the public contract:

```python
def test_daily_step_and_inclusive_bounds():
    plan = build_daily_plan(
        "2026-07-25T10:00:00+08:00",
        "2026-07-29T18:00:00+08:00",
        ["09:00:00", "18:00:00"],
        step=2,
        now=datetime(2026, 7, 25, 9, 0, tzinfo=SHANGHAI).timestamp(),
    )
    assert flatten_occurrences(plan) == [
        ts("2026-07-25T18:00:00+08:00"),
        ts("2026-07-27T09:00:00+08:00"),
        ts("2026-07-27T18:00:00+08:00"),
        ts("2026-07-29T09:00:00+08:00"),
        ts("2026-07-29T18:00:00+08:00"),
    ]


@pytest.mark.parametrize("clock", ["9:00:00", "09:00", "09:00:00.000", "24:00:00"])
def test_clock_requires_exact_hh_mm_ss(clock):
    with pytest.raises(ScheduleValidationError):
        build_daily_plan(
            "2026-07-25T00:00:00+08:00",
            "2026-07-26T23:59:59+08:00",
            [clock],
            step=1,
            now=0,
        )


def test_frequency_raw_list_rejects_more_than_five_points():
    with pytest.raises(ScheduleValidationError, match="最多 5"):
        build_daily_plan(START, END, [f"0{i}:00:00" for i in range(6)], 1, now=0)
```

- [x] **Step 2: Run the daily schedule tests and verify the expected import failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_schedule.py -q
```

Expected: FAIL because `timer.schedule` and its public builders do not exist.

- [x] **Step 3: Implement schedule value objects, strict parsers, and daily generation**

Add these public types and functions:

```python
SHANGHAI = timezone(timedelta(hours=8))


class ScheduleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SchedulePointPlan:
    period_value: int | None
    clock_time: str | None
    exact_at: float | None
    first_fire_at: float
    last_fire_at: float
    planned_count: int


@dataclass(frozen=True)
class SchedulePlan:
    mode: Literal["daily", "weekly", "monthly", "at"]
    start_at: float | None
    end_at: float | None
    step: int | None
    effective_until: float
    total_occurrences: int
    truncated: bool
    points: tuple[SchedulePointPlan, ...]


def parse_clock(value: str) -> time:
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", value) is None:
        raise ScheduleValidationError("错误：时间点必须严格使用 HH:MM:SS 格式。")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleValidationError(f"错误：无效时间点 {value}。") from exc


def parse_boundary(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleValidationError(f"错误：无法解析时间 {value}。") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScheduleValidationError("错误：起止时间必须包含时区偏移。")
    return parsed.astimezone(SHANGHAI)
```

Define `TIMER_MAX_FREQUENCY_POINTS = 5` and `TIMER_MAX_EXACT_POINTS = 10` in
`config.py`; import them into the schedule module so configuration ownership
remains centralized. Frequency schedules are bounded by `end_at`, not by a
task-wide occurrence count.

Implement `build_daily_plan()`, `flatten_occurrences()`, and private allocation helpers. Generate each point from the start calendar date in `step`-day increments, filter with inclusive boundaries and `now`, then record per-point first/last/count values without materializing all occurrences during normal creation.

- [x] **Step 4: Run the daily schedule tests and verify they pass**

Run the same focused command. Expected: PASS with no warnings.

- [x] **Step 5: Write failing weekly, monthly, exact, and unbounded-frequency tests**

Add tests for anchored interval periods and raw collection limits:

```python
def test_weekly_step_is_anchored_to_start_week():
    plan = build_weekly_plan(
        "2026-07-29T00:00:00+08:00",  # Wednesday
        "2026-08-25T23:59:59+08:00",
        [{"weekday": 1, "time": "09:00:00"}, {"weekday": 5, "time": "18:00:00"}],
        step=2,
        now=0,
    )
    assert flatten_occurrences(plan) == [
        ts("2026-07-31T18:00:00+08:00"),
        ts("2026-08-10T09:00:00+08:00"),
        ts("2026-08-14T18:00:00+08:00"),
        ts("2026-08-24T09:00:00+08:00"),
    ]


def test_monthly_skips_nonexistent_day():
    plan = build_monthly_plan(
        "2026-01-01T00:00:00+08:00",
        "2026-04-30T23:59:59+08:00",
        [{"day": 31, "time": "08:00:00"}],
        step=1,
        now=0,
    )
    assert flatten_occurrences(plan) == [
        ts("2026-01-31T08:00:00+08:00"),
        ts("2026-03-31T08:00:00+08:00"),
    ]


def test_exact_rejects_raw_list_longer_than_ten_and_duplicates():
    with pytest.raises(ScheduleValidationError, match="最多 10"):
        build_at_plan([iso_day(index) for index in range(11)], now=0)
    with pytest.raises(ScheduleValidationError, match="重复"):
        build_at_plan([AT_ONE, AT_ONE], now=0)


def test_frequency_counts_every_occurrence_through_end_at():
    plan = build_daily_plan(START, FAR_END, ["09:00:00", "18:00:00"], 1, now=0)
    assert plan.total_occurrences > 50
    assert plan.truncated is False
    assert not hasattr(plan, "occurrences")
```

- [x] **Step 6: Run the new cases and verify they fail for missing builders**

Run the focused schedule test command. Expected: daily tests pass; weekly/monthly/exact cases fail because those builders are absent.

- [x] **Step 7: Implement weekly, monthly, exact, and indexed occurrence APIs**

Implement `build_weekly_plan(start_at: str, end_at: str,
time_points: list[Mapping[str, object]], step: int, *, now: float | None = None)
-> SchedulePlan`, `build_monthly_plan()` with the same boundary/point/step shape,
`build_at_plan(trigger_times: list[str], *, now: float | None = None) ->
SchedulePlan`, and `occurrence_at_index(task: Mapping[str, object], point:
Mapping[str, object], index: int) -> float`.

Validate the raw list before normalization, reject duplicate complete points,
anchor weekly periods to Monday of the start week, anchor monthly periods to the
start month, and stop allocation after the earliest 50 merged occurrences.

- [x] **Step 8: Run schedule tests and static checks**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_schedule.py -q
.venv/bin/ruff check hatsume/plugins/hatsume-plugin/timer/schedule.py tests/test_timer_schedule.py
npx --no-install pyright
```

Expected: all schedule tests pass; Ruff and Pyright report no errors.

- [x] **Step 9: Inspect status and diff without committing**

Run:

```bash
git status --short
git diff --check
```

Confirm only planned timer/config/test files plus the user's pre-existing changes are present.

### Task 2: V2 Store and Progress Accounting

**Files:**
- Replace: `tests/test_timer_store.py`
- Replace: `hatsume/plugins/hatsume-plugin/timer/store.py`

- [x] **Step 1: Write failing schema and default-path tests**

Assert the default suffix and complete tables:

```python
def test_default_path_uses_timer_v2_directory():
    assert Path(_get_default_db_path()).parts[-3:] == ("data", "timer-v2-db", "timer.db")


def test_v2_schema(store):
    tables = table_names(store)
    assert {"timer_tasks", "timer_schedule_points", "timer_migrations"} <= tables
    assert columns(store, "timer_tasks") >= {
        "schedule_type", "start_at", "end_at", "step", "effective_until",
        "total_occurrences", "processed_occurrences", "legacy_task_id",
    }
    assert columns(store, "timer_schedule_points") >= {
        "period_value", "clock_time", "exact_at", "first_fire_at",
        "last_fire_at", "planned_occurrences", "processed_occurrences",
        "last_processed_at", "job_id",
    }
```

- [x] **Step 2: Run store tests and verify they fail against the v1 schema**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_store.py -q
```

Expected: FAIL because the v2 tables and columns do not exist.

- [x] **Step 3: Implement the v2 schema and plan insertion**

Replace timestamp-list CRUD with `TimerStore.__init__(db_path: str | None =
None)`, `init_db()`, `create_task(group_id, user_id, prompt, plan, *, task_type=
"normal", task_id=None, legacy_task_id=None) -> int`, `get_task(task_id)`,
`list_tasks_by_group(group_id)`, `get_points_for_task(task_id)`,
`get_point(point_id)`, `list_incomplete_points()`, `transaction()`, and
`delete_task(task_id)`. The transaction context owns `BEGIN IMMEDIATE`, commit,
and rollback; insertion and migration-marker helpers accept an internal
`commit=False` option when called inside that context.

Use `timer_tasks` and `timer_schedule_points` columns from the design. Insert the
task and every point in one transaction, assign `timer_v2_point_<id>` job IDs,
and preserve cascading deletion.

- [x] **Step 4: Write failing CRUD, idempotent progress, replacement, and cleanup tests**

```python
def test_mark_occurrence_processed_is_idempotent(store, daily_plan):
    task_id = store.create_task(1, 2, "prompt", daily_plan)
    point = store.get_points_for_task(task_id)[0]
    scheduled_at = point["first_fire_at"]
    assert store.mark_occurrence_processed(point["id"], scheduled_at) is True
    assert store.mark_occurrence_processed(point["id"], scheduled_at) is False
    assert store.get_task(task_id)["processed_occurrences"] == 1


def test_replace_with_exact_plan_replaces_points_atomically(store, daily_plan, at_plan):
    task_id = store.create_task(1, 2, "old", daily_plan)
    store.replace_task_with_exact_plan(task_id, "new", at_plan)
    assert store.get_task(task_id)["schedule_type"] == "at"
    assert [p["exact_at"] for p in store.get_points_for_task(task_id)] == flatten_occurrences(at_plan)


def test_delete_finished_tasks_excludes_auto_response(store, at_plan):
    normal_id = store.create_task(1, 2, "normal", at_plan)
    internal_id = store.create_task(0, 0, "internal", at_plan, task_type="auto_response")
    finish_all(store, normal_id)
    finish_all(store, internal_id)
    assert store.delete_finished_tasks() == [normal_id]
    assert store.get_task(internal_id) is not None
```

- [x] **Step 5: Run the new store tests and verify the missing-method failures**

Run the store test command. Expected: schema tests pass and progress/replacement/cleanup tests fail for absent methods.

- [x] **Step 6: Implement progress, exact replacement, cleanup, and auto-response APIs**

Add `mark_occurrence_processed(point_id, scheduled_at) -> bool`,
`replace_task_with_exact_plan(task_id, prompt, plan)`,
`list_finished_task_ids() -> list[int]`, `delete_finished_tasks() -> list[int]`,
`upsert_auto_response(trigger_at, prompt=None) -> int`,
`get_auto_response_point()`, `delete_auto_response_tasks()`,
`has_migration(name) -> bool`, and `record_migration(name)`.

`mark_occurrence_processed` must update point and task counters in one immediate
transaction only when `scheduled_at` is later than `last_processed_at` and the
planned count has not been exhausted. Exact replacement updates the existing
task ID and replaces point rows in one transaction.

- [x] **Step 7: Run store tests, Ruff, and Pyright**

Run focused store tests, then Ruff on `timer/store.py` and its tests, then Pyright.
Expected: clean results.

### Task 3: Read-Only Legacy Migration

**Files:**
- Modify: `tests/test_timer_schedule.py`
- Create: `tests/test_timer_migration.py`
- Modify: `hatsume/plugins/hatsume-plugin/timer/schedule.py`
- Create: `hatsume/plugins/hatsume-plugin/timer/migration.py`

- [x] **Step 1: Write failing legacy-classification tests**

Use explicit China Standard Time fixtures:

```python
@pytest.mark.parametrize(
    ("prompt", "times", "mode", "step"),
    [
        ("每天提醒喝水", daily_times(step=2), "daily", 2),
        ("每两周周一检查", weekly_times(step=2), "weekly", 2),
        ("每月十五号提醒", monthly_times(step=1), "monthly", 1),
        ("三个不规则日期提醒", irregular_times(), "at", None),
    ],
)
def test_classifies_legacy_prompt_and_cadence(prompt, times, mode, step):
    plan = infer_legacy_plan(prompt, times)
    assert plan.mode == mode
    assert plan.step == step
```

Also test an ambiguous seven-day cadence with a weekly prompt, six daily clock
points trimmed to five, recurrence capped at 50, and irregular fallback capped at
ten.

- [x] **Step 2: Run classification tests and verify the missing function failure**

Run `tests/test_timer_schedule.py`. Expected: FAIL because `infer_legacy_plan` is missing.

- [x] **Step 3: Implement deterministic classification**

Add:

```python
def infer_legacy_plan(prompt: str, trigger_times: Sequence[float]) -> SchedulePlan:
    """Infer a bounded v2 plan from sorted, pending legacy instants."""
```

Build daily, weekly, and monthly candidates, regenerate each candidate inside its
first/last bounds, and compare to the source instants. Use Chinese and English
daily/weekly/monthly prompt hints to resolve overlaps. Without a hint, prefer a
multi-month day-of-month pattern, then a whole-week weekday pattern, then a
constant-day pattern. Trim recurring period points to the earliest five before
the 50-occurrence allocation; otherwise return an exact plan with the earliest
ten instants.

- [x] **Step 4: Write failing migration transaction tests**

Create a real temporary v1 SQLite database and assert:

```python
def test_migrates_only_unfinished_normal_tasks_read_only(tmp_path):
    legacy = create_legacy_db(tmp_path, normal_pending=True, normal_finished=True,
                              auto_response=True, auto_create=True)
    before = legacy.read_bytes()
    store = make_v2_store(tmp_path)
    result = migrate_legacy_timer_db(store, legacy)
    assert result.migrated_tasks == 1
    assert store.get_task(LEGACY_PENDING_ID)["legacy_task_id"] == LEGACY_PENDING_ID
    assert legacy.read_bytes() == before


def test_migration_is_idempotent(tmp_path):
    legacy = create_legacy_db(tmp_path, normal_pending=True)
    store = make_v2_store(tmp_path)
    migrate_legacy_timer_db(store, legacy)
    migrate_legacy_timer_db(store, legacy)
    assert count_normal_tasks(store) == 1


def test_failed_migration_rolls_back_and_retries(tmp_path, monkeypatch):
    legacy = create_legacy_db(tmp_path, normal_pending=True)
    store = make_v2_store(tmp_path)
    monkeypatch.setattr(store, "create_task", raising_create_task)
    with pytest.raises(RuntimeError):
        migrate_legacy_timer_db(store, legacy)
    assert not store.has_migration(LEGACY_MIGRATION_NAME)
```

- [x] **Step 5: Run migration tests and verify they fail for the missing module**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_migration.py -q
```

Expected: FAIL because `timer.migration` does not exist.

- [x] **Step 6: Implement migration with a read-only private snapshot and one destination transaction**

Add `LEGACY_MIGRATION_NAME = "legacy_timer_v1"`, an immutable
`MigrationResult(migrated_tasks: int, skipped_tasks: int, already_applied: bool)`
dataclass, and `migrate_legacy_timer_db(store: TimerStore, legacy_path: str |
Path) -> MigrationResult`.

Copy the source database and any WAL into a private temporary directory, then
connect to that snapshot with
`sqlite3.connect(f"{snapshot.resolve().as_uri()}?mode=ro", uri=True)`. Set the
legacy row factory, select only `task_type='normal'` tasks having `fired=0`
triggers, infer each plan, preserve an available legacy task ID, and use `with
store.transaction():` to insert all tasks and the migration marker through their
internal `commit=False` path. SQLite must never open, create, checkpoint, or alter
the source database, WAL, or SHM files.

- [x] **Step 7: Run schedule and migration tests plus static checks**

Run both focused files, Ruff on the two modules/tests, and Pyright. Expected: all pass.

### Task 4: Native APScheduler Jobs, Recovery, and Cleanup

**Files:**
- Create: `tests/test_timer_executor.py`
- Replace: `hatsume/plugins/hatsume-plugin/timer/executor.py`
- Modify: `tests/test_auto_response.py`

- [x] **Step 1: Write failing native-trigger registration tests**

Stub the scheduler and inspect triggers:

```python
@pytest.mark.parametrize(
    ("mode", "trigger_type"),
    [
        ("daily", IntervalTrigger),
        ("weekly", IntervalTrigger),
        ("monthly", CalendarIntervalTrigger),
        ("at", DateTrigger),
    ],
)
def test_register_point_uses_native_trigger(mode, trigger_type, executor, store, plans):
    task_id = store.create_task(1, 2, "prompt", plans[mode])
    point = store.get_points_for_task(task_id)[0]
    executor.register_point(point, store)
    call = executor.scheduler.add_job.call_args
    assert isinstance(call.args[1], trigger_type)
    assert call.kwargs["id"] == point["job_id"]
    assert call.kwargs["replace_existing"] is True
```

Test interval `days` versus `weeks`, calendar `months`, exact start/end bounds,
and cancellation of every point job.

- [x] **Step 2: Run executor tests and verify registration failures**

Run `tests/test_timer_executor.py`. Expected: FAIL against the date-trigger-only executor.

- [x] **Step 3: Implement trigger factories, registration, and cancellation**

Implement `build_trigger(task: dict, point: dict, *, start_at: float | None =
None)`, `register_point(point: dict, store: TimerStore) -> str`,
`add_jobs_for_task(task_id: int, store: TimerStore)`,
`cancel_point_job(point_id: int)`, and `cancel_task_jobs(task_id: int, store:
TimerStore)`.

Use the point's next unprocessed occurrence as a recovery start, its retained last
occurrence as the end, China Standard Time on every trigger, stable job IDs,
`misfire_grace_time=300`, `coalesce=False`, and `replace_existing=True`.

- [x] **Step 4: Write failing execution and recovery tests**

```python
async def test_execute_point_injects_then_marks_scheduled_occurrence(executor, store):
    point_id, scheduled_at = create_due_point(store)
    await executor._execute_point(point_id, store, scheduled_at=scheduled_at)
    executor._inject_timer_to_graph.assert_awaited_once()
    assert store.get_point(point_id)["processed_occurrences"] == 1


async def test_recovery_compensates_recent_and_expires_old(executor, store):
    old_id, recent_id, future_id = create_recovery_points(store)
    await executor.reload_all_schedules(store, now=NOW)
    assert store.get_point(old_id)["processed_occurrences"] == 1
    executor._execute_point.assert_called_once_with(recent_id, store, scheduled_at=RECENT)
    assert executor.register_point.call_args.args[0]["id"] == future_id


def test_cleanup_job_runs_daily_at_three(executor, store):
    executor.register_cleanup_job(store)
    trigger = executor.scheduler.add_job.call_args.args[1]
    assert "hour='3'" in str(trigger)
    assert executor.scheduler.add_job.call_args.kwargs["id"] == "timer_v2_cleanup"
```

Also assert repeated recovery does not compensate the same occurrence twice and
cleanup excludes active and auto-response tasks.

- [x] **Step 5: Run the recovery tests and verify missing APIs fail**

Run the executor test file. Expected: native registration passes; recovery and cleanup tests fail for missing behavior.

- [x] **Step 6: Implement execution, recovery, and daily cleanup**

Add `_execute_point(point_id: int, store: TimerStore, *, scheduled_at: float |
None = None)`, `reload_all_schedules(store: TimerStore, *, now: float | None =
None)`, `cleanup_finished_tasks(store: TimerStore)`, and
`register_cleanup_job(store: TimerStore)`.

Derive expected occurrences with `occurrence_at_index`. During recovery, advance
all expired occurrences, schedule at most the most recent occurrence inside the
tolerance, and register future native work. Normal execution injects through the
existing graph path and marks progress after the attempt. Auto-response marks its
exact point before injection and immediately creates/registers its successor.

- [x] **Step 7: Port auto-response tests to v2 points**

Update `tests/test_auto_response.py` to use `get_auto_response_point`,
`delete_auto_response_tasks`, and `_execute_point`. Retain assertions that an
unconfigured group never injects or reschedules and that startup owns exactly one
future internal task.

- [x] **Step 8: Run executor, auto-response, injection, Ruff, and Pyright checks**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_executor.py tests/test_auto_response.py tests/test_timer_injection.py -q
.venv/bin/ruff check hatsume/plugins/hatsume-plugin/timer tests/test_timer_executor.py tests/test_auto_response.py
npx --no-install pyright
```

Expected: all pass without warnings or collection errors.

### Task 5: Four Creation Tools and Detailed Listing

**Files:**
- Modify: `tests/test_tools.py`
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

- [x] **Step 1: Replace old creation tests with failing four-mode tool tests**

Use a mocked schedule module/store/executor and assert each tool delegates to the
matching builder:

```python
async def test_daily_tool_documents_and_checks_five_hh_mm_ss_points(tools):
    result = await tools.create_daily_timer(
        456, "提醒", START, END,
        ["08:00:00", "10:00:00", "12:00:00", "16:00:00", "20:00:00", "22:00:00"],
        1,
    )
    assert "最多 5" in result
    assert "HH:MM:SS" in tools.create_daily_timer.__doc__
    TIMER_STORE.create_task.assert_not_called()


async def test_at_tool_rejects_raw_list_longer_than_ten(tools):
    result = await tools.create_at_timer(456, "提醒", eleven_iso_timestamps())
    assert "最多 10" in result


@pytest.mark.parametrize(
    "name",
    ["create_daily_timer", "create_weekly_timer", "create_monthly_timer", "create_at_timer"],
)
def test_chat_tools_registers_each_creation_tool_once(tools, name):
    tool = getattr(tools, name)
    assert tools.CHAT_TOOLS.count(tool) == 1


def test_removed_timer_tools_are_absent(tools):
    assert not hasattr(tools, "create_timer")
    assert not hasattr(tools, "get_timer")
```

- [x] **Step 2: Run focused tool tests and verify old surface failures**

Run:

```bash
.venv/bin/python -m pytest tests/test_tools.py -q
```

Expected: FAIL because the four functions are missing and old functions remain.

- [x] **Step 3: Implement a shared creation helper and four decorated tools**

Replace `_exceeds_timer_trigger_frequency` and `create_timer` with a shared
creation helper:

```python
async def _create_scheduled_timer(user_id: int, prompt: str, plan: SchedulePlan) -> str:
    if _current_group_id is None:
        return "错误：无法确定当前群聊 ID。"
    store = get_store()
    if prompt_error := store.validate_prompt(prompt):
        return prompt_error
    task_id = store.create_task(_current_group_id, user_id, prompt, plan)
    add_jobs_for_task(task_id, store)
    return format_creation_confirmation(task_id, prompt, plan)
```

Define `create_daily_timer(user_id, prompt, start_at, end_at, time_points,
step=1)`, `create_weekly_timer()` and `create_monthly_timer()` with their typed
complete point lists, and `create_at_timer(user_id, prompt, trigger_times)` as
decorated async tools that build a plan and pass it to the helper.

Each decorated function must contain the complete Chinese parameter contract,
strict limits, and at least one exact invocation example. Catch only
`ScheduleValidationError` and return its message without writing or registering.

- [x] **Step 4: Write failing detailed listing tests**

```python
async def test_list_timers_shows_complete_weekly_frequency(tools):
    result = await tools.list_timers()
    assert "类型：每 2 周" in result
    assert "范围：2026-07-25 00:00:00 至 2026-12-31 23:59:59" in result
    assert "时间点：周一 09:00:00、周五 18:00:00" in result
    assert "计划触发：20 次；已处理：3 次" in result
    assert "下一次触发：2026-08-03 09:00:00" in result


async def test_list_timers_shows_every_exact_timestamp_and_status(tools):
    result = await tools.list_timers()
    assert "2026-08-01 09:00:00：已完成" in result
    assert "2026-08-02 18:00:00：未完成" in result
```

- [x] **Step 5: Run listing tests and verify they fail against trigger-row formatting**

Run only the `TestTimerListing` class. Expected: FAIL because v1 output lacks frequency metadata and exact point details.

- [x] **Step 6: Implement v2 overview formatting and remove `get_timer`**

Have `get_timer_overview()` load each task's points, calculate its next occurrence
from stored progress, and render daily/weekly/monthly rules or all exact points.
Keep the unfinished/finished grouping and full prompt. Delete the decorated
`get_timer` function and register exactly:

```python
CHAT_TOOLS = [
    # existing non-timer tools in their existing order,
    create_daily_timer,
    create_weekly_timer,
    create_monthly_timer,
    create_at_timer,
    list_timers,
    delete_timer,
    # remaining existing tools,
]
```

- [x] **Step 7: Run tool tests, Ruff, and Pyright**

Run the complete `tests/test_tools.py`, Ruff on `graph/tools.py` and the test, and Pyright. Expected: clean results.

### Task 6: Startup, Commands, and Integration Stubs

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/__init__.py`
- Create or modify: `tests/test_timer_startup.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/tools.py`
- Modify: `tests/test_graph_nodes.py`
- Modify: `tests/test_timer_injection.py`
- Modify: `tests/test_membersearch.py`
- Modify: `tests/test_auto_response.py`
- Create or modify: `tests/test_handlers_tools.py` when needed for command coverage

- [x] **Step 1: Write failing startup isolation and ordering tests**

Load `timer/__init__.py` with only a stub store module. Do not install a migration
module in `sys.modules`; the test must fail if startup imports one. Assert
`get_store()` constructs and initializes exactly one v2 store, and
`init_scheduler()` orders recovery before internal refresh while registering
cleanup:

```python
def test_get_store_initializes_only_v2_storage():
    calls = []

    class Store:
        _db_path = "v2.db"

        def __init__(self):
            calls.append("construct")

        def init_db(self):
            calls.append("init")

    timer = load_timer_init(Store)
    assert timer.get_store() is timer.get_store()
    assert calls == ["construct", "init"]


async def test_init_scheduler_orders_v2_lifecycle(monkeypatch):
    calls = []
    monkeypatch.setattr(timer, "get_store", lambda: STORE)
    monkeypatch.setattr(executor, "reload_all_schedules", record_async(calls, "recover"))
    monkeypatch.setattr(executor, "refresh_auto_response", record_async(calls, "auto"))
    monkeypatch.setattr(executor, "register_cleanup_job", record(calls, "cleanup"))
    await timer.init_scheduler()
    assert calls == ["recover", "auto", "cleanup"]
```

- [x] **Step 2: Run the startup test and verify migration coupling fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_startup.py -q
```

Expected: FAIL because `get_store()` imports `timer.migration` and calls
`migrate_legacy_timer_db()`.

- [x] **Step 3: Remove migration from Bot startup and retain v2 recovery**

Remove the `Path` import, legacy path construction, lazy migration import,
migration call, and migration-result logging from `timer/__init__.py`.
`get_store()` must initialize the candidate, close it on initialization failure,
and cache it only after success:

```python
candidate = TimerStore()
try:
    candidate.init_db()
except BaseException:
    print(f"⏰ [timer] TimerStore initialization failed (db: {candidate._db_path})")
    candidate.close()
    raise
_store = candidate
```

Keep `init_scheduler()` calling only the v2 lifecycle in order:

```python
await reload_all_schedules(store)
await refresh_auto_response(store)
register_cleanup_job(store)
```

- [x] **Step 4: Write failing `/timer` command compatibility tests**

Cover current-group list reuse, administrator-only explicit-group listing,
invalid group IDs, exact replacement, and deletion:

```python
async def test_timer_list_reuses_shared_overview(handler_fixture):
    await handle_timer(BOT, EVENT, MATCHER, message("list"))
    MATCHER.finish.assert_awaited_once_with("shared detailed overview")


async def test_admin_timer_list_passes_explicit_group(handler_fixture):
    await handle_timer(BOT, ADMIN_EVENT, MATCHER, message("list 456"))
    GET_TIMER_OVERVIEW.assert_awaited_once_with(456)


async def test_non_admin_cannot_list_another_group(handler_fixture):
    await handle_timer(BOT, MEMBER_EVENT, MATCHER, message("list 456"))
    GET_TIMER_OVERVIEW.assert_not_awaited()


async def test_timer_update_replaces_with_validated_exact_plan(handler_fixture):
    await handle_timer(BOT, EVENT, MATCHER, message(f"update 7 new prompt @ {AT_ONE}, {AT_TWO}"))
    EXECUTOR.cancel_task_jobs.assert_called_once_with(7, STORE)
    STORE.replace_task_with_exact_plan.assert_called_once()
    EXECUTOR.add_jobs_for_task.assert_called_once_with(7, STORE)
```

Also reject more than ten timestamps before cancellation and preserve cross-group
ownership checks.

- [x] **Step 5: Run command tests and verify they fail against v1 formatting/update**

Run the relevant handler test file. Expected: FAIL because list is duplicated and update calls v1 `update_task`.

- [x] **Step 6: Port `/timer` to shared v2 APIs**

Make `list` call `get_timer_overview()`. Make `update` parse the existing `prompt @
timestamps` syntax, call `build_at_plan`, validate before cancellation, cancel old
jobs, replace the task schedule transactionally, and register new date jobs.
Retain `delete` ownership checks and v2 cancellation. Add
`get_timer_overview(group_id: int | None = None)` so explicit inspection queries
the requested group without mutating `_current_group_id`; keep no-argument tool
and system-prompt calls unchanged.

- [x] **Step 7: Update graph and isolated-import stubs**

Replace every `create_timer`/`get_timer` stub with the four creation names, update
`CHAT_TOOLS` lengths/order, and replace v1 store method stubs with
`get_points_for_task`, v2 creation/replacement, and progress APIs. Do not weaken
assertions unrelated to timers.

- [x] **Step 8: Run all timer-adjacent integration tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_timer_schedule.py \
  tests/test_timer_store.py \
  tests/test_timer_migration.py \
  tests/test_timer_executor.py \
  tests/test_auto_response.py \
  tests/test_timer_injection.py \
  tests/test_tools.py \
  tests/test_graph_nodes.py \
  tests/test_membersearch.py -q
```

Expected: all selected tests pass without collection errors or warnings.

### Task 7: Standalone Manual Migration Command

**Files:**
- Create: `scripts/migrate_timer_v2.py`
- Create: `tests/test_timer_migration_cli.py`

- [x] **Step 1: Write failing CLI contract tests**

Load the script with `importlib.util.spec_from_file_location()` and cover default
paths, explicit paths, missing-source behavior, close-on-success,
close-on-migration-failure, redacted error output, and already-applied JSON:

```python
def test_defaults_point_to_runtime_legacy_and_v2_databases(cli):
    args = cli._parse_args([])
    assert args.source == ROOT / "data/hatsume-plugin/timer_db/timer.db"
    assert args.destination == ROOT / "data/timer-v2-db/timer.db"


def test_missing_source_fails_without_creating_destination(cli, tmp_path):
    destination = tmp_path / "v2/timer.db"
    code = cli.main([
        "--source", str(tmp_path / "missing.db"),
        "--destination", str(destination),
    ])
    assert code == 2
    assert not destination.exists()


def test_migration_failure_closes_destination_and_redacts_prompt(
    cli, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "legacy.db"
    source.touch()
    store = RecordingStore()
    monkeypatch.setattr(cli, "_load_components", lambda: (lambda _: store, failing_migrate))
    code = cli.main(["--source", str(source), "--destination", str(tmp_path / "v2.db")])
    assert code == 1
    assert store.closed is True
    assert "private task prompt" not in capsys.readouterr().err
```

Add one integration test using a minimal real legacy SQLite fixture. Run
`main()` twice with explicit temporary paths, parse the single JSON object from
each successful call, assert first-run migration and second-run
`already_applied=true`, and compare source DB/WAL/SHM bytes before and after.

- [x] **Step 2: Run CLI tests and verify the script is missing**

Run:

```bash
.venv/bin/python -m pytest tests/test_timer_migration_cli.py -q
```

Expected: FAIL because `scripts/migrate_timer_v2.py` does not exist.

- [x] **Step 3: Implement the isolated command loader and CLI**

The script must not import the NoneBot plugin package. Create isolated package
aliases for `config.py` and `timer/`, then load `schedule.py`, `store.py`, and
`migration.py` through `importlib.util` so relative imports resolve without
executing `hatsume-plugin/__init__.py`:

```python
ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
TIMER_DIR = PLUGIN_DIR / "timer"
DEFAULT_SOURCE = ROOT / "data/hatsume-plugin/timer_db/timer.db"
DEFAULT_DESTINATION = ROOT / "data/timer-v2-db/timer.db"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate unfinished Timer v1 tasks to Timer v2.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    return parser.parse_args(argv)
```

Implement `_load_components() -> tuple[type, Callable]`, using a private module
prefix and returning `TimerStore` plus `migrate_legacy_timer_db`. Implement the
command flow as:

```python
def _run_migration(source: Path, destination: Path):
    store_type, migrate = _load_components()
    store = store_type(str(destination))
    try:
        store.init_db()
        return migrate(store, source)
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.source.is_file():
        print(f"Timer migration source not found: {args.source}", file=sys.stderr)
        return 2
    try:
        result = _run_migration(args.source, args.destination)
    except Exception as exc:
        print(
            f"Timer migration failed ({type(exc).__name__}; "
            f"source: {args.source}; destination: {args.destination})",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({
        "already_applied": result.already_applied,
        "migrated_tasks": result.migrated_tasks,
        "skipped_tasks": result.skipped_tasks,
    }, sort_keys=True))
    return 0
```

End with `raise SystemExit(main())` under the normal `__main__` guard.

- [x] **Step 4: Run CLI, migration, startup, Ruff, and Pyright checks**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_timer_startup.py \
  tests/test_timer_migration.py \
  tests/test_timer_migration_cli.py -q
.venv/bin/ruff check scripts/migrate_timer_v2.py tests/test_timer_migration_cli.py
npx --no-install pyright
```

Expected: all commands exit zero with no resource warnings.

### Task 8: Architecture Documentation, Manual Migration, and Full Verification

**Files:**
- Modify: `docs/arch.md`
- Verify: `docs/superpowers/specs/2026-07-25-timer-v2-scheduling-design.md`
- Modify: `docs/superpowers/plans/2026-07-25-timer-v2-native-scheduling.md`
- Verify: all files changed in Tasks 1-7

- [x] **Step 1: Update the architecture feature map and timer chapter**

Document:

```text
- four creation tools and exact list-size/runtime checks;
- daily/weekly interval jobs, monthly calendar-interval jobs, and exact date jobs;
- timer_tasks + timer_schedule_points + timer_migrations ownership;
- data/timer-v2-db/timer.db and read-only legacy source;
- unfinished-only classification and migration caps;
- standalone `scripts/migrate_timer_v2.py` ownership and one-shot workflow;
- startup isolation from legacy paths and migration imports;
- v2 recovery and internal auto-response ordering;
- daily 03:00 cleanup;
- detailed list_timers output and removal of get_timer;
- /timer exact update compatibility;
- timer/schedule.py and timer/migration.py module-index entries.
```

Remove statements describing the 30-day limit, rolling 24-hour limit, expanded
trigger rows, `get_timer`, and v1 as the active database.

- [x] **Step 2: Search for stale runtime names and limits**

Run:

```bash
rg -n "create_timer|get_timer|TIMER_MAX_FUTURE_DAYS|TIMER_MAX_TRIGGERS_PER_24_HOURS|get_triggers_for_task|timer_triggers" \
  hatsume/plugins/hatsume-plugin tests docs/arch.md
rg -n "migrate_legacy_timer_db|hatsume-plugin/timer_db" \
  hatsume/plugins/hatsume-plugin/timer/__init__.py
```

Expected: no active v1 names and no migration or legacy-path references in Bot
startup. Migration references remain only in the standalone script, migration
module, tests, and current documentation.

- [x] **Step 3: Run focused timer verification fresh**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_timer_schedule.py \
  tests/test_timer_store.py \
  tests/test_timer_migration.py \
  tests/test_timer_migration_cli.py \
  tests/test_timer_executor.py \
  tests/test_auto_response.py \
  tests/test_timer_injection.py \
  tests/test_tools.py -q
```

Expected: zero failed tests, zero collection errors, and no resource warnings.

- [x] **Step 4: Run the repository-required full checks fresh**

Run exactly:

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Expected: each command exits zero; pytest reports no failures, collection errors,
or resource warnings.

- [x] **Step 5: Verify requirements line by line**

Confirm from code and tests:

```text
[ ] Four and only four user-facing creation tools exist.
[ ] Frequency start/end, positive step, and exact HH:MM:SS points work.
[ ] Frequency raw point lists are limited to five.
[ ] Exact raw timestamp lists are limited to ten.
[ ] Recurrence is native APScheduler and capped at the earliest 50 fires.
[ ] Cleanup is registered daily at 03:00 UTC+08:00.
[ ] V2 database path is data/timer-v2-db/timer.db.
[ ] Migration is read-only, idempotent, unfinished-only, and classified by prompt plus cadence.
[ ] Bot startup does not import migration code or inspect the legacy path.
[ ] The standalone script validates its source, supports explicit paths, emits JSON, closes the store, and reports failures with nonzero status.
[ ] list_timers shows complete rule/timestamp information.
[ ] /timer list accepts a positive target group for administrators without changing global group context.
[ ] get_timer is absent.
[ ] Existing auto-response, injection, deletion, and exact /timer update still work.
```

- [x] **Step 6: Manually migrate the runtime legacy database once**

First confirm no Bot process is writing the legacy timer database. Record SHA-256
and file sizes for every existing source DB/WAL/SHM file, run the standalone
command with its defaults, and record them again:

```bash
pgrep -af "nonebot|hatsume|nb run"
shasum -a 256 data/hatsume-plugin/timer_db/timer.db*
.venv/bin/python scripts/migrate_timer_v2.py
shasum -a 256 data/hatsume-plugin/timer_db/timer.db*
```

Expected: no active Bot writer; the command exits zero and prints exactly one JSON
object; every source hash is unchanged. Open the destination read-only and verify
the migration marker exists, no completed/internal legacy tasks were copied, and
the migrated count matches the JSON report. Do not add either database to the
main repository.

- [x] **Step 7: Re-run migration-focused tests after the manual operation**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_timer_startup.py \
  tests/test_timer_migration.py \
  tests/test_timer_migration_cli.py \
  tests/test_timer_executor.py -q
```

Expected: all selected tests pass with no warnings.

- [x] **Step 8: Inspect final worktree without altering unrelated changes**

Run:

```bash
git status --short
git diff --check
git diff --stat
git -C data/hatsume-plugin status --short
```

Do not stage, commit, push, or disturb the user's pre-existing changes. The only
authorized runtime mutation is the explicit destination database written by the
manual Timer migration; source runtime files must remain byte-identical. Report
unrelated dirty files separately from Timer V2 work.

## Execution Record

On 2026-07-25 the default manual command exited zero with
`{"already_applied": true, "migrated_tasks": 0, "skipped_tasks": 0}` because
the destination already contained the idempotency marker from an earlier
development startup. The destination contained eight normal tasks with eight
legacy IDs, matching the eight unfinished normal tasks in the source. Source
DB/WAL/SHM SHA-256 values were identical immediately before and after the manual
command. Runtime databases were not added to the main repository.
