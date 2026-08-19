"""Focused tests for Hook script execution and scheduling."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
BASE_NAME = "hatsume.plugins.hatsume-plugin"


class FakeJob:
    def __init__(self, job_id, trigger):
        self.id = job_id
        self.trigger = trigger
        self.next_run_time = getattr(trigger, "start_date", None)


class FakeScheduler:
    def __init__(self):
        self.jobs = {}
        self.add_calls = []

    def add_job(self, func, trigger, *, id, args, **kwargs):
        job = FakeJob(id, trigger)
        self.jobs[id] = job
        self.add_calls.append((func, trigger, id, args, kwargs))
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def get_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_modules(tmp_path: Path):
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        (BASE_NAME, PLUGIN_DIR),
        (f"{BASE_NAME}.hooks", PLUGIN_DIR / "hooks"),
        (f"{BASE_NAME}.graph", PLUGIN_DIR / "graph"),
        (f"{BASE_NAME}.utils", PLUGIN_DIR / "utils"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = lambda _name: tmp_path / "hooks.db"
    sys.modules[localstore.__name__] = localstore

    apscheduler = types.ModuleType("apscheduler")
    apscheduler.__path__ = []
    interval = types.ModuleType("apscheduler.triggers.interval")
    interval.IntervalTrigger = type(
        "IntervalTrigger",
        (),
        {
            "__init__": lambda self, **kwargs: self.__dict__.update(kwargs),
        },
    )
    triggers = types.ModuleType("apscheduler.triggers")
    triggers.__path__ = []
    sys.modules["apscheduler"] = apscheduler
    sys.modules["apscheduler.triggers"] = triggers
    sys.modules["apscheduler.triggers.interval"] = interval

    hooks_root = tmp_path / "hooks"
    config = types.ModuleType(f"{BASE_NAME}.config")
    config.HOOKS_DIR = hooks_root
    config.HOOK_MAX_ACTIVE_PER_GROUP = 5
    config.HOOK_MIN_INTERVAL_SECONDS = 300
    config.HOOK_DEFAULT_INTERVAL_SECONDS = 900
    config.HOOK_DEFAULT_TIMEOUT_SECONDS = 15
    config.HOOK_MAX_TIMEOUT_SECONDS = 60
    sys.modules[config.__name__] = config

    security = types.ModuleType(f"{BASE_NAME}.utils.security")
    security.mask_secret_keys = lambda value: str(value).replace("SECRET", "***")
    sys.modules[security.__name__] = security

    registry = types.SimpleNamespace(routed_group_ids=lambda: (100,))
    group_runtime = types.ModuleType(f"{BASE_NAME}.group_runtime")
    group_runtime.group_runtime_registry = registry
    sys.modules[group_runtime.__name__] = group_runtime

    nodes = types.ModuleType(f"{BASE_NAME}.graph.nodes")
    nodes.inject_hook = MagicMock()
    sys.modules[nodes.__name__] = nodes

    scheduler = FakeScheduler()
    plugin = types.ModuleType("nonebot_plugin_apscheduler")
    plugin.scheduler = scheduler
    sys.modules[plugin.__name__] = plugin
    nonebot = types.ModuleType("nonebot")
    nonebot.require = lambda _name: plugin
    sys.modules[nonebot.__name__] = nonebot

    for module_name in (
        f"{BASE_NAME}.hooks.store",
        f"{BASE_NAME}.hooks.executor",
    ):
        sys.modules.pop(module_name, None)
    store = _load_file(
        f"{BASE_NAME}.hooks.store",
        PLUGIN_DIR / "hooks/store.py",
    )
    executor = _load_file(
        f"{BASE_NAME}.hooks.executor",
        PLUGIN_DIR / "hooks/executor.py",
    )
    executor.scheduler = scheduler
    return store, executor, scheduler, hooks_root, registry, nodes


@pytest.fixture
def modules(tmp_path):
    return _load_modules(tmp_path)


def _script(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def _record(store, script: Path, *, last_run_at=None, enabled=True):
    instance = store.HookStore(":memory:")
    instance.init_db()
    record = instance.create_hook(
        group_id=100,
        name="mail",
        script_path=str(script),
        prompt="Handle mail",
        interval_seconds=300,
        timeout_seconds=15,
        created_by=123,
        enabled=enabled,
    )
    if last_run_at is not None:
        instance.record_success(record["id"], 0, last_run_at)
        record = instance.get_hook(record["id"])
    return instance, record


def test_path_validation_is_group_scoped_and_requires_executable(modules, tmp_path):
    _, executor, _, hooks_root, _, _ = modules
    valid = _script(hooks_root / "100/mail.sh", "exit 0")
    assert executor.validate_hook_script_path(valid, 100, hooks_root=hooks_root) == valid.resolve()

    other_group = _script(hooks_root / "200/mail.sh", "exit 0")
    with pytest.raises(ValueError, match="group Hook directory"):
        executor.validate_hook_script_path(other_group, 100, hooks_root=hooks_root)

    outside = _script(tmp_path / "outside.sh", "exit 0")
    link = hooks_root / "100/escape.sh"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="group Hook directory"):
        executor.validate_hook_script_path(link, 100, hooks_root=hooks_root)

    valid.chmod(0o600)
    with pytest.raises(ValueError, match="executable"):
        executor.validate_hook_script_path(valid, 100, hooks_root=hooks_root)

    with pytest.raises(ValueError, match="absolute"):
        executor.validate_hook_script_path("mail.sh", 100, hooks_root=hooks_root)


def test_path_validation_requires_shebang(modules):
    _, executor, _, hooks_root, _, _ = modules
    path = hooks_root / "100/no-shebang"
    path.parent.mkdir(parents=True)
    path.write_text("exit 0\n", encoding="utf-8")
    path.chmod(0o700)
    with pytest.raises(ValueError, match="shebang"):
        executor.validate_hook_script_path(path, 100, hooks_root=hooks_root)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "exit_code", "stdout", "error_fragment"),
    [
        ("exit 0", 0, "", None),
        ("printf 'log'; exit 0", 0, "log", "empty stdout"),
        ("printf 'new mail'; exit 10", 10, "new mail", None),
        ("exit 10", 10, "", "non-empty stdout"),
        ("printf 'bad' >&2; exit 3", 3, "", "exit code 3"),
    ],
)
async def test_exit_code_protocol(modules, tmp_path, body, exit_code, stdout, error_fragment):
    _, executor, _, _, _, _ = modules
    script = _script(tmp_path / "script.sh", body)
    result = await executor.run_hook_script(script, timeout_seconds=1, workdir=tmp_path)
    assert result.exit_code == exit_code
    assert result.stdout == stdout
    if error_fragment is None:
        assert result.error is None
    else:
        assert error_fragment in result.error


@pytest.mark.asyncio
async def test_validation_environment_is_exported(modules, tmp_path):
    _, executor, _, _, _, _ = modules
    script = _script(
        tmp_path / "validation.sh",
        "[ \"$HATSUME_HOOK_VALIDATION\" = 1 ] || exit 4\nexit 0",
    )
    result = await executor.run_hook_script(
        script,
        timeout_seconds=1,
        validation=True,
        workdir=tmp_path,
    )
    assert result.error is None


@pytest.mark.asyncio
async def test_timeout_and_output_limit_are_programmatically_enforced(modules, tmp_path):
    _, executor, _, _, _, _ = modules
    slow = _script(tmp_path / "slow.sh", "sleep 5")
    timed_out = await executor.run_hook_script(slow, timeout_seconds=1, workdir=tmp_path)
    assert "timed out" in timed_out.error

    noisy = _script(tmp_path / "noisy.sh", "head -c 9000 /dev/zero; exit 10")
    oversized = await executor.run_hook_script(noisy, timeout_seconds=1, workdir=tmp_path)
    assert "output limit" in oversized.error


@pytest.mark.asyncio
async def test_execute_hook_injects_exit_10_and_records_success(modules, tmp_path):
    store, executor, _, hooks_root, _, nodes = modules
    script = _script(hooks_root / "100/mail.sh", "printf 'message 42'; exit 10")
    instance, record = _record(store, script)

    assert await executor.execute_hook(record["id"], instance, workdir=tmp_path) is True
    nodes.inject_hook.assert_called_once_with(
        group_id=100,
        hook_name="mail",
        prompt="Handle mail",
        event_text="message 42",
    )
    saved = instance.get_hook(record["id"])
    assert saved["last_exit_code"] == 10
    assert saved["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_execute_hook_is_non_reentrant(modules, tmp_path):
    store, executor, _, hooks_root, _, _ = modules
    script = _script(hooks_root / "100/mail.sh", "sleep 0.2; exit 0")
    instance, record = _record(store, script)

    first = asyncio.create_task(
        executor.execute_hook(record["id"], instance, workdir=tmp_path)
    )
    await asyncio.sleep(0.03)
    second = await executor.execute_hook(record["id"], instance, workdir=tmp_path)
    assert second is False
    assert await first is True


def test_register_and_restore_jobs_are_route_aware(modules, tmp_path):
    store, executor, scheduler, hooks_root, registry, _ = modules
    script = _script(hooks_root / "100/mail.sh", "exit 0")
    instance, record = _record(store, script)

    job = executor.register_hook_job(record, instance, now=1_000.0)
    assert job.id == f"hook_heartbeat_{record['id']}"
    assert job.next_run_time.timestamp() == pytest.approx(1_300.0)
    _, _, _, args, kwargs = scheduler.add_calls[-1]
    assert args == [record["id"]]
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True

    registry.routed_group_ids = lambda: ()
    assert executor.register_hook_job(record, instance, now=1_000.0) is None
    assert scheduler.get_job(job.id) is None


def test_overdue_restore_runs_once_promptly(modules):
    store, executor, scheduler, hooks_root, _, _ = modules
    script = _script(hooks_root / "100/mail.sh", "exit 0")
    instance, record = _record(store, script, last_run_at=100.0)

    executor.restore_hook_jobs(instance, [100], now=1_000.0)
    job = scheduler.get_job(f"hook_heartbeat_{record['id']}")
    assert job.next_run_time.timestamp() == pytest.approx(1_000.0)


@pytest.mark.asyncio
async def test_pause_and_shutdown_cancel_jobs(modules):
    store, executor, scheduler, hooks_root, _, _ = modules
    script = _script(hooks_root / "100/mail.sh", "exit 0")
    instance, record = _record(store, script)
    executor.register_hook_job(record, instance, now=1_000.0)

    executor.pause_hook_jobs_for_groups(instance, [100])
    assert scheduler.get_jobs() == []

    executor.register_hook_job(record, instance, now=1_000.0)
    await executor.shutdown_hook_executor()
    assert scheduler.get_jobs() == []
