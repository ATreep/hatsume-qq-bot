"""Timer module: scheduled task creation, persistence, and execution."""

from __future__ import annotations

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


async def init_scheduler() -> None:
    """Load pending triggers from DB and register APScheduler jobs.

    Called on NoneBot startup. Handles:
    - Re-registering future pending triggers
    - Compensating missed triggers within tolerance window
    - Marking expired triggers as fired
    """
    from .executor import (
        refresh_auto_response,
        register_cleanup_job,
        reload_all_schedules,
    )

    print("⏰ [timer] Starting scheduler recovery...")
    store = get_store()
    await reload_all_schedules(store)

    await refresh_auto_response(store)
    register_cleanup_job(store)

    print("⏰ [timer] Scheduler recovery complete")
