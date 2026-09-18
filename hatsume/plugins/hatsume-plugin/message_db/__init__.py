"""Persistent per-group chat message history."""

from __future__ import annotations

from .store import (
    DEFAULT_SEARCH_LIMIT,
    MAX_SEARCH_LIMIT,
    MessageRecord,
    MessageStore,
    MessageValidationError,
    parse_local_time,
)

__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "MAX_SEARCH_LIMIT",
    "MessageRecord",
    "MessageStore",
    "MessageValidationError",
    "get_store",
    "parse_local_time",
]

_store: MessageStore | None = None


def get_store() -> MessageStore:
    """Get or create the process-level message store."""
    global _store
    if _store is None:
        candidate = MessageStore()
        try:
            candidate.init_db()
        except BaseException:
            candidate.close()
            raise
        _store = candidate
    return _store
