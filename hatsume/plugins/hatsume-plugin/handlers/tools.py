"""Tool commands: poke handler and shell/image/video/timer/skills command handlers."""

from __future__ import annotations

import base64
import time

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import Message, MessageSegment, PokeNotifyEvent

from ..infra import cleanup_persistent_container, run_cmd
from ..models import choose_video_model, generate_video_for
from ..state import ConversationState


# ---- Section 1: Poke Handler ----


async def handle_poke(bot: Bot, event: PokeNotifyEvent) -> None:
    """When the bot is poked, export and send a random ACG photo.

    Silently ignores errors (Photos not running, album empty, etc.) to avoid
    spamming the group chat on every poke.
    """
    from ..graph.tools import _export_random_acg_photo

    host_file = await _export_random_acg_photo()
    if host_file.startswith("❌"):
        # All failures are silent — don't spam the chat
        return

    try:
        with open(host_file, "rb") as f:
            img_data = f.read()
        b64 = base64.b64encode(img_data).decode("ascii")
        await bot.send(event, MessageSegment.image(f"base64://{b64}"))
    except Exception:
        # File read / network errors: also silent
        return


# ---- Section 2: Command Handlers ----

_conv_state: ConversationState | None = None


def _wire_conv_state(state: ConversationState) -> None:
    """Wire the shared ConversationState for rate limiting."""
    global _conv_state
    _conv_state = state


async def handle_shell(matcher, args: Message) -> None:
    cmd = args.extract_plain_text()
    print("Start running shell.")
    out = await run_cmd(cmd)
    print("Running finished.")
    await matcher.finish(out)


async def handle_model(matcher, args: Message) -> None:
    """Show or update the process-local advanced model name."""
    from .. import config as runtime_config

    requested_name = args.extract_plain_text().strip()
    if not requested_name:
        await matcher.finish(
            f"当前高级模型：{runtime_config.ADVANCE_MODEL_NAME}\n"
            "Provider、Base URL 和 API Key 保持不变。"
        )
        return

    previous_name = runtime_config.ADVANCE_MODEL_NAME
    runtime_config.ADVANCE_MODEL_NAME = requested_name
    await matcher.finish(
        f"✅ 高级模型已切换：{previous_name} → {requested_name}\n"
        "仅模型名称已更改；Provider、Base URL 和 API Key 保持不变。"
    )


async def handle_generate_video(matcher, args: Message) -> None:
    prompt = args.extract_plain_text()

    input_img: str | None = None
    if args.count("image") > 0:
        first_img = next(args.include("image")) # type: ignore
        url = first_img.data.get("url")
        if url:
            input_img = url

    if _conv_state is not None and _conv_state.is_video_rate_limited():
        await matcher.finish("❌ 视频生成请求过于频繁，稍后再试。")

    print("Generate video: ", prompt)
    try:
        url = await generate_video_for(
            prompt, image_url=input_img, model=choose_video_model()
        )
        if _conv_state is not None:
            _conv_state.last_video_time = time.time()
    except Exception as e:
        await matcher.finish("❌ 视频生成失败。\n" + str(e))
    else:
        if url is None:
            await matcher.finish("❌ 视频生成失败，请稍后再试。")
        await matcher.finish(MessageSegment.video(file=url)) # type: ignore


async def handle_timer(bot, event, matcher, args: Message) -> None:
    """Handle /timer command: list, delete, update."""
    from datetime import datetime, timedelta, timezone

    from ..graph.tools import set_current_group_id
    from ..timer import get_store
    from ..timer.executor import add_jobs_for_task, cancel_task_jobs

    set_current_group_id(event.group_id)
    store = get_store()
    text = args.extract_plain_text().strip()
    parts = text.split() if text else []

    HELP = (
        "/timer 命令用法：\n\n"
        "/timer list                    列出当前群的所有定时任务\n"
        "/timer delete <id>             删除指定 ID 的定时任务\n"
        "/timer update <id> <内容> @ <时间1>, <时间2>, ..."
        "  更新定时任务的内容和触发时间\n\n"
        "时间格式：ISO 8601 带时区，如 2026-06-08T08:00:00+08:00\n"
        "多个时间用逗号分隔"
    )

    if not parts:
        await matcher.finish(HELP)

    sub = parts[0].lower()

    if sub == "list":
        tasks = store.list_tasks_by_group(event.group_id)
        if not tasks:
            await matcher.finish("当前群没有定时任务。")
        tz_shanghai = timezone(timedelta(hours=8))

        # Look up user names (cache per user_id for tasks sharing the same owner)
        from ..utils import get_group_member_name

        user_names: dict[int, str] = {}
        try:
            for task in tasks:
                uid = task["user_id"]
                if uid not in user_names:
                    user_names[uid] = await get_group_member_name(
                        bot, event.group_id, uid
                    )
        except Exception:
            pass

        lines = ["当前群的定时任务："]
        for task in tasks:
            tid = task["id"]
            uid = task["user_id"]
            prompt = task["prompt"][:50]
            owner = user_names.get(uid, str(uid))
            triggers = store.get_triggers_for_task(tid)
            trigger_strs = []
            for t in triggers:
                ts = datetime.fromtimestamp(t["trigger_at"], tz=tz_shanghai).strftime(
                    "%m/%d %H:%M"
                )
                status = "✓" if t["fired"] else "○"
                trigger_strs.append(f"{status} {ts}")
            if uid == 0:
                lines.append(
                    f"\n[{tid}]: {prompt}\n" + "  ".join(trigger_strs)
                )
            else:
                lines.append(
                f"\n[{tid}] @{owner}({uid}): {prompt}\n" + "  ".join(trigger_strs)
            )
        await matcher.finish("\n".join(lines))

    elif sub == "autocreate":
        task = store.get_auto_create()
        if task is None or task.get("trigger_at") is None:
            await matcher.finish("当前没有排期的自主创作任务。")

        trigger_at = task["trigger_at"]  # type: ignore[index]  # guarded above
        now = time.time()
        tz_shanghai = timezone(timedelta(hours=8))
        run_dt = datetime.fromtimestamp(trigger_at, tz=tz_shanghai)
        ts_str = run_dt.strftime("%Y-%m-%d %H:%M:%S")

        if trigger_at > now:
            remaining = trigger_at - now
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            await matcher.finish(
                f"🎨 下一次自主创作预计在 {ts_str} 触发（约 {hours} 小时 {minutes} 分钟后）。"
            )
        else:
            await matcher.finish(
                f"🎨 上一次自主创作预计在 {ts_str} 触发，当前正在等待重新排期中..."
            )

    elif sub == "delete":
        if len(parts) < 2:
            await matcher.finish(f"请提供任务 ID。\n\n{HELP}")
            return
        task_id: int | None = None
        try:
            task_id = int(parts[1])
        except ValueError:
            await matcher.finish(f"无效的任务 ID：{parts[1]}")
            return
        if task_id is None:
            await matcher.finish(f"无效的任务 ID：{parts[1]}")
            return

        task = store.get_task(task_id)
        if task is None:
            await matcher.finish(f"任务 ID {task_id} 不存在。")
            return

        if task["group_id"] != event.group_id:
            await matcher.finish(f"任务 ID {task_id} 不属于当前群。")
            return

        cancel_task_jobs(task_id, store)
        store.delete_task(task_id)
        await matcher.finish(f"✅ 定时任务（ID: {task_id}）已删除。")

    elif sub == "update":
        if len(parts) < 2:
            await matcher.finish(f"请提供任务 ID 和新的内容。\n\n{HELP}")
            return
        task_id: int | None = None
        try:
            task_id = int(parts[1])
        except ValueError:
            await matcher.finish(f"无效的任务 ID：{parts[1]}")
            return
        if task_id is None:
            await matcher.finish(f"无效的任务 ID：{parts[1]}")
            return

        task = store.get_task(task_id)
        if task is None:
            await matcher.finish(f"任务 ID {task_id} 不存在。")
            return

        rest = " ".join(parts[2:])
        if "@" not in rest:
            await matcher.finish(f"请用 @ 分隔新内容和新时间。\n\n{HELP}")
        new_prompt, times_str = rest.split("@", 1)
        new_prompt = new_prompt.strip()
        if not new_prompt:
            await matcher.finish("任务内容不能为空。")

        trigger_times: list[float] = []
        for ts in times_str.split(","):
            ts = ts.strip()
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    trigger_times.append(dt.timestamp())
                except ValueError:
                    await matcher.finish(
                        f"无效的时间格式：{ts}\n请使用 ISO 8601 格式。\n\n{HELP}"
                    )

        if not trigger_times:
            await matcher.finish("请至少提供一个触发时间。")

        errors = store.validate_trigger_times(trigger_times)
        if errors:
            await matcher.finish("\n".join(errors))
        prompt_err = store.validate_prompt(new_prompt)
        if prompt_err:
            await matcher.finish(prompt_err)

        cancel_task_jobs(task_id, store)
        store.update_task(task_id, new_prompt, trigger_times)
        add_jobs_for_task(task_id, store)

        await matcher.finish(f"✅ 定时任务（ID: {task_id}）已更新。")

    else:
        await matcher.finish(HELP)


async def handle_list_skills(matcher, args: Message) -> None:
    """Handle /skills command: list all available skills."""
    from ..skills import get_skill_manager

    skills = get_skill_manager().list_skills()
    if not skills:
        await matcher.finish("当前没有可用技能。")

    lines = ["当前可用技能："]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    await matcher.finish("\n\n".join(lines))


async def handle_membersearch(bot, event, matcher, args: Message) -> None:
    """Handle /membersearch command: fuzzy search group members."""
    from ..utils import search_group_members

    query = args.extract_plain_text().strip()

    if not query:
        await matcher.finish(
            "用法：/membersearch <昵称关键词>\n"
            "示例：/membersearch 菠萝\n\n"
            "模糊搜索当前群聊中的成员，最多返回 5 个结果。"
        )

    results: list = []
    try:
        results = await search_group_members(bot, event.group_id, query)
    except Exception as e:
        print(f"❌ membersearch command failed: {e}")
        import traceback

        traceback.print_exc()
        await matcher.finish(f"搜索失败：{e}")
        return

    if not results:
        await matcher.finish(f"未找到匹配 '{query}' 的群成员。")

    lines = [f"搜索 '{query}' 的结果："]
    for i, r in enumerate(results):
        lines.append(f"{i + 1}. {r['username']} (QQ: {r['id']}) - {r['level']}")
    await matcher.finish("\n".join(lines))


async def handle_resetsandbox(matcher) -> None:
    """Handle /resetsandbox command: cleanup the persistent Docker sandbox."""
    cleanup_persistent_container()
    await matcher.finish("✅ Sandbox 容器已重置。")


async def handle_agents(matcher) -> None:
    """Handle /agents command: display only currently running agents."""
    from datetime import datetime, timedelta, timezone

    from ..graph.agents import get_running_instances

    running = get_running_instances()
    if not running:
        await matcher.finish("当前没有正在运行的 Agent。")

    tz_shanghai = timezone(timedelta(hours=8))
    lines = ["🤖 当前正在运行的 Agent："]

    for inst in running:
        name = inst.get("name", "unknown")
        task = inst.get("task", "未知")[:150]
        started = inst.get("started_at")
        if started:
            dt = datetime.fromtimestamp(started, tz=tz_shanghai).strftime(
                "%Y/%m/%d %H:%M:%S"
            )
            lines.append(f"\n🟡 {name} — 执行中 [{dt}]\n  任务：{task}")
        else:
            lines.append(f"\n🟡 {name} — 执行中\n  任务：{task}")

    await matcher.finish("\n".join(lines))


async def handle_clear(matcher) -> None:
    """Handle /clear command: forcibly end the current conversation and clear all queues."""
    if _conv_state is None:
        await matcher.finish("❌ 对话状态未初始化，无法清除。")
        return

    was_chatting = _conv_state.is_chatting

    # Cancel any pending debounce timer
    if _conv_state._debounce_cancel is not None:
        _conv_state._debounce_cancel.set()
        _conv_state._debounce_cancel = None

    # Cancel the running graph task if active
    if _conv_state._graph_task is not None and not _conv_state._graph_task.done():
        _conv_state._graph_task.cancel()
        print("🛑 [clear] Graph task cancelled")

    # End the conversation (sets is_chatting=False, clears chat_peers)
    _conv_state.end_conversation()

    # Clear all message queues — always, regardless of conversation state
    _conv_state.idle_queue.clear()
    _conv_state.idle_source_queue.clear()
    _conv_state.pending_queue.clear()
    _conv_state.pending_source_queue.clear()
    _conv_state.human_queue.clear()
    _conv_state.human_source_queue.clear()

    # Reset memory recording context
    _conv_state.reset_memory_context()

    # Reset runtime flags
    _conv_state.is_graph_running = False
    _conv_state.face_cooling_count = 0

    if was_chatting:
        await matcher.finish("✅ 对话已强制结束，上下文已清除。")
    else:
        await matcher.finish("✅ 上下文已清除。（当前无活跃对话）")


async def handle_autocreate(bot, event, matcher, args: Message) -> None:
    """Immediately trigger an auto-create execution (debug command).

    Injects the auto-create prompt into the graph targeting the group
    where the command was sent.
    If args is non-empty, use it as the prompt instead of AUTO_CREATE_PROMPT.
    Does NOT modify the database — no task created, no reschedule.
    """
    from ..graph.nodes import inject_timer
    from ..prompts import get_auto_create_prompt
    from ..config import AUTO_CREATE_GROUP_ID

    custom_prompt = args.extract_plain_text().strip()
    group_id = event.group_id
    if args.extract_plain_text().strip() == "prod":
        prompt = get_auto_create_prompt()
        group_id = AUTO_CREATE_GROUP_ID
    else:
        prompt = custom_prompt if custom_prompt else get_auto_create_prompt()

    inject_timer(
        user_id=0,
        group_id=group_id,
        timer_prompt=prompt,
        start_conversation_cb=None,
    )
    await matcher.finish(f"🎨 Autonomous Creative Mode ON\n\n {prompt}")


async def handle_autoresponse(bot, event, matcher, args: Message) -> None:
    """Immediately trigger an auto-response execution (debug command).

    Injects the auto-response prompt into the graph targeting the group
    where the command was sent.
    If args is non-empty, use it as the prompt instead of the default.
    Does NOT modify the database — no task created, no reschedule.
    """
    from ..graph.nodes import inject_timer
    from ..prompts import get_auto_response_prompt
    from ..config import AUTO_RESPONSE_GROUP_ID

    custom_prompt = args.extract_plain_text().strip()
    group_id = event.group_id
    if args.extract_plain_text().strip() == "prod":
        prompt = get_auto_response_prompt()
        group_id = AUTO_RESPONSE_GROUP_ID
    else:
        prompt = custom_prompt if custom_prompt else get_auto_response_prompt()

    inject_timer(
        user_id=0,
        group_id=group_id,
        timer_prompt=prompt,
        start_conversation_cb=None,
    )
    await matcher.finish(f"💬 Auto Response Mode ON\n\n {prompt}")
