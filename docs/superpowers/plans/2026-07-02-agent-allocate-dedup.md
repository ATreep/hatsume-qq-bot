# Agent Allocate Deduplication Guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate agent allocation by refusing `agent_allocate` when an agent of the same name is already running, unless `check_agent` was called first in the same turn.

**Architecture:** Add a guard block at the top of `agent_allocate` that checks `is_agent_running(agent_name)` (existing function from `agents.py`) and `_check_agent_used` (existing module-level flag). If running + not checked → refuse. Otherwise → proceed.

**Tech Stack:** Python 3.12+, pytest

## Global Constraints

- Follow existing code patterns in `tools.py` (module-level globals, deferred references pattern)
- Use existing `is_agent_running()` from `graph/agents.py` (line 75)
- Use existing `_check_agent_used` flag from `tools.py` (line 81, reset at line 133)
- Message language: Chinese (matching other tool error messages)
- Test in `tests/test_agent_allocate.py` following existing test patterns

---

### Task 1: Add import for `is_agent_running` in tools.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py:25`

**Interfaces:**
- Consumes: `is_agent_running` from `hatsume.plugins.hatsume_plugin.graph.agents`
- Produces: import available for use in Task 2

- [ ] **Step 1: Add `is_agent_running` to the existing agents import**

Current line 25:
```python
from .agents import get_agent_list, get_agent_handler
```

Change to:
```python
from .agents import get_agent_list, get_agent_handler, is_agent_running
```

- [ ] **Step 2: Verify import works**

Run: `cd /path/to/hatsume && python -c "from hatsume.plugins.hatsume_plugin.graph.agents import is_agent_running; print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py
git commit -m "feat: add is_agent_running import to tools.py"
```

---

### Task 2: Add deduplication guard to agent_allocate

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py:861-903`

**Interfaces:**
- Consumes: `is_agent_running(name)` from Task 1, `_check_agent_used` global (existing)
- Produces: guarded `agent_allocate` — refuses duplicate allocations unless `check_agent` was called

- [ ] **Step 1: Add guard block after handler lookup**

In `agent_allocate`, after the existing handler check (lines 863-866):
```python
    handler = get_agent_handler(agent_name)
    if handler is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"错误：未知 Agent '{agent_name}'。可用 Agent: {available}"
```

Insert the guard:
```python
    # Dedup guard: refuse if agent is already running and LLM hasn't checked status
    if is_agent_running(agent_name) and not _check_agent_used:
        return (
            f"Agent {agent_name} 分配失败：为避免重复创建同一个 Agent，"
            f"需要进行二次确认。请先调用 check_agent 工具后再决定是否分配 Agent。"
        )
```

The complete `agent_allocate` function should look like:
```python
@tool(description=f"""将特定任务分配给 Subagent 后台执行。Subagent 完成任务后会通知你。
    不要暴露你使用 Agent 的事实，你要让用户认为所有的任务都是你在处理。

## 参数：
- agent_name: 内置 Agent 名称
- task: 要执行的任务描述
- notified_user_id: 需要通知的用户 QQ ID，如果有用户向你发起了任务，必须传入其QQ号（可选，默认为 0。如果不需要 @ 提醒任何用户，请设置为 0）

## 可用 Agent：
{_AGENT_LIST_STR}""")
async def agent_allocate(agent_name: str, task: str, notified_user_id: int = 0) -> str:

    handler = get_agent_handler(agent_name)
    if handler is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"错误：未知 Agent '{agent_name}'。可用 Agent: {available}"

    # Dedup guard: refuse if agent is already running and LLM hasn't checked status
    if is_agent_running(agent_name) and not _check_agent_used:
        return (
            f"Agent {agent_name} 分配失败：为避免重复创建同一个 Agent，"
            f"需要进行二次确认。请先调用 check_agent 工具后再决定是否分配 Agent。"
        )

    print(f"🧩 [agent_allocate] Dispatching {agent_name} (notify_user={notified_user_id})")

    async def _run_and_notify() -> None:
        from .agents import add_agent_instance, set_agent_state
        import time as _time

        instance_id = add_agent_instance(
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
        set_agent_state(agent_name, instance_id=instance_id, status="done", result=result)

        from .nodes import inject_agent_notification
        if _agent_notification_callback is not None:
            inject_agent_notification(
                user_id=notified_user_id,
                group_id=_current_group_id or 0,
                agent_name=agent_name,
                result=result,
                task=task,
                start_conversation_cb=_agent_notification_callback,
            )
        else:
            print("❌ _agent_notification_callback is None, agent result lost")

    asyncio.create_task(_run_and_notify())
    return f"✅ Agent '{agent_name}' 正在执行，完成后将通知你。"
```

- [ ] **Step 2: Run existing tests to ensure no regression**

Run: `cd /path/to/hatsume && python -m pytest tests/test_agent_allocate.py -xvs`
Expected: existing tests still pass

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py
git commit -m "feat: add agent dedup guard to agent_allocate tool"
```

---

### Task 3: Write tests for the dedup guard

**Files:**
- Modify: `tests/test_agent_allocate.py`

**Interfaces:**
- Consumes: `agent_allocate` from Task 2, `check_agent` from `tools.py`, `is_agent_running` / `_AGENT_STATES` from `agents.py`
- Produces: test coverage for the three guard scenarios

- [ ] **Step 1: Add test class and imports to test file**

At the top of `tests/test_agent_allocate.py`, add the needed imports after the existing ones:
```python
    async def dummy_handler(task: str, user_id: int) -> str:
        return f"done: {task"
```

Wait, let me write the actual test code properly. Let me look at the exact test patterns used.

Actually, let me write the test additions:

```python
class TestAgentAllocateDedupGuard:
    """Tests for the agent deduplication guard in agent_allocate."""

    def test_refuses_when_agent_running_and_not_checked(self):
        """agent_allocate refuses when agent is running and check_agent wasn't called."""
        import asyncio
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
            _AGENT_STATES,
            register_agent,
            is_agent_running,
        )
        from hatsume.plugins.hatsume_plugin.graph import tools

        original_registry = dict(AGENT_REGISTRY)
        original_states = dict(_AGENT_STATES)
        AGENT_REGISTRY.clear()
        _AGENT_STATES.clear()
        try:
            async def dummy_handler(task: str, user_id: int) -> str:
                return f"done: {task}"

            register_agent("test_dedup", "Test dedup agent", dummy_handler)

            # Simulate agent already running
            _AGENT_STATES["test_dedup"] = [{
                "instance_id": "test_dedup_abc123",
                "name": "test_dedup",
                "status": "running",
                "task": "some task",
                "user_id": 0,
                "started_at": 1234567890.0,
            }]

            # Reset _check_agent_used to False
            tools.reset_capture_flag()

            result = asyncio.run(
                tools.agent_allocate.ainvoke({
                    "agent_name": "test_dedup",
                    "task": "do something",
                    "notified_user_id": 0,
                })
            )

            assert "分配失败" in str(result)
            assert "check_agent" in str(result)
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(original_registry)
            _AGENT_STATES.clear()
            _AGENT_STATES.update(original_states)

    def test_allows_when_agent_running_and_check_agent_was_called(self):
        """agent_allocate allows when check_agent was called this turn."""
        import asyncio
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
            _AGENT_STATES,
            register_agent,
        )
        from hatsume.plugins.hatsume_plugin.graph import tools

        original_registry = dict(AGENT_REGISTRY)
        original_states = dict(_AGENT_STATES)
        AGENT_REGISTRY.clear()
        _AGENT_STATES.clear()
        try:
            async def dummy_handler(task: str, user_id: int) -> str:
                return f"done: {task}"

            register_agent("test_dedup2", "Test dedup agent 2", dummy_handler)

            # Simulate agent already running
            _AGENT_STATES["test_dedup2"] = [{
                "instance_id": "test_dedup2_abc123",
                "name": "test_dedup2",
                "status": "running",
                "task": "some task",
                "user_id": 0,
                "started_at": 1234567890.0,
            }]

            # Simulate check_agent was called (sets _check_agent_used = True)
            tools.reset_capture_flag()
            # Directly set the flag as check_agent would
            tools._check_agent_used = True

            result = asyncio.run(
                tools.agent_allocate.ainvoke({
                    "agent_name": "test_dedup2",
                    "task": "do something else",
                    "notified_user_id": 0,
                })
            )

            assert "正在执行" in str(result)
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(original_registry)
            _AGENT_STATES.clear()
            _AGENT_STATES.update(original_states)

    def test_allows_when_agent_not_running(self):
        """agent_allocate allows when agent is not running (normal path)."""
        import asyncio
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
            _AGENT_STATES,
            register_agent,
        )
        from hatsume.plugins.hatsume_plugin.graph import tools

        original_registry = dict(AGENT_REGISTRY)
        original_states = dict(_AGENT_STATES)
        AGENT_REGISTRY.clear()
        _AGENT_STATES.clear()
        try:
            async def dummy_handler(task: str, user_id: int) -> str:
                return f"done: {task}"

            register_agent("test_dedup3", "Test dedup agent 3", dummy_handler)

            # No agent running
            tools.reset_capture_flag()

            result = asyncio.run(
                tools.agent_allocate.ainvoke({
                    "agent_name": "test_dedup3",
                    "task": "do something",
                    "notified_user_id": 0,
                })
            )

            assert "正在执行" in str(result)
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(original_registry)
            _AGENT_STATES.clear()
            _AGENT_STATES.update(original_states)
```

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `cd /path/to/hatsume && python -m pytest tests/test_agent_allocate.py -xvs -k "TestAgentAllocateDedupGuard"`
Expected: 3 tests pass

- [ ] **Step 3: Run all tests to ensure no regression**

Run: `cd /path/to/hatsume && python -m pytest tests/ -xvs`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_allocate.py
git commit -m "test: add dedup guard tests for agent_allocate"
```
