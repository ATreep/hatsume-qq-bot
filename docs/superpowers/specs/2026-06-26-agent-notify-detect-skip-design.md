# Agent Notification Detection Skip in chat_end_detect_node

**Date:** 2026-06-26
**Status:** Designed
**Context:** Spec 015 — agent_allocate tool

## Problem

When `chat_agent` (ai_node) calls the `agent_allocate` tool, the spawned agent runs asynchronously and injects its result into `human_queue` via `inject_agent_notification()`. The injected message carries a `__agent_notify__` (NOTIFY_MARK) prefix.

After `human_node` drains the queue and creates a `HumanMessage`, the graph routes through `chat_end_detect_node`. The detect node has no awareness of the notification mark — it may run LLM-based detection and return "yes" (conversation should end), causing the graph to terminate at `finish` before `chat_llm` can process the agent result.

## Design

### Extract `detect_agent_notification()` — Reusable Function

Extract the NOTIFY_MARK scanning logic currently inline in `ai_node` (lines ~180–200) into a standalone function in `ai.py`:

```python
def detect_agent_notification(state: MessagesState) -> int | None:
    """Scan state["messages"][-1].content for NOTIFY_MARK.
    
    Returns the notified user_id (int) if the last message contains
    a __agent_notify__ mark, or None otherwise.
    """
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
                return int(uid_str)
    elif isinstance(last_content, str) and last_content.startswith(NOTIFY_MARK):
        _, uid_str, _ = last_content.split(":", 2)
        return int(uid_str)
    
    return None
```

### Early Return in `chat_end_detect_node`

At the top of `chat_end_detect_node`, before any existing logic:

```python
async def chat_end_detect_node(state: MessagesState) -> dict:
    # Early return: agent notification must always proceed to chat_llm
    if detect_agent_notification(state) is not None:
        return {"messages": []}
    # ... existing logic unchanged ...
```

Returning `{"messages": []}` makes the condition routing in `builder.py` take the `"continue"` path to `chat_llm`.

### Refactor `ai_node` to Use Extracted Function

Replace the inline detection block in `ai_node` with a call to the new function, removing the duplication.

### Exports

Add `detect_agent_notification` to `__init__.py`'s import from `.ai`.

## Files Changed

| File | Change |
|------|--------|
| `graph/nodes/ai.py` | Add `detect_agent_notification()` function; refactor `ai_node` to use it |
| `graph/nodes/detect.py` | Import `detect_agent_notification`; add early return at top of `chat_end_detect_node` |
| `graph/nodes/__init__.py` | Export `detect_agent_notification` |

## Edge Cases

- **No messages in state**: Impossible — the graph always has at least the system prompt + human message at this point.
- **Last message content is non-text** (e.g., image): `detect_agent_notification` gracefully returns `None` — no false positives.
- **NOTIFY_MARK appears mid-content, not at start**: `startswith()` check correctly ignores it — only true notification prefixes trigger the skip.
- **`detect_agent_notification` returns `None`**: Existing logic runs unchanged — no regression.

## Verification

- Unit test: `detect_agent_notification` returns uid for NOTIFY_MARK prefixed content, None otherwise
- Unit test: `chat_end_detect_node` returns `{"messages": []}` when last message has NOTIFY_MARK
- Integration: agent_allocate → inject → graph flow reaches chat_llm without early termination
