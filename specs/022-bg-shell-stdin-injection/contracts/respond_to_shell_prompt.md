# Contract: respond_to_shell_prompt Tool

## Interface

**Tool name**: `respond_to_shell_prompt`

**Purpose**: Allows the chat agent (main LLM) to pass raw input text to the background shell agent's stdin queue when a process is waiting for interactive input.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `request_id` | `str` | Yes | Unique identifier from the `SHELL_STDIN_REQUEST` notification (format: `stdin_<proc_id>_<seq>`) |
| `text` | `str` | Yes | Raw text to pass to the background shell agent. The code model will transform this into process-appropriate stdin content. |

## Returns

| Condition | Return Value |
|-----------|-------------|
| Success | `"✅ 已成功向后台进程发送 stdin 输入 (request_id=<id>)。"` |
| Invalid/expired request_id | `"错误：找不到 pending stdin 请求 (request_id=<id>)。可能该请求已超时、已被处理、或 request_id 不正确。"` |

## Behavior

1. Look up `request_id` in `_stdin_queues` (module-level dict in `graph/agents.py`)
2. If not found → return error immediately (idempotent — no side effects)
3. If found → `queue.put(text)`, pop entry from `_stdin_queues` (prevents double-reply), return success

## Notification Format (Input Trigger)

The chat agent receives a `SHELL_STDIN_REQUEST` notification when stdin is needed:

```
__agent_notify__:<user_id>:background_shell
[SHELL_STDIN_REQUEST]
request_id: stdin_<proc_id>_<seq>
description: <what input is needed>
context: <recent process output showing the prompt>
timeout: <seconds>s
[/SHELL_STDIN_REQUEST]
(SYSTEM) Agent 'background_shell' 进程正在等待输入。
请使用 respond_to_shell_prompt 工具回复所需信息。
```

## Error Handling

- Double-reply: Second call to same `request_id` returns error (queue already popped)
- Wrong agent: Calling when no background_shell is running returns error (no matching queue)
- Timeout: If user doesn't respond within timeout, the queue is cleaned up and subsequent calls return error
