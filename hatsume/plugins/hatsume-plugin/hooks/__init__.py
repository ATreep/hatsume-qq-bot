"""Persistent per-group Hook management and lifecycle."""

from __future__ import annotations

from collections.abc import Iterable

from .store import HookStore

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
    "get_store",
    "init_hook_system",
    "pause_hooks_for_groups",
    "restore_hooks",
    "shutdown_hooks",
]
