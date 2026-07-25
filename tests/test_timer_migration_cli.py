"""Tests for the explicit Timer v1-to-v2 migration command."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/migrate_timer_v2.py"


def _load_cli():
    name = "hatsume_test_timer_migration_cli"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli():
    return _load_cli()


def test_defaults_point_to_runtime_legacy_and_v2_databases(cli):
    args = cli._parse_args([])

    assert args.source == ROOT / "data/hatsume-plugin/timer_db/timer.db"
    assert args.destination == ROOT / "data/timer-v2-db/timer.db"


def test_explicit_paths_migrate_once_close_and_emit_json(
    cli, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "legacy.db"
    source.touch()
    destination = tmp_path / "custom-v2.db"
    stores = []

    class Store:
        def __init__(self, db_path):
            self.db_path = db_path
            self.initialized = False
            self.closed = False
            stores.append(self)

        def init_db(self):
            self.initialized = True

        def close(self):
            self.closed = True

        def expand_truncated_frequency_tasks(self):
            return 4

    def migrate(store, legacy_path):
        assert store is stores[0]
        assert legacy_path == source
        return types.SimpleNamespace(
            migrated_tasks=3,
            skipped_tasks=2,
            already_applied=False,
        )

    monkeypatch.setattr(cli, "_load_components", lambda: (Store, migrate))

    code = cli.main(
        ["--source", str(source), "--destination", str(destination)]
    )

    assert code == 0
    assert stores[0].db_path == str(destination)
    assert stores[0].initialized is True
    assert stores[0].closed is True
    assert json.loads(capsys.readouterr().out) == {
        "already_applied": False,
        "expanded_frequency_tasks": 4,
        "migrated_tasks": 3,
        "skipped_tasks": 2,
    }


def test_missing_source_fails_without_loading_or_creating_destination(
    cli, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "missing.db"
    destination = tmp_path / "v2/timer.db"
    monkeypatch.setattr(
        cli,
        "_load_components",
        lambda: pytest.fail("components loaded for missing source"),
    )

    code = cli.main(
        ["--source", str(source), "--destination", str(destination)]
    )

    assert code == 2
    assert not destination.exists()
    output = capsys.readouterr()
    assert output.out == ""
    assert str(source) in output.err


def test_migration_failure_closes_destination_and_redacts_prompt(
    cli, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "legacy.db"
    source.touch()
    destination = tmp_path / "v2.db"
    stores = []

    class Store:
        def __init__(self, db_path):
            self.db_path = db_path
            self.closed = False
            stores.append(self)

        def init_db(self):
            pass

        def close(self):
            self.closed = True

    def failing_migrate(store, legacy_path):
        raise RuntimeError("migration failed for private task prompt")

    monkeypatch.setattr(
        cli,
        "_load_components",
        lambda: (Store, failing_migrate),
    )

    code = cli.main(
        ["--source", str(source), "--destination", str(destination)]
    )

    assert code == 1
    assert stores[0].closed is True
    output = capsys.readouterr()
    assert output.out == ""
    assert "RuntimeError" in output.err
    assert str(source) in output.err
    assert str(destination) in output.err
    assert "private task prompt" not in output.err


def test_frequency_expansion_failure_closes_destination_and_redacts_prompt(
    cli, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "legacy.db"
    source.touch()
    destination = tmp_path / "v2.db"
    stores = []

    class Store:
        def __init__(self, db_path):
            self.db_path = db_path
            self.closed = False
            stores.append(self)

        def init_db(self):
            pass

        def close(self):
            self.closed = True

        def expand_truncated_frequency_tasks(self):
            raise RuntimeError("expansion failed for private task prompt")

    def migrate(store, legacy_path):
        return types.SimpleNamespace(
            migrated_tasks=0,
            skipped_tasks=0,
            already_applied=True,
        )

    monkeypatch.setattr(cli, "_load_components", lambda: (Store, migrate))

    code = cli.main(
        ["--source", str(source), "--destination", str(destination)]
    )

    assert code == 1
    assert stores[0].closed is True
    output = capsys.readouterr()
    assert output.out == ""
    assert "RuntimeError" in output.err
    assert "private task prompt" not in output.err


def _create_wal_legacy_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE timer_tasks (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            task_type TEXT NOT NULL
        );
        CREATE TABLE timer_triggers (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            trigger_at REAL NOT NULL,
            fired INTEGER NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO timer_tasks (id, group_id, user_id, prompt, task_type) "
        "VALUES (7, 100, 200, '手动迁移测试', 'normal')"
    )
    connection.execute(
        "INSERT INTO timer_triggers (task_id, trigger_at, fired) VALUES (?, ?, 0)",
        (7, time.time() + 86400),
    )
    connection.commit()
    return connection


def test_real_command_is_idempotent_and_preserves_source_sidecars(
    cli, tmp_path, capsys
):
    source = tmp_path / "legacy.db"
    destination = tmp_path / "v2/timer.db"
    writer = _create_wal_legacy_db(source)
    source_files = [source, Path(f"{source}-wal"), Path(f"{source}-shm")]
    try:
        before = {path: path.read_bytes() for path in source_files}

        first_code = cli.main(
            ["--source", str(source), "--destination", str(destination)]
        )
        first = json.loads(capsys.readouterr().out)
        second_code = cli.main(
            ["--source", str(source), "--destination", str(destination)]
        )
        second = json.loads(capsys.readouterr().out)

        assert first_code == 0
        assert first == {
            "already_applied": False,
            "expanded_frequency_tasks": 0,
            "migrated_tasks": 1,
            "skipped_tasks": 0,
        }
        assert second_code == 0
        assert second == {
            "already_applied": True,
            "expanded_frequency_tasks": 0,
            "migrated_tasks": 0,
            "skipped_tasks": 0,
        }
        assert {path: path.read_bytes() for path in source_files} == before
    finally:
        writer.close()
