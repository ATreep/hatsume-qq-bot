"""Normalize and parse OneBot V11 merged-forward messages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import Message

from ..config import FORWARD_API_TIMEOUT_SECONDS, MAX_FORWARD_DEPTH
from ..utils import message_to_json

logger = logging.getLogger(__name__)

_FETCH_FAILED_TEXT = "（合并转发消息获取失败）"
_DEPTH_EXCEEDED_TEXT = "（嵌套层数过多，已省略）"


def has_forward_segment(msg: Message) -> str | None:
    """Return the first non-empty merged-forward ID in ``msg``."""
    for segment in msg:
        if segment.type != "forward":
            continue
        forward_id = segment.data.get("id")
        if forward_id is not None and str(forward_id):
            return str(forward_id)
    return None


def _placeholder(content: str, depth: int) -> dict[str, Any]:
    return message_to_json("系统", 0, content, "", depth=depth or None)


def _extract_nodes(response: Any) -> list[Any]:
    """Accept the OneBot response and compatible implementation variants.

    OneBot V11 specifies ``{"message": [node segments]}``. Some implementations
    expose ``messages`` instead, while older adapters already unwrap the node list.
    """
    value = response
    for _ in range(3):
        if isinstance(value, list):
            return value
        if not isinstance(value, dict):
            break
        if _looks_like_node(value):
            return [value]
        for key in ("message", "messages", "data"):
            if key in value:
                value = value[key]
                break
        else:
            break
    raise ValueError("get_forward_msg returned no node list")


def _extract_node(node: Any) -> tuple[int, str, Any, str]:
    """Return ``(user_id, nickname, content, time)`` from a forward node."""
    if isinstance(node, str):
        return 0, "未知", node, ""
    if not isinstance(node, dict):
        return 0, "未知", str(node), ""

    payload = node.get("data") if node.get("type") == "node" else node
    if not isinstance(payload, dict):
        return 0, "未知", str(payload), ""

    sender = payload.get("sender") or node.get("sender") or {}
    if not isinstance(sender, dict):
        sender = {}

    raw_user_id = payload.get("user_id", sender.get("user_id", 0))
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        user_id = 0

    nickname = payload.get("nickname") or sender.get("card") or sender.get("nickname")
    content = payload.get("content", payload.get("message", ""))
    node_time = payload.get("time", node.get("time", ""))
    return user_id, str(nickname or user_id or "未知"), content, str(node_time or "")


def _coerce_segments(content: Any) -> list[Any]:
    if content is None:
        return []
    if isinstance(content, dict):
        return [content]
    if isinstance(content, str):
        if "[CQ:" not in content:
            return [{"type": "text", "data": {"text": content}}]
        try:
            parsed = list(Message(content))
            if all(hasattr(segment, "type") for segment in parsed):
                return parsed
        except (TypeError, ValueError):
            pass
        return [{"type": "text", "data": {"text": content}}]
    if isinstance(content, Iterable):
        return list(content)
    return [{"type": "text", "data": {"text": str(content)}}]


def _segment_type_and_data(segment: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(segment, str):
        return "text", {"text": segment}
    if isinstance(segment, dict):
        segment_type = str(segment.get("type", ""))
        data = segment.get("data", {})
    else:
        segment_type = str(getattr(segment, "type", ""))
        data = getattr(segment, "data", {})
    if isinstance(data, dict):
        return segment_type, data
    if segment_type == "text":
        return segment_type, {"text": str(data)}
    return segment_type, {"value": data}


def _looks_like_node(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("type") == "node":
        return True
    has_sender = any(key in value for key in ("sender", "user_id", "nickname"))
    has_content = any(key in value for key in ("content", "message"))
    return has_sender and has_content


def _extract_inline_nodes(
    segment: Any,
    segment_type: str,
    data: dict[str, Any],
) -> list[Any] | None:
    """Return nested nodes embedded directly in a message segment.

    OneBot implementations represent nested merged-forwards inconsistently:
    some provide another ``forward`` ID, while others inline ``node`` segments
    or put a node list under ``messages``, ``message``, ``nodes``, or ``content``.
    """
    if segment_type == "node":
        return [segment]

    source: dict[str, Any] | None = None
    if segment_type == "forward":
        source = data
    elif not segment_type and isinstance(segment, dict):
        if _looks_like_node(segment):
            return [segment]
        source = segment

    if source is None:
        return None

    for key in ("messages", "message", "nodes", "content"):
        if key not in source:
            continue
        candidate = source[key]
        try:
            return _extract_nodes(candidate)
        except ValueError:
            continue
    return None


def _render_segment(segment_type: str, data: dict[str, Any]) -> str:
    """Render non-forward segments without silently dropping their meaning."""
    if segment_type == "text":
        return str(data.get("text", ""))
    if segment_type == "image":
        source = data.get("url") or data.get("file")
        return f" ![图片（临时链接）]({source}) " if source else " [图片] "
    if segment_type == "at":
        return f" @{data.get('qq', '未知用户')} "
    if segment_type == "face":
        return f" [表情 id={data.get('id', '')}] "
    if segment_type in {"record", "video"}:
        source = data.get("url") or data.get("file", "")
        return f" [{segment_type} {source}] "
    if segment_type in {"json", "xml"}:
        return f" [{segment_type.upper()}消息: {data.get('data', '')}] "
    if segment_type:
        return f" [{segment_type}: {data}] "
    return ""


async def _parse_nodes(
    bot: Bot,
    nodes: list[Any],
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Parse fetched or inline node lists through the same recursive path."""
    if depth > MAX_FORWARD_DEPTH:
        return [_placeholder(_DEPTH_EXCEEDED_TEXT, depth)]

    messages: list[dict[str, Any]] = []
    for node in nodes:
        user_id, nickname, raw_content, node_time = _extract_node(node)
        segments = _coerce_segments(raw_content)
        text_parts: list[str] = []

        def flush_text() -> None:
            text = "".join(text_parts).strip()
            text_parts.clear()
            if text:
                messages.append(
                    message_to_json(
                        nickname,
                        user_id,
                        text,
                        node_time,
                        depth=depth or None,
                    )
                )

        for segment in segments:
            segment_type, data = _segment_type_and_data(segment)
            inline_nodes = _extract_inline_nodes(segment, segment_type, data)
            if segment_type != "forward" and inline_nodes is None:
                text_parts.append(_render_segment(segment_type, data))
                continue

            flush_text()
            nested_depth = depth + 1
            if inline_nodes is not None:
                nested_messages = await _parse_nodes(bot, inline_nodes, nested_depth)
            else:
                nested_id = data.get("id")
                if nested_id is not None and str(nested_id):
                    nested_messages = await parse_forward_messages(
                        bot, str(nested_id), nested_depth
                    )
                else:
                    nested_messages = []

            if not nested_messages:
                text_parts.append(" [无法读取的嵌套合并转发] ")
                continue
            messages.append(
                {
                    "type": "forward",
                    "depth": nested_depth,
                    "user": {"id": user_id, "name": nickname},
                    "messages": nested_messages,
                }
            )

        flush_text()
        if not segments:
            messages.append(
                message_to_json(
                    nickname,
                    user_id,
                    "",
                    node_time,
                    depth=depth or None,
                )
            )

    return messages


async def parse_forward_messages(
    bot: Bot,
    forward_id: str,
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Resolve a merged forward into the unified recursive LLM message format."""
    if depth > MAX_FORWARD_DEPTH:
        return [_placeholder(_DEPTH_EXCEEDED_TEXT, depth)]

    try:
        response = await asyncio.wait_for(
            bot.call_api("get_forward_msg", id=forward_id),
            timeout=FORWARD_API_TIMEOUT_SECONDS,
        )
        nodes = _extract_nodes(response)
    except Exception as exc:
        logger.warning("Failed to resolve forward message %s: %s", forward_id, exc)
        return [_placeholder(_FETCH_FAILED_TEXT, depth)]

    return await _parse_nodes(bot, nodes, depth)


async def resolve_forward_content(
    bot: Bot,
    msg: Message,
    depth: int = 0,
) -> list[dict[str, Any]] | None:
    """Resolve the first merged-forward segment, or return ``None``."""
    forward_id = has_forward_segment(msg)
    if forward_id is None:
        return None
    return await parse_forward_messages(bot, forward_id, depth)


def collect_people_from_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, int | str]]:
    """Recursively collect unique, non-system senders."""
    seen: set[int] = set()
    people: list[dict[str, int | str]] = []

    def collect(items: list[dict[str, Any]]) -> None:
        for item in items:
            user = item.get("user", {})
            try:
                user_id = int(user.get("id", 0))
            except (TypeError, ValueError):
                user_id = 0
            if user_id and user_id not in seen:
                seen.add(user_id)
                people.append(
                    {"user_id": user_id, "user_name": user.get("name", str(user_id))}
                )
            if item.get("type") == "forward":
                nested = item.get("messages", [])
                if isinstance(nested, list):
                    collect(nested)

    collect(messages)
    return people
