# Data Model: 自动回复上下文窗口优化

**Feature**: 006-auto-reply-context-window
**Date**: 2026-06-04

## Overview

This feature does not introduce new persistent data entities. It modifies how existing in-memory message lists are partitioned before being passed to the AI model. The data model changes are limited to two new configuration constants.

## Configuration Constants

### New Constants (in `config.py`)

| Constant | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTO_REPLY_CURRENT_MSG_COUNT` | `int` | `10` | Number of most recent messages treated as "current chat" for auto-reply |
| `AUTO_REPLY_HISTORY_MSG_COUNT` | `int` | `20` | Maximum number of older messages treated as "historical chat" for auto-reply |

### Relationship to Existing Constants

| Existing Constant | Value | Relationship |
|-------------------|-------|-------------|
| `CONTEXT_QUEUE_LEN` | `30` | `AUTO_REPLY_CURRENT_MSG_COUNT + AUTO_REPLY_HISTORY_MSG_COUNT = CONTEXT_QUEUE_LEN` (by convention, not enforced) |
| `CONTEXT_QUEUE_OVERLAP_LEN` | `7` | Unchanged — overlap is trimmed before current/history split |

### Validation Rules

- `AUTO_REPLY_CURRENT_MSG_COUNT >= 1` (must have at least one current message)
- `AUTO_REPLY_HISTORY_MSG_COUNT >= 0` (zero means no history)
- No hard requirement that `CURRENT + HISTORY = CONTEXT_QUEUE_LEN`, but exceeding it means some messages won't be used

## Message Flow (In-Memory)

### Before Change

```
idle_queue (30 msgs)
  ↓ flush_idle_to_auxiliary()
messages (all 30, last 7 kept as overlap)
  ↓ messages[CONTEXT_QUEUE_OVERLAP_LEN:]  (23 msgs)
human_queue ← all as "current"
```

### After Change

```
idle_queue (30 msgs)
  ↓ flush_idle_to_auxiliary()
messages (all 30, last 7 kept as overlap)
  ↓ messages[CONTEXT_QUEUE_OVERLAP_LEN:]  (23 msgs)
  ↓ split by recency
  ├─ older msgs → append_auxiliary_message() → auxiliary_queue as "历史聊天记录"
  └─ last N msgs → human_queue as "当前聊天记录"
```

### Split Logic (Pseudocode)

```python
msgs = messages[CONTEXT_QUEUE_OVERLAP_LEN:]  # trim overlap
N = AUTO_REPLY_CURRENT_MSG_COUNT

if len(msgs) <= N:
    current_msgs = msgs
    history_msgs = []
else:
    history_msgs = msgs[:-N]   # older messages
    current_msgs = msgs[-N:]   # latest N messages

append_auxiliary_message(history_msgs, history_sources)
# Then pass current_msgs to start_new_conversation()
```

## Entity Relationships

No new entities. The change affects how `idle_queue` messages are distributed across two existing queues:

```
idle_queue ──(flush)──→ messages[]
                           ├── older → auxiliary_messages_queue
                           └── recent → human_queue
                                        ↓
                                   human_node
                                        ↓
                              AI model context
```
