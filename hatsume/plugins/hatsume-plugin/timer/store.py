"""TimerStore: SQLite CRUD for timer tasks and triggers."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ..config import TIMER_MAX_FUTURE_DAYS

# Default DB path in plugin data directory
_DEFAULT_DB_PATH: str | None = None


def _get_default_db_path() -> str:
    global _DEFAULT_DB_PATH
    if _DEFAULT_DB_PATH is None:
        try:
            import nonebot_plugin_localstore as local_store
            _DEFAULT_DB_PATH = str(
                Path(local_store.get_plugin_data_dir()) / "timer_db" / "timer.db"
            )
        except Exception:
            _DEFAULT_DB_PATH = str(
                Path(__file__).resolve().parents[4] / "data" / "hatsume-plugin" / "timer_db" / "timer.db"
            )
    return _DEFAULT_DB_PATH


class TimerStore:
    """Manages timer tasks and triggers in SQLite."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _get_default_db_path()
        self._conn: sqlite3.Connection | None = None

    def init_db(self) -> None:
        """Create database schema if it doesn't exist."""
        path = self._db_path
        if path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS timer_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                prompt      TEXT    NOT NULL,
                created_at  REAL    NOT NULL,
                updated_at  REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS timer_triggers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER NOT NULL REFERENCES timer_tasks(id) ON DELETE CASCADE,
                trigger_at  REAL    NOT NULL,
                fired       INTEGER NOT NULL DEFAULT 0,
                job_id      TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_triggers_pending
                ON timer_triggers(trigger_at) WHERE fired = 0;
        """)
        # Auto-create timer support (safe migration)
        try:
            self._conn.execute(
                "ALTER TABLE timer_tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'normal'"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        self._conn.execute("DELETE FROM timer_tasks WHERE task_type = 'auto_create'")
        self._conn.commit()
        print(f"⏰ [timer] DB initialized at {path}")

    # ------------------------------------------------------------------
    # CRUD: Tasks
    # ------------------------------------------------------------------

    def create_task(
        self, group_id: int, user_id: int, prompt: str,
        trigger_times: list[float],
    ) -> int:
        """Create a task with its trigger times. Returns the new task ID."""
        assert self._conn is not None, "TimerStore not initialized"
        now = time.time()
        unique_times = sorted(set(trigger_times))
        cur = self._conn.execute(
            "INSERT INTO timer_tasks (group_id, user_id, prompt, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (group_id, user_id, prompt, now, now),
        )
        task_id = cur.lastrowid
        assert task_id is not None
        for t in unique_times:
            cur = self._conn.execute(
                "INSERT INTO timer_triggers (task_id, trigger_at) VALUES (?, ?)",
                (task_id, t),
            )
            trigger_id = cur.lastrowid
            self._conn.execute(
                "UPDATE timer_triggers SET job_id = ? WHERE id = ?",
                (f"timer_{trigger_id}", trigger_id),
            )
        self._conn.commit()
        print(
            f"⏰ [timer] Task created: id={task_id} group={group_id} "
            f"user={user_id} triggers={len(unique_times)} prompt={prompt[:50]} trigger_times={trigger_times}"
        )
        return task_id

    def get_task(self, task_id: int) -> dict | None:
        """Get a task by ID, or None."""
        assert self._conn is not None, "TimerStore not initialized"
        row = self._conn.execute(
            "SELECT * FROM timer_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_tasks_by_group(self, group_id: int) -> list[dict]:
        """List all tasks for a group, ordered by creation time."""
        assert self._conn is not None, "TimerStore not initialized"
        rows = self._conn.execute(
            "SELECT * FROM timer_tasks WHERE group_id = ? ORDER BY created_at",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_task(
        self, task_id: int, prompt: str, trigger_times: list[float],
    ) -> None:
        """Update a task's prompt and replace all its triggers."""
        assert self._conn is not None, "TimerStore not initialized"
        now = time.time()
        self._conn.execute(
            "UPDATE timer_tasks SET prompt = ?, updated_at = ? WHERE id = ?",
            (prompt, now, task_id),
        )
        self._conn.execute(
            "DELETE FROM timer_triggers WHERE task_id = ?", (task_id,)
        )
        unique_times = sorted(set(trigger_times))
        for t in unique_times:
            cur = self._conn.execute(
                "INSERT INTO timer_triggers (task_id, trigger_at) VALUES (?, ?)",
                (task_id, t),
            )
            trigger_id = cur.lastrowid
            self._conn.execute(
                "UPDATE timer_triggers SET job_id = ? WHERE id = ?",
                (f"timer_{trigger_id}", trigger_id),
            )
        self._conn.commit()
        print(
            f"⏰ [timer] Task updated: id={task_id} "
            f"prompt={prompt[:50]} triggers={len(unique_times)}"
        )

    def delete_task(self, task_id: int) -> None:
        """Delete a task and its triggers (CASCADE)."""
        assert self._conn is not None, "TimerStore not initialized"
        self._conn.execute("DELETE FROM timer_tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        print(f"⏰ [timer] Task deleted: id={task_id}")

    # ------------------------------------------------------------------
    # Auto-response special timer
    # ------------------------------------------------------------------

    def upsert_auto_response(
        self, trigger_at: float, prompt: str | None = None,
    ) -> int:
        """Delete all old auto_response tasks and create a new one.

        Guarantees at most one auto_response row in the database.
        Returns the new task_id.
        """
        from ..prompts import get_auto_response_prompt

        assert self._conn is not None, "TimerStore not initialized"
        self._conn.execute(
            "DELETE FROM timer_tasks WHERE task_type = 'auto_response'"
        )
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO timer_tasks "
            "(group_id, user_id, prompt, created_at, updated_at, task_type) "
            "VALUES (?, ?, ?, ?, ?, 'auto_response')",
            (0, 0, prompt or get_auto_response_prompt(), now, now),
        )
        task_id = cur.lastrowid
        assert task_id is not None
        cur = self._conn.execute(
            "INSERT INTO timer_triggers (task_id, trigger_at) VALUES (?, ?)",
            (task_id, trigger_at),
        )
        trigger_id = cur.lastrowid
        self._conn.execute(
            "UPDATE timer_triggers SET job_id = ? WHERE id = ?",
            (f"timer_{trigger_id}", trigger_id),
        )
        self._conn.commit()
        run_dt = datetime.fromtimestamp(trigger_at, tz=timezone(timedelta(hours=8)))
        ts_str = run_dt.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"💬 [auto_response] Task upserted: id={task_id} "
            f"trigger_at={ts_str}"
        )
        return task_id

    def list_auto_response_triggers(self) -> list[dict]:
        """Get all unfired triggers for auto_response tasks."""
        assert self._conn is not None, "TimerStore not initialized"
        rows = self._conn.execute(
            "SELECT tr.* FROM timer_triggers tr "
            "JOIN timer_tasks t ON t.id = tr.task_id "
            "WHERE t.task_type = 'auto_response' AND tr.fired = 0"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # CRUD: Triggers
    # ------------------------------------------------------------------

    def get_triggers_for_task(self, task_id: int) -> list[dict]:
        """Get all triggers for a task, ordered by trigger_at."""
        assert self._conn is not None, "TimerStore not initialized"
        rows = self._conn.execute(
            "SELECT * FROM timer_triggers WHERE task_id = ? ORDER BY trigger_at",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_trigger_fired(self, trigger_id: int) -> None:
        """Mark a trigger as fired."""
        assert self._conn is not None, "TimerStore not initialized"
        self._conn.execute(
            "UPDATE timer_triggers SET fired = 1 WHERE id = ?", (trigger_id,)
        )
        self._conn.commit()
        print(f"⏰ [timer] Trigger fired: id={trigger_id}")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_trigger_times(
        self, trigger_times: list[float], now: float | None = None,
    ) -> list[str]:
        """Validate trigger times. Returns errors."""
        if now is None:
            now = time.time()
        errors: list[str] = []
        max_future = now + TIMER_MAX_FUTURE_DAYS * 24 * 3600

        seen: set[float] = set()
        for t in trigger_times:
            if t in seen:
                continue
            seen.add(t)
            if t <= now:
                errors.append(f"错误：触发时间 {t} 已过期，必须是当前时间之后。")
            elif t > max_future:
                errors.append(
                    f"错误：触发时间 {t} 超过 {TIMER_MAX_FUTURE_DAYS} 天限制。"
                )

        return errors

    def validate_prompt(self, prompt: str) -> str | None:
        """Validate prompt. Returns error str or None if valid."""
        if not prompt or not prompt.strip():
            return "错误：任务内容不能为空。"
        if len(prompt) > 500:
            return "错误：任务内容过长（最多 500 字符）。"
        return None
