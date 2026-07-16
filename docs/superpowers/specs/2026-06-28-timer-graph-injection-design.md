# Design: Timer Graph Injection — Route Timer Prompts Through Existing Chat Agent

**Date:** 2026-06-28
**Status:** Approved
**Author:** Claude (one-workflow:brainstorm-specify-implement)

## Motivation

Currently, when a timer fires (`timer/executor.py:_run_timer_agent`), it creates a **completely standalone LangChain agent** that runs independently of the main conversation graph. This standalone agent:

- Has no access to conversation state, memory, or context
- Requires fragile tool isolation (`_save_tools_globals` / `_restore_tools_globals`)
- Delivers results directly via `bot.send_group_msg`, bypassing the graph entirely
- Can't benefit from the graph's memory retrieval, auxiliary context, or face-matching features

The goal is to route timer prompts through the **existing** LangGraph conversation, using the same injection pattern already proven by `agent_allocate` → `inject_agent_notification`.

## Design Decisions (Clarified During Brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Timer priority when chatting | **Interrupt** — inject directly into `human_queue` | Same as agent_allocate; timer message appears next in the graph loop |
| No active conversation | **Start new conversation** — like `_start_conv_for_agent` | Timer should be delivered promptly, not wait for idle queue to fill |
| Timer message format | **Include timer context** — system prompt + recent chat + user identity | Gives the AI full context about who set the timer and what's happening |
| Special identification mark | **Use `__timer__` mark** — mirrors `__agent_notify__` | Enables detect_node routing and AI @-mention of timer creator |

## Architecture

### Current Flow (BEFORE)

```
APScheduler fires
  ↓
_execute_wrapper()
  ↓
_execute_timer()
  ├─ Lookup task (user_id, group_id, prompt)
  ├─ Lookup username
  ├─ Fetch recent 5 messages
  ├─ Build timer system prompt
  ↓
_run_timer_agent()           ← INDEPENDENT AGENT
  ├─ Save/isolate tools globals
  ├─ Create standalone ChatOpenAI agent
  ├─ Replace _ai_answer with direct send_to_group
  ├─ Run agent independently
  ├─ Restore tools globals
  ↓
bot.send_group_msg()          ← Direct delivery, bypassing graph
```

### New Flow (AFTER)

```
APScheduler fires
  ↓
_execute_wrapper()
  ↓
_execute_timer()
  ├─ Lookup task (user_id, group_id, prompt)
  ├─ Lookup username
  ├─ Fetch recent 5 messages
  ├─ Build timer system prompt + context + task
  ├─ Build __timer__:{user_id} marked message
  ↓
_inject_timer_to_graph()     ← MIRRORS inject_agent_notification
  ├─ If chatting: append to _state.human_queue
  └─ If not chatting: start_conversation_cb()
  ↓
Existing LangGraph handles it:
  human_node → detect_node → ai_node → @mention user → continue/finish
```

### How It Mirrors Agent Allocate

```
agent_allocate                          timer
─────────────                          ─────
NOTIFY_MARK = "__agent_notify__"       TIMER_MARK = "__timer__"

detect_agent_notification()            detect_timer_notification()
  scans last message for                 scans last message for
  "__agent_notify__:" prefix             "__timer__:" prefix

inject_agent_notification()            inject_timer()
  appends to human_queue                 appends to human_queue
  (if chatting)                          (if chatting)
  OR calls start_conversation_cb         OR calls start_conversation_cb
  (if not chatting)                      (if not chatting)

detect_node:                           detect_node:
  if agent notify → continue             if timer → continue
                                          (add check alongside agent)

ai_node:                               ai_node:
  if notified_uid → @mention             if timer_uid → @mention
                                          (add check alongside agent)
```

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `timer/executor.py` | Remove `_run_timer_agent()`, `_save_tools_globals()`, `_restore_tools_globals()`. Add `_inject_timer_to_graph()`. Modify `_execute_timer()` to call injection instead of standalone agent. | ~-80, +40 |
| `graph/nodes/ai.py` | Add `TIMER_MARK`, `detect_timer_notification()`, `inject_timer()` functions. Wire timer detection into `ai_node`. | +40 |
| `graph/nodes/detect.py` | Add timer notification check alongside agent notification check in `chat_end_detect_node`. | +2 |
| `handlers/chat.py` | Add `_start_conv_for_timer()` callback (or extend `_start_conv_for_agent` to handle timer). Register timer injection callback. | +20 |
| `prompts.py` | Optionally simplify timer prompt builders (they no longer need to be full system prompts for a standalone agent). | ~-10 |

### No Changes To

- `timer/store.py` — storage layer unchanged
- `timer/__init__.py` — scheduler init unchanged
- `config.py` — timer constants unchanged
- `graph/tools.py` — `create_timer`, `list_timers`, `delete_timer` tools unchanged
- `state.py` — `ConversationState` unchanged (existing queues suffice)
- `graph/builder.py` — graph structure unchanged

## Detailed Implementation

### 1. New `TIMER_MARK` and Detection in `ai.py`

```python
TIMER_MARK = "__timer__"

def detect_timer_notification(state: MessagesState) -> int | None:
    """Scan state["messages"][-1].content for TIMER_MARK.
    Returns the notified user_id (int) or None."""
    last_content = state["messages"][-1].content
    if isinstance(last_content, list):
        for part in reversed(last_content):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(TIMER_MARK):
                _, uid_str = text.split(":", 1)
                return int(uid_str)
    elif isinstance(last_content, str) and last_content.startswith(TIMER_MARK):
        _, uid_str = last_content.split(":", 1)
        return int(uid_str)
    return None

def inject_timer(
    user_id: int,
    timer_prompt: str,
    context: str,
    start_conversation_cb: Any = None,
) -> None:
    """Build a __timer__ marked message and inject into the graph."""
    timer_msg = (
        f"{TIMER_MARK}:{user_id}\n"
        f"(SYSTEM) 定时任务已触发。以下是定时任务的上下文和内容，"
        f"请以你的口吻告知用户：\n\n"
        f"{context}\n\n"
        f"定时任务内容：{timer_prompt}"
    )
    if _state and _state.is_chatting:
        _state.human_queue.append({"type": "text", "text": timer_msg})
        _state.chat_peers.add(str(user_id))
    else:
        if start_conversation_cb is not None:
            start_conversation_cb(user_id, timer_msg)
```

### 2. Updated `detect_node` in `detect.py`

```python
from .ai import detect_agent_notification, detect_timer_notification

async def chat_end_detect_node(state: MessagesState) -> dict:
    # Agent notification: always route to chat_llm
    if detect_agent_notification(state) is not None:
        return {"messages": []}
    # Timer notification: always route to chat_llm
    if detect_timer_notification(state) is not None:
        return {"messages": []}
    # ... rest unchanged
```

### 3. Updated `ai_node` in `ai.py`

```python
async def ai_node(state: MessagesState) -> dict:
    # ...
    notified_uid = detect_agent_notification(state)
    timer_uid = detect_timer_notification(state)

    # ... (agent creation unchanged) ...

    # Send response
    ai_msg = MessageSegment.text(ai_text)
    if notified_uid is not None:
        # ... existing agent notification @mention ...
    elif timer_uid is not None:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, timer_uid)
    else:
        # ... normal send ...
```

### 4. Simplified `executor.py`

Remove (approximately lines 242–347):
- `_run_timer_agent()`
- `_save_tools_globals()`
- `_restore_tools_globals()`

Modify `_execute_timer()` (approximately line 140):
- Lines 172-178: Replace `_run_timer_agent()` call with `_inject_timer_to_graph()` call
- Lines 191-207: Remove steps 5-6 (mark fired + deliver) — firing is still marked, but delivery happens through the graph

### 5. New Injection in `executor.py`

```python
async def _inject_timer_to_graph(
    user_id: int, group_id: int, sys_prompt: str,
    task_prompt: str, context_msgs: list[dict],
) -> None:
    """Inject a timer prompt into the graph via the same pattern as agent_allocate."""
    from ..graph.nodes.ai import inject_timer

    context_text = "\n".join(
        m["text"] for m in context_msgs if isinstance(m, dict)
    ) if context_msgs else ""

    inject_timer(
        user_id=user_id,
        timer_prompt=task_prompt,
        context=f"System prompt: {sys_prompt}\n\nRecent context: {context_text}",
        start_conversation_cb=_timer_conv_callback,
    )
```

### 6. Callback Registration in `chat.py`

```python
def _start_conv_for_timer(user_id: int, notify_msg: str) -> None:
    """Start a new conversation for timer notification (mirrors _start_conv_for_agent)."""
    # ... identical pattern to _start_conv_for_agent ...
    conv_state.activate_chat(str(user_id))
    asyncio.create_task(
        start_new_conversation(
            conv_state, ai_cb, configure_tools,
            user_id=user_id,
            messages=[{"type": "text", "text": notify_msg}],
        )
    )
```

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Timer fires, conversation active | Inject into `human_queue` immediately; graph picks it up next cycle |
| Timer fires, no conversation | Start new conversation via `_start_conv_for_timer` |
| Timer fires, user not found | Still inject — AI can respond without @mention (existing behavior) |
| Timer fires, group unreachable | Log error, mark triggered as fired (existing behavior) |
| Timer fires during agent_allocate | Both use `human_queue` — processed in FIFO order |
| Timer fires right before detect_node ends conversation | `detect_timer_notification` check prevents end; routes to continue |
| Multiple timers fire simultaneously | All injected into `human_queue` in order; graph processes sequentially |
| Timer fires during clear command | `end_conversation()` clears state first, then `_start_conv_for_timer` starts fresh |

## Verification Strategy

1. **Unit tests** (`tests/test_timer_executor.py`): Test `_inject_timer_to_graph` builds correct message format; test `detect_timer_notification` extracts user_id correctly.
2. **Integration tests**: Test timer injection when chatting vs. not chatting.
3. **Manual test**: Create a short timer (1 minute), verify AI responds naturally with @mention to the timer creator.

## Rollback Plan

The change is additive in detection (new `detect_timer_notification`) and replaces `_run_timer_agent` with `_inject_timer_to_graph`. If issues arise:

1. Revert `executor.py` to restore `_run_timer_agent`
2. Remove `TIMER_MARK` detection from `ai.py` and `detect.py`
3. Remove `_start_conv_for_timer` from `chat.py`

The timer storage (`store.py`) and APScheduler integration (`__init__.py`) are unchanged, so the core timer infrastructure is unaffected by rollback.
