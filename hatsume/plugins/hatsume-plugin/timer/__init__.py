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
        _store = TimerStore()
        _store.init_db()
        print(f"⏰ [timer] TimerStore ready (db: {_store._db_path})")
    return _store


async def init_scheduler() -> None:
    """Load pending triggers from DB and register APScheduler jobs.

    Called on NoneBot startup. Handles:
    - Re-registering future pending triggers
    - Compensating missed triggers within tolerance window
    - Marking expired triggers as fired
    """
    from .executor import reload_all_triggers, refresh_auto_response

    print("⏰ [timer] Starting scheduler recovery...")
    store = get_store()
    await reload_all_triggers(store)

    # Refresh auto-response: re-register pending or create fresh
    await refresh_auto_response(store)

    print("⏰ [timer] Scheduler recovery complete")
