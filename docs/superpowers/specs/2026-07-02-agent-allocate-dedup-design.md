# Agent Allocate Deduplication Guard

**Date:** 2026-07-02
**Status:** approved

## Motivation

Currently `agent_allocate` unconditionally dispatches a new agent instance. If the chat LLM attempts to allocate an agent whose name already has a running instance, a duplicate is created. The LLM should instead call `check_agent` first to inspect the running state, then make an informed decision.

## Design

Add a guard in `agent_allocate` (in `graph/tools.py`) that:

1. Checks `is_agent_running(agent_name)` from `agents.py`
2. If running AND `_check_agent_used` is `False` → refuse with message instructing LLM to call `check_agent`
3. If running AND `_check_agent_used` is `True` → allow (LLM has seen the state)
4. If not running → allow (existing behavior, unchanged)

### Error message

```
Agent {name} 分配失败：为避免重复创建同一个 Agent，需要进行二次确认。请先调用 check_agent 工具后再决定是否分配 Agent。
```

## Files changed

- `hatsume/plugins/hatsume-plugin/graph/tools.py` — add `is_agent_running` import, add guard block in `agent_allocate`

## Edge cases

| Scenario | Behavior |
|----------|----------|
| Agent not running | Allow (unchanged) |
| Agent running, `check_agent` not called | Refuse, instruct to call `check_agent` |
| Agent running, `check_agent` just called | Allow (informed re-allocation) |
| `_check_agent_used` reset by `reset_capture_flag()` | Per-turn scope, no stale state |

## Dependencies

- `is_agent_running()` already exists in `agents.py` (line 75)
- `_check_agent_used` flag already tracked in `tools.py` (line 81), reset per turn (line 133)
