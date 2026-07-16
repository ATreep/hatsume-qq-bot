# Remove check_agent Tool & Inject Agent States into System Prompt

## Motivation

Currently, the LLM must explicitly call `check_agent` (a tool) to discover whether
any background agents are running. This adds a tool-call round-trip and is gated
by `agent_allocate`'s dedup guard: if an agent is already running and `check_agent`
hasn't been called yet, `agent_allocate` refuses the allocation with a "call
check_agent first" message.

This was designed as a safety net to prevent duplicate agent creation. However,
the same information can be provided passively via system prompt injection,
eliminating the tool round-trip while still giving the LLM full visibility into
running agent states.

## Changes

### 1. Remove `check_agent` tool

**Rationale:** The LLM currently uses `check_agent` as a one-shot-per-turn status
query. By injecting the same information into the system prompt, the LLM always
knows what's running without an explicit tool call.

**What's removed:**
- `check_agent` tool function (`tools.py:926-988`)
- `_check_agent_used` global flag (`tools.py:80`)
- Reset of `_check_agent_used` in `reset_capture_flag()` (`tools.py:132-136`)
- Import of `check_agent` in `ai.py`
- `check_agent` from `chat_agent` tools list in `ai.py`

### 2. Remove dedup gate from `agent_allocate`

**Rationale:** The gate (`is_agent_running(agent_name) and not _check_agent_used`)
depends on `_check_agent_used`, which is removed. With agent states now injected
into the system prompt, the LLM can make informed decisions about whether to
re-allocate an agent.

**What's removed:**
- The `if is_agent_running(agent_name) and not _check_agent_used: return (...)` block
  in `agent_allocate` (`tools.py:881-886`)

### 3. Inject running agent states into chat_agent system prompt

**Rationale:** Mirroring the pattern of `build_skill_prompt()`, a new
`build_agent_state_prompt()` function generates a markdown section listing
all currently running background agents. This is appended to the system prompt
each `ai_node` call, giving the LLM passive visibility into agent states.

**Design:**
- New function `build_agent_state_prompt()` in `prompts.py`
- Called in `ai_node()` after skill prompt injection
- Uses `get_running_instances()` from `agents.py` (already exists)
- Lazy import inside the function to avoid circular imports (`prompts.py` →
  `agents.py` → `prompts.py`)
- Returns empty string when no agents are running (no injection)

**Injected prompt format:**
```markdown
# 后台 Agent 状态

以下 Agent 正在后台执行任务。你可以通过 agent_allocate 分配新任务，
但请注意当前已有 Agent 正在运行，避免分配重复或冲突的任务。

- **coding_agent**: 实现用户登录功能，已运行 45s
- **background_shell**: npm install large-package，已运行 120s
```

## Files Modified

| File | Changes |
|------|---------|
| `graph/tools.py` | Remove `_check_agent_used` flag, dedup gate, `check_agent` function |
| `graph/nodes/ai.py` | Remove `check_agent` from imports/tools; add `build_agent_state_prompt()` call |
| `prompts.py` | Add `build_agent_state_prompt()` function |

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| No agents running | `build_agent_state_prompt()` returns `""`, no injection |
| Multiple instances of same agent | Each shown as separate bullet with task and elapsed time |
| Agent finishes mid-conversation | Next `ai_node` call reflects updated state (prompt rebuilt each turn) |
| `_AGENT_STATES` never populated | Empty string, no injection |
| Circular import | Avoided by lazy import inside `build_agent_state_prompt()` function body |

## Non-Goals

- Changing `is_agent_running()` or `get_running_instances()` — these utilities remain
- Adding a new tool — the LLM learns about agent states passively, no new active query mechanism
- Showing completed/idle agent states — only running agents are injected; completed agents
  already notify via `inject_agent_notification()`
