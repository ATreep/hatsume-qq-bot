# Quickstart: Background Shell Agent

**Date**: 2026-06-30
**Feature**: [spec.md](./spec.md)

## How It Works (User Perspective)

1. A user asks the bot to run an interactive or long-running shell command
2. The bot's chat agent calls `agent_allocate("background_shell", task="...")` and tells the user "started"
3. The background_shell agent runs the command in Docker, polls periodically
4. If the command outputs a URL or other info the user needs, the bot relays it to chat
5. When the command finishes, times out, or fails — the bot notifies the user with results

## Testing

### Unit Tests

```bash
# Infra function tests (no Docker needed for read/kill)
python -m pytest tests/test_background_shell_infra.py -v

# Agent handler tests (mocked code model + infra)
python -m pytest tests/test_background_shell_agent.py -v
```

### Manual Integration Test

1. Start the bot: `nb run`
2. In a QQ group, ask: `帮我运行 gh auth login --hostname github.com --web`
3. Verify: bot responds it started, and relays the auth URL when it appears
4. Complete the auth in browser
5. Verify: bot notifies that auth succeeded

### Quick Smoke Test

```bash
# Verify imports resolve
python -c "
from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_handler
from hatsume.plugins.hatsume_plugin.infra import read_background_output, kill_background_cmd
from hatsume.plugins.hatsume_plugin.prompts import BACKGROUND_SHELL_DECISION_PROMPT
assert get_agent_handler('background_shell') is not None
assert len(BACKGROUND_SHELL_DECISION_PROMPT) > 0
print('All OK')
"
```

## Files Changed

| File | What Changed | Lines |
|------|-------------|-------|
| `prompts.py` | +`BACKGROUND_SHELL_DECISION_PROMPT` constant | ~40 |
| `infra.py` | +`start_background_cmd`, +`read_background_output`, +`kill_background_cmd`, +`_background_procs` dict, +`import tempfile` | ~70 |
| `graph/agents.py` | +`_run_background_shell` handler (~130 lines), +`register_agent("background_shell", ...)` | ~140 |

## Files NOT Changed

- `graph/tools.py` — `agent_allocate` dispatches by name; no new tool needed
- `graph/nodes/ai.py` — `inject_agent_notification`, `NOTIFY_MARK` used as-is
- `handlers/chat.py` — `_start_conv_for_agent` already wires agent notification callback
- `handlers/commands.py` — `/agents` already displays all agent states
