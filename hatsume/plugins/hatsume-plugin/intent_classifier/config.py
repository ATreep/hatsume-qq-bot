"""Configuration for the intent classifier module.

All settings are driven by environment variables via os.getenv, so they can be
enabled or tuned without code changes.  The default is DISABLED (False) to avoid
changing existing behavior on deploy.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Enable/disable switch
# ---------------------------------------------------------------------------
INTENT_CLASSIFIER_ENABLED: bool = os.getenv(
    "INTENT_CLASSIFIER_ENABLED", "0"
).lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Labels — override with comma-separated values in env var
# ---------------------------------------------------------------------------
_DEFAULT_LABELS = [
    "询价砍价",
    "闲聊问候",
    "技术求助",
    "吐槽卖惨",
    "指令请求",
    "其他",
]

_INTENT_LABELS_STR = os.getenv("INTENT_CLASSIFIER_LABELS", "")
if _INTENT_LABELS_STR.strip():
    INTENT_CLASSIFIER_LABELS: list[str] = [
        s.strip() for s in _INTENT_LABELS_STR.split(",") if s.strip()
    ]
else:
    INTENT_CLASSIFIER_LABELS = list(_DEFAULT_LABELS)

# ---------------------------------------------------------------------------
# Timeout & URL
# ---------------------------------------------------------------------------
_INTENT_TIMEOUT = os.getenv("INTENT_CLASSIFIER_TIMEOUT", "1.5")
try:
    INTENT_CLASSIFIER_TIMEOUT: float = float(_INTENT_TIMEOUT)
except ValueError:
    INTENT_CLASSIFIER_TIMEOUT = 1.5

INTENT_CLASSIFIER_BASE_URL: str = os.getenv(
    "INTENT_CLASSIFIER_BASE_URL", "https://classifier.dev/v1/classify"
)
