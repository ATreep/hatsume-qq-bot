# Quickstart: Agent State Prompt Injection

**Feature**: 026-agent-state-injection

## Overview

This feature replaces the `check_agent` tool with passive system prompt injection. The chat_agent LLM always sees which background agents are running without needing to call a dedicated tool.

## Files Changed

| File | Change |
|------|--------|
| `prompts.py` | Add `build_agent_state_prompt()` |
| `graph/tools.py` | Remove `check_agent`, `_check_agent_used`, dedup gate |
| `graph/nodes/ai.py` | Remove `check_agent` from tools, inject agent state prompt |
| `tests/test_graph_nodes.py` | Remove `check_agent` stub |
| `tests/test_agent_allocate.py` | Remove `TestAgentAllocateDedupGuard` class |

## Verification

```bash
# Run full test suite
python -m pytest tests/ -xvs

# Verify check_agent is fully removed
grep -r "check_agent\|_check_agent_used" hatsume/

# Verify new function imports cleanly
python -c "from hatsume.plugins.hatsume_plugin.prompts import build_agent_state_prompt; print('OK')"
```

## Key Behavior Changes

**Before**: LLM calls `check_agent` → sees agent states → decides whether to allocate. If an agent is running and `check_agent` wasn't called first, `agent_allocate` refuses with a "call check_agent first" message.

**After**: Agent states are always visible in the system prompt. `agent_allocate` always accepts valid allocations (no gate). The LLM makes informed decisions based on the prompt context.
