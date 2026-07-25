"""Tests for read-only migration from the legacy timer database."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
BASE_NAME = "hatsume.plugins.hatsume-plugin"


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_modules():
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        (BASE_NAME, PLUGIN_DIR),
        (f"{BASE_NAME}.timer", PLUGIN_DIR / "timer"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    config = types.ModuleType(f"{BASE_NAME}.config")
    config.TIMER_MAX_FREQUENCY_POINTS = 5
    config.TIMER_MAX_EXACT_POINTS = 10
    sys.modules[config.__name__] = config

    prompts = types.ModuleType(f"{BASE_NAME}.prompts")
    prompts.get_auto_response_prompt = lambda: "auto response"
    sys.modules[prompts.__name__] = prompts

    schedule = _load_file(
        f"{BASE_NAME}.timer.schedule", PLUGIN_DIR / "timer/schedule.py"
    )
    store = _load_file(f"{BASE_NAME}.timer.store", PLUGIN_DIR / "timer/store.py")
    migration = _load_file(
        f"{BASE_NAME}.timer.migration", PLUGIN_DIR / "timer/migration.py"
    )
    return schedule, store, migration


def _create_legacy_db(
    path: Path,
    *,
    journal_mode: str = "DELETE",
    keep_open: bool = False,
) -> sqlite3.Connection | None:
    conn = sqlite3.connect(path)
    if journal_mode not in {"DELETE", "WAL"}:
        raise ValueError(f"unsupported journal mode: {journal_mode}")
    conn.execute(f"PRAGMA journal_mode={journal_mode}")
    if journal_mode == "WAL":
        conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.executescript(
        """
        CREATE TABLE timer_tasks (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            task_type TEXT NOT NULL DEFAULT 'normal'
        );
        CREATE TABLE timer_triggers (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            trigger_at REAL NOT NULL,
            fired INTEGER NOT NULL DEFAULT 0,
            job_id TEXT
        );
        """
    )
    tasks = [
        (7, 100, 200, "每两天早晚提醒", "normal"),
        (8, 100, 201, "finished", "normal"),
        (9, 0, 0, "internal", "auto_response"),
        (10, 0, 0, "removed", "auto_create"),
    ]
    conn.executemany(
        "INSERT INTO timer_tasks "
        "(id, group_id, user_id, prompt, created_at, updated_at, task_type) "
        "VALUES (?, ?, ?, ?, 1, 1, ?)",
        tasks,
    )
    def timestamp(value: str) -> float:
        return datetime.fromisoformat(value).timestamp()

    triggers = [
        (1, 7, timestamp("2026-08-01T09:00:00+08:00"), 1),
        (2, 7, timestamp("2026-08-01T18:00:00+08:00"), 0),
        (3, 7, timestamp("2026-08-03T09:00:00+08:00"), 0),
        (4, 7, timestamp("2026-08-03T18:00:00+08:00"), 0),
        (5, 8, timestamp("2026-08-01T09:00:00+08:00"), 1),
        (6, 9, timestamp("2026-08-01T09:00:00+08:00"), 0),
        (7, 10, timestamp("2026-08-01T09:00:00+08:00"), 0),
    ]
    conn.executemany(
        "INSERT INTO timer_triggers (id, task_id, trigger_at, fired) "
        "VALUES (?, ?, ?, ?)",
        triggers,
    )
    conn.commit()
    if keep_open:
        return conn
    conn.close()
    return None


@pytest.fixture
def modules():
    return _load_modules()


def test_migrates_only_unfinished_normal_tasks_read_only(tmp_path, modules):
    _, store_module, migration = modules
    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    before = legacy.read_bytes()
    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()

    result = migration.migrate_legacy_timer_db(destination, legacy)

    assert result.migrated_tasks == 1
    assert result.skipped_tasks == 3
    task = destination.get_task(7)
    assert task["legacy_task_id"] == 7
    assert task["schedule_type"] == "daily"
    assert task["total_occurrences"] == 3
    assert legacy.read_bytes() == before
    assert not (tmp_path / "legacy.db-wal").exists()
    assert not (tmp_path / "legacy.db-shm").exists()
    destination.close()


def test_migration_persists_each_inferred_schedule_type(tmp_path, modules):
    _, store_module, migration = modules
    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    connection = sqlite3.connect(legacy)

    def timestamp(value: str) -> float:
        return datetime.fromisoformat(value).timestamp()

    connection.executemany(
        "INSERT INTO timer_tasks "
        "(id, group_id, user_id, prompt, created_at, updated_at, task_type) "
        "VALUES (?, 100, 200, ?, 1, 1, 'normal')",
        [
            (11, "每两周周一和周五提醒"),
            (12, "每两个月15日提醒"),
            (13, "irregular exact reminders"),
        ],
    )
    trigger_values = {
        11: [
            "2026-08-03T09:00:00+08:00",
            "2026-08-07T18:00:00+08:00",
            "2026-08-17T09:00:00+08:00",
            "2026-08-21T18:00:00+08:00",
        ],
        12: [
            "2026-08-15T09:00:00+08:00",
            "2026-10-15T09:00:00+08:00",
            "2026-12-15T09:00:00+08:00",
        ],
        13: [
            "2026-08-02T10:00:00+08:00",
            "2026-08-05T11:00:00+08:00",
            "2026-08-11T13:00:00+08:00",
        ],
    }
    trigger_id = 100
    for task_id, values in trigger_values.items():
        for value in values:
            connection.execute(
                "INSERT INTO timer_triggers "
                "(id, task_id, trigger_at, fired) VALUES (?, ?, ?, 0)",
                (trigger_id, task_id, timestamp(value)),
            )
            trigger_id += 1
    connection.commit()
    connection.close()

    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()
    try:
        result = migration.migrate_legacy_timer_db(destination, legacy)

        assert result.migrated_tasks == 4
        assert destination.get_task(7)["schedule_type"] == "daily"
        assert destination.get_task(7)["step"] == 2
        assert destination.get_task(11)["schedule_type"] == "weekly"
        assert destination.get_task(11)["step"] == 2
        assert destination.get_task(12)["schedule_type"] == "monthly"
        assert destination.get_task(12)["step"] == 2
        assert destination.get_task(13)["schedule_type"] == "at"
        assert destination.get_task(13)["step"] is None
    finally:
        destination.close()


def test_migration_keeps_more_than_fifty_frequency_occurrences(
    tmp_path, modules
):
    _, store_module, migration = modules
    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    connection = sqlite3.connect(legacy)
    connection.execute(
        "INSERT INTO timer_tasks "
        "(id, group_id, user_id, prompt, created_at, updated_at, task_type) "
        "VALUES (14, 100, 200, '每天早上提醒', 1, 1, 'normal')"
    )
    first = datetime.fromisoformat("2026-08-01T09:00:00+08:00")
    connection.executemany(
        "INSERT INTO timer_triggers (task_id, trigger_at, fired) "
        "VALUES (14, ?, 0)",
        [((first + timedelta(days=index)).timestamp(),) for index in range(60)],
    )
    connection.commit()
    connection.close()

    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()
    try:
        migration.migrate_legacy_timer_db(destination, legacy)

        task = destination.get_task(14)
        assert task["schedule_type"] == "daily"
        assert task["total_occurrences"] == 60
        assert task["truncated"] == 0
        assert destination.get_points_for_task(14)[0][
            "planned_occurrences"
        ] == 60
    finally:
        destination.close()


def test_wal_source_and_sidecars_remain_byte_identical(tmp_path, modules):
    _, store_module, migration = modules
    legacy = tmp_path / "legacy.db"
    writer = _create_legacy_db(legacy, journal_mode="WAL", keep_open=True)
    assert writer is not None
    source_files = [legacy, Path(f"{legacy}-wal"), Path(f"{legacy}-shm")]
    assert all(path.is_file() for path in source_files)
    before = {path: path.read_bytes() for path in source_files}
    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()

    try:
        result = migration.migrate_legacy_timer_db(destination, legacy)

        assert result.migrated_tasks == 1
        assert destination.get_task(7)["total_occurrences"] == 3
        assert {path: path.read_bytes() for path in source_files} == before
    finally:
        destination.close()
        writer.close()


def test_migration_is_idempotent(tmp_path, modules):
    _, store_module, migration = modules
    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()

    first = migration.migrate_legacy_timer_db(destination, legacy)
    second = migration.migrate_legacy_timer_db(destination, legacy)

    assert first.already_applied is False
    assert second.already_applied is True
    assert [task["id"] for task in destination.list_tasks_by_group(100)] == [7]
    destination.close()


def test_failed_migration_rolls_back_and_can_retry(tmp_path, modules, monkeypatch):
    _, store_module, migration = modules
    legacy = tmp_path / "legacy.db"
    _create_legacy_db(legacy)
    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()
    original_create = destination.create_task

    def fail_create(*args, **kwargs):
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(destination, "create_task", fail_create)
    with pytest.raises(RuntimeError, match="injected"):
        migration.migrate_legacy_timer_db(destination, legacy)

    assert destination.has_migration(migration.LEGACY_MIGRATION_NAME) is False
    assert destination.list_tasks_by_group(100) == []

    monkeypatch.setattr(destination, "create_task", original_create)
    assert migration.migrate_legacy_timer_db(destination, legacy).migrated_tasks == 1
    destination.close()


def test_missing_legacy_database_is_not_marked_applied(tmp_path, modules):
    _, store_module, migration = modules
    destination = store_module.TimerStore(str(tmp_path / "v2.db"))
    destination.init_db()

    result = migration.migrate_legacy_timer_db(
        destination, tmp_path / "missing.db"
    )

    assert result.migrated_tasks == 0
    assert result.already_applied is False
    assert destination.has_migration(migration.LEGACY_MIGRATION_NAME) is False
    destination.close()
