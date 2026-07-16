# Agent Dispatch Context — Design Spec

**Date:** 2026-07-06
**Status:** approved
**Predecessor:** [2026-06-26-agent-allocate-tool-design.md](2026-06-26-agent-allocate-tool-design.md)

## Motivation

When `chat_agent` dispatches a subagent via `agent_allocate`, the main conversation loses context about *why* that agent was dispatched. When the agent result is injected back into `human_queue`, there is no breadcrumb trail connecting the result to the original conversation. Adding a `context` argument closes this gap.

Additionally, the tool name `agent_allocate` is being renamed to `agent_dispatch` for better semantic clarity — "dispatch" more accurately describes sending an agent to execute a task, while "allocate" implies resource reservation.

## Requirements

1. **Add `context` parameter to the tool.** `context: str` — captures the background story at dispatch time: what users just discussed, what task was requested, and why a subagent is needed.
2. **Store `context` in agent instance state.** Use the existing `agent_instances` tracking in `agents.py` so `inject_agent_notification()` can retrieve it later.
3. **Include `context` in the injection message.** When the agent finishes, append context to the `notify_msg` in `human_queue` so the main chat agent sees why this subagent was dispatched.
4. **Rename `agent_allocate` → `agent_dispatch`.** Update all references across the project.

## Design

### Data Flow

```
User asks chat_agent to do something
        │
        ▼
chat_agent calls agent_dispatch(
    agent_name="coding_agent",
    task="optimize webpack config",
    context="用户刚才在讨论网站性能，首页加载 5s，需要降到 2s。需要重构打包配置来完成。"
)
        │
        ▼
agent_dispatch stores context in agent instance state
  → add_agent_instance(name, context=context, ...)
  → spawns background task _run_and_notify()
        │
        ▼
handler runs... completes... returns result
        │
        ▼
inject_agent_notification() reads context from agent state
  → get_agent_context(agent_name)
        │
        ▼
notify_msg injected into human_queue:
  __agent_notify__:123456:coding_agent
  (SYSTEM) Agent 'coding_agent' 执行完毕。
  📋 派发背景：用户刚才在讨论网站性能...
  任务：optimize webpack config
  ---
  {result}
```

### File-by-File Changes

#### 1. `graph/agents.py` — Extend agent state with context

- Add `"context"` key to the agent state dict returned by `get_agent_state()` (default `""` when absent)
- `set_agent_state()` accepts optional `context` kwarg, stores it
- New function `get_agent_context(name: str) -> str` for convenient retrieval
- `add_agent_instance()` passes through `context` kwarg

```python
# New helper
def get_agent_context(name: str) -> str:
    state = get_agent_state(name)
    return state.get("context", "") if state else ""
```

#### 2. `graph/tools.py` — Rename tool, add context param

- Function: `agent_allocate` → `agent_dispatch`
- New parameter: `context: str` (no default — required)
- Tool description updated with context usage guidance
- `_run_and_notify()`: calls `set_agent_state(agent_name, instance_id, context=context)` so the context persists through agent execution

```python
@tool(description=f"""将特定任务分配给 Subagent 后台执行。...
## 参数：
- agent_name: 内置 Agent 名称
- task: 要执行的任务描述
- context: 派发此 Agent 的背景上下文，包括用户的对话背景、需求和派发原因
- notified_user_id: 需要通知的用户 QQ ID,...""")
async def agent_dispatch(
    agent_name: str,
    task: str,
    context: str,
    notified_user_id: int = 0,
) -> str:
```

#### 3. `graph/nodes/ai.py` — Update injection message, update tool list

- `inject_agent_notification()`: new `context: str = ""` parameter. Embedded after the SYSTEM line, before the task line.
- Import `agent_dispatch` instead of `agent_allocate`. Add to `chat_agent` tools list.
- `respond_to_shell_prompt` import unchanged.
- Note: `inject_agent_notification` caller in `_run_and_notify` (tools.py) reads context from agent state and passes it explicitly.

```python
# Updated notify_msg format in inject_agent_notification:
notify_msg = (
    f"{NOTIFY_MARK}:{user_id}:{agent_name}\n"
    f"(SYSTEM) Agent '{agent_name}' 执行完毕。\n"
    f"📋 派发背景：{context}\n"
    f"任务：{task}\n"
    f"---\n"
    f"{result}"
)
```

#### 4. Global reference rename

Search and replace `agent_allocate` → `agent_dispatch` in:
- `graph/nodes/ai.py` (import + tools list)
- `graph/tools.py` (definition + description)
- `prompts.py` (any prompt text referencing the tool)
- `spec/modules/` (documentation)
- `CLAUDE.md` (project instructions)
- `tests/` (test files referencing the tool)
- `memory/MEMORY.md` and related memory files (if present)
- Any other files matched by `grep -r "agent_allocate"`

### Edge Cases

| Scenario | Handling |
|----------|----------|
| `context` is empty string | Still embed the `📋 派发背景：` line; the LLM can infer from task alone |
| `context` is very long (500+ chars) | The existing LLM context window handles this; no truncation needed — LLM benefits from full context |
| Multiple agents dispatched in sequence | Each gets its own context stored per-instance; `get_agent_context()` returns the latest instance's context |
| Agent dispatched when NOT chatting | `inject_agent_notification` path goes through `start_conversation_cb` — context is embedded in notify_msg regardless |
| Old `agent_allocate` references in memory/docs | Grep-and-replace covers all files; git history retains old name for archaeology |

### Non-Goals

- Not changing handler signatures (`_run_coding_agent`, `_run_background_shell`) — context is stored in state, not passed to handlers
- Not modifying `build_agent_state_prompt()` in this change (future enhancement: show context in agent state prompt)
- Not changing `respond_to_shell_prompt` or timer injection

## Verification

1. **Unit test**: `agent_dispatch` stores context in agent state
2. **Unit test**: `inject_agent_notification` formats message with context
3. **Unit test**: `get_agent_context` returns empty string for agents without context
4. **Grep verification**: No remaining `agent_allocate` references in working tree
5. **Integration**: Full agent dispatch → completion → injection flow with context preserved end-to-end

## Rollback Plan

If the context feature causes issues:
- Revert to treating `context` as optional with default `""`
- The `📋 派发背景：` line with empty content is harmless
- Rename `agent_dispatch` → `agent_allocate` would require another rename pass (not a rollback concern — this rename is a one-way improvement)
