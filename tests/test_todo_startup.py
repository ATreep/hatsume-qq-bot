"""Tests for TodoStore singleton initialization and retry behavior."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
TEST_PACKAGE = "_hatsume_todo_startup_test"


def _load_todo_package(store_type):
    package = types.ModuleType(TEST_PACKAGE)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[TEST_PACKAGE] = package

    store_module = types.ModuleType(f"{TEST_PACKAGE}.todo.store")
    store_module.TodoCreateResult = type("TodoCreateResult", (), {})
    store_module.TodoItem = dict
    store_module.TodoStore = store_type
    store_module.TodoValidationError = type("TodoValidationError", (ValueError,), {})
    sys.modules[store_module.__name__] = store_module

    name = f"{TEST_PACKAGE}.todo"
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN_DIR / "todo/__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR / "todo")],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_singleton_closes_failed_candidate_and_retries():
    instances = []

    class FakeStore:
        def __init__(self):
            self.closed = False
            instances.append(self)

        def init_db(self):
            if len(instances) == 1:
                raise RuntimeError("database unavailable")

        def close(self):
            self.closed = True

    todo = _load_todo_package(FakeStore)

    with pytest.raises(RuntimeError, match="database unavailable"):
        todo.get_store()
    assert instances[0].closed is True
    assert todo._store is None

    recovered = todo.get_store()
    assert recovered is instances[1]
    assert todo.get_store() is recovered
    assert len(instances) == 2
