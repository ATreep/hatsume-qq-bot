"""Message-match Hook triggering driven by incoming group messages."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..group_runtime import group_runtime_registry
from ..state import peer_session_id
from .store import ANY_MATCH_USER_ID, HOOK_TRIGGER_MESSAGE, HookStore

HOOK_MATCH_TEXT_LIMIT = 2_000

__all__ = [
    "HOOK_MATCH_TEXT_LIMIT",
    "activate_trigger_peer",
    "build_message_event_text",
    "dispatch_message_hooks",
    "peer_session_id",
    "select_message_hooks",
]


def activate_trigger_peer(group_id: int, user_id: int) -> bool:
    """Add the triggering member to the owning group's chat peers."""
    runtime = group_runtime_registry.get_existing(int(group_id))
    if runtime is None:
        return False
    runtime.conversation.activate_chat(peer_session_id(group_id, user_id))
    return True


def select_message_hooks(
    records: Iterable[dict[str, Any]],
    *,
    user_id: int,
    text: str,
) -> list[tuple[dict[str, Any], str]]:
    """Return ``(record, matched_text)`` for every Hook matching one message."""
    scanned = str(text)[:HOOK_MATCH_TEXT_LIMIT]
    matched: list[tuple[dict[str, Any], str]] = []
    for record in records:
        if not record.get("enabled"):
            continue
        if str(record.get("trigger_type") or "") != HOOK_TRIGGER_MESSAGE:
            continue
        trigger_user_id = record.get("match_user_id")
        if (
            trigger_user_id is not None
            and int(trigger_user_id) != ANY_MATCH_USER_ID
            and int(trigger_user_id) != int(user_id)
        ):
            continue
        pattern = str(record.get("match_pattern") or "").strip()
        if not pattern:
            continue
        try:
            match = re.search(pattern, scanned)
        except re.error:
            continue
        if match is None:
            continue
        matched.append((record, match.group(0)))
    return matched


def build_message_event_text(
    *,
    hook_name: str,
    match_pattern: str,
    group_id: int,
    user_id: int,
    user_name: str,
    text: str,
    matched_text: str,
    fired_at: float,
) -> str:
    """Render one matched message as the Hook event payload."""
    display_name = str(user_name).strip() or str(user_id)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(fired_at))
    body = str(text)[:HOOK_MATCH_TEXT_LIMIT]
    lines = [
        f"群消息命中 Hook '{hook_name}' 的匹配规则。",
        f"时间：{timestamp}",
        f"群号：{int(group_id)}",
        f"发送者：{display_name}（QQ {int(user_id)}）",
        f"匹配正则：{match_pattern}",
    ]
    if matched_text:
        lines.append(f"命中内容：{matched_text}")
    lines.append("消息原文：")
    lines.append(body)
    return "\n".join(lines)


async def dispatch_message_hooks(
    *,
    group_id: int,
    user_id: int,
    text: str,
    resolve_user_name: Callable[[], Awaitable[str]] | None = None,
    store: HookStore | None = None,
    inject_fn: Callable[..., None] | None = None,
    now: float | None = None,
) -> list[str]:
    """Fire every message-match Hook triggered by one group message."""
    if store is None:
        from . import get_store

        store = get_store()
    group_id = int(group_id)
    user_id = int(user_id)
    records = store.list_enabled_message_hooks(group_id)
    if not records:
        return []
    matches = select_message_hooks(records, user_id=user_id, text=text)
    if not matches:
        return []

    user_name = str(user_id)
    if resolve_user_name is not None:
        try:
            resolved_name = await resolve_user_name()
        except Exception as exc:  # noqa: BLE001 - display name is best effort
            print(f"🪝 [hook-message] user name lookup failed: {exc}")
        else:
            if resolved_name:
                user_name = str(resolved_name)

    if inject_fn is None:
        from ..graph.nodes import inject_hook as resolved_inject

        inject_fn = resolved_inject

    fired_at = time.time() if now is None else float(now)
    fired: list[str] = []
    for record, matched_text in matches:
        hook_name = str(record["name"])
        event_text = build_message_event_text(
            hook_name=hook_name,
            match_pattern=str(record.get("match_pattern") or ""),
            group_id=group_id,
            user_id=user_id,
            user_name=user_name,
            text=text,
            matched_text=matched_text,
            fired_at=fired_at,
        )
        try:
            inject_fn(
                group_id=group_id,
                hook_name=hook_name,
                prompt=str(record["prompt"]),
                event_text=event_text,
            )
        except Exception as exc:  # noqa: BLE001 - one Hook must not break the batch
            error = f"Hook injection failed: {exc}"
            store.record_failure(int(record["id"]), None, error, fired_at)
            print(f"🪝 [hook-message] failure hook={hook_name!r} error={error!r}")
            continue
        store.record_trigger(int(record["id"]), fired_at)
        fired.append(hook_name)
        print(f"🪝 [hook-message] fired hook={hook_name!r} group_id={group_id} user_id={user_id}")
    if fired and activate_trigger_peer(group_id, user_id):
        print(f"🪝 [hook-message] peer session active group_id={group_id} user_id={user_id}")
    return fired
