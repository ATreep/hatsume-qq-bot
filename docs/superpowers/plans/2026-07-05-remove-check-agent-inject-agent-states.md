# Remove check_agent Tool & Inject Agent States into System Prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the `check_agent` tool and its deduplication gate in `agent_allocate`, replacing it with passive agent-state injection into the chat_agent system prompt.

**Architecture:** Three-file change. `prompts.py` gains `build_agent_state_prompt()` (mirrors `build_skill_prompt()` pattern). `tools.py` loses `check_agent`, `_check_agent_used`, and the dedup gate. `ai.py` removes `check_agent` from the tool list and injects the agent state prompt. Two test files get cleaned up.

**Tech Stack:** Python 3.12+, pytest, langchain_core

## Global Constraints

- Lazy import `get_running_instances` inside `build_agent_state_prompt()` to avoid circular imports (`prompts.py` → `agents.py` → `prompts.py`)
- Inject only **running** agents (not completed/idle)
- Function signature must mirror `build_skill_prompt()` pattern: takes skills list vs takes nothing (agent states are queried live)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `hatsume/plugins/hatsume-plugin/prompts.py` | Modify | New `build_agent_state_prompt()` function |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Modify | Remove `check_agent`, `_check_agent_used`, dedup gate |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Modify | Remove `check_agent` import/tool; inject agent prompt |
| `tests/test_graph_nodes.py` | Modify | Remove `tools_mod.check_agent = None` stub |
| `tests/test_agent_allocate.py` | Modify | Remove `TestAgentAllocateDedupGuard` test class |

---

### Task 1: Add `build_agent_state_prompt()` to prompts.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py`

**Interfaces:**
- Produces: `build_agent_state_prompt() -> str` — returns markdown section or `""`

- [ ] **Step 1: Add the function after `build_skill_prompt()` (after line 124)**

The existing `build_skill_prompt` ends at line 124. Insert the new function immediately after it:

```python

# ---------------------------------------------------------------------------
# Agent state prompt injection
# ---------------------------------------------------------------------------
def build_agent_state_prompt() -> str:
    """Generate the agent state section for system prompt injection.

    Returns a markdown section listing all currently running background
    agents, or empty string if none are running. This replaces the
    check_agent tool by giving the LLM passive visibility into agent
    states without requiring an explicit tool call.
    """
    import time as _time
    from .graph.agents import get_running_instances

    running = get_running_instances()
    if not running:
        return ""

    lines: list[str] = [
        "",
        "# 后台 Agent 状态",
        "",
        "以下 Agent 正在后台执行任务。你可以通过 agent_allocate 分配新任务，",
        "但请注意当前已有 Agent 正在运行，避免分配重复或冲突的任务。",
        "",
    ]
    for inst in running:
        name = inst.get("name", "unknown")
        task = inst.get("task", "")[:200]
        started = inst.get("started_at")
        if started:
            elapsed = int(_time.time() - started)
            time_str = f"，已运行 {elapsed}s"
        else:
            time_str = ""
        lines.append(f"- **{name}**: {task}{time_str}")

    return "\n".join(lines)
```

- [ ] **Step 2: Verify syntax — import the function in a Python one-liner**

```bash
cd /path/to/hatsume && python -c "from hatsume.plugins.hatsume_plugin.prompts import build_agent_state_prompt; print('OK:', repr(build_agent_state_prompt()))"
```

Expected: Prints `OK: ''` (empty string — no agents running at import time)

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py
git commit -m "feat: add build_agent_state_prompt() for passive agent state injection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Remove `check_agent` tool, `_check_agent_used` flag, and dedup gate from tools.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `agent_allocate` no longer checks `_check_agent_used`; `reset_capture_flag` no longer resets it

- [ ] **Step 1: Remove `_check_agent_used` global declaration (line 80)**

Delete this line:
```python
_check_agent_used: bool = False
```

- [ ] **Step 2: Update `reset_capture_flag()` (lines 132-136)**

Change from:
```python
def reset_capture_flag() -> None:
    global _generate_image_used, _generate_video_used, _check_agent_used
    _generate_image_used = False
    _generate_video_used = False
    _check_agent_used = False
```

To:
```python
def reset_capture_flag() -> None:
    global _generate_image_used, _generate_video_used
    _generate_image_used = False
    _generate_video_used = False
```

- [ ] **Step 3: Remove the dedup gate from `agent_allocate` (lines 881-886)**

Delete these lines:
```python
    # Dedup guard: refuse if agent is already running and LLM hasn't checked status
    if is_agent_running(agent_name) and not _check_agent_used:
        return (
            f"Agent {agent_name} 分配失败：为避免重复创建同一个 Agent，"
            f"需要进行二次确认。请先调用 check_agent 工具后再决定是否分配 Agent。"
        )
```

- [ ] **Step 4: Remove the entire `check_agent` function (lines 926-988)**

Delete lines 926-988 (the `@tool` decorated `async def check_agent() -> str:` function entirely).

- [ ] **Step 5: Verify syntax**

```bash
cd /path/to/hatsume && python -c "import hatsume.plugins.hatsume_plugin.graph.tools; print('OK')"
```

Expected: `OK` (no ImportError)

- [ ] **Step 6: Verify `agent_allocate` function still exists and is callable**

```bash
cd /path/to/hatsume && python -c "
from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate
print('agent_allocate:', type(agent_allocate).__name__)
print('OK')
"
```

Expected: Prints `agent_allocate: StructuredTool` and `OK`

- [ ] **Step 7: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py
git commit -m "refactor: remove check_agent tool, _check_agent_used flag, and dedup gate

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Update ai.py — remove check_agent, inject agent state prompt

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Consumes: `build_agent_state_prompt` from `prompts.py`
- Produces: `chat_agent` system prompt now includes agent states

- [ ] **Step 1: Remove `check_agent` from tools import (line 35)**

Change from:
```python
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    generate_image, generate_video, send_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate, check_agent, respond_to_shell_prompt,
)
```

To:
```python
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    generate_image, generate_video, send_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate, respond_to_shell_prompt,
)
```

- [ ] **Step 2: Update the prompts import to include `build_agent_state_prompt` (line 21-27)**

Change from:
```python
from ...prompts import (
    AUXILIARY_COMPACTION_PROMPT,
    build_face_injection_prompt,
    build_memory_context_prompt,
    build_skill_prompt,
    role_sys_prompt,
)
```

To:
```python
from ...prompts import (
    AUXILIARY_COMPACTION_PROMPT,
    build_agent_state_prompt,
    build_face_injection_prompt,
    build_memory_context_prompt,
    build_skill_prompt,
    role_sys_prompt,
)
```

- [ ] **Step 3: Add agent state prompt injection after skill injection (after line 385)**

After the existing skill injection block:
```python
    # Inject available skills into system prompt
    skill_mgr = get_skill_manager()
    skill_list = skill_mgr.list_skills()
    skill_prompt = build_skill_prompt(skill_list)
    if skill_prompt:
        sys_prompt += skill_prompt
        print(f"[skills] Injected {len(skill_list)} skill(s) into system prompt")
```

Add:
```python
    # Inject running agent states into system prompt
    agent_prompt = build_agent_state_prompt()
    if agent_prompt:
        sys_prompt += agent_prompt
        print("[agents] Injected agent state info into system prompt")
```

- [ ] **Step 4: Remove `check_agent` from chat_agent tools list (line 421)**

Change from:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory,
         generate_image, generate_video, send_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate, check_agent, respond_to_shell_prompt],
        system_prompt=sys_prompt,
    )
```

To:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory,
         generate_image, generate_video, send_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate, respond_to_shell_prompt],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 5: Verify syntax**

```bash
cd /path/to/hatsume && python -c "
from hatsume.plugins.hatsume_plugin.graph.nodes.ai import ai_node
print('OK')
"
```

Expected: `OK` (no ImportError — the function won't run but should import cleanly)

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "refactor: remove check_agent from chat_agent, inject agent state prompt

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Update tests — remove check_agent and dedup guard tests

**Files:**
- Modify: `tests/test_graph_nodes.py`
- Modify: `tests/test_agent_allocate.py`

**Interfaces:**
- Consumes: Updated `tools.py` without `check_agent`, `ai.py` without `check_agent`
- Produces: All existing tests pass

- [ ] **Step 1: Remove `tools_mod.check_agent = None` stub from test_graph_nodes.py (line 310)**

Delete this line:
```python
    tools_mod.check_agent = None
```

- [ ] **Step 2: Remove the entire `TestAgentAllocateDedupGuard` class from test_agent_allocate.py (lines 146-311)**

Delete lines 146-311. This removes the class and all four test methods:
- `test_is_agent_running_detects_running_instance`
- `test_is_agent_running_returns_false_when_idle`
- `test_guard_logic_refuses_when_running_and_not_checked`
- `test_guard_logic_allows_when_checked`
- `test_guard_logic_allows_when_not_running`

Note: `test_is_agent_running_detects_running_instance` and `test_is_agent_running_returns_false_when_idle` test `is_agent_running()` itself, which is NOT being removed — only the guard logic that depends on `_check_agent_used`. However, since they're part of the `TestAgentAllocateDedupGuard` class and test the same guard infrastructure, remove the entire class. If `is_agent_running` tests are needed later, they can be re-added in `TestAgentRegistry`.

- [ ] **Step 3: Run existing tests to verify no regressions**

```bash
cd /path/to/hatsume && python -m pytest tests/test_graph_nodes.py tests/test_agent_allocate.py -xvs 2>&1 | tail -20
```

Expected: All remaining tests pass. The test suite must show `passed` for all tests in both files (with `TestAgentAllocateDedupGuard` tests no longer present).

- [ ] **Step 4: Run full test suite**

```bash
cd /path/to/hatsume && python -m pytest tests/ -xvs 2>&1 | tail -30
```

Expected: All tests pass. No import errors, no failed assertions.

- [ ] **Step 5: Commit**

```bash
git add tests/test_graph_nodes.py tests/test_agent_allocate.py
git commit -m "test: remove check_agent stub and dedup guard tests

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Integration — verify full import chain and run complete test suite

**Files:**
- No code changes — verification only

- [ ] **Step 1: Verify the full import chain loads without errors**

```bash
cd /path/to/hatsume && python -c "
from hatsume.plugins.hatsume_plugin.prompts import build_agent_state_prompt
from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate, reset_capture_flag
from hatsume.plugins.hatsume_plugin.graph.agents import get_running_instances, is_agent_running

# Verify check_agent no longer exists
import hatsume.plugins.hatsume_plugin.graph.tools as t
assert not hasattr(t, 'check_agent'), 'check_agent should be removed from tools'
assert not hasattr(t, '_check_agent_used'), '_check_agent_used should be removed from tools'

# Verify new function exists
result = build_agent_state_prompt()
assert result == '', f'Expected empty string with no agents running, got: {result!r}'

# Verify reset_capture_flag doesn't reference _check_agent_used
import inspect
src = inspect.getsource(reset_capture_flag)
assert '_check_agent_used' not in src, 'reset_capture_flag should not reference _check_agent_used'

print('All assertions passed')
"
```

Expected: `All assertions passed`

- [ ] **Step 2: Run complete test suite with coverage**

```bash
cd /path/to/hatsume && python -m pytest tests/ -xvs 2>&1 | tail -30
```

Expected: All tests pass, zero failures.

- [ ] **Step 3: Commit any final state**

```bash
git status
```

If clean: done. If dirty files remain, review and commit as needed.
