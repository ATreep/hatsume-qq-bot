#!/usr/bin/env python3
"""Migrate unfinished legacy Timer tasks into the Timer v2 database."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
TIMER_DIR = PLUGIN_DIR / "timer"
DEFAULT_SOURCE = ROOT / "data/hatsume-plugin/timer_db/timer.db"
DEFAULT_DESTINATION = ROOT / "data/timer-v2-db/timer.db"
_RUNTIME_PACKAGE = "_hatsume_timer_v2_migration"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate unfinished Timer v1 tasks to Timer v2."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    return parser.parse_args(argv)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _install_package(name: str, path: Path) -> None:
    package = ModuleType(name)
    package.__path__ = [str(path)]
    package.__package__ = name
    sys.modules[name] = package


def _load_components() -> tuple[type[Any], Callable[..., Any]]:
    for name in tuple(sys.modules):
        if name == _RUNTIME_PACKAGE or name.startswith(f"{_RUNTIME_PACKAGE}."):
            sys.modules.pop(name, None)

    timer_package = f"{_RUNTIME_PACKAGE}.timer"
    _install_package(_RUNTIME_PACKAGE, PLUGIN_DIR)
    _load_module(f"{_RUNTIME_PACKAGE}.config", PLUGIN_DIR / "config.py")
    _install_package(timer_package, TIMER_DIR)
    _load_module(f"{timer_package}.schedule", TIMER_DIR / "schedule.py")
    store = _load_module(f"{timer_package}.store", TIMER_DIR / "store.py")
    migration = _load_module(
        f"{timer_package}.migration", TIMER_DIR / "migration.py"
    )
    return store.TimerStore, migration.migrate_legacy_timer_db


def _run_migration(source: Path, destination: Path) -> tuple[Any, int]:
    store_type, migrate = _load_components()
    store = store_type(str(destination))
    try:
        with redirect_stdout(StringIO()):
            store.init_db()
            result = migrate(store, source)
            expanded = store.expand_truncated_frequency_tasks()
            return result, expanded
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.source.is_file():
        print(f"Timer migration source not found: {args.source}", file=sys.stderr)
        return 2

    try:
        result, expanded = _run_migration(args.source, args.destination)
    except Exception as exc:
        print(
            f"Timer migration failed ({type(exc).__name__}; "
            f"source: {args.source}; destination: {args.destination})",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "already_applied": result.already_applied,
                "expanded_frequency_tasks": expanded,
                "migrated_tasks": result.migrated_tasks,
                "skipped_tasks": result.skipped_tasks,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
