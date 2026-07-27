"""Utility functions: QQ helpers and message formatting."""

from __future__ import annotations

import time as _time
import re
from datetime import datetime

from nonebot.adapters import Bot

from .security import mask_secret_keys as mask_secret_keys


CQ_AT_PATTERN = re.compile(r"\[[ \t]*CQ:at,qq=(\d+)\]")


async def get_group_member_name(bot: Bot, group_id: int | None, user_id: int) -> str:
    """Fetch group member nickname. Falls back to QQ ID on failure."""
    if not group_id:
        return (await bot.get_stranger_info(user_id=user_id)).get("nickname")
    try:
        member_info = await bot.get_group_member_info(
            group_id=group_id, user_id=user_id, no_cache=True
        )
        return member_info["card"] if member_info["card"].strip() else member_info["nickname"]
    except Exception:
        return str(user_id)


def extract_cq_at_user_ids(text: str) -> list[int]:
    """Extract unique QQ IDs from CQ at placeholders, preserving order."""
    user_ids: list[int] = []
    seen: set[int] = set()
    for match in CQ_AT_PATTERN.finditer(text):
        uid = int(match.group(1))
        if uid not in seen:
            seen.add(uid)
            user_ids.append(uid)
    return user_ids


async def render_cq_at_placeholders(
    text: str,
    group_id: int | None,
) -> tuple[str, list[int]]:
    """Replace CQ at placeholders with @display names and return IDs to notify."""
    user_ids = extract_cq_at_user_ids(text)
    if not user_ids:
        return text, []

    bot = None
    try:
        from nonebot import get_bot

        bot = get_bot()
    except Exception:
        bot = None

    display_names: dict[int, str] = {}
    for uid in user_ids:
        if bot is None:
            display_names[uid] = str(uid)
            continue
        try:
            display_names[uid] = await get_group_member_name(bot, group_id, uid)
        except Exception:
            display_names[uid] = str(uid)

    def _replace(match: re.Match[str]) -> str:
        uid = int(match.group(1))
        return f"@{display_names.get(uid, str(uid))}"

    return CQ_AT_PATTERN.sub(_replace, text), user_ids


def get_date() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def get_qq_avatar_url(qq_id: int | str) -> str:
    return f"https://q.qlogo.cn/g?b=qq&nk={qq_id}&s=640"


def message_to_json(
    user_name: str,
    user_id: int,
    content: str | list[dict],
    msg_time: str,
    reply_to: dict | None = None,
    depth: int | None = None,
    message_id: int | None = None,
) -> dict:
    """Build a single message dict in the unified JSON format for LLM input."""
    msg: dict = {
        "type": "message",
        "time": msg_time,
        "user": {"id": user_id, "name": user_name},
        "content": content,
        "reply_to": reply_to,
    }
    if message_id is not None:
        msg["message_id"] = int(message_id)
    if depth is not None:
        msg["depth"] = depth
    return msg


def build_forward_json(
    forwarder_name: str,
    forwarder_id: int,
    messages: list[dict],
    msg_time: str,
    message_id: int | None = None,
) -> dict:
    """Build a forward message dict for LLM input."""
    result = {
        "type": "forward",
        "time": msg_time,
        "user": {"id": forwarder_id, "name": forwarder_name},
        "messages": messages,
    }
    if message_id is not None:
        result["message_id"] = int(message_id)
    return result


# ---------------------------------------------------------------------------
# Group member fuzzy search
# ---------------------------------------------------------------------------
_member_list_cache: dict[int, tuple[float, list[dict]]] = {}


async def search_group_members(
    bot: Bot, group_id: int, query: str, max_results: int = 5
) -> list[dict[str, str]]:
    """Fuzzy search group members by nickname/card.

    Two-pass matching:
    1. Substring match (case-insensitive) — ranked first (most accurate)
    2. Character-overlap — for remaining members, ranked by overlap ratio

    Returns up to max_results matches sorted by relevance.
    Each result: {"username": str, "id": str, "level": str}
    """
    if not query.strip():
        return []

    # Fetch member list (with TTL cache per group_id)
    now = _time.time()
    if group_id in _member_list_cache:
        cached_at, cached_list = _member_list_cache[group_id]
        if now - cached_at < 300:
            members = cached_list
        else:
            del _member_list_cache[group_id]
            members = await bot.get_group_member_list(group_id=group_id)
            _member_list_cache[group_id] = (now, members)
    else:
        members = await bot.get_group_member_list(group_id=group_id)
        _member_list_cache[group_id] = (now, members)

    query_lower = query.lower()

    # Build username list: (user_id, username)
    entries: list[tuple[int, str]] = []
    for m in members:
        username = m["card"].strip() if m.get("card", "").strip() else m.get("nickname", "")
        if username:
            entries.append((m["user_id"], username))

    # Pass 1: substring match (sort by length ascending — shorter = more exact)
    substring_matches: list[dict[str, str]] = []
    remaining: list[tuple[int, str]] = []
    for uid, username in entries:
        if query_lower in username.lower():
            substring_matches.append({"username": username, "id": str(uid)})
        else:
            remaining.append((uid, username))

    substring_matches.sort(key=lambda r: len(r["username"]))

    # Pass 2: character-overlap match
    query_chars = set(query)
    char_matches: list[tuple[float, int, str]] = []  # (neg_overlap, uid, username)
    for uid, username in remaining:
        username_chars = set(username)
        overlap = len(query_chars & username_chars)
        if overlap > 0:
            ratio = overlap / max(len(query_chars), len(username_chars))
            char_matches.append((-ratio, uid, username))

    # Sort by overlap ratio descending (neg → ascending = highest ratio first)
    char_matches.sort()
    for neg_ratio, uid, username in char_matches:
        substring_matches.append({"username": username, "id": str(uid)})

    # Truncate
    results = substring_matches[:max_results]

    # Fetch level for each result
    for r in results:
        try:
            info = await bot.get_group_member_info(
                group_id=group_id, user_id=int(r["id"]), no_cache=True
            )
            r["level"] = info.get("level", "未知") if isinstance(info, dict) else "未知"
        except Exception:
            r["level"] = "未知"

    return results
