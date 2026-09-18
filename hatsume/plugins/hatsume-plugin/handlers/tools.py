"""Tool commands: poke handler and shell/image/video/timer/skills command handlers."""

from __future__ import annotations

import asyncio
import base64
import os as _os
import subprocess
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import Message, MessageSegment, PokeNotifyEvent

from ..config import ADMIN_QQ_ID
from ..group_runtime import bind_group_runtime, group_runtime_registry
from ..infra import (
    cache_sandbox_message_image,
    cleanup_persistent_container,
    run_cmd,
)


# ---- Section 1: Poke Handler ----


async def _export_random_acg_photo() -> str:
    """Export a random photo from the macOS Photos ``ACG`` album."""
    import shutil as _shutil

    export_dir = tempfile.mkdtemp(prefix="hatsume-acg-export-")
    succeeded = False

    try:
        applescript = f'''
    try
        tell application "Photos"
            if not (exists album "ACG") then
                error "ALBUM_NOT_FOUND"
            end if
            set targetAlbum to album "ACG"
            set allPhotos to every media item of targetAlbum
            set photoCount to count of allPhotos
            if photoCount is 0 then
                error "ALBUM_EMPTY"
            end if
            set randomIndex to random number from 1 to photoCount
            set thePhoto to item randomIndex of allPhotos
            set exportDir to POSIX file "{export_dir}"
            export {{thePhoto}} to exportDir with using originals
        end tell
    on error errMsg
        return "ERROR:" & errMsg
    end try
    '''

        try:
            result = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return "❌ 错误：Photos 操作超时。"

        stdout_text = result.stdout.decode("utf-8", errors="replace").strip()
        if stdout_text.startswith("ERROR:"):
            err_msg = stdout_text[len("ERROR:") :].strip()
            if "ALBUM_NOT_FOUND" in err_msg:
                return "❌ 错误：未找到名为 'ACG' 的相簿。"
            if "ALBUM_EMPTY" in err_msg:
                return "❌ 错误：'ACG' 相簿中没有照片。"
            return f"❌ 错误：Photos 操作失败：{err_msg}"

        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
            combined = (stdout_text + " " + stderr_text).strip()
            if (
                "not running" in combined.lower()
                or "application isn't running" in combined.lower()
            ):
                return "❌ 错误：无法访问 Photos 应用，请确认 Photos.app 已打开并授权。"
            return f"❌ 错误：Photos 操作失败：{combined}"

        exported = [
            filename
            for filename in _os.listdir(export_dir)
            if _os.path.isfile(_os.path.join(export_dir, filename))
        ]
        if not exported:
            return "❌ 错误：照片导出失败，未找到导出文件。"

        succeeded = True
        return _os.path.join(export_dir, exported[0])
    finally:
        if not succeeded:
            _shutil.rmtree(export_dir, ignore_errors=True)


def _cleanup_exported_acg_photo(host_file: str) -> None:
    """Remove the unique host export directory created for one photo."""
    import shutil as _shutil

    export_dir = _os.path.dirname(host_file)
    if _os.path.basename(export_dir).startswith("hatsume-acg-export-"):
        _shutil.rmtree(export_dir, ignore_errors=True)


async def handle_poke(bot: Bot, event: PokeNotifyEvent) -> None:
    """When the bot is poked, export and send a random ACG photo.

    Silently ignores errors (Photos not running, album empty, etc.) to avoid
    spamming the group chat on every poke.
    """
    group_id = int(getattr(event, "group_id", 0))
    if group_id <= 0:
        return
    from ..config import POKE_GROUP_WHITELIST

    if group_id not in POKE_GROUP_WHITELIST:
        return

    runtime = group_runtime_registry.bind_bot(group_id, bot)
    with bind_group_runtime(runtime):
        host_file = await _export_random_acg_photo()
    if host_file.startswith("❌"):
        # All failures are silent — don't spam the chat
        return

    try:
        try:
            with open(host_file, "rb") as f:
                img_data = f.read()
            b64 = base64.b64encode(img_data).decode("ascii")
            send_result = await bot.send(
                event,
                MessageSegment.image(f"base64://{b64}"),
            )
            if isinstance(send_result, dict):
                raw_message_id = send_result.get("message_id")
                if isinstance(raw_message_id, (int, str)) and not isinstance(
                    raw_message_id,
                    bool,
                ):
                    try:
                        message_id = int(raw_message_id)
                    except (TypeError, ValueError):
                        pass
                    else:
                        await cache_sandbox_message_image(
                            img_data,
                            message_id,
                            1,
                            group_id=group_id,
                        )
        except Exception:
            # File read / network errors: also silent
            return
    finally:
        _cleanup_exported_acg_photo(host_file)


# ---- Section 2: Command Handlers ----


async def _resolve_target_group(
    event,
    matcher,
    args: Message,
    *,
    usage: str,
    allow_cross_group: bool = True,
) -> int:
    text = args.extract_plain_text().strip()
    if not text:
        return int(event.group_id)
    parts = text.split()
    try:
        if len(parts) != 1:
            raise ValueError
        group_id = int(parts[0])
        if group_id <= 0:
            raise ValueError
    except ValueError:
        await matcher.finish(f"群号必须是正整数。\n用法：{usage}")
        return int(event.group_id)

    if group_id != int(event.group_id):
        if not allow_cross_group or str(event.get_user_id()) != str(ADMIN_QQ_ID):
            await matcher.finish("只有管理员可以访问其他群的数据。")
            return int(event.group_id)
    return group_id


async def handle_shell(event, matcher, args: Message) -> None:
    cmd = args.extract_plain_text()
    runtime = group_runtime_registry.get_or_create(event.group_id)
    with bind_group_runtime(runtime):
        print("Start running shell.")
        out = await run_cmd(cmd, group_id=event.group_id)
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


async def handle_mcp(event, matcher, args: Message) -> None:
    """Administrator diagnostics for group-isolated MCP JSON configs."""
    if str(event.get_user_id()) != str(ADMIN_QQ_ID):
        await matcher.finish("只有管理员可以使用 /mcp。")
        return
    from ..mcp.manager import get_mcp_manager

    parts = args.extract_plain_text().strip().split()
    if not parts or parts[0] in {"help", "-h"}:
        await matcher.finish("用法：/mcp list [群号] | tools <server> [群号] | refresh <server> [群号] | status [群号]")
        return
    subcommand = parts[0].lower()
    target_group = int(event.group_id)
    if parts and parts[-1].isdigit() and int(parts[-1]) != target_group:
        target_group = await _resolve_target_group(event, matcher, Message(" ".join(parts[-1:])), usage="/mcp <命令> [群号]")
        parts = parts[:-1]
    manager = get_mcp_manager()
    try:
        if subcommand == "list":
            servers = manager.list_servers(target_group)
            result = "\n".join(f"- {item.name}：{item.description}（{'启用' if item.enabled else '停用'}）" for item in servers) or "目标群没有 MCP Server。"
        elif subcommand in {"tools", "refresh"} and len(parts) >= 2:
            infos = await manager.discover_tools(parts[1], target_group, refresh=subcommand == "refresh")
            result = "\n".join(f"- {item.name}：{item.description or '无描述'}" for item in infos) or "该 Server 没有工具。"
        elif subcommand == "status":
            result = "\n".join(f"- {item.name}：{'启用' if item.enabled else '停用'}" for item in manager.list_servers(target_group)) or "目标群没有 MCP Server。"
        elif subcommand in {"enable", "disable"} and len(parts) >= 2:
            manager.set_enabled(parts[1], subcommand == "enable", target_group)
            result = f"✅ 已{'启用' if subcommand == 'enable' else '停用'} MCP Server：{parts[1]}"
        elif subcommand == "remove" and len(parts) >= 2:
            result = "✅ MCP Server 已删除。" if manager.remove(parts[1], target_group) else "目标群不存在该 MCP Server。"
        else:
            result = "用法：/mcp list [群号] | tools <server> [群号] | refresh <server> [群号] | status [群号] | enable/disable/remove <server> [群号]"
    except Exception as exc:
        result = f"❌ MCP 操作失败：{exc}"
    await matcher.finish(result)


async def handle_todo(event, matcher, args: Message) -> None:
    """List active todos for the current group or an admin-selected group."""
    text = args.extract_plain_text().strip()
    target_group_id = event.group_id
    if text:
        parts = text.split()
        try:
            if len(parts) != 1:
                raise ValueError
            target_group_id = int(parts[0])
            if target_group_id <= 0:
                raise ValueError
        except ValueError:
            await matcher.finish("群号必须是正整数。\n用法：/todo [群号]")
            return

        if target_group_id != event.group_id:
            from ..config import ADMIN_QQ_ID

            if str(event.get_user_id()) != str(ADMIN_QQ_ID):
                await matcher.finish("只有管理员可以查看其他群的待办。")
                return

    from ..todo import get_store

    try:
        store = get_store()
        store.delete_expired()
        items = store.list_items(target_group_id)
    except Exception as exc:
        print(f"❌ todo command failed: {exc}")
        await matcher.finish("❌ 待办数据库暂时不可用。")
        return

    is_current_group = target_group_id == event.group_id
    scope = "当前群" if is_current_group else f"群 {target_group_id}"
    separator = "" if is_current_group else " "
    if not items:
        await matcher.finish(f"{scope}{separator}没有活动待办。")
        return

    lines = [f"{scope}{separator}活动待办（{len(items)} 项）："]
    for index, item in enumerate(items, start=1):
        created_at = datetime.fromtimestamp(float(item["created_at"])).strftime(
            "%Y/%m/%d %H:%M:%S"
        )
        lines.extend(
            [
                "",
                f"{index}. 待办 ID：{item['id']}",
                "发起人："
                f"{item['initiator_group_name']}（QQ：{item['initiator_qq_id']}）",
                f"创建时间：{created_at}",
                f"待办内容：{item['content']}",
                f"完成条件：\n{item['finish_condition']}",
            ]
        )

    await matcher.finish("\n".join(lines))


async def handle_proxy_command(event, matcher, args: Message) -> None:
    """Create, inspect, or terminate the single RAM character proxy."""
    runtime = group_runtime_registry.get_or_create(event.group_id)
    with bind_group_runtime(runtime):
        await _handle_proxy_command_bound(event, matcher, args)


async def _handle_proxy_command_bound(event, matcher, args: Message) -> None:
    from ..graph.tools import (
        create_character_proxy,
        terminate_character_proxy,
    )

    help_text = (
        "用法：\n"
        "/proxy create <QQ号> [持续分钟数]\n"
        "/proxy terminate\n"
        "/proxy status"
    )
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await matcher.finish(help_text)
        return

    action = parts[0].lower()
    if action == "create":
        if len(parts) not in (2, 3):
            await matcher.finish(help_text)
            return
        try:
            proxied_user_id = int(parts[1])
            during_time = int(parts[2]) if len(parts) == 3 else None
        except ValueError:
            await matcher.finish("QQ号和持续分钟数必须是整数。")
            return
        if proxied_user_id <= 0:
            await matcher.finish("QQ号必须是正整数。")
            return

        tool_input = {"proxied_user_id": proxied_user_id}
        if during_time is not None:
            tool_input["during_time"] = during_time
        result = await create_character_proxy.ainvoke(tool_input)
        await matcher.finish(result)
        return

    if action == "terminate" and len(parts) == 1:
        result = await terminate_character_proxy.ainvoke({})
        await matcher.finish(result)
        return

    if action == "status" and len(parts) == 1:
        from ..character_proxy import (
            build_active_character_proxy_role_prompt,
            get_character_proxy,
        )

        proxy = get_character_proxy()
        if proxy is None:
            await matcher.finish("当前没有开启角色代理。")
            return
        role_prompt = build_active_character_proxy_role_prompt(proxy)
        await matcher.finish(
            f"当前被代理角色：{proxy.user_name}（QQ：{proxy.user_id}）\n"
            f"自动结束时间：{proxy.auto_terminate_at}\n\n"
            f"角色提示词：\n{role_prompt}"
        )
        return

    await matcher.finish(help_text)


async def handle_timer(bot, event, matcher, args: Message) -> None:
    runtime = group_runtime_registry.bind_bot(event.group_id, bot)
    with bind_group_runtime(runtime):
        await _handle_timer_bound(bot, event, matcher, args)


async def _handle_timer_bound(bot, event, matcher, args: Message) -> None:
    """Handle /timer command: list, delete, update."""
    from ..graph.tools import get_timer_overview
    from ..timer import get_store
    from ..timer.executor import add_jobs_for_task, cancel_task_jobs
    from ..timer.schedule import ScheduleValidationError, build_at_plan

    store = get_store()
    text = args.extract_plain_text().strip()
    parts = text.split() if text else []

    HELP = (
        "/timer 命令用法：\n\n"
        "/timer list                    列出当前群的所有定时任务\n"
        "/timer list <群号>             管理员查看指定群的定时任务\n"
        "/timer delete <id>             删除指定 ID 的定时任务\n"
        "/timer update <id> <内容> @ <时间1>, <时间2>, ..."
        "  更新定时任务的内容和触发时间\n\n"
        "时间格式：ISO 8601 带时区，如 2026-06-08T08:00:00+08:00\n"
        "多个时间用逗号分隔，最多 10 个"
    )

    if not parts:
        await matcher.finish(HELP)

    sub = parts[0].lower()

    if sub == "list":
        if len(parts) > 2:
            await matcher.finish(f"群号必须是正整数。\n\n{HELP}")
            return
        if len(parts) == 1:
            await matcher.finish(await get_timer_overview())
            return

        try:
            target_group_id = int(parts[1])
        except ValueError:
            await matcher.finish(f"群号必须是正整数。\n\n{HELP}")
            return
        if target_group_id <= 0:
            await matcher.finish(f"群号必须是正整数。\n\n{HELP}")
            return

        if target_group_id != event.group_id:
            from ..config import ADMIN_QQ_ID

            if str(event.get_user_id()) != str(ADMIN_QQ_ID):
                await matcher.finish("只有管理员可以查看其他群的定时任务。")
                return

        await matcher.finish(await get_timer_overview(target_group_id))
        return

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
        if task["group_id"] != event.group_id:
            await matcher.finish(f"任务 ID {task_id} 不属于当前群。")
            return

        rest = " ".join(parts[2:])
        if "@" not in rest:
            await matcher.finish(f"请用 @ 分隔新内容和新时间。\n\n{HELP}")
        new_prompt, times_str = rest.split("@", 1)
        new_prompt = new_prompt.strip()
        if not new_prompt:
            await matcher.finish("任务内容不能为空。")

        trigger_times = [value.strip() for value in times_str.split(",") if value.strip()]
        if not trigger_times:
            await matcher.finish("请至少提供一个触发时间。")
        prompt_err = store.validate_prompt(new_prompt)
        if prompt_err:
            await matcher.finish(prompt_err)
        try:
            plan = build_at_plan(trigger_times)
        except ScheduleValidationError as exc:
            await matcher.finish(str(exc))
            return

        cancel_task_jobs(task_id, store)
        store.replace_task_with_exact_plan(task_id, new_prompt, plan)
        add_jobs_for_task(task_id, store)

        await matcher.finish(f"✅ 定时任务（ID: {task_id}）已更新。")

    else:
        await matcher.finish(HELP)


async def handle_list_skills(event, matcher, args: Message) -> None:
    """Handle /skills [group_id] without creating target-group resources."""
    from ..skills import get_skill_manager

    target_group_id = await _resolve_target_group(
        event,
        matcher,
        args,
        usage="/skills [群号]",
    )
    skills = get_skill_manager(target_group_id, create_local=False).list_skills()
    if not skills:
        await matcher.finish("当前没有可用技能。")
        return

    scope = "当前群" if target_group_id == event.group_id else f"群 {target_group_id}"
    lines = [f"{scope}可用技能："]
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


async def handle_resetsandbox(event, matcher, args: Message) -> None:
    """Reset only the admin-selected group's local process runtime."""
    if str(event.get_user_id()) != str(ADMIN_QQ_ID):
        await matcher.finish("只有管理员可以重置 Sandbox。")
        return
    target_group_id = await _resolve_target_group(
        event,
        matcher,
        args,
        usage="/resetsandbox [群号]",
    )
    from ..graph.agents import shutdown_group_agents

    await shutdown_group_agents(target_group_id)
    removed = await cleanup_persistent_container(target_group_id)
    if not removed:
        await matcher.finish(f"群 {target_group_id} 当前没有 Sandbox 容器。")
        return
    await matcher.finish(f"✅ 群 {target_group_id} 的 Sandbox 容器已重置。")


async def handle_agents(event, matcher, args: Message) -> None:
    """Handle /agents [group_id] with group-filtered state."""
    from datetime import datetime, timedelta, timezone

    from ..graph.agents import get_running_instances

    target_group_id = await _resolve_target_group(
        event,
        matcher,
        args,
        usage="/agents [群号]",
    )
    running = get_running_instances(target_group_id)
    if not running:
        await matcher.finish("当前没有正在运行的 Agent。")
        return

    tz_shanghai = timezone(timedelta(hours=8))
    scope = "当前群" if target_group_id == event.group_id else f"群 {target_group_id}"
    lines = [f"🤖 {scope}正在运行的 Agent："]

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


async def handle_hooks(event, matcher, args: Message) -> None:
    """Handle /hooks [group_id] with group-filtered persistent state."""
    target_group_id = await _resolve_target_group(
        event,
        matcher,
        args,
        usage="/hooks [群号]",
    )
    from ..hooks import get_store
    from ..hooks.executor import get_hook_next_run

    try:
        records = get_store().list_hooks(target_group_id)
    except Exception as exc:
        print(f"❌ hooks command failed: {exc}")
        await matcher.finish("❌ Hook 数据库暂时不可用。")
        return

    scope = (
        "当前群" if target_group_id == int(event.group_id) else f"群 {target_group_id}"
    )
    if not records:
        await matcher.finish(f"{scope}没有 Hook。")
        return

    lines = [f"{scope} Hooks（{len(records)} 项）："]
    for index, record in enumerate(records, start=1):
        if str(record.get("trigger_type") or "heartbeat") == "message_match":
            match_user = record["match_user_id"]
            match_user_text = "任意成员" if not match_user else f"QQ {match_user}"
            trigger_lines = [
                "触发方式：用户消息匹配",
                f"触发人：{match_user_text}",
                f"匹配正则：/{record['match_pattern']}/",
                f"上次触发：{record['last_run_at'] or '无'}",
            ]
        else:
            next_run = get_hook_next_run(int(record["id"]))
            next_text = next_run.isoformat() if next_run is not None else "未调度"
            last_exit_text = (
                str(record["last_exit_code"])
                if record["last_exit_code"] is not None
                else "无"
            )
            trigger_lines = [
                "触发方式：脚本 heartbeat",
                f"间隔：{record['interval_seconds']} 秒；超时：{record['timeout_seconds']} 秒",
                f"脚本：{record['script_path']}",
                f"下次运行：{next_text}",
                f"上次退出码：{last_exit_text}",
            ]
        lines.extend(
            [
                "",
                f"{index}. {record['name']}（ID：{record['id']}）",
                f"状态：{'启用' if record['enabled'] else '停用'}",
                *trigger_lines,
                f"连续失败：{record['consecutive_failures']}",
                f"最近错误：{record['last_error'] or '无'}",
            ]
        )
    await matcher.finish("\n".join(lines))


async def handle_aps(matcher) -> None:
    """List every job currently registered with the shared APScheduler."""
    from nonebot import require

    scheduler = require("nonebot_plugin_apscheduler").scheduler
    try:
        jobs = sorted(scheduler.get_jobs(), key=lambda job: str(job.id))
    except Exception as exc:
        print(f"❌ aps command failed: {exc}")
        await matcher.finish("❌ APScheduler 状态暂时不可用。")
        return

    if not jobs:
        await matcher.finish("APScheduler 当前没有已注册任务。")
        return

    lines = [f"APScheduler 已注册任务（{len(jobs)} 项）："]
    for index, job in enumerate(jobs, start=1):
        next_run = getattr(job, "next_run_time", None)
        next_text = next_run.isoformat() if next_run is not None else "暂停或未排期"
        lines.extend(
            [
                "",
                f"{index}. {job.id}",
                f"名称：{job.name}",
                f"触发器：{job.trigger}",
                f"下次运行：{next_text}",
            ]
        )
    await matcher.finish("\n".join(lines))


def _fetch_deepseek_balance(api_key: str, base_url: str) -> dict:
    """Fetch one DeepSeek balance snapshot without blocking the async caller."""
    response = requests.get(
        f"{base_url.rstrip('/')}/user/balance",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Hatsume/1.0",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _build_deepseek_balance_report(payload: object) -> str | None:
    """Build the balance report text, or None when the payload is invalid."""
    if not isinstance(payload, dict):
        return None
    is_available = payload.get("is_available")
    balance_infos = payload.get("balance_infos") or payload.get("balances")
    if not isinstance(balance_infos, list) or not balance_infos:
        return None

    lines = ["✅ DeepSeek 账户余额："]
    for info in balance_infos:
        if not isinstance(info, dict):
            continue
        currency = str(info.get("currency", "CNY"))
        total = _format_balance_amount(info.get("total_balance"))
        granted = _format_balance_amount(info.get("granted_balance"))
        topped_up = _format_balance_amount(info.get("topped_up_balance"))
        lines.append(
            f"{currency} 总余额：{total}（充值 {topped_up}，赠送 {granted}）"
        )
    if len(lines) == 1:
        return None

    status_text = "✅ 可用" if is_available else "❌ 不可用"
    lines.append(f"账户状态：{status_text}")
    return "\n".join(lines)


def _format_balance_amount(raw_value: object) -> str:
    """Format a balance amount, converting integer 分 amounts into 元."""
    text = str(raw_value).strip()
    try:
        value = Decimal(text)
        if text.lstrip("-").isdigit():
            # Integer amounts are in 人民币分; decimal strings are already in 元.
            value = value / Decimal(100)
        return f"¥{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
    except InvalidOperation:
        return "未知"


async def handle_dsbalance(event, matcher, args: Message) -> None:
    """Show the DeepSeek account balance from the official balance API."""
    from .. import config as runtime_config

    api_key = getattr(runtime_config, "DS_API_KEY", "").strip()
    if not api_key:
        await matcher.finish("❌ 错误：未配置 DeepSeek API Key（DS_API_KEY）。")
        return
    base_url = getattr(runtime_config, "DS_BASE_URL", "https://api.deepseek.com")

    print("Querying DeepSeek balance.")
    try:
        payload = await asyncio.to_thread(
            _fetch_deepseek_balance, api_key, base_url
        )
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 0
        print(f"DeepSeek balance HTTP error: {status_code or 'unknown'}")
        if status_code in (401, 403):
            await matcher.finish("❌ 错误：DeepSeek API Key 无效或无权访问。")
        elif status_code == 429:
            await matcher.finish("❌ 错误：请求过于频繁，请稍后重试。")
        elif status_code:
            await matcher.finish(
                f"❌ 错误：DeepSeek 余额接口返回 HTTP {status_code}。"
            )
        else:
            await matcher.finish("❌ 错误：DeepSeek 余额接口返回了未知 HTTP 错误。")
        return
    except requests.exceptions.SSLError:
        print("DeepSeek balance SSL error.")
        await matcher.finish("❌ 错误：无法验证 DeepSeek API 的 SSL 证书。")
        return
    except requests.exceptions.Timeout:
        print("DeepSeek balance timeout.")
        await matcher.finish("❌ 错误：连接 DeepSeek API 超时，请稍后重试。")
        return
    except requests.exceptions.ConnectionError:
        print("DeepSeek balance connection error.")
        await matcher.finish("❌ 错误：暂时无法连接 DeepSeek API。")
        return
    except requests.exceptions.InvalidJSONError:
        print("DeepSeek balance invalid JSON response.")
        await matcher.finish("❌ 错误：DeepSeek API 返回了无效数据。")
        return
    except requests.exceptions.RequestException:
        print("DeepSeek balance request error.")
        await matcher.finish("❌ 错误：查询 DeepSeek 余额失败，请稍后重试。")
        return
    except Exception:
        print("DeepSeek balance unexpected error.")
        await matcher.finish("❌ 错误：查询 DeepSeek 余额失败，请稍后重试。")
        return

    report = _build_deepseek_balance_report(payload)
    if report is None:
        await matcher.finish("❌ 错误：DeepSeek API 返回了无效数据。")
        return
    await matcher.finish(report)


async def handle_autoresponse(bot, event, matcher, args: Message) -> None:
    """List the next persisted auto-response trigger for every group."""
    from datetime import timedelta, timezone

    from ..timer import get_store

    store = get_store()
    group_ids = sorted(store.list_auto_response_group_ids())
    if not group_ids:
        await matcher.finish("当前没有自动回复定时任务。")
        return

    shanghai = timezone(timedelta(hours=8))
    lines = ["自动回复下次触发时间（上海时间）："]
    for group_id in group_ids:
        point = store.get_auto_response_point(group_id)
        if point is None:
            trigger_text = "暂无待触发时间"
        else:
            trigger_text = datetime.fromtimestamp(
                float(point["exact_at"]), tz=shanghai
            ).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"群 {group_id}：{trigger_text}")

    await matcher.finish("\n".join(lines))
