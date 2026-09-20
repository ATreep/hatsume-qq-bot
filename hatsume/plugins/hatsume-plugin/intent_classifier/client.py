"""classifier.dev client for zero-shot intent classification.

Adaptted from https://classifier.dev — free, no API key required.
- POST /v1/classify with {"inputs": [...], "labels": [...]}
- Returns JSON with results[], usage{}
- Graceful degradation on failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# Default label set for message intent analysis
DEFAULT_LABELS: list[str] = [
    "询价砍价",
    "闲聊问候",
    "技术求助",
    "吐槽卖惨",
    "指令请求",
    "其他",
]

DEGRADED_LABEL = "其他"

TIMEOUT_SECONDS: float = 1.5


@dataclass
class ClassificationResult:
    """Single classification result."""

    label: str       # matched label name
    confidence: float | None  # calibrated confidence [0, 1] or null
    scores: dict     # raw scores per label


class ClassifierClient:
    """Async wrapper around classifier.dev POST /v1/classify.

    All failures are silently degraded to DEGRADED_LABEL="其他" so that
    external service jitter never blocks the main message pipeline.
    """

    def __init__(self, timeout: float = TIMEOUT_SECONDS) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def classify(
        self,
        text: str,
        labels: list[str] | None = None,
        base_url: str = "https://classifier.dev/v1/classify",
    ) -> ClassificationResult:
        """Classify a single text against the given labels.

        Returns DEGRADED result on any error / timeout / non-2xx.
        """
        if not text.strip():
            return ClassificationResult(
                label=DEGRADED_LABEL, confidence=None, scores={}
            )
        results = await self.batch_classify([text], labels, base_url)
        return results[0] if results else ClassificationResult(
            label=DEGRADED_LABEL, confidence=None, scores={}
        )

    async def batch_classify(
        self,
        texts: list[str],
        labels: list[str] | None = None,
        base_url: str = "https://classifier.dev/v1/classify",
    ) -> list[ClassificationResult]:
        """Batch classify up to 1000 texts (fast tier limit).

        Returns DEGRADED result per item when the request fails entirely.
        """
        effective_labels = labels or DEFAULT_LABELS
        degraded = ClassificationResult(
            label=DEGRADED_LABEL, confidence=None, scores={}
        )

        if not texts:
            return []

        payload: dict = {
            "inputs": texts,
            "labels": effective_labels,
        }

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(base_url, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "classifier.dev returned %d, returning degraded",
                            resp.status,
                        )
                        return [degraded] * len(texts)

                    body_text = await resp.text()
                    try:
                        data = json.loads(body_text)
                    except json.JSONDecodeError:
                        logger.warning("classifier.dev returned invalid JSON")
                        return [degraded] * len(texts)

            # Parse response — must have "results" array
            results_raw = data.get("results")
            if not isinstance(results_raw, list) or len(results_raw) != len(texts):
                logger.warning(
                    "classifier.dev response missing or mismatched results (%d)",
                    len(results_raw) if results_raw else 0,
                )
                return [degraded] * len(texts)

            outcomes: list[ClassificationResult] = []
            for raw in results_raw:
                label_val = raw.get("label")
                conf_val = raw.get("confidence")
                scores_val = raw.get("scores", {})

                # Guard against null fields (smart-tier escalation)
                if label_val is None or not isinstance(label_val, str):
                    outcomes.append(degraded)
                    continue
                if conf_val is not None and not isinstance(conf_val, (int, float)):
                    conf_val = None

                outcomes.append(
                    ClassificationResult(
                        label=label_val,
                        confidence=float(conf_val) if conf_val is not None else None,
                        scores=dict(scores_val) if isinstance(scores_val, dict) else {},
                    )
                )

            return outcomes

        except TimeoutError:
            logger.info("classifier.dev timed out (%.1fs)", TIMEOUT_SECONDS)
            return [degraded] * len(texts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("classifier.dev request failed: %s", exc)
            return [degraded] * len(texts)


# Singleton instance used by the handler
_client: ClassifierClient | None = None


def get_classifier_client(timeout: float | None = None) -> ClassifierClient:
    """Return a shared ClassifierClient (lazy singleton)."""
    global _client
    if _client is None:
        _client = ClassifierClient(timeout=timeout or TIMEOUT_SECONDS)
    elif timeout is not None and timeout != TIMEOUT_SECONDS:
        # Recreate with new timeout
        _client = ClassifierClient(timeout=timeout)
    return _client
