# Data Model: Background Shell Stdin Injection

**Date**: 2026-06-30

## Entities

### StdinRequest

Represents a pending request for stdin input from a background process.

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | `str` | Unique identifier: `stdin_<proc_id>_<seq>` (e.g., `stdin_bgshell_a1b2c3d4_0`) |
| `description` | `str` | Human-readable description of what input is needed (e.g., "sudo 密码") |
| `timeout` | `int` | Maximum wait time in seconds (default 300, code-model adjustable) |
| `context` | `str` | Recent process output showing the prompt (truncated to 500 chars) |
| `queue` | `asyncio.Queue[str \| None]` | Async queue bridging chat agent → bg shell agent |

**Lifecycle**:

```
┌──────────┐   INPUT_NEEDED    ┌───────────┐   queue.put(text)   ┌───────────┐
│  ACTIVE   │──────────────────▶│  WAITING   │───────────────────▶│ RESOLVED  │
│ (process  │   decision made   │ (awaiting  │   user responded   │ (stdin    │
│  running) │                   │  chat rsp) │                     │  written) │
└──────────┘                   └─────┬─────┘                    └───────────┘
                                     │
                                     │ timeout / cancel
                                     ▼
                               ┌───────────┐
                               │  EXPIRED  │
                               │ (None in  │
                               │  queue)   │
                               └───────────┘
```

- **ACTIVE → WAITING**: Code model returns `INPUT_NEEDED:<t>:<d>`, request_id generated, queue created
- **WAITING → RESOLVED**: `respond_to_shell_prompt` tool writes text to queue, queue entry removed
- **WAITING → EXPIRED**: `asyncio.wait_for` times out, queue entry removed, code model decides fallback
- **WAITING → CANCELLED**: `_cleanup_stdin_queues` puts `None` into queue during agent shutdown

### StdinQueues (Container)

Module-level registry mapping `request_id` → `asyncio.Queue`.

| Field | Type | Description |
|-------|------|-------------|
| `_stdin_queues` | `dict[str, asyncio.Queue[str \| None]]` | Global dict in `graph/agents.py` |

**Constraints**:
- Maximum one entry per `request_id` (enforced by `dict` key uniqueness)
- Entry removed on first `pop()` or `_cleanup_stdin_queues()`
- Only one consumer (bg shell agent poll loop) and one producer (chat agent tool) per queue

### StdinResolution

Output from the code model's secondary call when transforming raw chat text → final stdin content.

| Decision | Format | Meaning |
|----------|--------|---------|
| `FINAL_INPUT` | `FINAL_INPUT:<text>` | Write `<text>` to stdin (auto-appended `\n` if missing) |
| `KILL` | `KILL` | Kill the process (no safe fallback available) |
| `REISSUE` | `REISSUE:<timeout>:<description>` | Re-request input with updated timeout/description |

## Relationships

```
ChatAgent ──(respond_to_shell_prompt tool)──▶ StdinQueues ◀──(await queue.get)── BgShellAgent
                                                  │
                                                  ▼
                                            StdinRequest
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                                RESOLVED      EXPIRED      CANCELLED
                                    │             │             │
                                    ▼             ▼             ▼
                              FINAL_INPUT    code model    cleanup
                              → stdin        → KILL or     → kill
                                write           fallback
```
