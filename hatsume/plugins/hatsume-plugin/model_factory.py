"""API-specific SDK construction from a resolved model configuration snapshot."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .model_config import ModelConfigError, get_model_config_store, validate_options


def create_chat_model(settings: dict[str, Any]) -> BaseChatModel:
    api = settings["api"]
    options = validate_options(api, settings["options"])
    kwargs = {
        "model": settings["model"],
        "base_url": settings["base_url"],
        "api_key": settings["api_key"],
    }
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


def get_model(
    role: str, *, reasoning_effort: str | None = None, thinking: bool = True
) -> BaseChatModel:
    settings = get_model_config_store().resolve(role)
    if not thinking:
        if settings["api"] == "google_genai":
            settings["options"].pop("thinking_level", None)
            settings["options"]["thinking_budget"] = 0
        else:
            settings["options"]["reasoning_effort"] = "none"
    elif reasoning_effort is not None:
        if settings["api"] == "google_genai":
            # Callers may override OpenAI reasoning labels, but Google settings
            # must be selected explicitly for the particular Google model.
            raise ModelConfigError(
                "Set Google thinking_budget or thinking_level in the model role."
            )
        settings["options"]["reasoning_effort"] = reasoning_effort
    return create_chat_model(settings)


def create_embedding_model(settings: dict[str, Any]) -> OpenAIEmbeddings:
    if settings["api"] != "openai_embeddings":
        raise ModelConfigError("Embedding role requires openai_embeddings.")
    return OpenAIEmbeddings(
        base_url=settings["base_url"],
        model=settings["model"],
        api_key=settings["api_key"],
        **validate_options(settings["api"], settings["options"]),
    )
