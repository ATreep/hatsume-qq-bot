"""Model factory functions for LLM, embedding, and image generation."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import subprocess
import uuid
from typing import Any, Literal

import httpx

# Preserve provider-specific response fields across LangChain message
# conversions. Both DeepSeek-compatible reasoning and Gemini-compatible tool
# calls require these fields to be sent back on later turns.
import langchain_core.messages as _lc_messages
import langchain_openai.chat_models.base as _openai_base
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .model_config import get_model_config_store
from .model_factory import entry_label, get_model, run_with_failover
from .model_factory import get_embedding_model as get_role_embedding_model

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


def _systemone_transport(settings: dict[str, Any]) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings["base_url"], model=settings["model"],
        api_key=settings["api_key"], use_responses_api=False,
        timeout=settings.get("timeout"),
    )


def get_typesafe_model() -> BaseChatModel:
    """Build the transport for the separate System One /systemone API."""
    return _systemone_transport(get_model_config_store().resolve("systemone"))


def get_systemone_chain() -> list[tuple[str, float | None, ChatOpenAI]]:
    """System One transports in failover order: (label, timeout, model)."""
    return [
        (entry_label(settings), settings.get("timeout"), _systemone_transport(settings))
        for settings in get_model_config_store().resolve_chain("systemone")
    ]


def get_jev_model() -> BaseChatModel:
    return get_typesafe_model()


def get_intent_model() -> BaseChatModel:
    return get_jev_model()


def get_code_model(reasoning_effort: ReasoningEffort | None = None) -> BaseChatModel:
    return get_model("coding", reasoning_effort=reasoning_effort)


def get_embedding_model() -> Embeddings:
    return get_role_embedding_model("embedding")


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

async def generate_image_for_openai(
    prompt: str,
    images: list[str] | None = None,
    *,
    model: str | None = None,
) -> str:
    """Generate or edit an image, returning an HTTP URL or sandbox file URI."""
    image_sources = await _resolve_image_srcs(images or [])
    role = "image_edit" if image_sources else "image_gen"
    endpoint = "edits" if image_sources else "generations"
    chain = get_model_config_store().resolve_chain(role)
    if model:
        # An explicit model ID names a model of the primary provider only.
        chain[0]["model"] = model

    async def request(settings: dict[str, Any]) -> str:
        payload: dict[str, Any] = {
            "model": settings["model"],
            "prompt": prompt,
            "n": 1,
            "size": "auto",
        }
        if image_sources:
            payload["images"] = [{"image_url": src} for src in image_sources]
        print(
            f"🖼️ [image] request role={role} model={settings['model']} "
            f"references={len(image_sources)} prompt_chars={len(prompt)}"
        )
        timeout = settings.get("timeout", 300)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings['base_url'].rstrip('/')}/images/{endpoint}",
                headers={"Authorization": f"Bearer {settings['api_key']}"},
                json=payload,
            )
            response.raise_for_status()
            response_data = response.json()

        if not isinstance(response_data, dict):
            raise ValueError("OpenAI image response missing image data")
        data = response_data.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise ValueError("OpenAI image response missing image data")
        image = data[0]
        encoded = image.get("b64_json")
        if isinstance(encoded, str) and encoded:
            import tempfile

            from .group_runtime import get_current_group_id
            from .infra import copy_host_file_to_sandbox

            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("OpenAI image response contains invalid base64") from exc
            if not image_bytes:
                raise ValueError("OpenAI image response contains empty image data")
            destination = f"/tmp/hatsume-generated-{uuid.uuid4().hex}.png"
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
                    temporary_path = Path(file.name)
                    file.write(image_bytes)
                await copy_host_file_to_sandbox(
                    temporary_path, destination, timeout=30,
                    group_id=get_current_group_id(),
                )
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            print(f"🖼️ [image] completed role={role} output=sandbox bytes={len(image_bytes)}")
            return f"file://{destination}"
        image_url = image.get("url")
        if not isinstance(image_url, str) or not image_url.startswith(("http://", "https://")):
            raise ValueError("OpenAI image response missing URL or base64 image")
        print(f"🖼️ [image] completed role={role} output=url")
        return image_url

    # HTTP enforces each entry timeout; failover retains cancellation semantics.
    return await run_with_failover(
        [
            (entry_label(settings), None, lambda settings=settings: request(settings))
            for settings in chain
        ],
        f"image model ({role})",
    )


async def generate_tts_audio(text: str) -> str:
    """Synthesize Hatsume voice and return an MP3 sandbox path."""
    from openai import AsyncOpenAI

    from .prompts import TTS_VOICE_PROMPT

    settings = get_model_config_store().resolve("tts")
    output_dir = Path("/tmp")
    wav_path = output_dir / f"hatsume-tts-{uuid.uuid4().hex}.wav"
    mp3_path = output_dir / f"hatsume-tts-{uuid.uuid4().hex}.mp3"

    client = AsyncOpenAI(
        api_key=settings["api_key"],
        base_url=settings["base_url"],
        timeout=settings.get("timeout"),
    )
    try:
        completion = await client.chat.completions.create(
            model=settings["model"],
            messages=[
                {"role": "user", "content": TTS_VOICE_PROMPT},
                {"role": "assistant", "content": text},
            ],
            audio={"format": "wav", "optimize_text_preview": False},
        )
        audio = getattr(completion.choices[0].message, "audio", None)
        data = getattr(audio, "data", None)
        if not isinstance(data, str) or not data:
            raise ValueError("TTS response did not contain audio data")
        audio_bytes = base64.b64decode(data)
    finally:
        await client.close()

    print(f"🔊 [tts] synthesizing {len(text)} characters with {settings['model']}")
    wav_path.write_bytes(audio_bytes)
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    finally:
        wav_path.unlink(missing_ok=True)
    print(f"🔊 [tts] generated sandbox audio: {mp3_path}")
    return str(mp3_path)
