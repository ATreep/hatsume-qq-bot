"""Memory-driven learning evolution and its midnight schedule."""

from __future__ import annotations

import time
import traceback
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from nonebot import require

from .config import LEARN_EVOLVE_MEMORY_LIMIT, LEARN_EVOLVE_WINDOW_HOURS
from .group_runtime import group_runtime_registry
from .memory import get_activated_group_ids, get_db, query_recent_memories
from .prompts import build_learn_evolve_prompt

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

SHANGHAI = ZoneInfo("Asia/Shanghai")


async def run_learn_evolve(
    memory_group_id: int | None,
    chat_group_id: int,
) -> str:
    """Read recent memories and inject the task into one chat agent."""
    try:
        memories = query_recent_memories(
            get_db(),
            group_id=memory_group_id,
            limit=LEARN_EVOLVE_MEMORY_LIMIT,
            since_time=time.time() - LEARN_EVOLVE_WINDOW_HOURS * 3600,
        )
        prompt = build_learn_evolve_prompt(memories)

        from .graph.nodes import inject_learn_evolve

        inject_learn_evolve(user_id=0, group_id=chat_group_id, learn_prompt=prompt)
    except Exception as exc:  # noqa: BLE001 - report injection failures to callers
        source = memory_group_id if memory_group_id is not None else "all groups"
        print(f"[learn-evolve] Memory source {source} failed: {exc}")
        traceback.print_exc()
        return f"学习进化执行失败：{exc}"
    if memory_group_id is None:
        return "已读取全部群最近 24 小时记忆并注入当前群 chat_agent。"
    return f"已读取群 {memory_group_id} 的记忆并注入当前群 chat_agent。"


@scheduler.scheduled_job(
    CronTrigger(hour=0, minute=0, second=0, timezone=SHANGHAI),
    id="daily_learn_evolve",
)
async def daily_learn_evolve() -> None:
    """Run learning evolution at midnight for routed activated groups."""
    activated = set(get_activated_group_ids())
    for group_id in group_runtime_registry.routed_group_ids():
        if group_id in activated:
            await run_learn_evolve(
                memory_group_id=group_id,
                chat_group_id=group_id,
            )
