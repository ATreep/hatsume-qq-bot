"""SQLite persistence for per-group conversational todos."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, TypedDict, cast

import nonebot_plugin_localstore as localstore

from ..config import TODO_EXPIRY_SECONDS, TODO_MAX_ITEMS

_DEFAULT_DB_PATH: str | None = None
_MAX_FIELD_LENGTH = 500
_EXPECTED_COLUMNS = {
    "id",
    "group_id",
    "initiator_qq_id",
    "initiator_group_name",
    "content",
    "finish_condition",
    "created_at",
}


class TodoItem(TypedDict):
    id: int
    group_id: int
    initiator_qq_id: int
    initiator_group_name: str
    content: str
    finish_condition: str
    created_at: float


@dataclass(frozen=True)
class TodoCreateResult:
    status: Literal["created", "duplicate", "full"]
    item: TodoItem | None


class TodoValidationError(ValueError):
    """Raised when a todo field violates the public tool contract."""


def _get_default_db_path() -> str:
    """Return the localstore-managed todo database path."""
    global _DEFAULT_DB_PATH
    if _DEFAULT_DB_PATH is None:
        _DEFAULT_DB_PATH = str(localstore.get_plugin_data_file("todo-db/todo.db"))
    return _DEFAULT_DB_PATH


def _validate_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != {"todo_items"}:
        raise RuntimeError("incompatible todo database schema")
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info('todo_items')")
    }
    if columns != _EXPECTED_COLUMNS:
        raise RuntimeError("incompatible todo database schema")


def _clean_field(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TodoValidationError(f"错误：{label}必须是文本。")
    cleaned = value.strip()
    if not cleaned:
        raise TodoValidationError(f"错误：{label}不能为空。")
    if len(cleaned) > _MAX_FIELD_LENGTH:
        raise TodoValidationError(
            f"错误：{label}过长（最多 {_MAX_FIELD_LENGTH} 个字符）。"
        )
    return cleaned


def _row_to_item(row: sqlite3.Row) -> TodoItem:
    return cast(TodoItem, dict(row))


class TodoStore:
    """Manage active todos and enforce their retention and capacity rules."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _get_default_db_path()
        self._conn: sqlite3.Connection | None = None

    def init_db(self) -> None:
        """Open the database and create its idempotent schema."""
        if self._conn is not None:
            return
        path = self._db_path
        if path == ":memory:":
            conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            existing_table = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
            if existing_table is not None:
                _validate_schema(conn)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS todo_items (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id                INTEGER NOT NULL,
                    initiator_qq_id         INTEGER NOT NULL,
                    initiator_group_name    TEXT NOT NULL,
                    content                 TEXT NOT NULL,
                    finish_condition        TEXT NOT NULL,
                    created_at              REAL NOT NULL,
                    CHECK (group_id > 0),
                    CHECK (initiator_qq_id > 0)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_todo_active_duplicate
                    ON todo_items(
                        group_id,
                        initiator_qq_id,
                        content,
                        finish_condition
                    );

                CREATE INDEX IF NOT EXISTS idx_todo_group_created
                    ON todo_items(group_id, created_at, id);
                """
            )
            _validate_schema(conn)
            conn.commit()
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("TodoStore not initialized")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write decision and its mutation atomically."""
        conn = self._connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    @staticmethod
    def build_finish_condition(
        permitted_finisher: str, completion_event: str
    ) -> str:
        """Validate and assemble the canonical two-clause condition."""
        finisher = _clean_field(permitted_finisher, "允许完成人")
        event = _clean_field(completion_event, "完成事件")
        return f"Permitted finisher: {finisher}\nCompletion event: {event}"

    @staticmethod
    def _cutoff(now: float) -> float:
        return now - TODO_EXPIRY_SECONDS

    @staticmethod
    def _delete_expired_with_connection(
        conn: sqlite3.Connection, *, now: float
    ) -> int:
        cursor = conn.execute(
            "DELETE FROM todo_items WHERE created_at <= ?",
            (TodoStore._cutoff(now),),
        )
        return max(cursor.rowcount, 0)

    def delete_expired(self, *, now: float | None = None) -> int:
        """Hard-delete all items at or beyond the 48-hour boundary."""
        effective_now = time.time() if now is None else now
        with self.transaction() as conn:
            return self._delete_expired_with_connection(conn, now=effective_now)

    def list_items(self, group_id: int) -> list[TodoItem]:
        """List one group's active rows in stable creation order."""
        if isinstance(group_id, bool) or group_id <= 0:
            raise TodoValidationError("错误：群聊 ID 无效。")
        rows = self._connection().execute(
            "SELECT * FROM todo_items WHERE group_id = ? "
            "ORDER BY created_at, id",
            (group_id,),
        ).fetchall()
        return [_row_to_item(row) for row in rows]

    def create_item(
        self,
        group_id: int,
        initiator_qq_id: int,
        initiator_group_name: str,
        content: str,
        permitted_finisher: str,
        completion_event: str,
        *,
        now: float | None = None,
    ) -> TodoCreateResult:
        """Create an item unless it is an exact duplicate or the group is full."""
        if isinstance(group_id, bool) or group_id <= 0:
            raise TodoValidationError("错误：群聊 ID 无效。")
        if isinstance(initiator_qq_id, bool) or initiator_qq_id <= 0:
            raise TodoValidationError("错误：发起人 QQ ID 无效。")
        cleaned_content = _clean_field(content, "待办内容")
        finish_condition = self.build_finish_condition(
            permitted_finisher, completion_event
        )
        cleaned_name = str(initiator_group_name or "").strip() or str(
            initiator_qq_id
        )
        created_at = time.time() if now is None else now

        with self.transaction() as conn:
            self._delete_expired_with_connection(conn, now=created_at)
            duplicate = conn.execute(
                "SELECT * FROM todo_items WHERE group_id = ? "
                "AND initiator_qq_id = ? AND content = ? "
                "AND finish_condition = ?",
                (
                    group_id,
                    initiator_qq_id,
                    cleaned_content,
                    finish_condition,
                ),
            ).fetchone()
            if duplicate is not None:
                return TodoCreateResult("duplicate", _row_to_item(duplicate))

            count = conn.execute(
                "SELECT COUNT(*) AS count FROM todo_items WHERE group_id = ?",
                (group_id,),
            ).fetchone()
            if count is None:
                raise RuntimeError("SQLite did not return a todo count")
            if int(count["count"]) >= TODO_MAX_ITEMS:
                return TodoCreateResult("full", None)

            cursor = conn.execute(
                "INSERT INTO todo_items "
                "(group_id, initiator_qq_id, initiator_group_name, content, "
                "finish_condition, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    group_id,
                    initiator_qq_id,
                    cleaned_name,
                    cleaned_content,
                    finish_condition,
                    created_at,
                ),
            )
            item_id = cursor.lastrowid
            if item_id is None:
                raise RuntimeError("SQLite did not return a todo ID")
            row = conn.execute(
                "SELECT * FROM todo_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("SQLite did not return the created todo")
            return TodoCreateResult("created", _row_to_item(row))

    def mark_item(
        self,
        group_id: int,
        todo_id: int,
        *,
        now: float | None = None,
    ) -> TodoItem | None:
        """Delete and return one active item scoped to the current group."""
        if isinstance(group_id, bool) or group_id <= 0:
            raise TodoValidationError("错误：群聊 ID 无效。")
        if isinstance(todo_id, bool) or todo_id <= 0:
            return None
        effective_now = time.time() if now is None else now
        with self.transaction() as conn:
            self._delete_expired_with_connection(conn, now=effective_now)
            row = conn.execute(
                "SELECT * FROM todo_items WHERE id = ? AND group_id = ?",
                (todo_id, group_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "DELETE FROM todo_items WHERE id = ? AND group_id = ?",
                (todo_id, group_id),
            )
            return _row_to_item(row)
