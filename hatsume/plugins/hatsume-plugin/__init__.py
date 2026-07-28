"""Hatsume plugin entry point: NoneBot event wiring and matcher registration."""

from __future__ import annotations

import nonebot
from nonebot import on_message, on_command, on_fullmatch, on_notice
from nonebot.rule import is_type, keyword, to_me
from nonebot.adapters.onebot.v11 import (
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    Message,
    PokeNotifyEvent,
)
from nonebot.exception import FinishedException
from nonebot.adapters import Bot
from nonebot.params import CommandArg

from .config import ADMIN_QQ_ID
from .handlers.dialogue import handle_group_increase, start_chat, user_chat_handle
from .handlers.tools import (
    handle_agents,
    handle_autoresponse,
    handle_clear,
    handle_generate_video,
    handle_list_skills,
    handle_membersearch,
    handle_model,
    handle_poke,
    handle_proxy_command,
    handle_resetsandbox,
    handle_shell,
    handle_timer,
)
from .handlers.social import handle_like, handle_likerank
from .memory import init_memory_system, init_tokenized_corpus  # noqa: F401 — scheduler decorator registers it
from .timer import init_scheduler

# Initialize memory system on plugin startup (DB init, JSON migration, memory load)
init_memory_system()

# Initialize timer scheduler after the OneBot connection is established.
# Registering on bot-connect (rather than on_startup) guarantees the adapter
# handshake is done, so timer delivery / auto-response callbacks that send
# messages have a live bot available when they fire.
nonebot.get_driver().on_bot_connect(init_scheduler)


# ---------------------------------------------------------------------------
# Monkey-patch: _check_at_me scans ALL segments, not just first and last.
#
# NoneBot2's default _check_at_me only inspects event.message[0] and
# event.message[-1]. When a user sends [image] + @bot + text, the @ lands
# in the middle and is never detected. This patch scans every segment.
# ---------------------------------------------------------------------------
def _patched_check_at_me(bot: Bot, event: GroupMessageEvent) -> None:
    from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

    if not isinstance(event, MessageEvent):
        return

    if not event.message:
        event.message.append(MessageSegment.text(""))

    if event.message_type == "private":
        event.to_me = True
        return

    def _is_at_me_seg(segment: MessageSegment) -> bool:
        return segment.type == "at" and str(segment.data.get("qq", "")) == str(
            event.self_id
        )

    # Check the first segment (original behaviour preserved)
    if _is_at_me_seg(event.message[0]):
        event.to_me = True
        event.message.pop(0)
        if event.message and event.message[0].type == "text":
            event.message[0].data["text"] = event.message[0].data["text"].lstrip()
            if not event.message[0].data["text"]:
                del event.message[0]
        if event.message and _is_at_me_seg(event.message[0]):
            event.message.pop(0)
            if event.message and event.message[0].type == "text":
                event.message[0].data["text"] = event.message[0].data["text"].lstrip()
                if not event.message[0].data["text"]:
                    del event.message[0]

    # Scan ALL remaining segments — not just the last one.
    if not event.to_me:
        for i, seg in enumerate(event.message):
            if _is_at_me_seg(seg):
                event.to_me = True
                del event.message[i]
                break

    if not event.message:
        event.message.append(MessageSegment.text(""))


import nonebot.adapters.onebot.v11.bot as _onebot_bot  # noqa: E402
_onebot_bot._check_at_me = _patched_check_at_me  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Command matchers
# ---------------------------------------------------------------------------
shell_cmd = on_command(
    "ccsh", 
    rule=lambda event: str(event.get_user_id()) == ADMIN_QQ_ID, 
    aliases={"cc"}, 
    priority=10, 
    block=True
)
model_cmd = on_command(
    "model",
    rule=lambda event: str(event.get_user_id()) == ADMIN_QQ_ID,
    priority=10,
    block=True,
)
generate_video_cmd = on_command(cmd="video", priority=10, block=True)
like_match = on_fullmatch(("赞我", "互赞", "点赞"), priority=10, block=True)
timer_cmd = on_command("timer", priority=10, block=True)
skills_cmd = on_command("skills", priority=10, block=True)
likerank_cmd = on_command("likerank", priority=10, block=True)
membersearch_cmd = on_command("membersearch", priority=10, block=True)
resetsandbox_cmd = on_command(
    "resetsandbox",
    rule=lambda event: str(event.get_user_id()) == ADMIN_QQ_ID,
    priority=10,
    block=True,
)
agents_cmd = on_command("agents", priority=10, block=True)
clear_cmd = on_command("clear", rule=lambda event: str(event.get_user_id()) == ADMIN_QQ_ID, priority=10, block=True)
autoresponse_cmd = on_command("autoresponse", rule=lambda event: str(event.get_user_id()) == ADMIN_QQ_ID, priority=10, block=True)
proxy_cmd = on_command("proxy", priority=10, block=True)

# ---------------------------------------------------------------------------
# Chat matchers
# ---------------------------------------------------------------------------
mention_rule = keyword("初芽", "hatsume", "出芽")

start_chat_by_at_and_mentioned = on_message(
    rule=to_me() & mention_rule, priority=20, block=True
)
start_chat_by_at = on_message(rule=to_me(), priority=30, block=False)
start_chat_by_mentioned = on_message(rule=mention_rule, priority=30, block=False)
user_chat = on_message(priority=100)

# ---------------------------------------------------------------------------
# Poke (戳一戳) notice — auto-reply with random ACG photo
# ---------------------------------------------------------------------------
poke_notice = on_notice(
    rule=is_type(PokeNotifyEvent),
    priority=10,
    block=False,
)
group_increase_notice = on_notice(
    rule=is_type(GroupIncreaseNoticeEvent),
    priority=10,
    block=False,
)

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
@shell_cmd.handle()
async def _(args: Message = CommandArg()):
    await handle_shell(shell_cmd, args)


@model_cmd.handle()
async def _(args: Message = CommandArg()):
    await handle_model(model_cmd, args)


@generate_video_cmd.handle()
async def _(args: Message = CommandArg()):
    await handle_generate_video(generate_video_cmd, args)


# ---------------------------------------------------------------------------
# Timer handler
# ---------------------------------------------------------------------------
@timer_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_timer(bot, event, timer_cmd, args)


# ---------------------------------------------------------------------------
# Skills handler
# ---------------------------------------------------------------------------
@skills_cmd.handle()
async def _(args: Message = CommandArg()):
    await handle_list_skills(skills_cmd, args)


# ---------------------------------------------------------------------------
# Like handler
# ---------------------------------------------------------------------------
@like_match.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await handle_like(bot, event, like_match)


# ---------------------------------------------------------------------------
# Likerank handler
# ---------------------------------------------------------------------------
@likerank_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await handle_likerank(bot, event, likerank_cmd)


@membersearch_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_membersearch(bot, event, membersearch_cmd, args)


@resetsandbox_cmd.handle()
async def _():
    await handle_resetsandbox(resetsandbox_cmd)


@agents_cmd.handle()
async def _():
    await handle_agents(agents_cmd)


@clear_cmd.handle()
async def _():
    await handle_clear(clear_cmd)


@autoresponse_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_autoresponse(bot, event, autoresponse_cmd, args)


@proxy_cmd.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_proxy_command(event, proxy_cmd, args)


# ---------------------------------------------------------------------------
# Chat handlers
# ---------------------------------------------------------------------------
@start_chat_by_at_and_mentioned.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    try:
        await start_chat(start_chat_by_at_and_mentioned, event)
    except FinishedException:
        pass
    await user_chat_handle(bot, event, user_chat)


@start_chat_by_at.handle()
async def _(event: GroupMessageEvent):
    await start_chat(start_chat_by_at, event)


@start_chat_by_mentioned.handle()
async def _(event: GroupMessageEvent):
    await start_chat(start_chat_by_mentioned, event)


@user_chat.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await user_chat_handle(bot, event, user_chat)


# ---------------------------------------------------------------------------
# Poke notice handler
# ---------------------------------------------------------------------------
@poke_notice.handle()
async def _(bot: Bot, event: PokeNotifyEvent):
    if event.is_tome():
        await handle_poke(bot, event)


@group_increase_notice.handle()
async def _(bot: Bot, event: GroupIncreaseNoticeEvent):
    await handle_group_increase(bot, event)
