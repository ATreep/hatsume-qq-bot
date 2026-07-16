"""Pure text security utilities with no bot-framework dependencies."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_SECRET_KEY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(sk-(?:ant(?:-api\d{2})?-)?)[A-Za-z0-9_-]{20,}"), "sk-*"),
    (re.compile(r"(gh[opu]_|github_pat_)[A-Za-z0-9_]{20,}"), "gh*_*"),
    (re.compile(r"(ark-)[A-Za-z0-9_-]{20,}"), "ark-*"),
    (re.compile(r"(ak-)[A-Za-z0-9_-]{20,}"), "ak-*"),
    (re.compile(r"(nvapi-)[A-Za-z0-9_-]{20,}"), "nvapi-*"),
)


def mask_secret_keys(text: str) -> str:
    """Mask recognized API-key bodies while preserving their prefixes."""
    try:
        for pattern, label in _SECRET_KEY_PATTERNS:
            if pattern.search(text):
                text = pattern.sub(r"\1xxx...xxx", text)
                logger.warning("Masked potential credential matching %s", label)
        return text
    except Exception:
        return text
