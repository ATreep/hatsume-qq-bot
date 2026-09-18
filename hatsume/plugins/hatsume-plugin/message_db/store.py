"""SQLite persistence for per-group chat message history."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal, TypedDict, cast

import nonebot_plugin_localstore as localstore

_DEFAULT_DB_PATH: str | None = None

DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50

_VALID_ROLES = ("user", "assistant")

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")

_EXPECTED_TABLES = {"messages"}
_EXPECTED_COLUMNS = {
    "id",
    "group_id",
    "role",
    "sender_qq_id",
    "sender_name",
    "content",
    "reply_to_message_id",
    "platform_message_id",
    "created_at",
    "inserted_at",
}


class MessageRecord(TypedDict):
    id: int
    group_id: int
    role: str
    sender_qq_id: int
    sender_name: str
    content: str
    reply_to_message_id: int | None
    platform_message_id: int | None
    created_at: float
    inserted_at: float


class MessageValidationError(ValueError):
    """Raised when a message field violates the store contract."""


def _get_default_db_path() -> str:
    """Return the localstore-managed message database path."""
    global _DEFAULT_DB_PATH
    if _DEFAULT_DB_PATH is None:
        _DEFAULT_DB_PATH = str(
            localstore.get_plugin_data_file("message-db/message.db")
        )
    return _DEFAULT_DB_PATH


def parse_local_time(value: str, label: str) -> float:
    """Parse a ``YYYY-MM-DD HH:MM`` style string into epoch seconds."""
    cleaned = str(value).strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).timestamp()
        except ValueError:
            continue
    raise MessageValidationError(
        f"错误：{label} 格式无效，应为 YYYY-MM-DD HH:MM。"
    )


def _validate_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != _EXPECTED_TABLES:
        raise RuntimeError("incompatible message database schema")
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info('messages')")
    }
    if columns != _EXPECTED_COLUMNS:
        raise RuntimeError("incompatible message database schema")


def _clean_role(role: str) -> str:
    if role not in _VALID_ROLES:
        raise MessageValidationError(
            "错误：role 只能是 'user' 或 'assistant'。"
        )
    return role


def _clean_optional_id(value: int | None, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MessageValidationError(f"错误：{label} 必须是正整数或省略。")
    return value


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _row_to_record(row: sqlite3.Row) -> MessageRecord:
    return cast(MessageRecord, dict(row))


class MessageStore:
    """Record per-group chat history and serve scoped searches."""

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
                CREATE TABLE IF NOT EXISTS messages (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id            INTEGER NOT NULL CHECK (group_id > 0),
                    role                TEXT NOT NULL
                                        CHECK (role IN ('user', 'assistant')),
                    sender_qq_id        INTEGER NOT NULL,
                    sender_name         TEXT NOT NULL,
                    content             TEXT NOT NULL,
                    reply_to_message_id INTEGER,
                    platform_message_id INTEGER,
                    created_at          REAL NOT NULL,
                    inserted_at         REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_group_created
                    ON messages(group_id, created_at, id);

                CREATE INDEX IF NOT EXISTS idx_messages_group_sender
                    ON messages(group_id, sender_qq_id, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_group_platform
                    ON messages(group_id, platform_message_id)
                    WHERE platform_message_id IS NOT NULL;
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
            raise RuntimeError("MessageStore not initialized")
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

    def insert_message(
        self,
        group_id: int,
        role: Literal["user", "assistant"],
        sender_qq_id: int,
        sender_name: str,
        content: str,
        *,
        reply_to_message_id: int | None = None,
        platform_message_id: int | None = None,
        created_at: float | None = None,
        now: float | None = None,
    ) -> MessageRecord | None:
        """Insert one message unless its platform id is already recorded.

        Returns the stored record, or ``None`` when the message was a
        duplicate of an existing ``(group_id, platform_message_id)`` pair.
        """
        if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
            raise MessageValidationError("错误：群聊 ID 无效。")
        cleaned_role = _clean_role(role)
        if (
            isinstance(sender_qq_id, bool)
            or not isinstance(sender_qq_id, int)
            or sender_qq_id < 0
        ):
            raise MessageValidationError("错误：发送者 QQ 号无效。")
        if not isinstance(content, str):
            raise MessageValidationError("错误：消息正文必须是文本。")
        cleaned_name = str(sender_name or "").strip() or str(sender_qq_id)
        cleaned_reply_id = _clean_optional_id(reply_to_message_id, "reply_to_message_id")
        cleaned_platform_id = _clean_optional_id(
            platform_message_id, "platform_message_id"
        )

        effective_now = time.time() if now is None else now
        message_time = effective_now if created_at is None else created_at

        with self.transaction() as conn:
            if cleaned_platform_id is not None:
                duplicate = conn.execute(
                    "SELECT id FROM messages "
                    "WHERE group_id = ? AND platform_message_id = ?",
                    (group_id, cleaned_platform_id),
                ).fetchone()
                if duplicate is not None:
                    return None

            cursor = conn.execute(
                "INSERT INTO messages "
                "(group_id, role, sender_qq_id, sender_name, content, "
                "reply_to_message_id, platform_message_id, created_at, inserted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    group_id,
                    cleaned_role,
                    sender_qq_id,
                    cleaned_name,
                    content,
                    cleaned_reply_id,
                    cleaned_platform_id,
                    float(message_time),
                    float(effective_now),
                ),
            )
            message_id = cursor.lastrowid
            if message_id is None:
                raise RuntimeError("SQLite did not return a message ID")
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("SQLite did not return the created message")
            return _row_to_record(row)

    def search_messages(
        self,
        group_id: int,
        *,
        keyword: str | None = None,
        sender_qq_id: int | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[MessageRecord]:
        """Return one group's messages, newest first, matching every filter."""
        if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
            raise MessageValidationError("错误：群聊 ID 无效。")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise MessageValidationError("错误：limit 必须是正整数。")
        effective_limit = min(limit, MAX_SEARCH_LIMIT)

        clauses = ["group_id = ?"]
        params: list[Any] = [group_id]
        if keyword:
            clauses.append("content LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(keyword)}%")
        if sender_qq_id is not None:
            clauses.append("sender_qq_id = ?")
            params.append(sender_qq_id)
        if start_time is not None:
            clauses.append("created_at >= ?")
            params.append(float(start_time))
        if end_time is not None:
            clauses.append("created_at <= ?")
            params.append(float(end_time))

        params.append(effective_limit)
        sql = (
            "SELECT * FROM messages WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC, id DESC LIMIT ?"
        )
        rows = self._connection().execute(sql, tuple(params)).fetchall()
        return [_row_to_record(row) for row in rows]
