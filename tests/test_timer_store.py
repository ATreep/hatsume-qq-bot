"""Tests for timer-v2 SQLite persistence and progress accounting."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
BASE_NAME = "hatsume.plugins.hatsume-plugin"
SHANGHAI_OFFSET = "+08:00"


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_timer_modules():
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
    prompts.get_auto_response_prompt = lambda: "auto response prompt"
    sys.modules[prompts.__name__] = prompts

    schedule = _load_file(
        f"{BASE_NAME}.timer.schedule", PLUGIN_DIR / "timer/schedule.py"
    )
    store_module = _load_file(
        f"{BASE_NAME}.timer.store", PLUGIN_DIR / "timer/store.py"
    )
    return schedule, store_module


@pytest.fixture
def modules():
    return _load_timer_modules()


@pytest.fixture
def store(tmp_path, modules):
    _, store_module = modules
    instance = store_module.TimerStore(str(tmp_path / "timer.db"))
    instance.init_db()
    yield instance
    instance.close()


@pytest.fixture
def daily_plan(modules):
    schedule, _ = modules
    return schedule.build_daily_plan(
        "2026-08-01T00:00:00+08:00",
        "2026-08-03T23:59:59+08:00",
        ["09:00:00", "18:00:00"],
        step=1,
        now=0,
    )


@pytest.fixture
def at_plan(modules):
    schedule, _ = modules
    return schedule.build_at_plan(
        ["2026-08-10T09:00:00+08:00", "2026-08-11T18:00:00+08:00"],
        now=0,
    )


def _columns(store, table: str) -> set[str]:
    assert store._conn is not None
    rows = store._conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return {row["name"] for row in rows}


def test_default_path_uses_timer_v2_directory(modules):
    _, store_module = modules
    assert Path(store_module._get_default_db_path()).parts[-3:] == (
        "data",
        "timer-v2-db",
        "timer.db",
    )


def test_v2_schema_and_indexes(store):
    assert store._conn is not None
    tables = {
        row["name"]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"timer_tasks", "timer_schedule_points", "timer_migrations"} <= tables
    assert {
        "schedule_type",
        "start_at",
        "end_at",
        "step",
        "effective_until",
        "total_occurrences",
        "processed_occurrences",
        "truncated",
        "legacy_task_id",
    } <= _columns(store, "timer_tasks")
    assert {
        "period_value",
        "clock_time",
        "exact_at",
        "first_fire_at",
        "last_fire_at",
        "planned_occurrences",
        "processed_occurrences",
        "last_processed_at",
        "job_id",
    } <= _columns(store, "timer_schedule_points")


def test_repeated_initialization_keeps_existing_data(tmp_path, modules, daily_plan):
    _, store_module = modules
    path = tmp_path / "timer.db"
    first = store_module.TimerStore(str(path))
    first.init_db()
    task_id = first.create_task(1, 2, "prompt", daily_plan)
    first.close()

    reopened = store_module.TimerStore(str(path))
    reopened.init_db()
    assert reopened.get_task(task_id)["prompt"] == "prompt"
    reopened.close()


def test_create_task_persists_plan_and_stable_point_jobs(store, daily_plan):
    task_id = store.create_task(100, 200, "提醒开会", daily_plan)

    task = store.get_task(task_id)
    assert task["group_id"] == 100
    assert task["user_id"] == 200
    assert task["schedule_type"] == "daily"
    assert task["total_occurrences"] == 6
    assert task["processed_occurrences"] == 0
    points = store.get_points_for_task(task_id)
    assert [point["clock_time"] for point in points] == ["09:00:00", "18:00:00"]
    assert all(point["job_id"] == f"timer_v2_point_{point['id']}" for point in points)


def test_create_task_persists_descriptive_zero_occurrence_point(store, modules):
    schedule, _ = modules
    plan = schedule.build_daily_plan(
        "2026-08-01T00:00:00+08:00",
        "2026-08-01T23:59:59+08:00",
        ["09:00:00", "18:00:00"],
        now=datetime.fromisoformat("2026-08-01T12:00:00+08:00").timestamp(),
    )

    task_id = store.create_task(1, 2, "prompt", plan)
    points = store.get_points_for_task(task_id)

    assert [point["clock_time"] for point in points] == ["09:00:00", "18:00:00"]
    assert [point["planned_occurrences"] for point in points] == [0, 1]
    assert points[0]["first_fire_at"] is None
    assert points[0]["last_fire_at"] is None
    assert [point["id"] for point in store.list_incomplete_points()] == [
        points[1]["id"]
    ]


def test_create_task_rolls_back_task_when_point_insert_fails(
    store, daily_plan, monkeypatch
):
    def fail_point_insert(task_id, plan):
        raise RuntimeError("point insert failed")

    monkeypatch.setattr(store, "_insert_points", fail_point_insert)

    with pytest.raises(RuntimeError, match="point insert failed"):
        store.create_task(1, 2, "prompt", daily_plan)

    assert store.list_tasks_by_group(1) == []


def test_list_tasks_by_group_excludes_internal_tasks(store, daily_plan, at_plan):
    visible_id = store.create_task(1, 2, "visible", daily_plan)
    store.create_task(1, 0, "internal", at_plan, task_type="auto_response")
    store.create_task(2, 3, "other", daily_plan)

    assert [task["id"] for task in store.list_tasks_by_group(1)] == [visible_id]


def test_delete_task_cascades_to_schedule_points(store, daily_plan):
    task_id = store.create_task(1, 2, "prompt", daily_plan)
    point_ids = [point["id"] for point in store.get_points_for_task(task_id)]

    store.delete_task(task_id)

    assert store.get_task(task_id) is None
    assert store.get_points_for_task(task_id) == []
    assert all(store.get_point(point_id) is None for point_id in point_ids)


def test_mark_occurrence_processed_is_idempotent(store, daily_plan):
    task_id = store.create_task(1, 2, "prompt", daily_plan)
    point = store.get_points_for_task(task_id)[0]
    scheduled_at = point["first_fire_at"]

    assert store.mark_occurrence_processed(point["id"], scheduled_at) is True
    assert store.mark_occurrence_processed(point["id"], scheduled_at) is False

    updated_point = store.get_point(point["id"])
    assert updated_point["processed_occurrences"] == 1
    assert updated_point["last_processed_at"] == scheduled_at
    assert store.get_task(task_id)["processed_occurrences"] == 1


def test_progress_does_not_exceed_planned_count(store, at_plan):
    task_id = store.create_task(1, 2, "prompt", at_plan)
    point = store.get_points_for_task(task_id)[0]

    assert store.mark_occurrence_processed(point["id"], point["exact_at"]) is True
    assert store.mark_occurrence_processed(point["id"], point["exact_at"] + 1) is False
    assert store.get_point(point["id"])["processed_occurrences"] == 1


def test_list_incomplete_points_joins_task_schedule_fields(store, daily_plan):
    task_id = store.create_task(1, 2, "prompt", daily_plan)

    rows = store.list_incomplete_points()

    assert {row["task_id"] for row in rows} == {task_id}
    assert {row["schedule_type"] for row in rows} == {"daily"}
    assert {row["step"] for row in rows} == {1}


def test_replace_with_exact_plan_replaces_points_atomically(store, daily_plan, at_plan):
    task_id = store.create_task(1, 2, "old", daily_plan)
    old_point_ids = {point["id"] for point in store.get_points_for_task(task_id)}

    store.replace_task_with_exact_plan(task_id, "new", at_plan)

    task = store.get_task(task_id)
    assert task["prompt"] == "new"
    assert task["schedule_type"] == "at"
    assert task["processed_occurrences"] == 0
    points = store.get_points_for_task(task_id)
    schedule = sys.modules[f"{BASE_NAME}.timer.schedule"]
    assert [point["exact_at"] for point in points] == schedule.flatten_occurrences(
        at_plan
    )
    assert all(store.get_point(point_id) is None for point_id in old_point_ids)


def _capped_daily_plan(schedule):
    full = schedule.build_daily_plan(
        "2026-08-01T00:00:00+08:00",
        "2026-10-31T23:59:59+08:00",
        ["09:00:00", "18:00:00"],
        now=0,
    )
    capped_points = tuple(
        replace(
            point,
            last_fire_at=point.first_fire_at + 24 * 86400,
            planned_count=25,
        )
        for point in full.points
    )
    return replace(
        full,
        effective_until=max(point.last_fire_at for point in capped_points),
        total_occurrences=50,
        truncated=True,
        points=capped_points,
    )


def test_expand_truncated_frequency_tasks_preserves_ids_and_progress(
    store, modules
):
    schedule, _ = modules
    task_id = store.create_task(1, 2, "uncap", _capped_daily_plan(schedule))
    before_points = store.get_points_for_task(task_id)
    store.mark_occurrence_processed(
        before_points[0]["id"], before_points[0]["first_fire_at"]
    )

    assert store.expand_truncated_frequency_tasks() == 1

    task = store.get_task(task_id)
    points = store.get_points_for_task(task_id)
    assert task["total_occurrences"] == 184
    assert task["processed_occurrences"] == 1
    assert task["truncated"] == 0
    assert [point["id"] for point in points] == [
        point["id"] for point in before_points
    ]
    assert [point["processed_occurrences"] for point in points] == [1, 0]
    assert [point["first_fire_at"] for point in points] == [
        point["first_fire_at"] for point in before_points
    ]
    assert [point["planned_occurrences"] for point in points] == [92, 92]
    assert store.expand_truncated_frequency_tasks() == 0


def test_expand_truncated_frequency_tasks_rolls_back_on_first_fire_mismatch(
    store, modules
):
    schedule, _ = modules
    task_id = store.create_task(1, 2, "uncap", _capped_daily_plan(schedule))
    point = store.get_points_for_task(task_id)[1]
    store._connection().execute(
        "UPDATE timer_schedule_points SET first_fire_at = first_fire_at + 1 "
        "WHERE id = ?",
        (point["id"],),
    )
    store._connection().commit()

    with pytest.raises(RuntimeError, match="first occurrence"):
        store.expand_truncated_frequency_tasks()

    task = store.get_task(task_id)
    assert task["total_occurrences"] == 50
    assert task["truncated"] == 1
    assert [
        point["planned_occurrences"]
        for point in store.get_points_for_task(task_id)
    ] == [25, 25]


def test_transaction_rolls_back_all_uncommitted_inserts(store, daily_plan):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.create_task(1, 2, "first", daily_plan, commit=False)
            store.create_task(1, 3, "second", daily_plan, commit=False)
            raise RuntimeError("abort")

    assert store.list_tasks_by_group(1) == []


def test_delete_finished_tasks_excludes_active_and_auto_response(store, at_plan):
    finished_id = store.create_task(1, 2, "finished", at_plan)
    active_id = store.create_task(1, 3, "active", at_plan)
    internal_id = store.create_task(
        0, 0, "internal", at_plan, task_type="auto_response"
    )
    for task_id in (finished_id, internal_id):
        for point in store.get_points_for_task(task_id):
            store.mark_occurrence_processed(point["id"], point["exact_at"])

    assert store.delete_finished_tasks() == [finished_id]
    assert store.get_task(finished_id) is None
    assert store.get_task(active_id) is not None
    assert store.get_task(internal_id) is not None


def test_upsert_auto_response_keeps_one_internal_task(store):
    first_id = store.upsert_auto_response(
        datetime.fromisoformat(f"2026-08-01T09:00:00{SHANGHAI_OFFSET}").timestamp()
    )
    second_id = store.upsert_auto_response(
        datetime.fromisoformat(f"2026-08-01T10:00:00{SHANGHAI_OFFSET}").timestamp(),
        prompt="custom",
    )

    assert second_id != first_id
    assert store.get_task(first_id) is None
    point = store.get_auto_response_point()
    assert point["task_id"] == second_id
    assert point["prompt"] == "custom"


def test_migration_marker_is_idempotent(store):
    assert store.has_migration("legacy_timer_v1") is False
    store.record_migration("legacy_timer_v1")
    store.record_migration("legacy_timer_v1")
    assert store.has_migration("legacy_timer_v1") is True


def test_validate_prompt_contract(store):
    assert store.validate_prompt("") is not None
    assert store.validate_prompt("   ") is not None
    assert store.validate_prompt("x" * 501) is not None
    assert store.validate_prompt("x" * 500) is None


def test_foreign_keys_are_enabled(store):
    assert store._conn is not None
    assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO timer_schedule_points "
            "(task_id, first_fire_at, last_fire_at, planned_occurrences, job_id) "
            "VALUES (999, 1, 1, 1, 'missing')"
        )
