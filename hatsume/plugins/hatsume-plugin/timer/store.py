"""SQLite persistence for timer-v2 tasks and native schedule points."""

from __future__ import annotations

import sqlite3
import time
import math
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .schedule import (
    SHANGHAI,
    SchedulePlan,
    _plan_from_epoch_times,
    build_daily_plan,
    build_monthly_plan,
    build_weekly_plan,
)

_DEFAULT_DB_PATH: str | None = None


def _get_default_db_path() -> str:
    """Return the repository-local timer-v2 database path."""
    global _DEFAULT_DB_PATH
    if _DEFAULT_DB_PATH is None:
        _DEFAULT_DB_PATH = str(
            Path(__file__).resolve().parents[4]
            / "data"
            / "timer-v2-db"
            / "timer.db"
        )
    return _DEFAULT_DB_PATH


class TimerStore:
    """Manage timer tasks, schedule points, progress, and migration markers."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _get_default_db_path()
        self._conn: sqlite3.Connection | None = None

    def init_db(self) -> None:
        """Open the v2 database and create its idempotent schema."""
        if self._conn is not None:
            return
        path = self._db_path
        if path == ":memory:":
            conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS timer_tasks (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id                INTEGER NOT NULL,
                user_id                 INTEGER NOT NULL,
                prompt                  TEXT NOT NULL,
                task_type               TEXT NOT NULL DEFAULT 'normal',
                schedule_type           TEXT NOT NULL,
                start_at                REAL,
                end_at                  REAL,
                step                    INTEGER,
                effective_until         REAL NOT NULL,
                total_occurrences       INTEGER NOT NULL,
                processed_occurrences   INTEGER NOT NULL DEFAULT 0,
                truncated               INTEGER NOT NULL DEFAULT 0,
                legacy_task_id          INTEGER UNIQUE,
                created_at              REAL NOT NULL,
                updated_at              REAL NOT NULL,
                CHECK (task_type IN ('normal', 'auto_response')),
                CHECK (schedule_type IN ('daily', 'weekly', 'monthly', 'at')),
                CHECK (total_occurrences > 0),
                CHECK (
                    processed_occurrences >= 0
                    AND processed_occurrences <= total_occurrences
                )
            );

            CREATE TABLE IF NOT EXISTS timer_schedule_points (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id                 INTEGER NOT NULL
                                            REFERENCES timer_tasks(id)
                                            ON DELETE CASCADE,
                period_value            INTEGER,
                clock_time              TEXT,
                exact_at                REAL,
                first_fire_at           REAL,
                last_fire_at            REAL,
                planned_occurrences     INTEGER NOT NULL,
                processed_occurrences   INTEGER NOT NULL DEFAULT 0,
                last_processed_at       REAL,
                job_id                  TEXT NOT NULL UNIQUE,
                CHECK (planned_occurrences >= 0),
                CHECK (
                    (
                        planned_occurrences = 0
                        AND first_fire_at IS NULL
                        AND last_fire_at IS NULL
                    ) OR (
                        planned_occurrences > 0
                        AND first_fire_at IS NOT NULL
                        AND last_fire_at IS NOT NULL
                    )
                ),
                CHECK (
                    processed_occurrences >= 0
                    AND processed_occurrences <= planned_occurrences
                )
            );

            CREATE TABLE IF NOT EXISTS timer_migrations (
                name            TEXT PRIMARY KEY,
                completed_at    REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_timer_tasks_group
                ON timer_tasks(group_id, created_at)
                WHERE task_type = 'normal';

            CREATE INDEX IF NOT EXISTS idx_timer_points_task
                ON timer_schedule_points(task_id, first_fire_at);

            CREATE INDEX IF NOT EXISTS idx_timer_points_progress
                ON timer_schedule_points(processed_occurrences, planned_occurrences);
            """
        )
        conn.commit()
        self._conn = conn
        print(f"[timer-v2] DB initialized at {path}")

    def close(self) -> None:
        """Close the store connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("TimerStore not initialized")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run multiple store writes as one immediate transaction."""
        conn = self._connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    def _insert_points(self, task_id: int, plan: SchedulePlan) -> None:
        conn = self._connection()
        for point in plan.points:
            cursor = conn.execute(
                "INSERT INTO timer_schedule_points "
                "(task_id, period_value, clock_time, exact_at, first_fire_at, "
                "last_fire_at, planned_occurrences, processed_occurrences, job_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, '')",
                (
                    task_id,
                    point.period_value,
                    point.clock_time,
                    point.exact_at,
                    point.first_fire_at,
                    point.last_fire_at,
                    point.planned_count,
                ),
            )
            point_id = cursor.lastrowid
            if point_id is None:
                raise RuntimeError("failed to create timer schedule point")
            conn.execute(
                "UPDATE timer_schedule_points SET job_id = ? WHERE id = ?",
                (f"timer_v2_point_{point_id}", point_id),
            )

    def create_task(
        self,
        group_id: int,
        user_id: int,
        prompt: str,
        plan: SchedulePlan,
        *,
        task_type: str = "normal",
        task_id: int | None = None,
        legacy_task_id: int | None = None,
        commit: bool = True,
    ) -> int:
        """Persist a validated schedule plan and return its task ID."""
        if commit:
            with self.transaction():
                return self.create_task(
                    group_id,
                    user_id,
                    prompt,
                    plan,
                    task_type=task_type,
                    task_id=task_id,
                    legacy_task_id=legacy_task_id,
                    commit=False,
                )

        conn = self._connection()
        now = time.time()
        values = (
            group_id,
            user_id,
            prompt,
            task_type,
            plan.mode,
            plan.start_at,
            plan.end_at,
            plan.step,
            plan.effective_until,
            plan.total_occurrences,
            int(plan.truncated),
            legacy_task_id,
            now,
            now,
        )
        if task_id is None:
            cursor = conn.execute(
                "INSERT INTO timer_tasks "
                "(group_id, user_id, prompt, task_type, schedule_type, start_at, "
                "end_at, step, effective_until, total_occurrences, truncated, "
                "legacy_task_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
        else:
            cursor = conn.execute(
                "INSERT INTO timer_tasks "
                "(id, group_id, user_id, prompt, task_type, schedule_type, start_at, "
                "end_at, step, effective_until, total_occurrences, truncated, "
                "legacy_task_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, *values),
            )
        inserted_id = cursor.lastrowid
        if inserted_id is None:
            raise RuntimeError("failed to create timer task")
        self._insert_points(int(inserted_id), plan)
        return int(inserted_id)

    def get_task(self, task_id: int) -> dict | None:
        row = self._connection().execute(
            "SELECT * FROM timer_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_tasks_by_group(self, group_id: int) -> list[dict]:
        rows = self._connection().execute(
            "SELECT * FROM timer_tasks "
            "WHERE group_id = ? AND task_type = 'normal' "
            "ORDER BY created_at, id",
            (group_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_point(self, point_id: int) -> dict | None:
        row = self._connection().execute(
            "SELECT * FROM timer_schedule_points WHERE id = ?", (point_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_points_for_task(self, task_id: int) -> list[dict]:
        rows = self._connection().execute(
            "SELECT * FROM timer_schedule_points "
            "WHERE task_id = ? ORDER BY first_fire_at, id",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_incomplete_points(self) -> list[dict]:
        rows = self._connection().execute(
            "SELECT p.*, t.schedule_type, t.step, t.task_type, t.group_id, "
            "t.user_id, t.prompt, t.total_occurrences AS task_total_occurrences, "
            "t.processed_occurrences AS task_processed_occurrences "
            "FROM timer_schedule_points AS p "
            "JOIN timer_tasks AS t ON t.id = p.task_id "
            "WHERE p.processed_occurrences < p.planned_occurrences "
            "ORDER BY p.first_fire_at, p.id"
        ).fetchall()
        return [dict(row) for row in rows]

    def replace_task_with_exact_plan(
        self, task_id: int, prompt: str, plan: SchedulePlan
    ) -> None:
        """Replace an existing task's schedule while preserving its public ID."""
        if plan.mode != "at":
            raise ValueError("replacement plan must use exact-time mode")
        conn = self._connection()
        with self.transaction():
            cursor = conn.execute(
                "UPDATE timer_tasks SET prompt = ?, schedule_type = 'at', "
                "start_at = NULL, end_at = NULL, step = NULL, effective_until = ?, "
                "total_occurrences = ?, processed_occurrences = 0, truncated = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    prompt,
                    plan.effective_until,
                    plan.total_occurrences,
                    int(plan.truncated),
                    time.time(),
                    task_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(task_id)
            conn.execute(
                "DELETE FROM timer_schedule_points WHERE task_id = ?", (task_id,)
            )
            self._insert_points(task_id, plan)

    def expand_truncated_frequency_tasks(self) -> int:
        """Remove the legacy task-wide cap without changing task progress."""
        conn = self._connection()
        tasks = conn.execute(
            "SELECT * FROM timer_tasks WHERE schedule_type != 'at' "
            "AND truncated = 1 ORDER BY id"
        ).fetchall()
        if not tasks:
            return 0

        with self.transaction():
            for task_row in tasks:
                task = dict(task_row)
                points = self.get_points_for_task(int(task["id"]))
                first_times = [
                    float(point["first_fire_at"])
                    for point in points
                    if point["first_fire_at"] is not None
                ]
                if not first_times:
                    raise RuntimeError(
                        f"frequency task {task['id']} has no first occurrence"
                    )
                if (
                    task["start_at"] is None
                    or task["end_at"] is None
                    or task["step"] is None
                ):
                    raise RuntimeError(
                        f"frequency task {task['id']} has incomplete bounds"
                    )

                start_at = datetime.fromtimestamp(
                    float(task["start_at"]), tz=SHANGHAI
                ).isoformat()
                end_at = datetime.fromtimestamp(
                    float(task["end_at"]), tz=SHANGHAI
                ).isoformat()
                step = int(task["step"])
                cutoff = min(first_times) - 1
                mode = str(task["schedule_type"])
                if mode == "daily":
                    plan = build_daily_plan(
                        start_at,
                        end_at,
                        [str(point["clock_time"]) for point in points],
                        step,
                        now=cutoff,
                    )
                elif mode == "weekly":
                    plan = build_weekly_plan(
                        start_at,
                        end_at,
                        [
                            {
                                "weekday": int(point["period_value"]),
                                "time": str(point["clock_time"]),
                            }
                            for point in points
                        ],
                        step,
                        now=cutoff,
                    )
                elif mode == "monthly":
                    plan = build_monthly_plan(
                        start_at,
                        end_at,
                        [
                            {
                                "day": int(point["period_value"]),
                                "time": str(point["clock_time"]),
                            }
                            for point in points
                        ],
                        step,
                        now=cutoff,
                    )
                else:
                    raise RuntimeError(
                        f"frequency task {task['id']} has unsupported mode {mode}"
                    )

                rebuilt = {
                    (point.period_value, point.clock_time): point
                    for point in plan.points
                }
                existing_keys = {
                    (point["period_value"], point["clock_time"])
                    for point in points
                }
                if set(rebuilt) != existing_keys:
                    raise RuntimeError(
                        f"frequency task {task['id']} point definitions changed"
                    )

                for point in points:
                    rebuilt_point = rebuilt[
                        (point["period_value"], point["clock_time"])
                    ]
                    old_first = point["first_fire_at"]
                    if old_first is not None and (
                        rebuilt_point.first_fire_at is None
                        or not math.isclose(
                            float(old_first),
                            rebuilt_point.first_fire_at,
                            rel_tol=0,
                            abs_tol=0.001,
                        )
                    ):
                        raise RuntimeError(
                            f"frequency task {task['id']} first occurrence changed"
                        )
                    if rebuilt_point.planned_count < int(
                        point["processed_occurrences"]
                    ):
                        raise RuntimeError(
                            f"frequency task {task['id']} progress exceeds plan"
                        )
                    conn.execute(
                        "UPDATE timer_schedule_points SET first_fire_at = ?, "
                        "last_fire_at = ?, planned_occurrences = ? WHERE id = ?",
                        (
                            rebuilt_point.first_fire_at,
                            rebuilt_point.last_fire_at,
                            rebuilt_point.planned_count,
                            point["id"],
                        ),
                    )

                conn.execute(
                    "UPDATE timer_tasks SET effective_until = ?, "
                    "total_occurrences = ?, truncated = 0, updated_at = ? "
                    "WHERE id = ?",
                    (
                        plan.effective_until,
                        plan.total_occurrences,
                        time.time(),
                        task["id"],
                    ),
                )
        return len(tasks)

    def delete_task(self, task_id: int, *, commit: bool = True) -> None:
        conn = self._connection()
        conn.execute("DELETE FROM timer_tasks WHERE id = ?", (task_id,))
        if commit:
            conn.commit()

    def mark_occurrence_processed(
        self, point_id: int, scheduled_at: float
    ) -> bool:
        """Advance point and task progress exactly once for a scheduled instant."""
        conn = self._connection()
        with self.transaction():
            row = conn.execute(
                "SELECT task_id, planned_occurrences, processed_occurrences, "
                "last_processed_at FROM timer_schedule_points WHERE id = ?",
                (point_id,),
            ).fetchone()
            if row is None:
                return False
            last_processed = row["last_processed_at"]
            if (
                row["processed_occurrences"] >= row["planned_occurrences"]
                or (last_processed is not None and last_processed >= scheduled_at)
            ):
                return False
            conn.execute(
                "UPDATE timer_schedule_points "
                "SET processed_occurrences = processed_occurrences + 1, "
                "last_processed_at = ? WHERE id = ?",
                (scheduled_at, point_id),
            )
            conn.execute(
                "UPDATE timer_tasks "
                "SET processed_occurrences = processed_occurrences + 1, "
                "updated_at = ? WHERE id = ?",
                (time.time(), row["task_id"]),
            )
        return True

    def list_finished_task_ids(self) -> list[int]:
        rows = self._connection().execute(
            "SELECT id FROM timer_tasks "
            "WHERE task_type = 'normal' "
            "AND processed_occurrences >= total_occurrences ORDER BY id"
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def delete_finished_tasks(self) -> list[int]:
        task_ids = self.list_finished_task_ids()
        if not task_ids:
            return []
        conn = self._connection()
        placeholders = ",".join("?" for _ in task_ids)
        conn.execute(
            f"DELETE FROM timer_tasks WHERE id IN ({placeholders})", task_ids
        )
        conn.commit()
        return task_ids

    def upsert_auto_response(
        self, trigger_at: float, prompt: str | None = None
    ) -> int:
        """Replace the internal auto-response task with one exact point."""
        from ..prompts import get_auto_response_prompt

        plan = _plan_from_epoch_times([trigger_at])
        conn = self._connection()
        with self.transaction():
            conn.execute("DELETE FROM timer_tasks WHERE task_type = 'auto_response'")
            task_id = self.create_task(
                0,
                0,
                prompt or get_auto_response_prompt(),
                plan,
                task_type="auto_response",
                commit=False,
            )
        return task_id

    def get_auto_response_point(self) -> dict | None:
        row = self._connection().execute(
            "SELECT p.*, t.prompt, t.task_type, t.schedule_type, t.step "
            "FROM timer_schedule_points AS p "
            "JOIN timer_tasks AS t ON t.id = p.task_id "
            "WHERE t.task_type = 'auto_response' "
            "AND p.processed_occurrences < p.planned_occurrences "
            "ORDER BY p.first_fire_at LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None

    def delete_auto_response_tasks(self) -> None:
        conn = self._connection()
        conn.execute("DELETE FROM timer_tasks WHERE task_type = 'auto_response'")
        conn.commit()

    def has_migration(self, name: str) -> bool:
        row = self._connection().execute(
            "SELECT 1 FROM timer_migrations WHERE name = ?", (name,)
        ).fetchone()
        return row is not None

    def record_migration(self, name: str, *, commit: bool = True) -> None:
        conn = self._connection()
        conn.execute(
            "INSERT OR IGNORE INTO timer_migrations (name, completed_at) "
            "VALUES (?, ?)",
            (name, time.time()),
        )
        if commit:
            conn.commit()

    def validate_prompt(self, prompt: str) -> str | None:
        if not prompt or not prompt.strip():
            return "错误：任务内容不能为空。"
        if len(prompt) > 500:
            return "错误：任务内容过长（最多 500 字符）。"
        return None
