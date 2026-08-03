"""Per-group Docker sandbox lifecycle tests."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _load_infra():
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume_plugin", PLUGIN_DIR),
    ):
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            sys.modules[name] = module

    config = types.ModuleType("hatsume.plugins.hatsume_plugin.config")
    config.CONTAINER_NAME_BASE = "hatsume-space"
    config.DOCKER_ENV_PATH = Path("/tmp/hatsume-container-tests")
    config.SHELL_TIMEOUT = 10
    sys.modules[config.__name__] = config

    runtime = types.ModuleType("hatsume.plugins.hatsume_plugin.group_runtime")

    def validate_group_id(group_id: int) -> int:
        if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
            raise ValueError("invalid group")
        return group_id

    runtime.validate_group_id = validate_group_id
    runtime.get_current_group_id = lambda: 101
    sys.modules[runtime.__name__] = runtime

    module_name = "hatsume.plugins.hatsume_plugin.infra"
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_DIR / "infra.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


infra = _load_infra()


@pytest_asyncio.fixture(autouse=True)
async def _clean_state():
    infra._container_states.clear()
    infra._background_procs.clear()
    infra._background_proc_groups.clear()
    infra._background_output_handles.clear()
    yield
    for state in infra._container_states.values():
        if state.stop_task is not None and not state.stop_task.done():
            state.stop_task.cancel()
            await asyncio.gather(state.stop_task, return_exceptions=True)
    infra._container_states.clear()


def test_container_name_requires_positive_integer_group():
    assert infra.container_name_for_group(123) == "hatsume-space-123"
    for invalid in (0, -1, True, "123"):
        with pytest.raises(ValueError):
            infra.container_name_for_group(invalid)


@pytest.mark.asyncio
async def test_refcounts_and_stop_tasks_are_group_isolated():
    first = infra._acquire_subprocess(101)
    second = infra._acquire_subprocess(202)
    infra._acquire_subprocess(101)

    assert first.refcount == 2
    assert second.refcount == 1

    infra._release_subprocess(101)
    assert first.refcount == 1
    assert first.stop_task is None

    infra._release_subprocess(202)
    assert second.refcount == 0
    assert second.stop_task is not None
    second.stop_task.cancel()
    await asyncio.gather(second.stop_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_delayed_stop_targets_only_its_group(monkeypatch):
    first = infra._get_container_state(101, create=True)
    second = infra._get_container_state(202, create=True)
    first.active = True
    second.active = True
    stopped: list[int] = []

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(infra.asyncio, "sleep", no_wait)
    monkeypatch.setattr(infra, "stop_container", stopped.append)
    await infra._delayed_stop_container(first)

    assert stopped == [101]
    assert first.active is False
    assert second.active is True


class _AsyncProcess:
    def __init__(self, stdout: bytes = b"ok", stderr: bytes = b""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0
        self.inputs: list[bytes | None] = []
        self.killed = False

    async def communicate(self, input=None):
        self.inputs.append(input)
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True


class _BlockingProcess:
    def __init__(self, *, termination_output=(b"partial stdout", b"partial stderr")):
        self.returncode = None
        self.inputs: list[bytes | None] = []
        self.killed = False
        self.communicate_calls = 0
        self.started = asyncio.Event()
        self.termination_started = asyncio.Event()
        self.allow_termination = asyncio.Event()
        self.termination_output = termination_output

    async def communicate(self, input=None):
        self.communicate_calls += 1
        self.inputs.append(input)
        if self.communicate_calls == 1:
            self.started.set()
            await asyncio.Event().wait()
        self.termination_started.set()
        await self.allow_termination.wait()
        return self.termination_output

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.mark.asyncio
async def test_same_group_startup_coalesces_and_other_group_starts_independently(monkeypatch):
    processes = [_AsyncProcess(), _AsyncProcess()]
    create = AsyncMock(side_effect=processes)
    monkeypatch.setattr(infra.asyncio, "create_subprocess_exec", create)

    await asyncio.gather(
        infra.ensure_container_running(101),
        infra.ensure_container_running(101),
        infra.ensure_container_running(202),
    )

    assert create.await_count == 2
    names = {call.args[2] for call in create.await_args_list}
    assert names == {"hatsume-space-101", "hatsume-space-202"}
    assert all(process.inputs == [b"echo ready\n"] for process in processes)


@pytest.mark.asyncio
async def test_run_cmd_uses_group_container_and_invocation_local_stdin(monkeypatch):
    state = infra._get_container_state(101, create=True)
    state.active = True
    process = _AsyncProcess(stdout=b"hello\n")
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(infra.asyncio, "create_subprocess_exec", create)

    result = await infra.run_cmd("echo hello", group_id=101)

    assert result == "hello\n"
    assert create.await_args.args[2] == "hatsume-space-101"
    assert process.inputs == [b"source ~/.bashrc\necho hello\n"]
    assert not (Path(infra.DOCKER_ENV_PATH) / "script.sh").exists()
    assert state.refcount == 0
    assert state.stop_task is not None


@pytest.mark.asyncio
async def test_read_sandbox_image_data_uri_validates_bytes_in_target_group(
    monkeypatch,
):
    encoded = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    run_cmd = AsyncMock(return_value=f"{encoded}::EXIT::0\n")
    monkeypatch.setattr(infra, "run_cmd", run_cmd)

    result = await infra.read_sandbox_image_data_uri(
        "/work/reference image.wrong-extension",
        group_id=202,
    )

    assert result == f"data:image/png;base64,{encoded}"
    assert base64.b64decode(result.split(",", 1)[1]) == base64.b64decode(encoded)
    run_cmd.assert_awaited_once_with(
        "base64 -w 0 -- '/work/reference image.wrong-extension' "
        "2>&1; echo '::EXIT::'$?",
        timeout=30,
        group_id=202,
    )


@pytest.mark.asyncio
async def test_read_sandbox_image_data_uri_rejects_non_image_bytes(monkeypatch):
    encoded = base64.b64encode(b"not an image").decode("ascii")
    monkeypatch.setattr(
        infra,
        "run_cmd",
        AsyncMock(return_value=f"{encoded}::EXIT::0\n"),
    )

    with pytest.raises(ValueError, match="not a valid image"):
        await infra.read_sandbox_image_data_uri("/work/not-image.jpg", group_id=101)


@pytest.mark.asyncio
async def test_cancelling_run_cmd_kills_awaits_and_untracks_process(monkeypatch):
    state = infra._get_container_state(101, create=True)
    state.active = True
    process = _BlockingProcess()
    monkeypatch.setattr(
        infra.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )

    command_task = asyncio.create_task(infra.run_cmd("long command", group_id=101))
    await process.started.wait()
    assert process in state.foreground_processes

    command_task.cancel()
    await process.termination_started.wait()
    assert not command_task.done()
    process.allow_termination.set()
    with pytest.raises(asyncio.CancelledError):
        await command_task

    assert process.killed
    assert process.communicate_calls == 2
    assert process not in state.foreground_processes
    assert process not in state.foreground_tasks
    assert state.refcount == 0


@pytest.mark.asyncio
async def test_run_cmd_timeout_keeps_output_collected_during_termination(monkeypatch):
    state = infra._get_container_state(101, create=True)
    state.active = True

    class _TimeoutProcess:
        def __init__(self):
            self.returncode = None
            self.calls = 0
            self.killed = False

        async def communicate(self, input=None):
            self.calls += 1
            if self.calls == 1:
                raise asyncio.TimeoutError
            return b"partial stdout", b"partial stderr"

        def kill(self):
            self.killed = True
            self.returncode = -9

    process = _TimeoutProcess()
    monkeypatch.setattr(
        infra.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )

    result = await infra.run_cmd("slow", timeout=0.01, group_id=101)

    assert "partial stdout" in result
    assert "partial stderr" in result
    assert process.killed
    assert process.calls == 2


@pytest.mark.asyncio
async def test_user_image_copy_targets_current_group(monkeypatch):
    process = _AsyncProcess()
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(infra, "_ensure_user_image_sandbox_dir", AsyncMock())
    monkeypatch.setattr(infra.asyncio, "create_subprocess_exec", create)

    result = await infra.save_sandbox_user_image(
        b"image",
        9,
        1,
        "png",
        group_id=101,
    )

    assert result == "/tmp/hatsume-user-images/9-1.png"
    assert create.await_args.args[3] == (
        "hatsume-space-101:/tmp/hatsume-user-images/9-1.png"
    )
    assert not Path(create.await_args.args[2]).exists()


@pytest.mark.asyncio
async def test_reset_missing_group_does_not_create_state(monkeypatch):
    monkeypatch.setattr(infra, "_container_exists", lambda _group_id: False)

    assert await infra.cleanup_persistent_container(404) is False
    assert 404 not in infra._container_states


@pytest.mark.asyncio
async def test_reset_removes_only_selected_group(monkeypatch):
    first = infra._get_container_state(101, create=True)
    second = infra._get_container_state(202, create=True)
    first.active = True
    second.active = True
    deleted: list[int] = []
    monkeypatch.setattr(infra, "delete_container", deleted.append)

    assert await infra.cleanup_persistent_container(101) is True

    assert deleted == [101]
    assert 101 not in infra._container_states
    assert infra._container_states[202] is second
    assert second.active is True


@pytest.mark.asyncio
async def test_reset_waits_for_foreground_owner_before_deleting(monkeypatch):
    state = infra._get_container_state(101, create=True)
    state.active = True
    process = _BlockingProcess()
    deleted: list[int] = []
    monkeypatch.setattr(
        infra.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    monkeypatch.setattr(infra, "delete_container", deleted.append)

    command_task = asyncio.create_task(infra.run_cmd("long command", group_id=101))
    await process.started.wait()
    reset_task = asyncio.create_task(infra.cleanup_persistent_container(101))

    await process.termination_started.wait()
    assert process.killed
    assert deleted == []
    assert not reset_task.done()

    process.allow_termination.set()
    assert await reset_task is True
    assert deleted == [101]
    assert command_task.cancelled()
    assert state.foreground_processes == set()
    assert state.foreground_tasks == {}
    assert state.refcount == 0
