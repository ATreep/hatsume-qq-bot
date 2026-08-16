"""Container-only execution contract for the self-hosted Hatsume copy."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _load_infra():
    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume_plugin", PLUGIN_DIR),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

    config = types.ModuleType("hatsume.plugins.hatsume_plugin.config")
    config.CONTAINER_NAME_BASE = "hatsume-space"
    config.DOCKER_ENV_PATH = PLUGIN_DIR / "virtual"
    config.IMAGE_MAX_PIXELS = 36_000_000
    config.IMAGE_MAX_SIZE_BYTES = 9 * 1024 * 1024
    config.SHELL_TIMEOUT = 10
    sys.modules[config.__name__] = config

    runtime = types.ModuleType("hatsume.plugins.hatsume_plugin.group_runtime")
    runtime.get_current_group_id = lambda: 101
    runtime.validate_group_id = lambda group_id: group_id
    sys.modules[runtime.__name__] = runtime

    module_name = "hatsume.plugins.hatsume_plugin.infra"
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_DIR / "infra.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


infra = _load_infra()


@pytest.fixture(autouse=True)
def _clean_runtime_state():
    infra._container_states.clear()
    infra._background_procs.clear()
    infra._background_proc_groups.clear()
    infra._background_output_handles.clear()
    yield
    for proc, _path in infra._background_procs.values():
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    infra._container_states.clear()
    infra._background_procs.clear()
    infra._background_proc_groups.clear()
    infra._background_output_handles.clear()


def test_local_execution_is_the_only_runtime_mode():
    assert infra.LOCAL_EXECUTION is True
    assert infra.LOCAL_WORKSPACE_PATH == Path("/work")
    assert infra.LOCAL_HOME_PATH == Path("/root")


@pytest.mark.asyncio
async def test_run_cmd_executes_in_local_workspace():
    result = await infra.run_cmd("pwd", group_id=101)

    assert result.strip() == "/work"


@pytest.mark.asyncio
async def test_run_cmd_uses_root_home(monkeypatch):
    monkeypatch.setenv("HOME", "/tmp/not-root")

    result = await infra.run_cmd('printf "%s" "$HOME"', group_id=101)

    assert result == "/root"


@pytest.mark.asyncio
async def test_copy_host_file_to_sandbox_is_a_local_copy(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("container local", encoding="utf-8")

    await infra.copy_host_file_to_sandbox(
        source,
        str(destination),
        group_id=101,
    )

    assert destination.read_text(encoding="utf-8") == "container local"


@pytest.mark.asyncio
async def test_cleanup_never_invokes_docker(monkeypatch):
    state = infra._get_container_state(101, create=True)
    state.active = True

    def reject_docker(*_args, **_kwargs):
        raise AssertionError("local cleanup must not invoke Docker")

    monkeypatch.setattr(infra.subprocess, "run", reject_docker)

    assert await infra.cleanup_persistent_container(101) is True
    assert 101 not in infra._container_states


def test_background_command_runs_in_local_workspace_with_root_home(monkeypatch):
    monkeypatch.setenv("HOME", "/tmp/not-root")
    tmp = infra.start_background_cmd(
        'printf "%s\\n%s\\n" "$PWD" "$HOME"',
        "local-pwd",
        group_id=101,
    )
    proc, _ = infra.get_background_process("local-pwd", group_id=101)
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait(timeout=5)

    output, _ = infra.read_background_output(tmp, 0)
    assert output.splitlines() == ["/work", "/root"]

    infra.kill_background_cmd("local-pwd", group_id=101)


@pytest.mark.asyncio
async def test_message_image_paths_are_namespaced_by_group(monkeypatch):
    async def no_copy(*_args, **_kwargs):
        return None

    async def no_dir(*_args, **_kwargs):
        return None

    monkeypatch.setattr(infra, "_ensure_user_image_sandbox_dir", no_dir)
    monkeypatch.setattr(infra, "copy_host_file_to_sandbox", no_copy)

    first = await infra.save_sandbox_user_image(
        b"first",
        9,
        1,
        "png",
        group_id=101,
    )
    second = await infra.save_sandbox_user_image(
        b"second",
        9,
        1,
        "png",
        group_id=202,
    )

    assert first == "/tmp/hatsume-user-images/101/9-1.png"
    assert second == "/tmp/hatsume-user-images/202/9-1.png"
