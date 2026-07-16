# Data Model: Agent Dispatch Context

**Feature**: 028-agent-dispatch-context  
**Date**: 2026-07-06

## Entity: Agent Instance State

Stored in-memory in `_AGENT_STATES: dict[str, list[dict]]` (`graph/agents.py`).

### Attributes

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `instance_id` | `str` | Yes | Unique ID: `{agent_name}_{uuid.hex[:8]}` |
| `name` | `str` | Yes | Agent type name (e.g., `coding_agent`) |
| `status` | `str` | Yes | `"running"` or `"done"` |
| `task` | `str` | Yes | Task description given to the agent |
| `context` | `str` | **NEW** — Yes | Background story: why this agent was dispatched |
| `user_id` | `int` | No | QQ user ID to notify (0 = no user) |
| `started_at` | `float` | No | `time.time()` at dispatch |
| `result` | `str` | No | Agent output (set on completion) |

### State Transitions

```
[dispatch] → status="running"
                  │
                  ▼
          [handler completes]
                  │
                  ▼
            status="done"
            result=<output>
```

Context is set at `[dispatch]` and never modified afterward.

## Entity: Agent Notification Message

Constructed in `inject_agent_notification()` (`graph/nodes/ai.py`).

### Structure

```
{NOTIFY_MARK}:{user_id}:{agent_name}
(SYSTEM) Agent '{agent_name}' 执行完毕。
📋 派发背景：{context}          ← NEW — omitted if context is empty
请你简单复述一下任务原文内容，然后告诉用户执行结果。

## 该 Agent 执行的任务原文

```
{task[:200]}
```

## Agent 执行结果

{result}
```

### Validation Rules

- `context` may be any string (including empty)
- If `context` is empty (`""`), the `📋 派发背景：` line is omitted entirely
- `NOTIFY_MARK` is `"__agent_notify__"` (constant)
- `task` is truncated to 200 chars in display (full task stored in agent state)
