# Timer API Contract

**Feature**: 008-timer-module | **Date**: 2026-06-07

## LLM Tools

### create_timer

```
create_timer(prompt: str, trigger_times: list[str]) -> str
```

Creates a timer task with the given prompt and ISO 8601 trigger times.

**Parameters**:
- `prompt` (str): Task content. Max 500 chars. Do not include time info (it's in trigger_times).
- `trigger_times` (list[str]): ISO 8601 timestamps with timezone offset. Each must be > now and <= now + 30 days. After deduplication, no rolling 24-hour window may contain more than 10 trigger times.

**Returns**: Confirmation message with task ID and trigger times (to relay to user).

**Errors**:
- If any trigger_at is in the past: "错误：触发时间 [time] 已过期，必须是当前时间之后。"
- If any trigger_at exceeds 30 days: "错误：触发时间 [time] 超过 30 天限制。"
- If any rolling 24-hour window contains more than 10 unique trigger times: "错误：同一个定时任务在任意连续 24 小时内最多触发 10 次。"
- If prompt is empty: "错误：任务内容不能为空。"
- If prompt > 500 chars: "错误：任务内容过长（最多 500 字符）。"

**See spec.md for 5 few-shot examples.**

### list_timers

```
list_timers() -> str
```

Lists all timer tasks for the current group.

**Returns**: Formatted list of tasks (ID, prompt summary, trigger times, fired status), or "当前群没有定时任务" if empty.

### delete_timer

```
delete_timer(task_id: int) -> str
```

Deletes a timer task and all its triggers.

**Parameters**:
- `task_id` (int): Task ID to delete.

**Returns**: Confirmation or "任务 ID {task_id} 不存在" if not found.

## Slash Command

### /timer

```
/timer [subcommand]
```

| Subcommand | Format | Description |
|-----------|--------|-------------|
| _(none)_ | `/timer` | Show help with all sub-commands |
| `list` | `/timer list` | List all timers in current group |
| `delete` | `/timer delete <id>` | Delete timer by ID |
| `update` | `/timer update <id> <prompt> @ <time1>, <time2>, ...` | Update timer prompt and trigger times |

**Help Output** (when no subcommand or invalid):
```
/timer 命令用法：

/timer list                    列出当前群的所有定时任务
/timer delete <id>             删除指定 ID 的定时任务
/timer update <id> <内容> @ <时间1>, <时间2>, ...  更新定时任务的内容和触发时间

时间格式：ISO 8601 带时区，如 2026-06-08T08:00:00+08:00
多个时间用逗号分隔
```

## Debug API

### GET /debug/api/timers

Returns all timer tasks across all groups with trigger statuses.

**Response**: See `docs/debug-api-contract.md` Section 10 for full schema.
