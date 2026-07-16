# Quickstart: Agent Dispatch Context

**Feature**: 028-agent-dispatch-context  
**Date**: 2026-07-06

## Overview

This feature adds a `context` parameter to `agent_dispatch` (renamed from `agent_allocate`) so the chat agent records why it dispatched a subagent. Context is stored in agent state and injected back into the conversation on completion.

## How It Works

### 1. Dispatching with Context

When the main chat agent calls `agent_dispatch`:

```python
agent_dispatch(
    agent_name="coding_agent",
    task="optimize webpack config for homepage",
    context="用户讨论网站性能问题，首页加载 5s 需降到 2s，需重构打包配置",
    notified_user_id=123456,
)
```

The context is stored in agent instance state alongside the task.

### 2. Context Storage

```python
# In _run_and_notify() — context added to add_agent_instance()
instance_id = add_agent_instance(
    agent_name,
    status="running",
    task=task,
    context=context,  # NEW
    user_id=notified_user_id,
    started_at=_time.time(),
)
```

### 3. Context Retrieval

```python
from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_context

ctx = get_agent_context("coding_agent")
# Returns "用户讨论网站性能问题..." or "" if no context
```

### 4. Context in Notifications

When the subagent completes, `inject_agent_notification` embeds context:

```
__agent_notify__:123456:coding_agent
(SYSTEM) Agent 'coding_agent' 执行完毕。
📋 派发背景：用户讨论网站性能问题，首页加载 5s 需降到 2s，需重构打包配置
请你简单复述一下任务原文内容，然后告诉用户执行结果。
...
```

If context is empty, the `📋 派发背景：` line is omitted.

## Key Files

| File | Change |
|------|--------|
| `graph/agents.py` | Add `get_agent_context()` helper |
| `graph/tools.py` | Rename `agent_allocate` → `agent_dispatch`, add `context` param |
| `graph/nodes/ai.py` | `inject_agent_notification` accepts `context`, embed in message |
| `tests/` | Rename test file, add context tests |

## Verification

```bash
# Run all tests
python -m pytest tests/ -xvs

# Verify no remaining old name references
grep -rn "agent_allocate" hatsume/ tests/ CLAUDE.md
# Expected: zero results
```
