"""Timer module: scheduled task creation, persistence, and execution."""

from __future__ import annotations

from collections.abc import Iterable

from .store import TimerStore

# Singleton store instance — initialized on first access
_store: TimerStore | None = None


def get_store() -> TimerStore:
    """Get or create the singleton TimerStore instance."""
    global _store
    if _store is None:
        print("⏰ [timer] Initializing TimerStore...")
        candidate = TimerStore()
        try:
            candidate.init_db()
        except BaseException:
            print(
                "⏰ [timer] TimerStore initialization failed "
                f"(db: {candidate._db_path})"
            )
            candidate.close()
            raise
        _store = candidate
        print(f"⏰ [timer] TimerStore ready (db: {_store._db_path})")
    return _store


def sync_auto_response_for_group(group_id: int, active: bool) -> None:
    """Synchronize one activated group's auto-response point."""
    from ..group_runtime import group_runtime_registry
    from .executor import sync_auto_response_for_group as sync_for_group

    sync_for_group(
        get_store(),
        group_id,
        active,
        register_job=group_id in group_runtime_registry.routed_group_ids(),
    )


def reconcile_auto_response_for_group(group_id: int) -> None:
    """Synchronize one group from its memory-owned current activation state."""
    from ..memory import synchronize_activated_group

    synchronize_activated_group(group_id, sync_auto_response_for_group)


def reconcile_auto_responses() -> None:
    """Atomically reconcile current and persisted auto-response group owners."""
    from ..memory import get_activated_group_ids

    store = get_store()
    group_ids = set(get_activated_group_ids())
    group_ids.update(store.list_auto_response_group_ids())
    for group_id in sorted(group_ids):
        reconcile_auto_response_for_group(group_id)


async def init_scheduler(
    group_ids: Iterable[int], routable_group_ids: Iterable[int]
) -> None:
    """Load pending triggers from DB and register APScheduler jobs.

    Called on NoneBot startup. Handles:
    - Re-registering future pending triggers
    - Compensating missed triggers within tolerance window
    - Marking expired triggers as fired
    """
    from .executor import (
        remove_ineligible_auto_response_groups,
        refresh_auto_responses,
        register_cleanup_job,
        reload_all_schedules,
    )

    print("⏰ [timer] Starting scheduler recovery...")
    store = get_store()
    activated_groups = tuple(group_ids)
    routed_groups = tuple(routable_group_ids)
    remove_ineligible_auto_response_groups(store, activated_groups)
    await reload_all_schedules(store, group_ids=routed_groups)

    await refresh_auto_responses(
        store,
        activated_groups,
        routable_group_ids=routed_groups,
    )
    register_cleanup_job(store)
    reconcile_auto_responses()

    print("⏰ [timer] Scheduler recovery complete")
