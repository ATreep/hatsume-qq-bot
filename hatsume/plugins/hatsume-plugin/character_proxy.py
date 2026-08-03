"""Group-local, RAM-only character proxy state."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from langchain.messages import HumanMessage

from .memory import get_recent_user_memories
from .models import get_mini_model
from .group_runtime import (
    get_current_group_runtime,
    group_runtime_registry,
    validate_group_id,
)
from .prompts import (
    build_character_profile_generation_prompt,
    build_character_proxy_role_prompt,
)

_MEMORY_LIMIT = 100
_PROFILE_TIMEOUT_SECONDS = 25


@dataclass(frozen=True, slots=True)
class CharacterProxy:
    user_id: int
    user_name: str
    behavior_prompt: str
    aliases: tuple[str, ...]
    auto_terminate_at: str


@dataclass(frozen=True, slots=True)
class GeneratedCharacterProfile:
    behavior_prompt: str
    aliases: tuple[str, ...]


def _get_runtime(group_id: int | None = None):
    if group_id is None:
        return get_current_group_runtime()
    runtime = group_runtime_registry.get_existing(validate_group_id(group_id))
    if runtime is None:
        raise RuntimeError(f"group runtime is not initialized: {group_id}")
    return runtime


def get_character_proxy(group_id: int | None = None) -> CharacterProxy | None:
    return _get_runtime(group_id).character_proxy


def build_active_character_proxy_role_prompt(proxy: CharacterProxy) -> str:
    """Render the exact role prompt injected for an active proxy."""
    return build_character_proxy_role_prompt(
        user_id=proxy.user_id,
        user_name=proxy.user_name,
        behavior_prompt=proxy.behavior_prompt,
        aliases=proxy.aliases,
        auto_terminate_at=proxy.auto_terminate_at,
    )


def activate_character_proxy(
    *,
    user_id: int,
    user_name: str,
    behavior_prompt: str,
    aliases: tuple[str, ...] = (),
    during_time: int = 180,
    group_id: int | None = None,
) -> CharacterProxy:
    """Create the current group's single RAM proxy."""
    runtime = _get_runtime(group_id)
    if runtime.character_proxy is not None:
        raise RuntimeError("character proxy is already active")
    runtime.character_proxy = CharacterProxy(
        user_id=int(user_id),
        user_name=user_name,
        behavior_prompt=behavior_prompt,
        aliases=aliases,
        auto_terminate_at=(
            datetime.now().astimezone() + timedelta(minutes=during_time)
        ).isoformat(timespec="seconds"),
    )
    role_prompt = build_active_character_proxy_role_prompt(runtime.character_proxy)
    print(f"[character_proxy] Activated role prompt:\n{role_prompt}")
    return runtime.character_proxy


def terminate_character_proxy_state(group_id: int | None = None) -> CharacterProxy | None:
    """Destroy the active proxy, its behavior prompt, and its timeout."""
    runtime = _get_runtime(group_id)
    previous = runtime.character_proxy
    runtime.character_proxy = None
    if runtime.character_proxy_termination_handle is not None:
        runtime.character_proxy_termination_handle.cancel()
        runtime.character_proxy_termination_handle = None
    return previous


def schedule_character_proxy_termination(
    during_time: int,
    group_id: int | None = None,
) -> None:
    """Replace the current group's RAM timeout."""
    runtime = _get_runtime(group_id)
    if runtime.character_proxy_termination_handle is not None:
        runtime.character_proxy_termination_handle.cancel()
    runtime.character_proxy_termination_handle = asyncio.get_running_loop().call_later(
        during_time * 60,
        terminate_character_proxy_state,
        runtime.group_id,
    )


def message_targets_character_proxy(message: Any, sender_id: int) -> bool:
    """Return whether another user explicitly @mentions the proxied user."""
    proxy = get_character_proxy()
    if proxy is None or int(sender_id) == proxy.user_id:
        return False
    return any(
        segment.type == "at"
        and str(segment.data.get("qq", "")) == str(proxy.user_id)
        for segment in message
    )


def activate_character_proxy_peer(
    conversation_state: Any,
    *,
    message: Any,
    sender_id: int,
    session_id: str,
) -> bool:
    """Add a targeted sender to chat peers through the existing state API."""
    if not message_targets_character_proxy(message, sender_id):
        return False
    conversation_state.activate_chat(session_id)
    return True


def _extract_message_text(value: Any) -> str:
    """Extract only user-visible text from normalized message content."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.startswith(("{", "[")):
            return value
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            return value
        return _extract_message_text(parsed)
    if isinstance(value, list):
        return " ".join(_extract_message_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    if value.get("type") == "text" and "text" in value:
        return _extract_message_text(value["text"])
    if "content" in value:
        return _extract_message_text(value["content"])
    return ""


def message_mentions_character_proxy(content: Any) -> bool:
    """Return whether visible message text names the proxied user or an alias."""
    proxy = get_character_proxy()
    if proxy is None:
        return False
    message_text = _extract_message_text(content).casefold()
    names = (proxy.user_name, *proxy.aliases)
    return any(name.strip().casefold() in message_text for name in names if name.strip())


def _message_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        ).strip()
    return str(content).strip()


def _parse_generated_profile(text: str, user_name: str) -> GeneratedCharacterProfile:
    fallback = "使用自然、克制的 QQ 群聊口吻；没有依据时不要虚构该用户的经历、偏好或决定。"
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return GeneratedCharacterProfile(fallback, ())
    if not isinstance(data, dict):
        return GeneratedCharacterProfile(fallback, ())

    behavior_prompt = str(data.get("behavior_prompt", "")).strip() or fallback
    raw_aliases = data.get("aliases", [])
    aliases: list[str] = []
    seen = {user_name.strip().casefold()}
    if isinstance(raw_aliases, list):
        for item in raw_aliases:
            alias = str(item).strip()
            normalized = alias.casefold()
            if not alias or normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(alias)
            if len(aliases) >= 20:
                break
    return GeneratedCharacterProfile(behavior_prompt, tuple(aliases))


async def generate_character_profile(
    user_id: int,
    user_name: str,
) -> GeneratedCharacterProfile:
    """Generate behavior and aliases together once when proxy mode starts."""
    memories = get_recent_user_memories(user_id, _MEMORY_LIMIT)
    fallback = "使用自然、克制的 QQ 群聊口吻；没有依据时不要虚构该用户的经历、偏好或决定。"
    if not memories:
        return GeneratedCharacterProfile(fallback, ())

    try:
        response = await asyncio.wait_for(
            get_mini_model().ainvoke(
                [
                    HumanMessage(
                        build_character_profile_generation_prompt(memories, user_name)
                    )
                ]
            ),
            timeout=_PROFILE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        print(f"Character proxy profile generation failed: {exc}")
        return GeneratedCharacterProfile(fallback, ())
    return _parse_generated_profile(_message_text(response), user_name)
