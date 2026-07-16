# Data Model: Agent Allocate Tool

**Date**: 2026-06-26

## Entities

### Built-in Agent (in-memory registry entry)

```
AGENT_REGISTRY: dict[str, dict]
  key: agent_name (str) — unique identifier, e.g., "web_browser"
  value:
    description: str — human-readable description for tool prompt
    handler: Callable[[str, int], Coroutine[Any, Any, str]] — async handler function
```

**Validation**:
- Agent name must be a non-empty string
- Handler must be a callable accepting (task: str, user_id: int) and returning str
- Description must be non-empty

**State**: Static at runtime. Populated at module import by `register_agent()` calls.

### Agent Notification Mark

```
Format: "__agent_notify__:<user_id>:<agent_name>"
  user_id: int — QQ user ID to @-mention
  agent_name: str — originating agent name (for logging/tracing)
```

**Examples**:
- `__agent_notify__:123456:web_browser`
- `__agent_notify__:789012:generate_video`

### Notification Message

```
(SYSTEM) Agent '{agent_name}' 已执行完毕，以下是该 Agent 返回的结果，请以你的口吻告知用户结果：
__agent_notify__:<user_id>:<agent_name>
<agent_result_text>
```

Injected into `human_queue` as a dict:
```python
{"type": "text", "text": "<notification_message>"}
```

### Agent Allocate Tool Parameters

```
agent_allocate(
    notified_user_id: int,   # QQ ID to notify on completion
    agent_name: str,         # Registered agent name
    task: str                # Natural language task description
) -> str                     # Immediate confirmation or error
```

### Configuration Callbacks

```
_agent_notification_callback: Callable[[int, str], None] | None
  # (user_id: int, notify_msg: str) -> None
  # Set via configure_agent_notification_callback()
```

## State Transitions

```
[Idle] ──agent_allocate called──→ [Agent Running (background)]
                                        │
                               ┌────────┴────────┐
                               ▼                 ▼
                          [Success]          [Failure]
                               │                 │
                               └────────┬────────┘
                                        ▼
                              inject_agent_notification()
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                    is_chatting=True            is_chatting=False
                          │                           │
                   human_queue.append()    start_new_conversation()
                   chat_peers.add()

[human_node → ai_node]
  detect NOTIFY_MARK
  → ai_answer_with_at(msg, notified_uid)
```
