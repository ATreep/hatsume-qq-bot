"""Model factory functions for LLM, embedding, and image generation."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import requests

# Preserve provider-specific response fields across LangChain message
# conversions. Both DeepSeek-compatible reasoning and Gemini-compatible tool
# calls require these fields to be sent back on later turns.
import langchain_core.messages as _lc_messages
import langchain_openai.chat_models.base as _openai_base
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from .model_config import get_model_config_store
from .model_factory import create_embedding_model, get_model

_orig_convert_dict = _openai_base._convert_dict_to_message
_orig_convert_msg = _openai_base._convert_message_to_dict


def _patched_convert_dict(_dict):
    msg = _orig_convert_dict(_dict)
    if isinstance(msg, _lc_messages.AIMessage):
        reasoning_content = _dict.get("reasoning_content")
        if reasoning_content:
            msg.additional_kwargs["reasoning_content"] = reasoning_content

        thought_signatures = {
            tool_call["id"]: tool_call["thought_signature"]
            for tool_call in (_dict.get("tool_calls") or [])
            if tool_call.get("id") and tool_call.get("thought_signature")
        }
        if thought_signatures:
            msg.additional_kwargs["thought_signatures"] = thought_signatures
    return msg


def _patched_convert_msg(message, **kwargs):
    result = _orig_convert_msg(message, **kwargs)
    if isinstance(message, _lc_messages.AIMessage):
        if "reasoning_content" in message.additional_kwargs:
            result["reasoning_content"] = message.additional_kwargs[
                "reasoning_content"
            ]

        thought_signatures = message.additional_kwargs.get(
            "thought_signatures", {}
        )
        for tool_call in result.get("tool_calls", []):
            thought_signature = thought_signatures.get(tool_call.get("id", ""))
            if thought_signature:
                tool_call["thought_signature"] = thought_signature
    return result


_openai_base._convert_dict_to_message = _patched_convert_dict
_openai_base._convert_message_to_dict = _patched_convert_msg

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

def get_advance_model(
    thinking: bool = True,
    reasoning_effort: ReasoningEffort | None = None,
) -> BaseChatModel:
    return get_model("advance", thinking=thinking, reasoning_effort=reasoning_effort)


def get_lite_model() -> BaseChatModel:
    return get_model("lite")


def get_mini_model() -> BaseChatModel:
    return get_model("mini")


def get_view_image_model() -> BaseChatModel:
    return get_model("vision")


def get_typesafe_model() -> BaseChatModel:
    """Build the transport for the separate System One /decisions API."""
    settings = get_model_config_store().resolve("systemone")
    return ChatOpenAI(
        base_url=settings["base_url"], model=settings["model"],
        api_key=settings["api_key"], use_responses_api=False,
    )


def get_jev_model() -> BaseChatModel:
    return get_typesafe_model()


def get_intent_model() -> BaseChatModel:
    return get_jev_model()


def get_code_model(reasoning_effort: ReasoningEffort | None = None) -> BaseChatModel:
    return get_model("coding", reasoning_effort=reasoning_effort)


def get_embedding_model() -> OpenAIEmbeddings:
    return create_embedding_model(get_model_config_store().resolve("embedding"))


async def _resolve_image_srcs(images: list[str]) -> list[str]:
    """Convert sandbox image paths to base64 data URIs.

    URLs (http://, https://) and existing data URIs pass through unchanged.
    Sandbox file URIs and absolute Unix paths are read from the Docker sandbox
    and converted to base64 data URIs with a detected MIME type.
    """
    from .group_runtime import get_current_group_id
    from .infra import read_sandbox_image_data_uri

    group_id = get_current_group_id()

    resolved: list[str] = []
    for src in images:
        if src.startswith(("http://", "https://", "data:")):
            resolved.append(src)
            continue
        if src.startswith("file://"):
            src = src[7:]
        if src.startswith("/"):
            resolved.append(
                await read_sandbox_image_data_uri(src, group_id=group_id)
            )
        else:
            resolved.append(src)
    return resolved

async def generate_image_for_sensenova(
    prompt: str,
    images: list[str] | None = None,
    *,
    model: str | None = None,
) -> str:
    """Generate or edit an image via SenseNova and return its temporary URL."""
    settings = get_model_config_store().resolve("image_sensenova")

    image_sources = await _resolve_image_srcs(images or [])
    payload: dict[str, Any] = {
        "model": model or settings["model"],
        "prompt": prompt,
        "n": 1,
        "size": "auto",
        "watermark": False,
        "prompt_extend": True,
        "response_format": "url",
    }
    if image_sources:
        payload["images"] = [{"image_url": src} for src in image_sources]
    endpoint = "edits" if image_sources else "generations"

    response = await asyncio.to_thread(
        requests.post,
        f"{settings['base_url'].rstrip('/')}/images/{endpoint}",
        headers={"Authorization": f"Bearer {settings['api_key']}"},
        json=payload,
        timeout=300,
    )
    response.raise_for_status()

    image_url = response.json()["data"][0]["url"]
    if not isinstance(image_url, str) or not image_url.startswith(("http://", "https://")):
        raise ValueError("SenseNova image response missing URL")
    return image_url
