# Agent Monitor & Deepseek Provider — Design Spec

> **Date:** 2026-06-28
> **Status:** Approved

## Overview

Two features implemented with minimal intrusion into the existing codebase:

1. **Agent Monitor** — track subagent running states in memory, prevent duplicate allocation, provide a query tool for the chat agent
2. **Deepseek Model Provider** — add Deepseek as a new LLM provider, route `get_code_model()` through Deepseek's official API

---

## Feature 1: Agent Monitor & Allocation Limitation

### Architecture

```
agent_allocate tool ──▶ is_agent_running() ──▶ reject if running
        │
        └──▶ asyncio.create_task(_run_and_notify)
                │
                ├── set_agent_state("running")
                ├── handler(task, user_id)
                └── set_agent_state("done", result=...)

check_agent tool ──▶ get_agent_state(name) ──▶ formatted status text
```

### Data Model

In-memory dict in `graph/agents.py`:

```python
_AGENT_STATES: dict[str, dict] = {}
# {
#   "coding_agent": {
#     "status": "running",          # idle | running | done
#     "task": "fix the login bug",
#     "user_id": 123456789,
#     "started_at": 1719600000.0,
#     "result": None,               # str | None, populated when done
#   },
# }
```

### State Machine

```
idle ──agent_allocate──▶ running
running ──success/failure──▶ done (result saved)
```

Failures also end in `done` state — no separate `error` state. The result string captures the error message.

### Files Changed

| File | Change | Details |
|------|--------|---------|
| `graph/agents.py` | Modify | Add `_AGENT_STATES` dict, `set_agent_state()`, `get_agent_state()`, `is_agent_running()` |
| `graph/tools.py` | Modify | Add running check to `agent_allocate`; add new `check_agent` tool |
| `graph/nodes/ai.py` | Modify | Register `check_agent` in chat_agent tools list |

### API Contracts

#### `set_agent_state(name: str, **kwargs) -> None`
Update fields in `_AGENT_STATES[name]`. Creates entry if not exists.

#### `get_agent_state(name: str) -> dict | None`
Return current state dict, or `None` if agent has never been used.

#### `is_agent_running(name: str) -> bool`
Return `True` if agent status is `"running"`.

#### `agent_allocate` behavior change
Before dispatching: call `is_agent_running(agent_name)`. If `True`, return:
```
错误：Agent '{agent_name}' 正在执行中，请等待完成后再分配。
```

#### `check_agent` tool
```python
@tool
async def check_agent(agent_name: str) -> str:
    """查看指定内置 Agent 的当前运行状态和结果。

    ## 参数：
    - agent_name: 内置 Agent 名称

    ## 返回：
    根据 agent 状态返回不同格式的信息：
    - idle: 提示 agent 空闲
    - running: 显示正在执行的任务
    - done: 显示任务和最终执行结果
    """
```

Return formats:
- `idle` → `"Agent '{agent_name}' 当前空闲，没有执行中的任务。"`
- `running` → `"Agent '{agent_name}' 正在执行任务。\n任务：{task}\n开始时间：{started_at}"`
- `done` → `"Agent '{agent_name}' 已完成上次任务。\n任务：{task}\n结果：\n{result}"`
- unknown → `"Agent '{agent_name}' 暂无记录。可用 Agent: ..."`

### Edge Cases

1. **Race condition**: `agent_allocate` creates asyncio task immediately after state check — in single-threaded asyncio, no real race exists between check and dispatch
2. **Agent crash**: Handler exception is caught, state set to `done` with error message as result
3. **Restart behavior**: All states lost (in-memory), which is acceptable — agents that were running are orphaned but that's an existing issue

---

## Feature 2: Deepseek Model Provider

### Architecture

```
get_code_model()
    └── ChatOpenAI(
            base_url=DEEPSEEK_BASE_URL,    # https://api.deepseek.com/v1
            model=DEEPSEEK_V4_PRO,          # deepseek-chat
            api_key=get_deepseek_api_key(), # reads DEEPSEEK_API_KEY from env
            temperature=2,
        )
```

No dependency on volcengine functions. Completely decoupled.

### Files Changed

| File | Change | Details |
|------|--------|---------|
| `config.py` | Modify | Add `DEEPSEEK_BASE_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_V4_PRO` constants + `get_deepseek_api_key()` |
| `models.py` | Modify | Rewrite `get_code_model()` to use Deepseek config directly |
| `.env.prod` | Modify | Append `DEEPSEEK_API_KEY=` placeholder |

### config.py Additions

```python
# ---------------------------------------------------------------------------
# Deepseek provider
# ---------------------------------------------------------------------------
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_V4_PRO: str = "deepseek-chat"

def get_deepseek_api_key() -> Callable[[], str]:
    return lambda: DEEPSEEK_API_KEY
```

### models.py — get_code_model() Rewrite

Before:
```python
def get_code_model() -> ChatOpenAI:
    return get_volcengine_api_model(DEEPSEEK_V4_FLASH)
```

After:
```python
def get_code_model() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=DEEPSEEK_BASE_URL,
        model=DEEPSEEK_V4_PRO,
        api_key=get_deepseek_api_key(),
        temperature=2,
    )
```

### Backward Compatibility

All callers of `get_code_model()` work unchanged — they receive a `ChatOpenAI` instance:
- `graph/tools.py` → `capture_html_shot` — calls `get_code_model()` for HTML generation
- `graph/agents.py` → `_run_coding_agent` — calls `get_code_model()` for coding agent
- `graph/nodes/ai.py` → `_maybe_send_face` — does NOT call `get_code_model()`, unaffected

The `reasoning_content` monkey-patch at the top of `models.py` already handles Deepseek-compatible response formats — no additional changes needed.

### Edge Cases

1. **Empty API key**: User is expected to fill in `DEEPSEEK_API_KEY` in `.env.prod`. If empty, Deepseek API returns 401 — natural failure, no special handling needed.
2. **DEEPSEEK_V4_FLASH constant**: Existing constant in config.py is now unused by `get_code_model()`. Can be removed or kept (no harm).

---

## Testing Strategy

### Agent Monitor Tests

1. `test_set_agent_state` — verify state dict is updated correctly
2. `test_is_agent_running` — verify returns True/False based on status
3. `test_get_agent_state_unknown` — verify returns None for unknown agents
4. `test_agent_allocate_rejects_when_running` — mock running state, verify rejection
5. `test_agent_allocate_accepts_when_idle` — verify normal dispatch

### Deepseek Provider Tests

1. `test_get_code_model_returns_deepseek` — verify model name, base_url match Deepseek config
2. `test_deepseek_api_key_from_env` — verify reads DEEPSEEK_API_KEY env var
3. `test_get_code_model_interface` — verify returns ChatOpenAI with compatible interface

### Integration

- Existing tests should continue passing (no breaking API changes)
- `_run_coding_agent` continues to work (same ChatOpenAI interface)

## Implementation Order

1. Deepseek Provider (config.py + models.py + .env.prod) — no dependencies
2. Agent Monitor (agents.py + tools.py + ai.py) — depends on existing agent infrastructure
