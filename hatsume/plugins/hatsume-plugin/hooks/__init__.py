"""Persistent per-group Hook management and lifecycle.

This module provides:
1. Persistent hook storage and scheduling (HookStore, executor)
2. Sandbox-to-chat_agent Unix domain socket channel (sandbox_channel, sandbox_channel_handler)
"""

from __future__ import annotations

from collections.abc import Iterable

from .store import HookStore
from .sandbox_channel import SandboxChannelMessage, SandboxChannelSocketServer, get_or_create_sandbox_channel_server
from .sandbox_channel_handler import setup_sandbox_channel_handler

_store: HookStore | None = None


def get_store() -> HookStore:
    global _store
    if _store is None:
        candidate = HookStore()
        try:
            candidate.init_db()
        except BaseException:
            candidate.close()
            raise
        _store = candidate
        print(f"🪝 [hooks] HookStore ready (db: {_store._db_path})")
    return _store


def init_hook_system() -> None:
    """Initialize persistence without registering jobs before Bot routing."""
    get_store()


def restore_hooks(routable_group_ids: Iterable[int]) -> None:
    from .executor import restore_hook_jobs

    restore_hook_jobs(get_store(), tuple(routable_group_ids))


def pause_hooks_for_groups(group_ids: Iterable[int]) -> None:
    from .executor import pause_hook_jobs_for_groups

    pause_hook_jobs_for_groups(get_store(), tuple(group_ids))


async def shutdown_hooks() -> None:
    global _store
    from .executor import shutdown_hook_executor

    await shutdown_hook_executor()
    if _store is not None:
        _store.close()
        _store = None


__all__ = [
    "HookStore",
    "SandboxChannelMessage",
    "SandboxChannelSocketServer",
    "get_store",
    "get_or_create_sandbox_channel_server",
    "setup_sandbox_channel_handler",
    "init_hook_system",
    "init_sandbox_channel",
    "pause_hooks_for_groups",
    "restore_hooks",
    "shutdown_hooks",
]


async def init_sandbox_channel(socket_path: str = "/tmp/hatsume_channel.sock") -> SandboxChannelSocketServer:
    """Initialize the Sandbox Channel socket server and start it.

    Args:
        socket_path: Path to Unix domain socket (default: /tmp/hatsume_channel.sock)

    Returns:
        The initialized SandboxChannelSocketServer instance.
    """
    server = get_or_create_sandbox_channel_server(socket_path)
    setup_sandbox_channel_handler(server)
    await server.start()
    print(f"🪝 [sandbox_channel] Socket server started (socket={socket_path})")
    return server
