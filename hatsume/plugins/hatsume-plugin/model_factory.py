"""API-specific SDK construction from a resolved model configuration snapshot."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar
from uuid import UUID

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    BaseCallbackHandler,
    CallbackManagerForLLMRun,
)
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import ConfigDict

from .model_config import ModelConfigError, get_model_config_store, validate_options

T = TypeVar("T")


def entry_label(settings: dict[str, Any]) -> str:
    return f"{settings['provider']} / {settings['model']}"


def describe_failure(exc: BaseException) -> str:
    # SDK errors can contain the request, URL, or credentials. Report only the
    # status/type and never the raw exception text.
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    status = getattr(exc, "status_code", None)
    return f"HTTP {status}" if isinstance(status, int) else type(exc).__name__


class _InvocationLogger(BaseCallbackHandler):
    """Print one line when a chat model request starts, finishes or fails."""

    run_inline = True

    def __init__(self, label: str):
        self.label = label
        self._started: dict[UUID, float] = {}

    def _elapsed(self, run_id: UUID) -> float:
        return time.monotonic() - self._started.pop(run_id, time.monotonic())

    def on_chat_model_start(
        self, serialized: Any, messages: list[list[BaseMessage]], *, run_id: UUID, **kwargs: Any
    ) -> None:
        self._started[run_id] = time.monotonic()
        count = len(messages[0]) if messages else 0
        print(f"[llm] invoke {self.label} ({count} messages)")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = self._elapsed(run_id)
        usage = None
        try:
            usage = response.generations[0][0].message.usage_metadata  # type: ignore[union-attr]
        except (IndexError, AttributeError):
            pass
        tokens = f", {usage['total_tokens']} tokens" if usage else ""
        print(f"[llm] done {self.label} in {elapsed:.1f}s{tokens}")

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        elapsed = self._elapsed(run_id)
        print(f"[llm] error {self.label} after {elapsed:.1f}s ({describe_failure(error)})")


def _log_failure(what: str, labels: Sequence[str], index: int, exc: Exception) -> None:
    reason = describe_failure(exc)
    if index + 1 < len(labels):
        print(
            f"[failover] {what} {labels[index]} failed ({reason}); "
            f"falling back to {labels[index + 1]} ({index + 1}/{len(labels) - 1})."
        )
    elif len(labels) > 1:
        print(f"[failover] {what}: all {len(labels)} entries failed; last error {reason}.")


def _log_recovered(what: str, labels: Sequence[str], index: int) -> None:
    if index:
        print(f"[failover] {what} recovered with {labels[index]}.")


def _run_sync(
    calls: Sequence[tuple[str, Callable[[], T]]], what: str
) -> T:
    labels = [label for label, _ in calls]
    last: Exception | None = None
    for index, (_, call) in enumerate(calls):
        try:
            result = call()
        except Exception as exc:
            last = exc
            _log_failure(what, labels, index, exc)
            continue
        _log_recovered(what, labels, index)
        return result
    assert last is not None
    raise last


async def run_with_failover(
    calls: Sequence[tuple[str, float | None, Callable[[], Awaitable[T]]]],
    what: str,
) -> T:
    """Await each call in order until one succeeds; re-raise the last error.

    Cancellation is not an ``Exception`` and therefore always propagates.
    """
    labels = [label for label, _, _ in calls]
    last: Exception | None = None
    for index, (_, timeout, call) in enumerate(calls):
        try:
            result = await asyncio.wait_for(call(), timeout)
        except Exception as exc:
            last = exc
            _log_failure(what, labels, index, exc)
            continue
        _log_recovered(what, labels, index)
        return result
    assert last is not None
    raise last


def create_chat_model(
    settings: dict[str, Any], *, label: str | None = None
) -> BaseChatModel:
    api = settings["api"]
    options = validate_options(api, settings["options"])
    kwargs = {
        "model": settings["model"],
        "base_url": settings["base_url"],
        "api_key": settings["api_key"],
        "callbacks": [_InvocationLogger(label or entry_label(settings))],
    }
    if settings.get("timeout") is not None:
        # Bounds each HTTP attempt, including synchronous calls; the failover
        # wrapper additionally bounds the whole call including SDK retries.
        kwargs["timeout"] = settings["timeout"]
    if api in ("openai_chat_completions", "openai_responses"):
        responses = api == "openai_responses"
        effort = options.pop("reasoning_effort", None)
        if effort is not None:
            options["reasoning" if responses else "reasoning_effort"] = (
                {"effort": effort} if responses else effort
            )
        return ChatOpenAI(
            **kwargs,
            **options,
            use_responses_api=responses,
            use_previous_response_id=False,
            output_version="v1",
        )
    if api == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI

        level = options.pop("thinking_level", None)
        if level is not None:
            options["thinking_config"] = {"thinking_level": level}
        return ChatGoogleGenerativeAI(**kwargs, **options, vertexai=False)
    raise ModelConfigError("This role does not use a supported chat API.")


def _apply_thinking(
    settings: dict[str, Any],
    reasoning_effort: str | None,
    thinking: bool,
    primary: bool,
) -> None:
    if not thinking:
        if settings["api"] == "google_genai":
            settings["options"].pop("thinking_level", None)
            settings["options"]["thinking_budget"] = 0
        else:
            settings["options"]["reasoning_effort"] = "none"
    elif reasoning_effort is not None:
        if settings["api"] != "google_genai":
            settings["options"]["reasoning_effort"] = reasoning_effort
        elif primary:
            # Callers may override OpenAI reasoning labels, but Google settings
            # must be selected explicitly for the particular Google model. A
            # Google fallback keeps its own configured thinking settings.
            raise ModelConfigError(
                "Set Google thinking_budget or thinking_level in the model role."
            )


def get_model(
    role: str, *, reasoning_effort: str | None = None, thinking: bool = True
) -> BaseChatModel:
    chain = get_model_config_store().resolve_chain(role)
    for index, settings in enumerate(chain):
        _apply_thinking(settings, reasoning_effort, thinking, primary=index == 0)
    labels = [f"{role}: {entry_label(settings)}" for settings in chain]
    if len(chain) == 1:
        return create_chat_model(chain[0], label=labels[0])
    return FailoverChatModel(
        models=[
            create_chat_model(settings, label=label)
            for settings, label in zip(chain, labels)
        ],
        timeouts=[settings.get("timeout") for settings in chain],
        labels=labels,
    )


def create_embedding_model(settings: dict[str, Any]) -> OpenAIEmbeddings:
    if settings["api"] != "openai_embeddings":
        raise ModelConfigError("Embedding role requires openai_embeddings.")
    extra = {"timeout": settings["timeout"]} if settings.get("timeout") else {}
    return OpenAIEmbeddings(
        base_url=settings["base_url"],
        model=settings["model"],
        api_key=settings["api_key"],
        **extra,
        **validate_options(settings["api"], settings["options"]),
    )


def get_embedding_model(role: str = "embedding") -> Embeddings:
    chain = get_model_config_store().resolve_chain(role)
    if len(chain) == 1:
        return create_embedding_model(chain[0])
    return FailoverEmbeddings(
        [create_embedding_model(settings) for settings in chain],
        [settings.get("timeout") for settings in chain],
        [entry_label(settings) for settings in chain],
    )


class FailoverChatModel(BaseChatModel):
    """Try each configured chat model in order on error or timeout.

    ``models`` hold already-bound runnables so ``bind_tools`` can convert tools
    with each provider's own SDK format. Inner calls do not receive the outer
    run's callbacks; each inner model logs its own attempt.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    models: list[Runnable]
    timeouts: list[float | None]
    labels: list[str]

    @property
    def _llm_type(self) -> str:
        return "failover"

    @property
    def model_name(self) -> str:
        primary = self.models[0]
        bound = getattr(primary, "bound", primary)
        return getattr(bound, "model_name", None) or getattr(bound, "model", "")

    def _call_kwargs(self, stop: list[str] | None, kwargs: dict) -> dict:
        return kwargs | ({"stop": stop} if stop is not None else {})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        call_kwargs = self._call_kwargs(stop, kwargs)
        message = _run_sync(
            [
                (label, lambda model=model: model.invoke(messages, **call_kwargs))
                for model, label in zip(self.models, self.labels)
            ],
            "chat model",
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        call_kwargs = self._call_kwargs(stop, kwargs)
        message = await run_with_failover(
            [
                (
                    label,
                    timeout,
                    lambda model=model: model.ainvoke(messages, **call_kwargs),
                )
                for model, timeout, label in zip(
                    self.models, self.timeouts, self.labels
                )
            ],
            "chat model",
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> FailoverChatModel:
        return self.model_copy(
            update={"models": [model.bind_tools(tools, **kwargs) for model in self.models]}
        )


class FailoverEmbeddings(Embeddings):
    """Try each embedding client in order. All entries must share one vector space."""

    def __init__(
        self,
        models: list[Embeddings],
        timeouts: list[float | None],
        labels: list[str],
    ):
        self.models, self.timeouts, self.labels = models, timeouts, labels

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return _run_sync(
            [
                (label, lambda model=model: model.embed_documents(texts))
                for model, label in zip(self.models, self.labels)
            ],
            "embedding",
        )

    def embed_query(self, text: str) -> list[float]:
        return _run_sync(
            [
                (label, lambda model=model: model.embed_query(text))
                for model, label in zip(self.models, self.labels)
            ],
            "embedding",
        )

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await run_with_failover(
            [
                (label, timeout, lambda model=model: model.aembed_documents(texts))
                for model, timeout, label in zip(self.models, self.timeouts, self.labels)
            ],
            "embedding",
        )

    async def aembed_query(self, text: str) -> list[float]:
        return await run_with_failover(
            [
                (label, timeout, lambda model=model: model.aembed_query(text))
                for model, timeout, label in zip(self.models, self.timeouts, self.labels)
            ],
            "embedding",
        )
