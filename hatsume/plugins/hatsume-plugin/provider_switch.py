"""Global provider auto-switching for the standard language models.

When a completed ``chat_agent`` invocation takes longer than
``SLOW_THRESHOLD_SECONDS``, the current provider is marked slow for
``SLOW_COOLDOWN_SECONDS`` and all standard advanced/lite/mini model factories
switch to the next candidate that is not in its cooldown window. If every candidate is slow,
the selection stays put — the bot prefers one known-slow provider over
flip-flopping between two of them.

State is in-memory only: a restart resets the selection to the static
``config.PROVIDER`` default. Explicit special-purpose providers remain fixed.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import config as _config

# Provider-switch configuration lives in config.py with the other runtime
# settings. Keep these aliases local so the state machine remains readable and
# its public constants remain available to callers/tests.
CANDIDATE_PROVIDERS = getattr(
    _config, "CHAT_PROVIDER_SWITCH_CANDIDATES", ("ruoli", "waw")
)
SLOW_THRESHOLD_SECONDS = getattr(
    _config, "CHAT_PROVIDER_SWITCH_THRESHOLD_SECONDS", 150.0
)
SLOW_COOLDOWN_SECONDS = getattr(
    _config, "CHAT_PROVIDER_SWITCH_COOLDOWN_SECONDS", 3 * 60 * 60
)


class ProviderSwitcher:
    """Tracks the current chat provider and switches on slow invocations."""

    def __init__(
        self,
        candidates: tuple[str, ...] = CANDIDATE_PROVIDERS,
        default_provider: Optional[str] = None,
    ) -> None:
        if not candidates:
            raise ValueError("candidates must not be empty")
        self._candidates = tuple(candidates)
        if default_provider is None or default_provider not in self._candidates:
            default_provider = self._candidates[-1]
        self._current = default_provider
        # provider name -> epoch timestamp until which it is considered slow
        self._slow_until: dict[str, float] = {}
        # provider name -> monotonic start time of the newest slow report.
        # Older fast completions must not clear a newer slow mark.
        self._last_slow_started_at: dict[str, float] = {}
        # Protect state transitions if multiple graph loops/threads report
        # completed invocations concurrently.
        self._lock = threading.Lock()

    @property
    def current(self) -> str:
        """The provider the advance model should use right now."""
        with self._lock:
            return self._current

    def _is_slow(self, provider: str, now: float) -> bool:
        return self._slow_until.get(provider, 0.0) > now

    def record_elapsed(
        self,
        elapsed_seconds: float,
        provider: Optional[str] = None,
        now: Optional[float] = None,
        started_at: Optional[float] = None,
    ) -> Optional[str]:
        """Report one chat_agent invocation's elapsed time.

        ``provider`` is the provider that invocation actually used; it
        defaults to the current selection. ``started_at`` should be the
        monotonic start time of the invocation. It prevents an older fast
        completion from clearing a newer slow report. Returns the new
        provider name when a switch happened, else ``None``.
        """
        if now is None:
            now = time.time()
        if started_at is None:
            # Keep ordering tokens in the monotonic clock domain even when
            # ``now`` is injected as an epoch timestamp for tests.
            started_at = time.monotonic()
        with self._lock:
            if provider is None:
                provider = self._current

            if elapsed_seconds <= SLOW_THRESHOLD_SECONDS:
                # A fast completion only counts as recovery if it started
                # after the newest slow invocation for this provider.
                last_slow_started_at = self._last_slow_started_at.get(provider)
                if (
                    last_slow_started_at is None
                    or started_at > last_slow_started_at
                ):
                    self._slow_until.pop(provider, None)
                return None

            # Slow invocation: record its ordering token and mark the
            # provider slow before trying to switch away.
            previous_slow_started_at = self._last_slow_started_at.get(provider)
            if (
                previous_slow_started_at is None
                or started_at > previous_slow_started_at
            ):
                self._last_slow_started_at[provider] = started_at
            self._slow_until[provider] = now + SLOW_COOLDOWN_SECONDS
            if provider != self._current:
                # Another invocation already reselected the provider; only mark.
                return None
            for candidate in self._candidates:
                if candidate != provider and not self._is_slow(candidate, now):
                    self._current = candidate
                    return candidate
            # Every candidate is in cooldown: stay on the current provider.
            return None


_switcher = ProviderSwitcher(
    default_provider=getattr(_config, "PROVIDER", "waw")
)


def get_model_provider() -> str:
    """Return the provider used by standard advanced/lite/mini models."""
    return _switcher.current


def get_chat_provider() -> str:
    """Backward-compatible alias for the shared model provider."""
    return get_model_provider()


def report_chat_elapsed(
    elapsed_seconds: float,
    provider: Optional[str] = None,
    started_at: Optional[float] = None,
) -> Optional[str]:
    """Report a chat_agent invocation's elapsed time; return the provider
    switched to, or ``None`` when no switch happened."""
    return _switcher.record_elapsed(
        elapsed_seconds,
        provider=provider,
        started_at=started_at,
    )
