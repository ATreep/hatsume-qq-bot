"""Unified exception hierarchy for LLM / API error classification in Hatsume.

Categorises exceptions raised by the LLM provider SDKs (OpenAI-compatible,
Anthropic, etc.) so that callers can handle rate-limit, auth, and transient
failures with distinct user-visible messages rather than a catch-all
``except Exception`` block.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Public exception classes
# ---------------------------------------------------------------------------

class LLMBaseError(Exception):
    """Base class for all LLM-related errors in Hatsume."""


class LLMAuthError(LLMBaseError):
    """API key invalid, missing, or unauthorized (HTTP 401/403)."""


class LLMLimitExceededError(LLMBaseError):
    """Rate limit exceeded, free-tier quota exhausted, or usage cap hit.

    Commonly corresponds to HTTP 429 responses from provider APIs.
    """


class LLMRequestError(LLMBaseError):
    """Generic request failure — network timeout, server error (5xx), etc."""


class LLMResponseParseError(LLMBaseError):
    """The LLM response cannot be parsed into the expected format."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _LLMRateLimitInfo:
    """Hold optional rate-limit metadata extracted from OpenAI-style SDKs."""

    def __init__(self, retry_after: int | None = None, message: str | None = None) -> None:
        self.retry_after = retry_after
        self.message = message


def _extract_rate_limit_info(exc: Exception) -> _LLMRateLimitInfo | None:
    """Extract ``retry-after`` / quota info from common SDK exceptions.

    Inspects attributes on OpenAI / LangChain / litellm exception objects to
    surface rate-limit hints that callers may use for back-off decisions.
    """
    info = _LLMRateLimitInfo()

    # HTTP-level: status_code == 429 is the primary signal
    if hasattr(exc, "status_code") and exc.status_code == 429:  # type: ignore[attr-defined]
        info.retry_after = getattr(exc, "retry_after", None)
        return info

    # Message text heuristics (case-insensitive)
    if hasattr(exc, "message"):  # type: ignore[has-attr]
        msg = exc.message if isinstance(exc.message, str) else str(exc)  # type: ignore[attr-defined]
        lower_msg = msg.lower()
        if "rate limit" in lower_msg or "quota" in lower_msg or "free usage" in lower_msg:
            info.message = msg
            return info

    # Response object headers (common in httpx / requests-based wrappers)
    if hasattr(exc, "response"):  # type: ignore[has-attr]
        resp = exc.response  # type: ignore[attr-defined]
        if hasattr(resp, "headers"):
            hdrs = resp.headers
            if isinstance(hdrs, dict):
                ra = hdrs.get("Retry-After")
            else:
                ra = getattr(hdrs, "Retry-After", None)
            if ra is not None:
                try:
                    info.retry_after = int(ra)
                except (ValueError, TypeError):
                    pass

    return info
