# Agent Allocate Tool — Design Spec

**Date:** 2026-06-26
**Status:** approved

## Overview

Add an `agent_allocate` tool that dispatches built-in agents (web browser, video generation) to run in the background, then injects the agent's result back into the conversation flow for the LLM to process and @-notify the requesting user.

## Architecture

```
agents.py (NEW)         tools.py              nodes/ai.py           handlers/chat.py
─────────────           ────────              ───────────           ──────────────
AGENT_REGISTRY ──→  agent_allocate()                                   (callback)
  name, desc,           │                                               │
  handler_fn            ├─ get_agent_handler(name)                      │
                        ├─ asyncio.create_task(_run_and_notify)         │
                        └─ return "Agent 已开始执行"                    │
                                  │                                     │
                          background task                               │
                                  │                                     │
                          handler(task, uid)                            │
                                  │                                     │
                          inject_agent_notification()                   │
                            ├─ is_chatting=True                         │
                            │    human_queue.append(notify_msg)         │
                            │    chat_peers.add(str(uid))               │
                            └─ is_chatting=False                       │
                                 _start_conversation_for_agent() ───────┘

human_node → ai_node
  detect NOTIFY_MARK in last_content
  → ai_answer_with_at(msg, notified_uid)
```

## Components

### 1. `graph/agents.py` (NEW)

Built-in agent registry with handler functions.

```python
AGENT_REGISTRY: dict[str, dict] = {}
# name → {"description": str, "handler": async (task, user_id) -> str}

def register_agent(name, description, handler): ...
def get_agent_list() -> list[dict]: ...
def get_agent_handler(name) -> handler | None: ...
```

**Built-in agents:**

| name | description | handler |
|------|-------------|---------|
| `web_browser` | 网络浏览器 Agent，访问网站并返回检索结果报告 | `_run_web_browser_agent` |
| `generate_video` | AI 视频生成 Agent，根据文字描述生成短视频 | `_run_video_agent` |

Handler signature: `async def handler(task: str, user_id: int) -> str`

- `_run_web_browser_agent` — mirrors existing `web_browser` tool logic: creates browser agent, invokes shell_executor with WEB_BROWSER_AGENT_PROMPT, returns report
- `_run_video_agent` — mirrors existing `generate_video` tool logic: calls `generate_video_for()`, returns result status/url

### 2. `agent_allocate` tool in `graph/tools.py`

```python
@tool(description=f"""...可用 Agent：{_AGENT_LIST_STR}""")
async def agent_allocate(notified_user_id: int, agent_name: str, task: str) -> str:
```

- Imports `get_agent_handler`, `get_agent_list` from `.agents`
- Description built with f-string — `_AGENT_LIST_STR` evaluated at module import time from `get_agent_list()`
- Looks up handler via `get_agent_handler(agent_name)`
- Dispatches handler in background: `asyncio.create_task(_run_and_notify())`
- Returns immediately: `"✅ Agent '{agent_name}' 已开始执行，完成后将自动通知用户。"`
- On handler completion: calls `inject_agent_notification(user_id, agent_name, result)`

### 3. Notification injection in `graph/nodes/ai.py`

#### Special mark format

```
NOTIFY_MARK = "__agent_notify__"
```

#### `inject_agent_notification(user_id, agent_name, result)`

Builds the notification message:

```
(SYSTEM) Agent '{agent_name}' 已执行完毕，以下是该 Agent 返回的结果，请以你的口吻告知用户结果：
__agent_notify__:<user_id>:<agent_name>
<result>
```

- If `_state.is_chatting` → `human_queue.append(notify_msg)`, `chat_peers.add(str(user_id))`
- Else → calls `_start_conversation_for_agent(user_id, notify_msg)` (callback registered in chat.py)

#### Callback wiring

- `tools.py`: new `configure_agent_notification_callback(cb)` — stores the callback
- `handlers/chat.py`: registers `_start_conv_for_agent` callback that starts a new graph conversation when no active chat

### 4. NOTIFY_MARK detection in `ai_node`

In `ai_node()`, before invoking `chat_agent`, inspect `state["messages"][-1].content`:

```python
notified_uid: int | None = None
last_content = state["messages"][-1].content

if isinstance(last_content, list):
    for part in reversed(last_content):
        text = ""
        if isinstance(part, dict) and part.get("type") == "text":
            text = str(part.get("text", ""))
        elif isinstance(part, str):
            text = part
        if text.startswith(NOTIFY_MARK):
            _, uid_str, _ = text.split(":", 2)
            notified_uid = int(uid_str)
            break
elif isinstance(last_content, str) and last_content.startswith(NOTIFY_MARK):
    _, uid_str, _ = last_content.split(":", 2)
    notified_uid = int(uid_str)
```

After `chat_agent` produces `ai_text`:

```python
if notified_uid is not None:
    at_callback = _state.ai_answer_with_at if _state else None
    if at_callback:
        await at_callback(ai_text, notified_uid)
else:
    _ai_answer = _get_ai_answer()
    if _ai_answer:
        await _ai_answer(MessageSegment.text(ai_text))
```

Reverse iteration ensures the last NOTIFY_MARK wins when multiple exist.

### 5. Tool registration in `ai_node`

Add `agent_allocate` to `create_agent` tools list:

```python
from ..tools import (
    ..., agent_allocate
)

chat_agent = create_agent(
    model_chosen,
    [..., agent_allocate],
    system_prompt=sys_prompt,
)
```

## Files Changed

| File | Change |
|------|--------|
| `graph/agents.py` | **NEW** — Agent registry, handlers, register/get functions |
| `graph/tools.py` | Add `agent_allocate` tool, `_AGENT_LIST_STR`, `configure_agent_notification_callback` |
| `graph/nodes/ai.py` | Add `NOTIFY_MARK`, `inject_agent_notification()`, mark detection in ai_node, register tool in create_agent |
| `handlers/chat.py` | Register `_start_conv_for_agent` callback |

## Error Handling

- Unknown agent name → tool returns error string listing available agents
- Handler exception → caught in `_run_and_notify`, result set to `"Agent '{agent_name}' 执行失败。"`
- `_state` is None → `inject_agent_notification` is a no-op
- Multiple NOTIFY_MARKs → last one wins (reverse iteration with break)

## Testing

- Unit test: `agent_allocate` returns error for unknown agent name
- Unit test: `agent_allocate` returns success for known agent name
- Unit test: `inject_agent_notification` appends correct message format to human_queue
- Unit test: NOTIFY_MARK detection extracts correct user_id from list and str content
- Integration test: full flow — tool call → background execution → notification injection → mark detection
