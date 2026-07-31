"""Persistent per-group todo list."""

from __future__ import annotations

from .store import TodoCreateResult, TodoItem, TodoStore, TodoValidationError

__all__ = [
    "TodoCreateResult",
    "TodoItem",
    "TodoStore",
    "TodoValidationError",
    "get_store",
]

_store: TodoStore | None = None


def get_store() -> TodoStore:
    """Get or create the process-level todo store."""
    global _store
    if _store is None:
        candidate = TodoStore()
        try:
            candidate.init_db()
        except BaseException:
            candidate.close()
            raise
        _store = candidate
    return _store
