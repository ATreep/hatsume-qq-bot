"""Tests for auto-response timer scheduling and execution."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


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


_ensure_package_hierarchy()

# Stub utils.py before executor tries to import it
_utils_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
_utils_mod.get_group_member_name = lambda bot, group_id, user_id: f"user_{user_id}"
sys.modules["hatsume.plugins.hatsume-plugin.utils"] = _utils_mod

# Stub nonebot before loading executor (which imports get_bot, require at module level)
_nonebot_mod = types.ModuleType("nonebot")
_nonebot_mod.get_bot = lambda: None
_nonebot_mod.get_driver = lambda: None
_nonebot_mod.require = lambda name: sys.modules.get(name, types.ModuleType(name))
sys.modules["nonebot"] = _nonebot_mod

# Stub nonebot_plugin_apscheduler (imported by executor with require())
_apscheduler_mod = types.ModuleType("nonebot_plugin_apscheduler")
_apscheduler_mod.scheduler = type("Scheduler", (), {"add_job": lambda *a, **kw: None, "remove_job": lambda *a, **kw: None})()
sys.modules["nonebot_plugin_apscheduler"] = _apscheduler_mod

# Stub apscheduler.triggers.date (imported by executor)
_date_trigger_mod = types.ModuleType("apscheduler.triggers.date")
_date_trigger_mod.DateTrigger = type("DateTrigger", (), {})
_apscheduler_mod_pkg = types.ModuleType("apscheduler")
_apscheduler_mod_pkg.triggers = types.ModuleType("apscheduler.triggers")
_apscheduler_mod_pkg.triggers.date = _date_trigger_mod
sys.modules["apscheduler"] = _apscheduler_mod_pkg
sys.modules["apscheduler.triggers"] = _apscheduler_mod_pkg.triggers
sys.modules["apscheduler.triggers.date"] = _date_trigger_mod

_cfg = _load_module("config")
_timer_init = _load_submodule("timer", "timer.__init__")
_timer_store = _load_submodule("timer", "timer.store")
sys.modules["hatsume.plugins.hatsume-plugin.timer.store"] = _timer_store
_timer_executor = _load_submodule("timer", "timer.executor")

_random_response_trigger = _timer_executor._random_response_trigger


class TestRandomResponseTrigger:
    """Auto-response random trigger time generation."""

    def test_returns_within_valid_horizon(self):
        """_random_response_trigger returns a timestamp between 1h and 3h ahead."""
        now = datetime.now(timezone(timedelta(hours=8)))
        result_ts = _random_response_trigger()
        result_dt = datetime.fromtimestamp(result_ts, tz=timezone(timedelta(hours=8)))

        delta = result_dt - now
        assert timedelta(hours=1) <= delta <= timedelta(hours=3)

    def test_time_in_range(self):
        """Repeated trigger generation preserves the 1h-3h contract."""
        now = datetime.now(timezone(timedelta(hours=8)))
        result_ts = _random_response_trigger()
        result_dt = datetime.fromtimestamp(result_ts, tz=timezone(timedelta(hours=8)))
        assert timedelta(hours=1) <= result_dt - now <= timedelta(hours=3)


class TestAutoResponseTargetValidation:
    """Auto-response never injects or reschedules with group ID zero."""

    def test_auto_response_execution_uses_configured_target(self, monkeypatch):
        inject_timer = MagicMock()
        nodes_name = "hatsume.plugins.hatsume-plugin.graph.nodes"
        nodes = types.ModuleType(nodes_name)
        nodes.inject_timer = inject_timer
        reschedule = MagicMock()
        monkeypatch.setitem(sys.modules, nodes_name, nodes)
        monkeypatch.setattr(_timer_executor, "AUTO_RESPONSE_GROUP_ID", 123456)
        monkeypatch.setattr(_timer_executor, "reschedule_auto_response", reschedule)

        asyncio.run(
            _timer_executor._execute_auto_response(
                {"prompt": "participate in chat"}, MagicMock()
            )
        )

        inject_timer.assert_called_once_with(
            user_id=0,
            group_id=123456,
            timer_prompt="participate in chat",
            start_conversation_cb=_timer_executor._timer_start_conv_cb,
        )
        reschedule.assert_called_once()

    def test_auto_response_execution_skips_unconfigured_target(self, monkeypatch):
        reschedule = MagicMock()
        monkeypatch.setattr(_timer_executor, "AUTO_RESPONSE_GROUP_ID", 0)
        monkeypatch.setattr(_timer_executor, "reschedule_auto_response", reschedule)

        asyncio.run(
            _timer_executor._execute_auto_response(
                {"prompt": "participate in chat"}, MagicMock()
            )
        )

        reschedule.assert_not_called()

    def test_refresh_removes_pending_auto_response_when_disabled(self, monkeypatch):
        conn = MagicMock()
        store = types.SimpleNamespace(
            _conn=conn,
            list_auto_response_triggers=MagicMock(return_value=[{"id": 17}]),
        )
        cancel_job = MagicMock()
        monkeypatch.setattr(_timer_executor, "AUTO_RESPONSE_GROUP_ID", 0)
        monkeypatch.setattr(_timer_executor, "cancel_job", cancel_job)

        asyncio.run(_timer_executor.refresh_auto_response(store))

        cancel_job.assert_called_once_with(17)
        conn.execute.assert_called_once_with(
            "DELETE FROM timer_tasks WHERE task_type = 'auto_response'"
        )
        conn.commit.assert_called_once_with()

    def test_legacy_auto_create_task_is_deleted_without_injection(self, monkeypatch):
        store = MagicMock()
        store.get_task.return_value = {"id": 9, "task_type": "auto_create"}
        monkeypatch.setattr(_timer_executor, "_execute_auto_response", MagicMock())

        asyncio.run(_timer_executor._execute_timer({"id": 3, "task_id": 9}, store))

        store.delete_task.assert_called_once_with(9)
        store.mark_trigger_fired.assert_not_called()
