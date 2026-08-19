"""SQLite persistence for per-group heartbeat Hooks."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as localstore

from ..config import (
    HOOK_DEFAULT_INTERVAL_SECONDS,
    HOOK_DEFAULT_TIMEOUT_SECONDS,
    HOOK_MAX_ACTIVE_PER_GROUP,
    HOOK_MAX_TIMEOUT_SECONDS,
    HOOK_MIN_INTERVAL_SECONDS,
)

HOOK_MAX_NAME_LENGTH = 64
HOOK_MAX_PROMPT_LENGTH = 2_000
HOOK_MAX_ERROR_LENGTH = 2_000

EXPECTED_COLUMNS = {
    "id",
    "group_id",
    "name",
    "script_path",
    "prompt",
    "interval_seconds",
    "timeout_seconds",
    "enabled",
    "created_by",
    "created_at",
    "updated_at",
    "last_run_at",
    "last_exit_code",
    "last_error",
    "consecutive_failures",
}


class HookLimitError(ValueError):
    """Raised when one group would exceed its enabled Hook limit."""


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _bounded_int(value: Any, field: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} must be an integer <= {maximum}")
    return value


def _bounded_text(value: Any, field: str, maximum: int) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters")
    return normalized


def _script_path(value: Any) -> str:
    normalized = str(value).strip()
    if not normalized or "\0" in normalized:
        raise ValueError("script_path must not be empty")
    return normalized


def _enabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError("enabled must be a boolean")
    return value


class HookStore:
    """Manage persistent Hook definitions and execution status."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(localstore.get_plugin_data_file("hooks/hooks.db"))
        self._operation_lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @contextmanager
    def serialized(self) -> Iterator[None]:
        with self._operation_lock:
            yield

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("HookStore is not initialized")
        return self._conn

    def init_db(self) -> None:
        with self._operation_lock:
            if self._conn is not None:
                return
            if self._db_path == ":memory:":
                conn = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hooks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_id INTEGER NOT NULL CHECK (group_id > 0),
                        name TEXT NOT NULL,
                        script_path TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        interval_seconds INTEGER NOT NULL
                            CHECK (interval_seconds >= 300),
                        timeout_seconds INTEGER NOT NULL
                            CHECK (timeout_seconds >= 1 AND timeout_seconds <= 60),
                        enabled INTEGER NOT NULL DEFAULT 1
                            CHECK (enabled IN (0, 1)),
                        created_by INTEGER NOT NULL CHECK (created_by > 0),
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        last_run_at REAL,
                        last_exit_code INTEGER,
                        last_error TEXT,
                        consecutive_failures INTEGER NOT NULL DEFAULT 0,
                        UNIQUE (group_id, name)
                    )
                    """
                )
                columns = {
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info('hooks')")
                }
                if columns != EXPECTED_COLUMNS:
                    raise RuntimeError("incompatible Hook database schema")
                conn.commit()
            except BaseException:
                conn.close()
                raise
            self._conn = conn

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        return result

    def _active_count(self, conn: sqlite3.Connection, group_id: int) -> int:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM hooks WHERE group_id = ? AND enabled = 1",
            (group_id,),
        ).fetchone()
        return int(row["count"])

    def create_hook(
        self,
        *,
        group_id: int,
        name: str,
        script_path: str,
        prompt: str,
        interval_seconds: int = HOOK_DEFAULT_INTERVAL_SECONDS,
        timeout_seconds: int = HOOK_DEFAULT_TIMEOUT_SECONDS,
        created_by: int,
        enabled: bool = True,
    ) -> dict[str, Any]:
        resolved_group_id = _positive_int(group_id, "group_id")
        resolved_creator = _positive_int(created_by, "created_by")
        resolved_name = _bounded_text(name, "name", HOOK_MAX_NAME_LENGTH)
        resolved_prompt = _bounded_text(prompt, "prompt", HOOK_MAX_PROMPT_LENGTH)
        resolved_path = _script_path(script_path)
        resolved_interval = _bounded_int(
            interval_seconds,
            "interval_seconds",
            HOOK_MIN_INTERVAL_SECONDS,
        )
        resolved_timeout = _bounded_int(
            timeout_seconds,
            "timeout_seconds",
            1,
            HOOK_MAX_TIMEOUT_SECONDS,
        )
        resolved_enabled = _enabled(enabled)
        now = time.time()

        with self._operation_lock:
            conn = self._connection()
            with conn:
                if resolved_enabled and self._active_count(conn, resolved_group_id) >= HOOK_MAX_ACTIVE_PER_GROUP:
                    raise HookLimitError("a group may have at most 5 enabled Hooks")
                try:
                    cursor = conn.execute(
                        """
                        INSERT INTO hooks (
                            group_id, name, script_path, prompt,
                            interval_seconds, timeout_seconds, enabled,
                            created_by, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            resolved_group_id,
                            resolved_name,
                            resolved_path,
                            resolved_prompt,
                            resolved_interval,
                            resolved_timeout,
                            int(resolved_enabled),
                            resolved_creator,
                            now,
                            now,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError(
                        f"Hook '{resolved_name}' already exists in group {resolved_group_id}"
                    ) from exc
                if cursor.lastrowid is None:
                    raise RuntimeError("Hook insert did not return an ID")
                hook_id = cursor.lastrowid
            record = self.get_hook(hook_id)
            assert record is not None
            return record

    def get_hook(self, hook_id: int) -> dict[str, Any] | None:
        resolved_id = _positive_int(hook_id, "hook_id")
        with self._operation_lock:
            row = self._connection().execute(
                "SELECT * FROM hooks WHERE id = ?",
                (resolved_id,),
            ).fetchone()
            return self._row(row)

    def get_hook_by_name(self, group_id: int, name: str) -> dict[str, Any] | None:
        resolved_group_id = _positive_int(group_id, "group_id")
        resolved_name = _bounded_text(name, "name", HOOK_MAX_NAME_LENGTH)
        with self._operation_lock:
            row = self._connection().execute(
                "SELECT * FROM hooks WHERE group_id = ? AND name = ?",
                (resolved_group_id, resolved_name),
            ).fetchone()
            return self._row(row)

    def list_hooks(self, group_id: int) -> list[dict[str, Any]]:
        resolved_group_id = _positive_int(group_id, "group_id")
        with self._operation_lock:
            rows = self._connection().execute(
                "SELECT * FROM hooks WHERE group_id = ? ORDER BY created_at, id",
                (resolved_group_id,),
            ).fetchall()
            return [record for row in rows if (record := self._row(row)) is not None]

    def list_enabled_hooks(
        self,
        group_ids: Iterable[int] | None = None,
    ) -> list[dict[str, Any]]:
        params: tuple[int, ...] = ()
        clause = ""
        if group_ids is not None:
            normalized = tuple(sorted({_positive_int(value, "group_id") for value in group_ids}))
            if not normalized:
                return []
            clause = f" AND group_id IN ({','.join('?' for _ in normalized)})"
            params = normalized
        with self._operation_lock:
            rows = self._connection().execute(
                f"SELECT * FROM hooks WHERE enabled = 1{clause} ORDER BY group_id, id",
                params,
            ).fetchall()
            return [record for row in rows if (record := self._row(row)) is not None]

    def update_hook(self, group_id: int, name: str, **changes: Any) -> dict[str, Any]:
        resolved_group_id = _positive_int(group_id, "group_id")
        resolved_name = _bounded_text(name, "name", HOOK_MAX_NAME_LENGTH)
        allowed = {
            "script_path",
            "prompt",
            "interval_seconds",
            "timeout_seconds",
            "enabled",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported Hook fields: {', '.join(sorted(unknown))}")

        normalized: dict[str, Any] = {}
        if "script_path" in changes:
            normalized["script_path"] = _script_path(changes["script_path"])
        if "prompt" in changes:
            normalized["prompt"] = _bounded_text(
                changes["prompt"], "prompt", HOOK_MAX_PROMPT_LENGTH
            )
        if "interval_seconds" in changes:
            normalized["interval_seconds"] = _bounded_int(
                changes["interval_seconds"],
                "interval_seconds",
                HOOK_MIN_INTERVAL_SECONDS,
            )
        if "timeout_seconds" in changes:
            normalized["timeout_seconds"] = _bounded_int(
                changes["timeout_seconds"],
                "timeout_seconds",
                1,
                HOOK_MAX_TIMEOUT_SECONDS,
            )
        if "enabled" in changes:
            normalized["enabled"] = int(_enabled(changes["enabled"]))

        with self._operation_lock:
            conn = self._connection()
            with conn:
                current = conn.execute(
                    "SELECT * FROM hooks WHERE group_id = ? AND name = ?",
                    (resolved_group_id, resolved_name),
                ).fetchone()
                if current is None:
                    raise ValueError(f"Hook '{resolved_name}' does not exist")
                if (
                    normalized.get("enabled") == 1
                    and not bool(current["enabled"])
                    and self._active_count(conn, resolved_group_id) >= HOOK_MAX_ACTIVE_PER_GROUP
                ):
                    raise HookLimitError("a group may have at most 5 enabled Hooks")
                if normalized:
                    normalized["updated_at"] = time.time()
                    assignments = ", ".join(f"{field} = ?" for field in normalized)
                    conn.execute(
                        f"UPDATE hooks SET {assignments} WHERE id = ?",
                        (*normalized.values(), int(current["id"])),
                    )
                row = conn.execute(
                    "SELECT * FROM hooks WHERE id = ?",
                    (int(current["id"]),),
                ).fetchone()
            record = self._row(row)
            assert record is not None
            return record

    def delete_hook(self, group_id: int, name: str) -> dict[str, Any] | None:
        resolved_group_id = _positive_int(group_id, "group_id")
        resolved_name = _bounded_text(name, "name", HOOK_MAX_NAME_LENGTH)
        with self._operation_lock:
            conn = self._connection()
            with conn:
                row = conn.execute(
                    "SELECT * FROM hooks WHERE group_id = ? AND name = ?",
                    (resolved_group_id, resolved_name),
                ).fetchone()
                if row is None:
                    return None
                conn.execute("DELETE FROM hooks WHERE id = ?", (int(row["id"]),))
            return self._row(row)

    def record_success(self, hook_id: int, exit_code: int, run_at: float) -> None:
        resolved_id = _positive_int(hook_id, "hook_id")
        with self._operation_lock, self._connection() as conn:
            conn.execute(
                """
                UPDATE hooks
                SET last_run_at = ?, last_exit_code = ?, last_error = NULL,
                    consecutive_failures = 0
                WHERE id = ?
                """,
                (float(run_at), int(exit_code), resolved_id),
            )

    def record_failure(
        self,
        hook_id: int,
        exit_code: int | None,
        error: str,
        run_at: float,
    ) -> None:
        resolved_id = _positive_int(hook_id, "hook_id")
        bounded_error = str(error).strip()[:HOOK_MAX_ERROR_LENGTH] or "Hook execution failed"
        with self._operation_lock, self._connection() as conn:
            conn.execute(
                """
                UPDATE hooks
                SET last_run_at = ?, last_exit_code = ?, last_error = ?,
                    consecutive_failures = consecutive_failures + 1
                WHERE id = ?
                """,
                (float(run_at), exit_code, bounded_error, resolved_id),
            )

    def close(self) -> None:
        with self._operation_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
