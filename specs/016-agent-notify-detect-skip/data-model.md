# Data Model: Agent Notification Detection Skip

**Feature**: 016-agent-notify-detect-skip
**Date**: 2026-06-26

No new data entities are introduced. This feature operates on existing constructs:

## Existing Entities (read-only context)

### Agent Notification Mark (`NOTIFY_MARK`)

Constant string: `"__agent_notify__"`. Used as a message content prefix to identify agent result injections.

Format when embedded in a message:
```
__agent_notify__:<user_id:int>:<agent_name:str>
<result_text>
```

### MessagesState (LangGraph)

Standard LangGraph `MessagesState` dict with a `"messages"` key containing an ordered list of message objects. Each message has:
- `content`: `str | list[dict]` — text content or list of content parts (e.g., `[{"type": "text", "text": "..."}]`)
- `type`: str — message type (`"human"`, `"ai"`, `"system"`)
- `id`: str — unique message identifier

## New Interface

### `detect_agent_notification(state: MessagesState) -> int | None`

Pure function — no side effects.

- **Input**: `state["messages"][-1].content` — the last message's content
- **Output**: `int` (notified user ID) if NOTIFY_MARK found as prefix in any text part; `None` otherwise
- **Content type handling**:
  - `list[dict]`: Iterates parts in reverse, checks `part["text"]` for `startswith(NOTIFY_MARK)`
  - `str`: Checks `startswith(NOTIFY_MARK)` directly
  - Other types: Returns `None` (graceful fallback)
