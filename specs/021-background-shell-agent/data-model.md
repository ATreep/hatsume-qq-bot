# Data Model: Background Shell Agent

**Date**: 2026-06-30
**Feature**: [spec.md](./spec.md)

## Entity: Background Command

Represents a running shell process managed by the background_shell agent.

| Field | Type | Description |
|-------|------|-------------|
| `proc_id` | `str` | Unique identifier, format: `bgshell_<8-hex-chars>` |
| `process` | `subprocess.Popen` | The running subprocess handle |
| `tmp_path` | `Path` | Path to temp file receiving merged stdout+stderr |
| `cmd` | `str` | The original shell command being executed |
| `description` | `str` | Natural language description + termination condition |
| `total_timeout` | `int` | Maximum allowed elapsed seconds (default 300) |
| `elapsed` | `int` | Total seconds elapsed since process start |
| `offset` | `int` | Byte offset for incremental tmp file reading |
| `full_output` | `str` | Accumulated output collected across all poll cycles |
| `check_interval` | `int` | Seconds between poll cycles (adjusted by decisions) |

**Lifecycle states**:

```
Created → Running → Done (completed successfully)
                   → Killed (terminated on error decision)
                   → Timeout (force-killed on elapsed >= total_timeout)
                   → Cancelled (asyncio.CancelledError from /clear)
```

**Storage**: In-memory only (`_background_procs` dict in `infra.py`). No persistence. Lost on bot restart.

## Entity: Poll Decision

The output of the code model at each monitoring cycle.

| Value | Meaning |
|-------|---------|
| `DONE` | Command completed successfully; stop monitoring |
| `KILL` | Command failed or is stuck; terminate immediately |
| `CONTINUE:N` | Command running normally; check again in N seconds |
| `NOTIFY:N` | Output needs user attention; inject to chat, check again in N seconds |

**Decision flow**: Code model receives (task description, new output, elapsed time, process status) → returns one of the four decision strings → handler parses and acts.

## Entity: Agent State

Managed by existing `_AGENT_STATES` dict in `graph/agents.py`. No new fields needed beyond the existing schema:

| Field | Value for background_shell |
|-------|---------------------------|
| `name` | `"background_shell"` |
| `status` | `"running"` during poll loop; `"done"` after completion |
| `task` | Truncated task description (first 200 chars) |
| `user_id` | The QQ user ID to notify |
| `started_at` | Unix timestamp when agent started |
| `result` | Final result message (set on completion) |
