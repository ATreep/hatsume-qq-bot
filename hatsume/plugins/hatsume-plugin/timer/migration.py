"""Read-only migration from the legacy expanded-trigger timer database."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from .schedule import infer_legacy_plan
from .store import TimerStore

LEGACY_MIGRATION_NAME = "legacy_timer_v1"


@dataclass(frozen=True)
class MigrationResult:
    """Summary of one legacy migration attempt."""

    migrated_tasks: int
    skipped_tasks: int
    already_applied: bool


@contextmanager
def _open_read_only_snapshot(path: Path) -> Iterator[sqlite3.Connection]:
    """Read a private DB/WAL snapshot without opening SQLite on source files."""
    with TemporaryDirectory(prefix="hatsume-timer-migration-") as temp_dir:
        snapshot_path = Path(temp_dir) / path.name
        copyfile(path, snapshot_path)

        source_wal = Path(f"{path}-wal")
        if source_wal.is_file():
            copyfile(source_wal, Path(f"{snapshot_path}-wal"))

        uri = f"{snapshot_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()


def migrate_legacy_timer_db(
    store: TimerStore,
    legacy_path: str | Path,
) -> MigrationResult:
    """Copy unfinished normal legacy tasks without modifying the source DB."""
    if store.has_migration(LEGACY_MIGRATION_NAME):
        return MigrationResult(0, 0, True)

    source_path = Path(legacy_path)
    if not source_path.is_file():
        return MigrationResult(0, 0, False)

    with _open_read_only_snapshot(source_path) as source:
        columns = {
            row["name"]
            for row in source.execute("PRAGMA table_info('timer_tasks')").fetchall()
        }
        tasks = source.execute("SELECT * FROM timer_tasks ORDER BY id").fetchall()
        pending_by_task: dict[int, list[float]] = {}
        for row in source.execute(
            "SELECT task_id, trigger_at FROM timer_triggers "
            "WHERE fired = 0 ORDER BY task_id, trigger_at"
        ).fetchall():
            pending_by_task.setdefault(int(row["task_id"]), []).append(
                float(row["trigger_at"])
            )

        eligible: list[tuple[sqlite3.Row, list[float]]] = []
        skipped = 0
        for task in tasks:
            task_id = int(task["id"])
            task_type = str(task["task_type"]) if "task_type" in columns else "normal"
            pending = pending_by_task.get(task_id, [])
            if task_type != "normal" or not pending:
                skipped += 1
                continue
            eligible.append((task, pending))

        migrated = 0
        with store.transaction():
            for task, pending in eligible:
                legacy_id = int(task["id"])
                plan = infer_legacy_plan(str(task["prompt"]), pending)
                preserved_id = legacy_id if store.get_task(legacy_id) is None else None
                store.create_task(
                    int(task["group_id"]),
                    int(task["user_id"]),
                    str(task["prompt"]),
                    plan,
                    task_id=preserved_id,
                    legacy_task_id=legacy_id,
                    commit=False,
                )
                migrated += 1
            store.record_migration(LEGACY_MIGRATION_NAME, commit=False)
        return MigrationResult(migrated, skipped, False)
