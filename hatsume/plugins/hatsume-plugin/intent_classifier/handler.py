"""Intent classifier hook: fire-and-forget classification on incoming group messages.

This module provides a callable intended to be invoked from the main message
handling path (e.g. in handlers/dialogue.py). It is **fire-and-forget**: the
classification runs in a background task and its result never blocks or alters
the message processing chain.
"""

from __future__ import annotations

import logging

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from .client import get_classifier_client, ClassificationResult
from .config import (
    INTENT_CLASSIFIER_ENABLED,
    INTENT_CLASSIFIER_LABELS,
    INTENT_CLASSIFIER_TIMEOUT,
    INTENT_CLASSIFIER_BASE_URL,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global counter for stats (in-memory; resets on bot restart)
# ---------------------------------------------------------------------------
_classify_count: int = 0
_classify_success: int = 0


def _get_stats() -> dict[str, int]:
    """Return cumulative classify counters."""
    return {
        "total": _classify_count,
        "success": _classify_success,
    }


async def on_message_incoming(event: GroupMessageEvent) -> None:
    """Fire-and-forget intent classification on an incoming group message.

    This function is designed to be called (via create_task) from
    ``handlers/dialogue.py`` in the ``user_chat_handle`` flow, before the
    LangGraph conversation starts.  All errors are silently swallowed so
    external service failures never block the chat.

    Parameters
    ----------
    event : GroupMessageEvent
        The raw OneBot V11 group message event.
    """
    if not INTENT_CLASSIFIER_ENABLED:
        return

    global _classify_count, _classify_success

    # Extract plain text from the message
    text = event.message.extract_plain_text().strip()
    if not text:
        return

    _classify_count += 1

    try:
        client = get_classifier_client(INTENT_CLASSIFIER_TIMEOUT)
        results = await client.batch_classify(
            texts=[text],
            labels=INTENT_CLASSIFIER_LABELS,
            base_url=INTENT_CLASSIFIER_BASE_URL,
        )
        if not results:
            return

        result: ClassificationResult = results[0]
        _classify_success += 1

        # Log the classification result at info level with context
        confidence_str = (
            f", confidence={result.confidence:.2f}"
            if result.confidence is not None
            else ""
        )
        logger.info(
            "[intent-classifier] group=%s user=%d msg_id=%d label=%s%s",
            event.group_id,
            event.user_id,
            event.message_id,
            result.label,
            confidence_str,
        )

    except Exception as exc:
        # Swallow all exceptions — never let classifier failure block chat
        logger.warning(
            "[intent-classifier] failed for group=%s msg_id=%d: %s",
            event.group_id,
            event.message_id,
            exc,
        )


def get_intent_classifier_stats() -> dict[str, int]:
    """Return current statistics (for debugging / metrics exposure)."""
    return _get_stats()
