# Sandbox Channel System

Sandbox Channel lets scripts and services running in the hatsume sandbox inject a
message into a target group's 初芽 through a Unix domain socket.

Use Sandbox Channel for an immediate one-off result, progress update, failure,
alert, or an event from a sandbox service that may continue running after the
current Coding Agent task. A Coding Agent's final report already returns to 初芽
through `agent_dispatch`; do not duplicate that report through this socket.

Use a Heartbeat Hook when 初芽 needs a persistent periodic monitor for an
external source and incremental changes. Only 初芽 can create, update, or delete
Heartbeat Hooks; Coding Agent may write and validate their scripts when 初芽
dispatches that work. Use Message-match Hooks for incoming QQ text patterns and
Timers for fixed calendar schedules.

## Target group

Set the JSON payload's required `group_id` field to the target QQ group number
as a positive integer. There is no implicit current-group default in the socket
protocol. `user_id` and `agent_name` describe the sender; they do not select the
destination.

Each `coding_agent` task receives its current QQ group number in its system
prompt, read from the bound group runtime when the agent is created. Use that
number as `group_id` when sending a Sandbox Channel message back to the task's group. The prompt
also identifies the socket and the global `sandbox-channel-guide` skill.

The receiver selects the group runtime using `channel_message.group_id`. If that group's
conversation is running, it queues the message with the internal
`_hatsume_system_trigger="sandbox_channel"` marker; otherwise it triggers a new
conversation for that group. Use a group configured for the bot to serve.

## Socket protocol

- Socket: `/tmp/hatsume_channel.sock` in the environment running the channel server;
  the sending script must be able to access that socket.
- Send one UTF-8 JSON object per connection, on a single line ending in `\n`.
  Encode newlines inside `content` as JSON escapes.
- The server reads the line with a five-second timeout and closes the connection
  after processing it.
- Responses are newline-terminated: `OK`, `INVALID`, `ERROR`, or `TIMEOUT`.
  `OK` acknowledges handler completion, not that 初芽 has finished
  processing the message or delivered a reply to QQ.

The current implementation uses the socket protocol, rather than polling
`/tmp/hatsume_channel/global.channel`. Do not use `[CHANNEL]` blocks or a `type` field.

## Payload

```json
{
  "timestamp": 1634567890.5,
  "group_id": 123456789,
  "content": "Task completed.",
  "user_id": 0,
  "agent_name": "coding_agent",
  "priority": "normal"
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `timestamp` | Yes | Unix timestamp, such as Python's `time.time()` |
| `group_id` | Yes | Target QQ group number, a positive integer |
| `content` | Yes | Nonempty message text; whitespace-only text is rejected |
| `user_id` | No | Sender's QQ number; defaults to `0` for system/anonymous |
| `agent_name` | No | Source name; defaults to an empty string |
| `priority` | No | `critical`, `normal`, or `low`; defaults to `normal` |

Priority does not change queue ordering in the current handler. All channel messages use
the same message-injection path. Unknown payload fields are rejected.

## Python example

Replace `123456789` with the current group number supplied in the coding agent's
prompt, or the intended target QQ group number.

```python
import json
import socket
import time

payload = {
    "timestamp": time.time(),
    "group_id": 123456789,
    "content": "Task completed.",
    "agent_name": "coding_agent",
}

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.settimeout(10)
    sock.connect("/tmp/hatsume_channel.sock")
    sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    with sock.makefile("rb") as response:
        status = response.readline().decode("utf-8").strip()
    if status != "OK":
        raise RuntimeError(f"Sandbox Channel submission failed: {status!r}")
```

## Implementation references

- `hatsume/plugins/hatsume-plugin/hooks/sandbox_channel.py`: payload validation,
  socket lifecycle, and responses.
- `hatsume/plugins/hatsume-plugin/hooks/sandbox_channel_handler.py`: group selection and
  conversation injection.
- `hatsume/plugins/hatsume-plugin/graph/agents.py`: coding agent prompt assembly.
- `data/hatsume-plugin/skills/sandbox-channel-guide.md`: global sending guide.

This socket submission protocol is separate from the stored heartbeat and
message hooks managed by `create_heartbeat_hook` and `create_message_hook`.
