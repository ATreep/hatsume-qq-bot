"""Tests for TimerStore: SQLite CRUD operations for timer tasks and triggers."""

from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


# ---------------------------------------------------------------------------
# Module loading helpers (follows existing test patterns)
# ---------------------------------------------------------------------------
def _ensure_package_hierarchy():
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


def _load_module(short_name: str, **stub_attrs):
    """Load a plugin module using importlib."""
    full_name = f"hatsume.plugins.hatsume-plugin.{short_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PLUGIN_DIR / f"{short_name}.py"
    )
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    for k, v in stub_attrs.items():
        setattr(mod, k, v)
    spec.loader.exec_module(mod)
    return mod


def _load_submodule(package_short: str, module_name: str, **stub_attrs):
    """Load a submodule under a package directory."""
    full_name = f"hatsume.plugins.hatsume-plugin.{module_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PLUGIN_DIR / package_short / f"{module_name.split('.')[-1]}.py"
    )
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    for k, v in stub_attrs.items():
        setattr(mod, k, v)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
_ensure_package_hierarchy()

# Load config (required by timer/store.py)
_cfg = _load_module("config")

# Load timer subpackage
_timer_init = _load_submodule("timer", "timer.__init__")
# Load store module — make it available as timer.store
_timer_store = _load_submodule("timer", "timer.store")
sys.modules["hatsume.plugins.hatsume-plugin.timer.store"] = _timer_store
import importlib
TimerStore = importlib.import_module(
    "hatsume.plugins.hatsume-plugin.timer.store"
).TimerStore


@pytest.fixture
def store():
    """Create a TimerStore backed by a temporary in-memory database."""
    # Ensure prompts module has auto_response functions (other tests may leave stale stubs)
    prompts_name = "hatsume.plugins.hatsume-plugin.prompts"
    if prompts_name not in sys.modules:
        _ensure_package_hierarchy()
        mod = types.ModuleType(prompts_name)
        sys.modules[prompts_name] = mod
    if not hasattr(sys.modules[prompts_name], "get_auto_response_prompt"):
        sys.modules[prompts_name].get_auto_response_prompt = lambda: "auto response prompt"
    s = TimerStore()
    s._db_path = ":memory:"
    s.init_db()
    return s


class TestInitDb:
    """T003: TimerStore init_db() creates schema."""

    def test_creates_tables(self, store):
        """init_db() creates timer_tasks and timer_triggers tables."""
        cur = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] for row in cur.fetchall()]
        assert "timer_tasks" in tables
        assert "timer_triggers" in tables

    def test_tasks_schema_columns(self, store):
        """timer_tasks has expected columns."""
        cur = store._conn.execute("PRAGMA table_info('timer_tasks')")
        columns = {row["name"]: row["type"] for row in cur.fetchall()}
        assert columns["id"] == "INTEGER"
        assert columns["group_id"] == "INTEGER"
        assert columns["user_id"] == "INTEGER"
        assert columns["prompt"] == "TEXT"
        assert columns["created_at"] == "REAL"
        assert columns["updated_at"] == "REAL"
        assert columns["task_type"] == "TEXT"

    def test_triggers_schema_columns(self, store):
        """timer_triggers has expected columns."""
        cur = store._conn.execute("PRAGMA table_info('timer_triggers')")
        columns = {row["name"]: row["type"] for row in cur.fetchall()}
        assert columns["id"] == "INTEGER"
        assert columns["task_id"] == "INTEGER"
        assert columns["trigger_at"] == "REAL"
        assert columns["fired"] == "INTEGER"
        assert columns["job_id"] == "TEXT"

    def test_cascade_delete_foreign_key(self, store):
        """Deleting a task cascades to its triggers."""
        now = time.time()
        task_id = store.create_task(
            group_id=123, user_id=456, prompt="test",
            trigger_times=[now + 3600, now + 7200],
        )
        store.delete_task(task_id)
        cur = store._conn.execute(
            "SELECT COUNT(*) as cnt FROM timer_triggers WHERE task_id = ?",
            (task_id,),
        )
        assert cur.fetchone()["cnt"] == 0

    def test_pending_index_exists(self, store):
        """Partial index on pending triggers exists."""
        cur = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_triggers_pending'"
        )
        assert cur.fetchone() is not None


class TestCreateTask:
    """T004: create_task with trigger expansion."""

    def test_create_single_trigger(self, store):
        """Create a task with one trigger time."""
        now = time.time()
        trigger = now + 3600
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="提醒开会", trigger_times=[trigger]
        )
        assert task_id == 1

        task = store.get_task(task_id)
        assert task is not None
        assert task["group_id"] == 100
        assert task["user_id"] == 200
        assert task["prompt"] == "提醒开会"

        triggers = store.get_triggers_for_task(task_id)
        assert len(triggers) == 1
        assert triggers[0]["trigger_at"] == trigger
        assert triggers[0]["fired"] == 0
        assert triggers[0]["job_id"] == f"timer_{triggers[0]['id']}"

    def test_create_multiple_triggers(self, store):
        """Create a task with multiple trigger times."""
        now = time.time()
        times = [now + 3600, now + 7200, now + 10800]
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="每天提醒", trigger_times=times
        )
        triggers = store.get_triggers_for_task(task_id)
        assert len(triggers) == 3
        for i, t in enumerate(triggers):
            assert t["trigger_at"] == times[i]
            assert t["fired"] == 0

    def test_create_task_deduplicates_trigger_times(self, store):
        """Duplicate trigger_times are deduplicated."""
        now = time.time()
        dup = now + 3600
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="test",
            trigger_times=[dup, dup, now + 7200],
        )
        triggers = store.get_triggers_for_task(task_id)
        assert len(triggers) == 2


class TestListTasks:
    """T004: list_tasks_by_group."""

    def test_list_tasks_by_group(self, store):
        """list_tasks_by_group returns only tasks for that group."""
        now = time.time()
        store.create_task(
            group_id=111, user_id=1, prompt="task A", trigger_times=[now + 3600],
        )
        store.create_task(
            group_id=111, user_id=2, prompt="task B", trigger_times=[now + 7200],
        )
        store.create_task(
            group_id=222, user_id=3, prompt="task C", trigger_times=[now + 3600],
        )

        tasks_111 = store.list_tasks_by_group(111)
        assert len(tasks_111) == 2
        prompts = {t["prompt"] for t in tasks_111}
        assert prompts == {"task A", "task B"}

        tasks_222 = store.list_tasks_by_group(222)
        assert len(tasks_222) == 1
        assert tasks_222[0]["prompt"] == "task C"

    def test_list_empty_group(self, store):
        """Empty group returns empty list."""
        assert store.list_tasks_by_group(999) == []


class TestDeleteTask:
    """T004: delete_task with cascade."""

    def test_delete_task_removes_triggers(self, store):
        """delete_task also removes all associated triggers."""
        now = time.time()
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="test",
            trigger_times=[now + 3600, now + 7200],
        )
        assert len(store.get_triggers_for_task(task_id)) == 2

        store.delete_task(task_id)
        assert store.get_task(task_id) is None
        assert store.get_triggers_for_task(task_id) == []

    def test_delete_nonexistent_task(self, store):
        """Deleting nonexistent task does not raise."""
        store.delete_task(999)


class TestUpdateTask:
    """T004: update_task."""

    def test_update_task_prompt(self, store):
        """Update task prompt and updated_at timestamp."""
        now = time.time()
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="old prompt",
            trigger_times=[now + 3600],
        )
        old_updated = store.get_task(task_id)["updated_at"]

        time.sleep(0.01)
        store.update_task(
            task_id, prompt="new prompt", trigger_times=[now + 7200],
        )

        task = store.get_task(task_id)
        assert task["prompt"] == "new prompt"
        assert task["updated_at"] > old_updated

    def test_update_task_triggers(self, store):
        """update_task replaces all triggers."""
        now = time.time()
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="test",
            trigger_times=[now + 3600],
        )
        assert len(store.get_triggers_for_task(task_id)) == 1

        store.update_task(
            task_id, prompt="test updated",
            trigger_times=[now + 7200, now + 10800],
        )
        triggers = store.get_triggers_for_task(task_id)
        assert len(triggers) == 2
        assert triggers[0]["trigger_at"] == now + 7200
        assert triggers[1]["trigger_at"] == now + 10800


class TestMarkTriggerFired:
    """T004: mark_trigger_fired."""

    def test_mark_trigger_fired(self, store):
        """mark_trigger_fired sets fired=1."""
        now = time.time()
        task_id = store.create_task(
            group_id=100, user_id=200, prompt="test",
            trigger_times=[now + 3600],
        )
        triggers = store.get_triggers_for_task(task_id)
        trigger_id = triggers[0]["id"]
        assert triggers[0]["fired"] == 0

        store.mark_trigger_fired(trigger_id)
        triggers = store.get_triggers_for_task(task_id)
        assert triggers[0]["fired"] == 1


class TestValidateTriggerTimes:
    """T005: Validation methods."""

    def test_rejects_past_times(self, store):
        """validate_trigger_times rejects times in the past."""
        now = time.time()
        errors = store.validate_trigger_times([now - 3600], now)
        assert len(errors) > 0
        assert any("过期" in e or "past" in e.lower() for e in errors)

    def test_rejects_beyond_30_days(self, store):
        """validate_trigger_times rejects times beyond 30 days."""
        now = time.time()
        far_future = now + 31 * 24 * 3600
        errors = store.validate_trigger_times([far_future], now)
        assert len(errors) > 0

    def test_accepts_times_through_30_day_boundary(self, store):
        """validate_trigger_times accepts times through exactly 30 days."""
        now = time.time()
        errors = store.validate_trigger_times(
            [now + 3600, now + 30 * 24 * 3600], now,
        )
        assert len(errors) == 0

    def test_does_not_enforce_create_timer_frequency_limit(self, store):
        """The 10-per-24-hours limit belongs only to create_timer."""
        now = time.time()
        trigger_times = [now + (index + 1) * 3600 for index in range(11)]

        errors = store.validate_trigger_times(trigger_times, now)

        assert errors == []


class TestValidatePrompt:
    """T005: prompt validation."""

    def test_rejects_empty_prompt(self, store):
        """validate_prompt rejects empty strings."""
        err = store.validate_prompt("")
        assert err is not None

    def test_rejects_whitespace_only_prompt(self, store):
        """validate_prompt rejects whitespace-only strings."""
        err = store.validate_prompt("   ")
        assert err is not None

    def test_rejects_overlong_prompt(self, store):
        """validate_prompt rejects prompts over 500 characters."""
        err = store.validate_prompt("x" * 501)
        assert err is not None

    def test_accepts_valid_prompt(self, store):
        """validate_prompt accepts valid prompts."""
        err = store.validate_prompt("提醒开会")
        assert err is None

    def test_accepts_exact_max_length(self, store):
        """validate_prompt accepts prompts at exactly 500 chars."""
        err = store.validate_prompt("x" * 500)
        assert err is None


class TestLegacyAutoCreateCleanup:
    """Legacy auto_create rows are removed during DB initialization."""

    def test_init_db_removes_legacy_auto_create_tasks(self, tmp_path):
        db_path = tmp_path / "timer.db"
        s = TimerStore(str(db_path))
        s.init_db()
        assert s._conn is not None
        s._conn.execute(
            "INSERT INTO timer_tasks "
            "(group_id, user_id, prompt, created_at, updated_at, task_type) "
            "VALUES (0, 0, 'legacy', ?, ?, 'auto_create')",
            (time.time(), time.time()),
        )
        s._conn.commit()
        s._conn.close()

        reopened = TimerStore(str(db_path))
        reopened.init_db()
        assert reopened._conn is not None
        cur = reopened._conn.execute(
            "SELECT COUNT(*) as cnt FROM timer_tasks WHERE task_type = 'auto_create'"
        )
        assert cur.fetchone()["cnt"] == 0
