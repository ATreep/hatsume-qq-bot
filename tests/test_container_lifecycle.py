"""Tests for container auto-stop lifecycle — refcount and grace timer."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy():
    """Ensure hatsume.plugins.hatsume_plugin package hierarchy exists."""
    packages = [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]
    for name, path in packages:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias
    sys.modules["hatsume.plugins"].hatsume_plugin = sys.modules[
        "hatsume.plugins.hatsume_plugin"
    ]

    # Stub config
    config_name = "hatsume.plugins.hatsume_plugin.config"
    if config_name not in sys.modules:
        config_mod = types.ModuleType(config_name)
        sys.modules[config_name] = config_mod
    config_mod = sys.modules[config_name]
    config_mod.DOCKER_ENV_PATH = Path("/tmp/test_docker")
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    config_mod.CONTAINER_NAME = "hatsume-space-kali"
    sys.modules["hatsume.plugins.hatsume_plugin"].config = config_mod

    # Load infra module from actual file
    import importlib.util
    infra_path = PLUGIN_DIR / "infra.py"
    infra_name = "hatsume.plugins.hatsume_plugin.infra"
    if infra_name in sys.modules:
        del sys.modules[infra_name]
    if hasattr(sys.modules["hatsume.plugins.hatsume_plugin"], "infra"):
        delattr(sys.modules["hatsume.plugins.hatsume_plugin"], "infra")
    spec = importlib.util.spec_from_file_location(infra_name, infra_path)
    infra_mod = importlib.util.module_from_spec(spec)
    sys.modules[infra_name] = infra_mod
    spec.loader.exec_module(infra_mod)
    sys.modules["hatsume.plugins.hatsume_plugin"].infra = infra_mod


_setup_package_hierarchy()


@pytest.fixture(autouse=True)
def _reset_refcount_state():
    """Reset refcount state before each test to prevent cross-test pollution."""
    _setup_package_hierarchy()
    from hatsume.plugins.hatsume_plugin.infra import (
        _background_procs,
    )
    _background_procs.clear()

    # Ensure DOCKER_ENV_PATH exists for tests that call run_cmd
    Path("/tmp/test_docker").mkdir(parents=True, exist_ok=True)

    # Access and reset the refcount private state
    import hatsume.plugins.hatsume_plugin.infra as infra_mod
    infra_mod._subprocess_refcount = 0
    infra_mod._stop_timer_task = None
    yield
    _background_procs.clear()
    infra_mod._subprocess_refcount = 0
    infra_mod._stop_timer_task = None


# -----------------------------------------------------------------------
# _acquire_subprocess
# -----------------------------------------------------------------------


class TestAcquireSubprocess:
    """Tests for _acquire_subprocess() — increment refcount, cancel timer."""

    def test_increments_refcount(self):
        """_acquire_subprocess increments _subprocess_refcount by 1."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        assert infra_mod._subprocess_refcount == 0
        infra_mod._acquire_subprocess()
        assert infra_mod._subprocess_refcount == 1
        infra_mod._acquire_subprocess()
        assert infra_mod._subprocess_refcount == 2

    def test_cancels_pending_timer(self):
        """_acquire_subprocess cancels a pending _stop_timer_task."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        # Create a mock async task that represents a pending stop timer
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        infra_mod._stop_timer_task = mock_task
        infra_mod._subprocess_refcount = 0

        infra_mod._acquire_subprocess()

        assert infra_mod._subprocess_refcount == 1
        mock_task.cancel.assert_called_once()
        assert infra_mod._stop_timer_task is None

    def test_does_not_cancel_completed_timer(self):
        """_acquire_subprocess does not try to cancel an already-done task."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = True  # already finished
        infra_mod._stop_timer_task = mock_task
        infra_mod._subprocess_refcount = 0

        infra_mod._acquire_subprocess()

        assert infra_mod._subprocess_refcount == 1
        mock_task.cancel.assert_not_called()


# -----------------------------------------------------------------------
# _release_subprocess
# -----------------------------------------------------------------------


class TestReleaseSubprocess:
    """Tests for _release_subprocess() — decrement refcount, start timer."""

    def test_decrements_refcount(self):
        """_release_subprocess decrements _subprocess_refcount by 1."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 3
        infra_mod._release_subprocess()
        assert infra_mod._subprocess_refcount == 2

    def test_clamps_at_zero(self):
        """_release_subprocess does not let refcount go below 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._release_subprocess()
        assert infra_mod._subprocess_refcount == 0

    def test_starts_timer_when_refcount_reaches_zero(self):
        """_release_subprocess creates a _stop_timer_task when refcount hits 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 1

        async def _run_in_loop():
            infra_mod._release_subprocess()
            assert infra_mod._stop_timer_task is not None
            # Clean up: cancel the timer so it doesn't linger
            infra_mod._stop_timer_task.cancel()
            try:
                await infra_mod._stop_timer_task
            except asyncio.CancelledError:
                pass
            infra_mod._stop_timer_task = None

        asyncio.run(_run_in_loop())

    def test_no_timer_when_refcount_still_positive(self):
        """_release_subprocess does NOT start a timer when refcount > 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 2
        infra_mod._stop_timer_task = None

        async def _run_in_loop():
            infra_mod._release_subprocess()
            assert infra_mod._subprocess_refcount == 1
            assert infra_mod._stop_timer_task is None

        asyncio.run(_run_in_loop())


# -----------------------------------------------------------------------
# _delayed_stop_container
# -----------------------------------------------------------------------


class TestDelayedStopContainer:
    """Tests for _delayed_stop_container() — grace period then stop."""

    def test_stops_container_after_grace_period(self):
        """After _STOP_GRACE_SECONDS, stop_container() is called if refcount still 0."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0

        async def _run_test():
            with patch.object(infra_mod, "stop_container") as mock_stop:
                with patch.object(infra_mod, "asyncio") as mock_asyncio:
                    # Make sleep resolve immediately
                    async def fake_sleep(_seconds):
                        pass
                    mock_asyncio.sleep = fake_sleep
                    mock_asyncio.Task = asyncio.Task

                    await infra_mod._delayed_stop_container()

                    mock_stop.assert_called_once()
                    assert infra_mod._container_active is False
                    assert infra_mod._stop_timer_task is None

        asyncio.run(_run_test())

    def test_does_not_stop_if_refcount_increased_during_sleep(self):
        """If a new subprocess started during grace period, do NOT stop container."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0

        async def _run_test():
            with patch.object(infra_mod, "stop_container") as mock_stop:
                with patch.object(infra_mod, "asyncio") as mock_asyncio:
                    called = False

                    async def fake_sleep(_seconds):
                        nonlocal called
                        if not called:
                            called = True
                            # Simulate: new subprocess started during sleep
                            infra_mod._subprocess_refcount = 1

                    mock_asyncio.sleep = fake_sleep
                    mock_asyncio.Task = asyncio.Task

                    await infra_mod._delayed_stop_container()

                    # stop_container should NOT have been called
                    mock_stop.assert_not_called()
                    assert infra_mod._stop_timer_task is None

        asyncio.run(_run_test())


# -----------------------------------------------------------------------
# Integration: run_cmd refcount
# -----------------------------------------------------------------------


class TestRunCmdRefcount:
    """Tests that run_cmd() properly acquires and releases refcount."""

    @pytest.mark.asyncio
    async def test_run_cmd_releases_refcount_on_success(self):
        """run_cmd calls _acquire then _release, refcount returns to original."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._container_active = True  # skip ensure_container_running

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"hello world\n", b""))

        with patch.object(infra_mod.asyncio, "create_subprocess_exec",
                          new_callable=AsyncMock, return_value=mock_proc):
            await infra_mod.run_cmd("echo hello")

            # After run_cmd returns, refcount should be back at 0
            assert infra_mod._subprocess_refcount == 0
            infra_mod._stop_timer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await infra_mod._stop_timer_task
            infra_mod._stop_timer_task = None


class TestSandboxUserImages:
    """Tests for deterministic user-image lookup and Docker copying."""

    @pytest.mark.asyncio
    async def test_find_returns_matching_deterministic_path(self):
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        run_cmd = AsyncMock(
            return_value=(
                "/tmp/hatsume-user-images/123-2.webp\n"
                "::EXIT::0\n"
            )
        )
        with (
            patch.object(
                infra_mod,
                "_ensure_user_image_sandbox_dir",
                new_callable=AsyncMock,
            ),
            patch.object(infra_mod, "run_cmd", run_cmd),
        ):
            result = await infra_mod.find_sandbox_user_image(123, 2)

        assert result == "/tmp/hatsume-user-images/123-2.webp"
        assert "-name '123-2.*'" in run_cmd.await_args.args[0]

    @pytest.mark.asyncio
    async def test_find_returns_none_when_no_file_matches(self):
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        with (
            patch.object(
                infra_mod,
                "_ensure_user_image_sandbox_dir",
                new_callable=AsyncMock,
            ),
            patch.object(
                infra_mod,
                "run_cmd",
                new_callable=AsyncMock,
                return_value="\n::EXIT::0\n",
            ),
        ):
            result = await infra_mod.find_sandbox_user_image(123, 1)

        assert result is None

    @pytest.mark.asyncio
    async def test_save_copies_to_deterministic_path_and_cleans_host_temp(self):
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        proc = MagicMock(returncode=0)
        proc.communicate = AsyncMock(return_value=(b"", b""))
        create_subprocess = AsyncMock(return_value=proc)

        with (
            patch.object(
                infra_mod,
                "_ensure_user_image_sandbox_dir",
                new_callable=AsyncMock,
            ),
            patch.object(
                infra_mod.asyncio,
                "create_subprocess_exec",
                create_subprocess,
            ),
            patch.object(infra_mod, "_acquire_subprocess") as acquire,
            patch.object(infra_mod, "_release_subprocess") as release,
        ):
            result = await infra_mod.save_sandbox_user_image(
                b"image-bytes",
                message_id=456,
                image_order=3,
                extension="PNG",
            )

        assert result == "/tmp/hatsume-user-images/456-3.png"
        command = create_subprocess.await_args.args
        assert command[:2] == ("docker", "cp")
        assert command[3] == (
            "hatsume-space-kali:/tmp/hatsume-user-images/456-3.png"
        )
        assert not Path(command[2]).exists()
        acquire.assert_called_once_with()
        release.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_save_failure_releases_refcount_and_cleans_host_temp(self):
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        proc = MagicMock(returncode=1)
        proc.communicate = AsyncMock(return_value=(b"", b"copy failed"))
        create_subprocess = AsyncMock(return_value=proc)

        with (
            patch.object(
                infra_mod,
                "_ensure_user_image_sandbox_dir",
                new_callable=AsyncMock,
            ),
            patch.object(
                infra_mod.asyncio,
                "create_subprocess_exec",
                create_subprocess,
            ),
            patch.object(infra_mod, "_acquire_subprocess"),
            patch.object(infra_mod, "_release_subprocess") as release,
        ):
            with pytest.raises(RuntimeError, match="copy failed"):
                await infra_mod.save_sandbox_user_image(
                    b"image-bytes",
                    message_id=456,
                    image_order=1,
                    extension="jpg",
                )

        assert not Path(create_subprocess.await_args.args[2]).exists()
        release.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_save_timeout_kills_process_and_cleans_host_temp(self):
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        proc = MagicMock(returncode=None)
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()
        create_subprocess = AsyncMock(return_value=proc)

        async def timeout_wait_for(coroutine, *, timeout):
            coroutine.close()
            raise asyncio.TimeoutError

        with (
            patch.object(
                infra_mod,
                "_ensure_user_image_sandbox_dir",
                new_callable=AsyncMock,
            ),
            patch.object(
                infra_mod.asyncio,
                "create_subprocess_exec",
                create_subprocess,
            ),
            patch.object(infra_mod.asyncio, "wait_for", timeout_wait_for),
            patch.object(infra_mod, "_acquire_subprocess"),
            patch.object(infra_mod, "_release_subprocess") as release,
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await infra_mod.save_sandbox_user_image(
                    b"image-bytes",
                    message_id=789,
                    image_order=1,
                    extension="gif",
                )

        proc.kill.assert_called_once_with()
        assert proc.communicate.call_count == 2
        assert proc.communicate.await_count == 1
        assert not Path(create_subprocess.await_args.args[2]).exists()
        release.assert_called_once_with()


class TestRunCmdRefcountFailures:
    """Tests that run_cmd releases its reference on failure paths."""

    @pytest.mark.asyncio
    async def test_run_cmd_releases_refcount_on_timeout(self):
        """run_cmd releases refcount even when subprocess times out."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._container_active = True

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"partial stdout", b"partial stderr"))
        mock_proc.kill = MagicMock()

        async def timeout_wait_for(coroutine, timeout):
            coroutine.close()
            raise asyncio.TimeoutError("timed out")

        with patch.object(infra_mod.asyncio, "create_subprocess_exec",
                          new_callable=AsyncMock, return_value=mock_proc), \
             patch.object(infra_mod.asyncio, "wait_for",
                          new=timeout_wait_for):
            result = await infra_mod.run_cmd("sleep 999")

            # Should return timeout message (not crash)
            assert "Executing Timeout" in result
            # Refcount must be released even on exception
            assert infra_mod._subprocess_refcount == 0
            mock_proc.kill.assert_called_once()
            infra_mod._stop_timer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await infra_mod._stop_timer_task
            infra_mod._stop_timer_task = None

    @pytest.mark.asyncio
    async def test_run_cmd_releases_refcount_on_halt(self):
        """run_cmd releases refcount even when Docker is halted (assertion)."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._subprocess_refcount = 0
        infra_mod._container_active = True

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"[HALT] Docker not running\n", b""))

        with patch.object(infra_mod.asyncio, "create_subprocess_exec",
                          new_callable=AsyncMock, return_value=mock_proc):
            with pytest.raises(AssertionError, match="Docker is not running"):
                await infra_mod.run_cmd("anything")

            # Refcount must be released even on assertion failure
            assert infra_mod._subprocess_refcount == 0
            infra_mod._stop_timer_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await infra_mod._stop_timer_task
            infra_mod._stop_timer_task = None


# -----------------------------------------------------------------------
# Integration: kill_background_cmd releases refcount
# -----------------------------------------------------------------------


class TestKillBackgroundCmdRefcount:
    """Tests that kill_background_cmd() properly releases refcount."""

    def test_kill_releases_refcount(self):
        """After kill_background_cmd, _subprocess_refcount is decremented."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_procs,
            kill_background_cmd,
        )

        infra_mod._subprocess_refcount = 1  # simulate one active bg proc

        # Create a real process to kill
        proc = subprocess.Popen(
            ["sleep", "60"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        tmp = Path("/tmp/test_bg_refcount.log")
        tmp.write_text("test output")
        proc_id = "test_refcount_kill"
        _background_procs[proc_id] = (proc, tmp)

        kill_background_cmd(proc_id)

        assert infra_mod._subprocess_refcount == 0
        assert not tmp.exists()

    def test_kill_unknown_proc_does_not_decrement(self):
        """Killing a non-existent proc_id does NOT affect refcount."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod
        from hatsume.plugins.hatsume_plugin.infra import kill_background_cmd

        infra_mod._subprocess_refcount = 2
        result = kill_background_cmd("nonexistent_proc_xyz")

        assert result is None
        assert infra_mod._subprocess_refcount == 2  # unchanged


# -----------------------------------------------------------------------
# Integration: cleanup_persistent_container cancels timer
# -----------------------------------------------------------------------


class TestCleanupCancelsTimer:
    """Tests that cleanup_persistent_container() cancels the grace timer."""

    def test_cleanup_cancels_pending_timer(self):
        """cleanup_persistent_container cancels _stop_timer_task if pending."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        infra_mod._stop_timer_task = mock_task
        infra_mod._container_active = True

        with patch.object(infra_mod, "delete_container"):
            infra_mod.cleanup_persistent_container()

        mock_task.cancel.assert_called_once()
        assert infra_mod._stop_timer_task is None
        assert infra_mod._container_active is False

    def test_cleanup_with_no_timer(self):
        """cleanup_persistent_container works when no timer is pending."""
        import hatsume.plugins.hatsume_plugin.infra as infra_mod

        infra_mod._stop_timer_task = None
        infra_mod._container_active = True

        with patch.object(infra_mod, "delete_container"):
            infra_mod.cleanup_persistent_container()

        assert infra_mod._stop_timer_task is None
