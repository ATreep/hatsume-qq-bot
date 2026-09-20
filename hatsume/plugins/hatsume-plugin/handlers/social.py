"""Group-isolated QQ profile likes and leaderboard."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as store
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from ..config import ADMIN_QQ_ID
from ..group_runtime import validate_group_id
from ..utils import get_group_member_name


_likes_lock = threading.Lock()


def _likes_path() -> Path:
    return Path(store.get_plugin_data_file("likes.json"))


def _atomic_write_likes(path: Path, groups: dict[str, dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="likes-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(groups, temporary_file, ensure_ascii=False)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _normalize_counter_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("like counters must be an object")
    counters: dict[str, int] = {}
    for raw_user_id, raw_count in value.items():
        user_id = str(raw_user_id)
        if (
            not user_id.isdigit()
            or isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
        ):
            raise ValueError("invalid like counter")
        count = raw_count
        if count < 0:
            raise ValueError("invalid like counter")
        counters[user_id] = count
    return counters


def _load_like_groups(path: Path | None = None) -> dict[str, dict[str, int]]:
    resolved_path = path or _likes_path()
    try:
        raw: Any = json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("likes.json must contain an object")

    if any(not isinstance(value, dict) for value in raw.values()):
        raise ValueError("likes.json must use group-scoped counters")

    groups: dict[str, dict[str, int]] = {}
    for raw_group_id, counters in raw.items():
        try:
            group_id = validate_group_id(int(raw_group_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid likes group ID") from exc
        groups[str(group_id)] = _normalize_counter_map(counters)
    return groups


def _get_like_times(group_id: int, user_id: str) -> int:
    with _likes_lock:
        groups = _load_like_groups()
        return groups.get(str(validate_group_id(group_id)), {}).get(str(user_id), 0)


def _cumulate_user_like(group_id: int, user_id: str, likes: int) -> int:
    resolved_group_id = validate_group_id(group_id)
    if isinstance(likes, bool) or not isinstance(likes, int) or likes < 0:
        raise ValueError("likes must be a non-negative integer")
    with _likes_lock:
        groups = _load_like_groups()
        counters = groups.setdefault(str(resolved_group_id), {})
        total = counters.get(str(user_id), 0) + likes
        counters[str(user_id)] = total
        _atomic_write_likes(_likes_path(), groups)
        return total


async def _resolve_rank_group(event: GroupMessageEvent, matcher, args: Message) -> int:
    text = args.extract_plain_text().strip()
    if not text:
        return validate_group_id(event.group_id)
    parts = text.split()
    try:
        if len(parts) != 1:
            raise ValueError
        group_id = validate_group_id(int(parts[0]))
    except ValueError:
        await matcher.finish("群号必须是正整数。\n用法：/likerank [群号]")
        return validate_group_id(event.group_id)
    if (
        group_id != event.group_id
        and str(event.get_user_id()) != str(ADMIN_QQ_ID)
    ):
        await matcher.finish("只有管理员可以访问其他群的数据。")
        return validate_group_id(event.group_id)
    return group_id


async def handle_likerank(
    bot: Bot,
    event: GroupMessageEvent,
    matcher,
    args: Message,
) -> None:
    """Show one group's top 10 users by accumulated like count."""
    group_id = await _resolve_rank_group(event, matcher, args)
    try:
        with _likes_lock:
            counters = _load_like_groups().get(str(group_id), {})
    except Exception as exc:
        print(f"Failed to read group likes: {exc}")
        await matcher.finish("点赞数据暂时不可用。")
        return

    top10 = sorted(counters.items(), key=lambda item: item[1], reverse=True)[:10]
    if not top10:
        await matcher.finish("暂无点赞数据。")
        return

    scope = "当前群" if group_id == event.group_id else f"群 {group_id}"
    lines = [f"🏆 {scope}点赞排行榜 Top 10：\n"]
    for rank, (user_id, count) in enumerate(top10, 1):
        try:
            user_name = await get_group_member_name(bot, group_id, int(user_id))
        except Exception:
            user_name = user_id
        lines.append(f"{rank}. {user_name} (ID: {user_id}) - {count} 次点赞")
    await matcher.finish("\n".join(lines))


async def handle_like(bot: Bot, event: GroupMessageEvent, matcher) -> None:
    like_time = 0
    while True:
        try:
            await bot.send_like(user_id=event.get_user_id(), times=10)
        except Exception as exc:
            print(exc)
            break
        like_time += 10

    user_name = "你"
    try:
        user_name = await get_group_member_name(bot, event.group_id, event.user_id)
    except Exception:
        pass

    if like_time == 0:
        await matcher.finish(f"点赞失败，今日给 {user_name} 的点赞已达上限。")
        return

    try:
        total = _cumulate_user_like(
            event.group_id,
            event.get_user_id(),
            like_time,
        )
    except Exception as exc:
        print(f"Failed to persist group likes: {exc}")
        await matcher.finish("点赞成功，但累计数据暂时无法保存。")
        return
    await matcher.finish(
        f"刚刚成功点赞 {like_time} 次，已经累计为 {user_name} 点赞 {total} 次。"
    )
