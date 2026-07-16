# Quickstart: 自动回复上下文窗口优化

**Feature**: 006-auto-reply-context-window

## Overview

Modifies the auto-reply message context assembly to split messages into "current chat" (last 10) and "historical chat" (up to 20 earlier messages) before passing to the AI model.

## Files Changed

| File | Change |
|------|--------|
| `hatsume/plugins/hatsume-plugin/config.py` | Add 2 config constants |
| `hatsume/plugins/hatsume-plugin/handlers/chat.py` | Modify auto-reply message splitting in `user_chat_handle()` |

## Config Changes

Add to `config.py` in the Behavioral Constants section:

```python
AUTO_REPLY_CURRENT_MSG_COUNT: int = 10
AUTO_REPLY_HISTORY_MSG_COUNT: int = 20
```

## Logic Change

In `handlers/chat.py:user_chat_handle()`, replace the auto-reply `start_new_conversation()` call at lines 159-162.

**Before:**
```python
await start_new_conversation(
    conv_state, ai_cb, configure_tools,
    messages=messages[CONTEXT_QUEUE_OVERLAP_LEN:],
    sources=sources[CONTEXT_QUEUE_OVERLAP_LEN:]
)
```

**After:**
```python
from ..graph.nodes.ai import append_auxiliary_message

msgs = messages[CONTEXT_QUEUE_OVERLAP_LEN:]
srcs = sources[CONTEXT_QUEUE_OVERLAP_LEN:]
n = AUTO_REPLY_CURRENT_MSG_COUNT

if len(msgs) > n:
    append_auxiliary_message(msgs[:-n], srcs[:-n])
    msgs = msgs[-n:]
    srcs = srcs[-n:]

await start_new_conversation(
    conv_state, ai_cb, configure_tools,
    messages=msgs, sources=srcs,
)
```

## Verification

1. Start the bot in a test environment
2. Send 30+ messages to a group (can use mock/simulated messages)
3. Trigger auto-reply by reaching the queue threshold
4. Verify the AI receives context with "## 当前聊天记录：" (10 msgs) and "## 历史聊天记录：" (up to 20 msgs) markers

## No Downtime Required

This is a logic-only change. Deploy by restarting the NoneBot2 process.
