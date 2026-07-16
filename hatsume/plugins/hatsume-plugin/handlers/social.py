"""Social features: QQ profile likes and leaderboard."""

from __future__ import annotations

import json

import nonebot_plugin_localstore as store
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ..utils import get_group_member_name


def _get_like_times(user_id: str) -> int:
    try:
        obj = json.loads(store.get_plugin_data_file("likes.json").read_text())
        return obj[user_id]
    except Exception:
        return 0


def _cumulate_user_like(user_id: str, likes: int) -> None:
    new_likes = _get_like_times(user_id) + likes
    try:
        obj = json.loads(store.get_plugin_data_file("likes.json").read_text())
    except Exception:
        obj = {}
    obj[user_id] = new_likes
    store.get_plugin_data_file("likes.json").write_text(json.dumps(obj))


async def handle_likerank(bot: Bot, event: GroupMessageEvent, matcher) -> None:
    """Handle /likerank command: show top 10 users by like count."""
    obj = {}
    try:
        obj = json.loads(store.get_plugin_data_file("likes.json").read_text())
    except Exception:
        await matcher.finish("暂无点赞数据。")
        return

    # Sort by like count descending
    sorted_users = sorted(obj.items(), key=lambda x: x[1], reverse=True)
    top10 = sorted_users[:10]

    if not top10:
        await matcher.finish("暂无点赞数据。")

    group_id = event.group_id
    lines = ["🏆 点赞排行榜 Top 10：\n"]

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
        except Exception as e:
            print(e)
            break
        like_time += 10

    user_name = "你"
    try:
        group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
        user_name = await get_group_member_name(bot, group_id, event.user_id)
    except Exception:
        pass

    if like_time == 0:
        fail_msg = f"点赞失败，今日给 {user_name} 的点赞已达上限。"
        await matcher.finish(fail_msg)

    _cumulate_user_like(event.get_user_id(), like_time)

    success_msg = f"刚刚成功点赞 {like_time} 次，已经累计为 {user_name} 点赞 {_get_like_times(event.get_user_id())} 次。"
    await matcher.finish(success_msg)
