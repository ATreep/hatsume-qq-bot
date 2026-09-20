"""Intent classifier module: classify incoming messages via classifier.dev zero-shot API."""

from __future__ import annotations

from .client import ClassifierClient, ClassificationResult
from .config import (
    INTENT_CLASSIFIER_ENABLED,
    INTENT_CLASSIFIER_LABELS,
    INTENT_CLASSIFIER_TIMEOUT,
    INTENT_CLASSIFIER_BASE_URL,
)
from .handler import on_message_incoming

__all__ = [
    "ClassifierClient",
    "ClassificationResult",
    "INTENT_CLASSIFIER_ENABLED",
    "INTENT_CLASSIFIER_LABELS",
    "INTENT_CLASSIFIER_TIMEOUT",
    "INTENT_CLASSIFIER_BASE_URL",
    "on_message_incoming",
]
