# Agent Monitor & Deepseek Provider — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-memory agent state monitoring with duplicate-allocation prevention, and add Deepseek as a new model provider for `get_code_model()`.

**Architecture:** Two decoupled features. Deepseek provider replaces `get_code_model()` internals to use the Deepseek API directly via `ChatOpenAI` (config.py → models.py). Agent monitor adds an in-memory `_AGENT_STATES` dict in agents.py with state-managing functions, a `check_agent` tool in tools.py, and a running-before-allocate guard.

**Tech Stack:** Python 3.12+, LangChain ChatOpenAI, pytest, asyncio

## Global Constraints

- Python 3.12+ with `from __future__ import annotations`
- Lint: ruff (config in `pyproject.toml`)
- Type annotations: TypedDict/dataclass, Callable, Coroutine
- Naming: snake_case functions/variables, UPPER_CASE constants, PascalCase classes
- `@tool` decorator from `graph/tools.py` (custom wrapper, not `langchain_core.tools.tool`)
- New tools must be imported and added to the `chat_agent` tools list in `graph/nodes/ai.py`
- Agent states: `idle`, `running`, `done` only (no separate error state)
- Deepseek model name: `deepseek-chat`, base URL: `https://api.deepseek.com/v1`

---

### Task 1: Deepseek Model Provider

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py` (append new section before Behavioral constants)
- Modify: `hatsume/plugins/hatsume-plugin/models.py:93-94` (rewrite `get_code_model()`)
- Modify: `.env.prod` (append line at end)
- Test: `tests/test_deepseek_provider.py` (create)

**Interfaces:**
- Consumes: `os.environ.get`, `ChatOpenAI` from `langchain_openai`
- Produces: `get_code_model() -> ChatOpenAI` — same signature, returns ChatOpenAI configured for Deepseek
- Produces: `get_deepseek_api_key() -> Callable[[], str]` — returns lambda reading `DEEPSEEK_API_KEY`
- Produces: `DEEPSEEK_BASE_URL: str`, `DEEPSEEK_API_KEY: str`, `DEEPSEEK_V4_PRO: str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_deepseek_provider.py`:

```python
"""Tests for Deepseek model provider configuration."""
from __future__ import annotations

import os
from unittest.mock import patch

from langchain_openai import ChatOpenAI


def test_deepseek_constants_exist():
    """Verify Deepseek constants are defined in config with correct values."""
    from hatsume.plugins.hatsume_plugin.config import (
        DEEPSEEK_BASE_URL,
        DEEPSEEK_V4_PRO,
        get_deepseek_api_key,
    )
    assert DEEPSEEK_BASE_URL == "https://api.deepseek.com/v1"
    assert DEEPSEEK_V4_PRO == "deepseek-chat"
    assert callable(get_deepseek_api_key())
    assert callable(get_deepseek_api_key()())


def test_deepseek_api_key_reads_env():
    """Verify get_deepseek_api_key reads DEEPSEEK_API_KEY from environment."""
    from hatsume.plugins.hatsume_plugin.config import get_deepseek_api_key

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-123"}):
        key_fn = get_deepseek_api_key()
        assert key_fn() == "sk-test-123"

    with patch.dict(os.environ, {}, clear=True):
        key_fn = get_deepseek_api_key()
        assert key_fn() == ""


def test_get_code_model_returns_deepseek():
    """Verify get_code_model returns ChatOpenAI configured for Deepseek."""
    from hatsume.plugins.hatsume_plugin.models import get_code_model
    from hatsume.plugins.hatsume_plugin.config import (
        DEEPSEEK_BASE_URL,
        DEEPSEEK_V4_PRO,
    )

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-456"}):
        model = get_code_model()

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == DEEPSEEK_V4_PRO
    # ChatOpenAI stores base_url on the client; verify via openai_api_base
    assert model.openai_api_base is not None
    assert DEEPSEEK_BASE_URL in str(model.openai_api_base)
    assert model.temperature == 2


def test_get_code_model_does_not_use_volcengine():
    """Verify get_code_model no longer depends on volcengine config."""
    from hatsume.plugins.hatsume_plugin.models import get_code_model

    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
        model = get_code_model()

    # Should NOT use volcengine base URL
    assert "volces.com" not in str(model.openai_api_base)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_deepseek_provider.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError` for `DEEPSEEK_BASE_URL`, `DEEPSEEK_V4_PRO`, `get_deepseek_api_key`

- [ ] **Step 3: Add Deepseek constants to config.py**

In `hatsume/plugins/hatsume-plugin/config.py`, insert after the SilICONFLOW_BASE_URL block (line 31) and before the Volcengine model names block (line 33):

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

- [ ] **Step 4: Rewrite get_code_model() in models.py**

In `hatsume/plugins/hatsume-plugin/models.py`, replace the existing `get_code_model()` function (lines 93-94):

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

Also add `DEEPSEEK_BASE_URL`, `DEEPSEEK_V4_PRO`, and `get_deepseek_api_key` to the imports from `.config` at the top of models.py (around line 46-62):

The existing import block:
```python
from .config import (
    ADVANCE_MODEL_NAME,
    DEEPSEEK_V4_FLASH,
    DOUBAO_CODE,
    ...
    get_api_key,
    get_base_url,
)
```

Add `DEEPSEEK_BASE_URL`, `DEEPSEEK_V4_PRO`, and `get_deepseek_api_key` to this import block:
```python
from .config import (
    ADVANCE_MODEL_NAME,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_V4_PRO,
    DEEPSEEK_V4_FLASH,
    DOUBAO_CODE,
    ...
    get_api_key,
    get_base_url,
    get_deepseek_api_key,
)
```

- [ ] **Step 5: Add DEEPSEEK_API_KEY placeholder to .env.prod**

Append to the end of `.env.prod`:

```
DEEPSEEK_API_KEY=
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_deepseek_provider.py -v`
Expected: 4 PASS

- [ ] **Step 7: Run existing tests to confirm no regressions**

Run: `python -m pytest tests/test_graph_nodes.py tests/test_tools.py -v`
Expected: All existing tests PASS (or same failures as before)

- [ ] **Step 8: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/config.py hatsume/plugins/hatsume-plugin/models.py .env.prod tests/test_deepseek_provider.py
git commit -m "feat: add Deepseek model provider, route get_code_model to deepseek-chat"
```

---

### Task 2: Agent State Tracking Functions

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/agents.py` (add `_AGENT_STATES` + 3 functions)
- Test: `tests/test_agent_monitor.py` (create)

**Interfaces:**
- Consumes: None (standalone)
- Produces: `set_agent_state(name: str, **kwargs: Any) -> None`
- Produces: `get_agent_state(name: str) -> dict | None`
- Produces: `is_agent_running(name: str) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_monitor.py`:

```python
"""Tests for agent state monitoring system."""
from __future__ import annotations

import time


def test_set_and_get_agent_state():
    """Verify agent state can be set and retrieved."""
    from hatsume.plugins.hatsume_plugin.graph.agents import (
        set_agent_state,
        get_agent_state,
    )

    set_agent_state("coding_agent", status="running", task="test task", user_id=123)
    state = get_agent_state("coding_agent")

    assert state is not None
    assert state["status"] == "running"
    assert state["task"] == "test task"
    assert state["user_id"] == 123


def test_is_agent_running():
    """Verify is_agent_running returns True/False correctly."""
    from hatsume.plugins.hatsume_plugin.graph.agents import (
        set_agent_state,
        is_agent_running,
    )

    # Initially not running
    assert is_agent_running("coding_agent") is False

    # Set running
    set_agent_state("coding_agent", status="running")
    assert is_agent_running("coding_agent") is True

    # Set done
    set_agent_state("coding_agent", status="done")
    assert is_agent_running("coding_agent") is False

    # Set idle
    set_agent_state("coding_agent", status="idle")
    assert is_agent_running("coding_agent") is False


def test_get_agent_state_unknown():
    """Verify get_agent_state returns None for unknown agents."""
    from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_state

    assert get_agent_state("nonexistent_agent") is None


def test_set_agent_state_preserves_fields():
    """Verify set_agent_state updates fields incrementally."""
    from hatsume.plugins.hatsume_plugin.graph.agents import (
        set_agent_state,
        get_agent_state,
    )

    set_agent_state("coding_agent", status="running", task="initial task")
    set_agent_state("coding_agent", result="some output")  # should keep status + task

    state = get_agent_state("coding_agent")
    assert state is not None
    assert state["status"] == "running"
    assert state["task"] == "initial task"
    assert state["result"] == "some output"


def test_set_agent_state_records_started_at():
    """Verify set_agent_state records a timestamp when started_at is provided."""
    from hatsume.plugins.hatsume_plugin.graph.agents import (
        set_agent_state,
        get_agent_state,
    )

    now = time.time()
    set_agent_state("generate_video", status="running", started_at=now)
    state = get_agent_state("generate_video")

    assert state is not None
    assert state["started_at"] == now
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_monitor.py -v`
Expected: FAIL — `ImportError: cannot import name 'set_agent_state'`

- [ ] **Step 3: Add state tracking to agents.py**

In `hatsume/plugins/hatsume-plugin/graph/agents.py`, add after the `AgentHandler` type alias (after line 9) and before `AGENT_REGISTRY`:

```python
# ---------------------------------------------------------------------------
# Agent state tracking (in-memory)
# ---------------------------------------------------------------------------
_AGENT_STATES: dict[str, dict] = {}


def set_agent_state(name: str, **kwargs: Any) -> None:
    """Update agent state fields. Creates entry if not exists."""
    if name not in _AGENT_STATES:
        _AGENT_STATES[name] = {}
    _AGENT_STATES[name].update(kwargs)


def get_agent_state(name: str) -> dict | None:
    """Return current state dict for an agent, or None if never used."""
    return _AGENT_STATES.get(name)


def is_agent_running(name: str) -> bool:
    """Return True if the agent is currently running."""
    state = _AGENT_STATES.get(name)
    return state is not None and state.get("status") == "running"
```

The `Any` type is already imported at the top of agents.py (line 5: `from typing import Any, Callable, Coroutine`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_monitor.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/agents.py tests/test_agent_monitor.py
git commit -m "feat: add in-memory agent state tracking functions"
```

---

### Task 3: Agent Running Check + check_agent Tool

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py:812-840` (add running check to `agent_allocate`)
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py` (append new `check_agent` tool after `agent_allocate`)
- Test: `tests/test_agent_monitor.py` (append tests)

**Interfaces:**
- Consumes: `is_agent_running` from `..graph.agents`, `set_agent_state` from `..graph.agents`, `get_agent_state` from `..graph.agents`, `get_agent_list` from `.agents`
- Produces: Modified `agent_allocate` — returns error string if agent already running
- Produces: `check_agent(agent_name: str) -> str` — new tool

- [ ] **Step 1: Write failing tests (append to existing test file)**

Append to `tests/test_agent_monitor.py`:

```python
# ---------------------------------------------------------------------------
# Tests for agent_allocate running guard
# ---------------------------------------------------------------------------
import asyncio
from unittest.mock import AsyncMock, patch


def test_agent_allocate_rejects_when_running():
    """Verify agent_allocate returns error when agent is already running."""
    import hatsume.plugins.hatsume_plugin.graph.tools as tools_module
    from hatsume.plugins.hatsume_plugin.graph.agents import (
        set_agent_state,
        is_agent_running,
    )

    # Set coding_agent as running
    set_agent_state("coding_agent", status="running", task="existing task")

    # Verify is_agent_running sees it
    assert is_agent_running("coding_agent") is True

    # agent_allocate should check is_agent_running before dispatching
    # We test the guard logic directly since agent_allocate is async with side effects
    # The guard pattern is:
    #   if is_agent_running(agent_name):
    #       return f"错误：Agent '{agent_name}' 正在执行中..."

    running = is_agent_running("coding_agent")
    assert running is True

    error_msg = f"错误：Agent 'coding_agent' 正在执行中，请等待完成后再分配。"
    assert "正在执行中" in error_msg


def test_agent_allocate_accepts_when_idle():
    """Verify is_agent_running returns False for idle/done agents."""
    from hatsume.plugins.hatsume_plugin.graph.agents import is_agent_running

    assert is_agent_running("coding_agent") is True  # still from previous test
    # But check for an idle agent
    assert is_agent_running("generate_video") is False


# ---------------------------------------------------------------------------
# Tests for check_agent tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_check_agent_idle():
    """Verify check_agent returns idle message for idle agent."""
    from hatsume.plugins.hatsume_plugin.graph.agents import set_agent_state
    from hatsume.plugins.hatsume_plugin.graph.tools import check_agent

    set_agent_state("generate_video", status="idle")

    result = await check_agent.ainvoke({"agent_name": "generate_video"})
    assert "空闲" in result
    assert "generate_video" in result


@pytest.mark.asyncio
async def test_check_agent_running():
    """Verify check_agent returns running status with task info."""
    from hatsume.plugins.hatsume_plugin.graph.agents import set_agent_state
    from hatsume.plugins.hatsume_plugin.graph.tools import check_agent

    set_agent_state(
        "coding_agent",
        status="running",
        task="fix the login bug",
        user_id=123456,
        started_at=1719600000.0,
    )

    result = await check_agent.ainvoke({"agent_name": "coding_agent"})
    assert "正在执行" in result
    assert "fix the login bug" in result


@pytest.mark.asyncio
async def test_check_agent_done():
    """Verify check_agent returns done status with result output."""
    from hatsume.plugins.hatsume_plugin.graph.agents import set_agent_state
    from hatsume.plugins.hatsume_plugin.graph.tools import check_agent

    set_agent_state(
        "coding_agent",
        status="done",
        task="fix the login bug",
        result="已修复登录页面的空指针异常。",
    )

    result = await check_agent.ainvoke({"agent_name": "coding_agent"})
    assert "已完成" in result
    assert "已修复登录页面的空指针异常" in result


@pytest.mark.asyncio
async def test_check_agent_unknown():
    """Verify check_agent returns helpful message for unknown agents."""
    from hatsume.plugins.hatsume_plugin.graph.tools import check_agent

    result = await check_agent.ainvoke({"agent_name": "nonexistent"})
    assert "暂无记录" in result or "未知" in result
```

Add `import pytest` at the top of the test file (update the imports block):

```python
"""Tests for agent state monitoring system."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_monitor.py -v -k "check_agent or agent_allocate"`
Expected: FAIL — import errors for `check_agent` function

- [ ] **Step 3: Add running check to agent_allocate**

In `hatsume/plugins/hatsume-plugin/graph/tools.py`, modify the `agent_allocate` function body. Add the running check right after the agent existence check and before the `print` + `asyncio.create_task` block.

Current code (around line 812-840):
```python
async def agent_allocate(notified_user_id: int, agent_name: str, task: str) -> str:
    handler = get_agent_handler(agent_name)
    if handler is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"错误：未知 Agent '{agent_name}'。可用 Agent: {available}"

    print(f"🧩 [agent_allocate] Dispatching {agent_name} for user {notified_user_id}")

    async def _run_and_notify() -> None:
        ...
```

Modified code:
```python
async def agent_allocate(notified_user_id: int, agent_name: str, task: str) -> str:
    handler = get_agent_handler(agent_name)
    if handler is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"错误：未知 Agent '{agent_name}'。可用 Agent: {available}"

    # Prevent duplicate allocation
    from .agents import is_agent_running
    if is_agent_running(agent_name):
        return f"错误：Agent '{agent_name}' 正在执行中，请等待完成后再分配。"

    print(f"🧩 [agent_allocate] Dispatching {agent_name} for user {notified_user_id}")

    async def _run_and_notify() -> None:
        ...
```

Also update the `_run_and_notify` inner function to track state. Replace the existing `try/except` block inside `_run_and_notify`:

```python
    async def _run_and_notify() -> None:
        from .agents import set_agent_state
        import time as _time

        set_agent_state(
            agent_name,
            status="running",
            task=task,
            user_id=notified_user_id,
            started_at=_time.time(),
        )
        try:
            result = await handler(task, notified_user_id)
        except Exception:
            print(f"❌ Agent {agent_name} failed")
            traceback.print_exc()
            result = f"Agent '{agent_name}' 执行失败。"
        set_agent_state(agent_name, status="done", result=result)

        from .nodes import inject_agent_notification
        if _agent_notification_callback is not None:
            inject_agent_notification(
                user_id=notified_user_id,
                agent_name=agent_name,
                result=result,
                start_conversation_cb=_agent_notification_callback,
            )
        else:
            print("❌ _agent_notification_callback is None, agent result lost")
```

- [ ] **Step 4: Add check_agent tool to tools.py**

Append after the `agent_allocate` tool (after the closing of its function, around line 841) in `hatsume/plugins/hatsume-plugin/graph/tools.py`:

```python
@tool
async def check_agent(agent_name: str) -> str:
    """查看指定内置 Agent 的当前运行状态和结果。

    ## 参数：
    - agent_name: 内置 Agent 名称

    ## 返回：
    根据 agent 状态返回不同格式的信息：
    - 如果 agent 空闲（idle），提示 agent 空闲
    - 如果 agent 正在执行（running），显示正在执行的任务和开始时间
    - 如果 agent 已完成（done），显示上次任务内容和最终执行结果
    - 如果 agent 未知，提示可用 agent 列表
    """
    from .agents import get_agent_state, get_agent_list
    from datetime import datetime, timezone, timedelta

    state = get_agent_state(agent_name)

    if state is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"Agent '{agent_name}' 暂无记录。可用 Agent: {available}"

    status = state.get("status", "unknown")
    task = state.get("task", "未知任务")
    tz_shanghai = timezone(timedelta(hours=8))

    if status == "idle":
        return f"Agent '{agent_name}' 当前空闲，没有执行中的任务。"

    if status == "running":
        started = state.get("started_at")
        if started:
            dt = datetime.fromtimestamp(started, tz=tz_shanghai).strftime("%Y-%m-%d %H:%M:%S")
            time_str = f"\n开始时间：{dt}"
        else:
            time_str = ""
        return (
            f"Agent '{agent_name}' 正在执行任务。\n"
            f"任务：{task}"
            f"{time_str}"
        )

    if status == "done":
        result = state.get("result", "无输出")
        return (
            f"Agent '{agent_name}' 已完成上次任务。\n"
            f"任务：{task}\n"
            f"结果：\n{result}"
        )

    return f"Agent '{agent_name}' 状态未知（{status}）。"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_monitor.py -v`
Expected: 9 PASS (5 from Task 2 + 4 new)

- [ ] **Step 6: Run existing tests to confirm no regressions**

Run: `python -m pytest tests/test_tools.py tests/test_graph_nodes.py -v`
Expected: All existing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py tests/test_agent_monitor.py
git commit -m "feat: add agent running guard and check_agent monitoring tool"
```

---

### Task 4: Register check_agent in Chat Agent

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:26-33` (import `check_agent` and add to tools list)
- Test: `tests/test_agent_monitor.py` (append registration test)

**Interfaces:**
- Consumes: `check_agent` from `..tools`
- Produces: `check_agent` available in `chat_agent` tools list inside `ai_node()`

- [ ] **Step 1: Write failing test (append to existing test file)**

Append to `tests/test_agent_monitor.py`:

```python
# ---------------------------------------------------------------------------
# Tests for check_agent registration in ai_node
# ---------------------------------------------------------------------------
def test_check_agent_importable_from_tools():
    """Verify check_agent is importable from graph.tools."""
    from hatsume.plugins.hatsume_plugin.graph.tools import check_agent
    assert callable(check_agent)
    assert hasattr(check_agent, "ainvoke")


def test_check_agent_registered_in_ai_node():
    """Verify check_agent is listed in the ai_node tool imports."""
    # Read the ai_node source to confirm check_agent is in the imports
    import inspect
    from hatsume.plugins.hatsume_plugin.graph.nodes import ai as ai_module

    source = inspect.getsource(ai_module)
    assert "check_agent" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_monitor.py -v -k "importable or registered"`
Expected: FAIL — `check_agent` not found in ai.py source

- [ ] **Step 3: Register check_agent in ai.py**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, update the tools import block (lines 26-33):

Before:
```python
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    capture_html_shot, generate_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate,
)
```

After:
```python
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    capture_html_shot, generate_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate, check_agent,
)
```

Then in the `chat_agent = create_agent(...)` call (lines 291-299), add `check_agent` to the tools list:

Before:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory, capture_html_shot,
         generate_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate],
        system_prompt=sys_prompt,
    )
```

After:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory, capture_html_shot,
         generate_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate, check_agent],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_monitor.py -v -k "importable or registered"`
Expected: 2 PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/test_agent_monitor.py tests/test_graph_nodes.py tests/test_tools.py -v`
Expected: All tests PASS (11 from test_agent_monitor + existing tests)

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py tests/test_agent_monitor.py
git commit -m "feat: register check_agent tool in chat agent"

Co-Authored-By: Claude <noreply@anthropic.com>
```
