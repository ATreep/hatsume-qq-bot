"""Model factory functions for LLM, embedding, image, and video generation."""

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any, Literal, Optional

from . import config as _config
from .config import (
    DEEPSEEK_V4_FLASH_FREE,
    EMBEDDING_MODEL,
    GROK_IMAGINE_IMAGE,
    GPT_5_6_LUNA,
    KEGEAI_API_KEY,
    KEGEAI_BASE_URL,
    OPENCODE_API_KEY,
    OPENCODE_ZEN_BASE_URL,
    SEEDANCE_1_0,
    SEEDANCE_1_5,
    SEEDREAM_5_0_LITE,
    VOLCENGINE_BASE_URL,
    get_api_key,
    get_base_url,
)

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from volcenginesdkarkruntime import Ark

# Monkey-patch: preserve non-OpenAI fields through message round-trips.
# langchain_openai strips extra fields when serializing AIMessage dicts,
# but provider-specific APIs require them:
#   - reasoning_content: DeepSeek-compatible APIs (e.g. mimo, deepseek)
#   - thought_signature: Gemini OpenAI-compatible API (required for tool calls)
import langchain_core.messages as _lc_messages
import langchain_openai.chat_models.base as _openai_base

_orig_convert_dict = _openai_base._convert_dict_to_message
_orig_convert_msg = _openai_base._convert_message_to_dict


def _patched_convert_dict(_dict):
    msg = _orig_convert_dict(_dict)
    if isinstance(msg, _lc_messages.AIMessage):
        rc = _dict.get("reasoning_content")
        if rc:
            msg.additional_kwargs["reasoning_content"] = rc
        # Preserve thought_signature from each tool call (Gemini requirement)
        tool_calls = _dict.get("tool_calls") or []
        sigs = {}
        for tc in tool_calls:
            ts = tc.get("thought_signature")
            if ts and tc.get("id"):
                sigs[tc["id"]] = ts
        if sigs:
            msg.additional_kwargs["thought_signatures"] = sigs
    return msg


def _patched_convert_msg(message, **kwargs):
    d = _orig_convert_msg(message, **kwargs)
    if isinstance(message, _lc_messages.AIMessage):
        if "reasoning_content" in message.additional_kwargs:
            d["reasoning_content"] = message.additional_kwargs["reasoning_content"]
        # Restore thought_signature to each tool call (Gemini requirement)
        sigs = message.additional_kwargs.get("thought_signatures", {})
        if sigs and "tool_calls" in d:
            for tc in d["tool_calls"]:
                ts = sigs.get(tc.get("id", ""))
                if ts:
                    tc["thought_signature"] = ts
    return d


_openai_base._convert_dict_to_message = _patched_convert_dict
_openai_base._convert_message_to_dict = _patched_convert_msg


def get_volcengine_api_model(
    model_name: str,
    thinking: bool = True,
    effort_enable: bool = True,
    temperature: float = 2,
) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=get_base_url("volc_plan"),
        model=model_name,
        api_key=get_api_key("volc_plan"),
        temperature=temperature,
        extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
        reasoning_effort="high" if thinking and effort_enable else None,
    )

def get_standard_api_model(model_name: str):
    return ChatOpenAI(
        base_url=get_base_url(),
        model=model_name,
        api_key=get_api_key(),
        use_responses_api=True,
        context_management=[  # pyright: ignore[reportCallIssue]
            {"type": "compaction", "compact_threshold": 900_000}
        ],
    )

def get_advance_model(thinking: bool = True) -> ChatOpenAI:
    model_name = _config.ADVANCE_MODEL_NAME
    print(f"⚡ Using {model_name} for advance model")
    return get_standard_api_model(model_name)


def get_lite_model(thinking: bool = True) -> ChatOpenAI:
    return get_standard_api_model(GPT_5_6_LUNA)


def get_mini_model(thinking: bool = True) -> ChatOpenAI:
    return get_standard_api_model(GPT_5_6_LUNA)


def get_code_model() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=OPENCODE_ZEN_BASE_URL,
        model=DEEPSEEK_V4_FLASH_FREE,
        extra_body={"thinking": {"type": "enabled"}},
        reasoning_effort="high",
        api_key=lambda: OPENCODE_API_KEY,
    )


def choose_video_model() -> Literal["1.0", "1.5"]:
    return "1.5" if random.random() < 0.5 else "1.0"


def get_embedding_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        base_url=get_base_url("sf"),
        model=EMBEDDING_MODEL,
        api_key=get_api_key("sf"),
        chunk_size=32,
    )


async def _resolve_image_srcs(images: list[str]) -> list[str]:
    """Convert sandbox absolute paths to base64 data URIs.

    URLs (http://, https://) and existing data URIs pass through unchanged.
    Absolute Unix paths (starting with /) are read from the Docker sandbox
    and converted to base64 data URIs with a detected MIME type.
    """
    import shlex

    from .infra import ensure_container_running, run_cmd

    _MIME_FALLBACK: dict[str, str] = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "svg": "image/svg+xml",
    }

    resolved: list[str] = []
    for src in images:
        if src.startswith(("http://", "https://", "data:")):
            resolved.append(src)
            continue
        if src.startswith("/"):
            await ensure_container_running()
            mime = (await run_cmd(
                f"file --mime-type -b {shlex.quote(src)}"
            )).strip()
            if not mime or "/" not in mime:
                ext = src.rsplit(".", 1)[-1].lower() if "." in src else "png"
                mime = _MIME_FALLBACK.get(ext, "image/png")
            b64 = (await run_cmd(
                f"base64 -w 0 {shlex.quote(src)}"
            )).strip()
            resolved.append(f"data:{mime};base64,{b64}")
        else:
            resolved.append(src)
    return resolved


async def generate_image_for_volc(
    prompt: str,
    images: list[str],
) -> str:
    """Generate image via Seedream. Returns HTTP URL."""
    images = await _resolve_image_srcs(images)
    client = Ark(base_url=get_base_url("volc_plan"), api_key=get_api_key("volc_plan")())

    model_name = SEEDREAM_5_0_LITE

    response = client.images.generate(
        model=model_name,
        prompt=prompt,
        image=images,
        sequential_image_generation="disabled",
        response_format="url",
        size="2K",
        stream=False,
        watermark=False,
    )

    img_url = response.data[0].url
    assert img_url.startswith("http")
    return img_url





def generate_image_for_kege(
    prompt: str,
    aspect_ratio: str = "1:1",
    resolution: str = "1k",
    base_url: str = KEGEAI_BASE_URL,
    api_key: str = KEGEAI_API_KEY,
) -> str:
    """Generate image via Kege AI (grok-imagine-image). Returns image URL."""
    import requests as _requests


    payload: dict = {
        "model": GROK_IMAGINE_IMAGE,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "response_format": "url",
    }

    resp = _requests.post(
        f"{base_url}/images/generations",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    img_url: str = data["data"][0]["url"]
    assert img_url.startswith("http")
    return img_url


async def generate_video_for(
    video_prompt: str,
    image_url: Optional[str],
    duration: Literal[10, 15, 20, 25] = 10,
    model: Literal["1.0", "1.5"] = "1.5",
    poll_interval: int = 5,
    max_wait_time: int = 1200,
) -> Optional[str]:
    """Generate video via Seedance. Returns URL or None on failure."""
    client = Ark(base_url=VOLCENGINE_BASE_URL, api_key=os.environ.get("ARK_API_KEY"))

    content: list[dict[str, Any]] = [{"type": "text", "text": video_prompt}]
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    model_name = SEEDANCE_1_0 if model == "1.0" else SEEDANCE_1_5
    try:
        print(f"✅ 提交视频生成任务，模型：{model_name}")
        task = client.content_generation.tasks.create(
            model=model_name,
            content=content,  # type: ignore[arg-type]
            ratio="16:9",
            duration=duration,
            watermark=False,
            generate_audio=True,
        )

        task_id = task.id
        print(f"✅ 任务提交成功，任务ID：{task_id}")

        start_time = time.time()
        while True:
            if time.time() - start_time > max_wait_time:
                print(f"❌ 任务超时（{max_wait_time}秒）")
                return None

            task_status = client.content_generation.tasks.get(task_id=task_id)
            status = task_status.status

            if status == "succeeded":
                video_url = task_status.content.video_url
                print(f"🎉 视频生成完成！时长：{duration}秒")
                return video_url

            if status == "failed":
                print(f"❌ 生成失败：{task_status.error}")
                return None

            await asyncio.sleep(poll_interval)

    except Exception as e:
        print(f"❌ 执行异常：{str(e)}")
        return None
