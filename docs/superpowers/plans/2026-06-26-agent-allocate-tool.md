# Agent Allocate Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `agent_allocate` tool that dispatches built-in agents (web browser, video generation) in the background and injects results back into the conversation flow with @-notification.

**Architecture:** New `graph/agents.py` registers built-in agents with handler functions. `agent_allocate` tool in `graph/tools.py` dispatches them via `asyncio.create_task`. On completion, `inject_agent_notification()` in `graph/nodes/ai.py` injects a `__agent_notify__:<uid>:<name>` prefixed message into `human_queue` (or starts a new conversation via callback if idle). `ai_node` reverse-scans the last message content for the mark, extracts `notified_uid`, and sends via `ai_answer_with_at`.

**Tech Stack:** Python 3.12+, LangChain tools, NoneBot2, asyncio

## Global Constraints

- Python 3.12+, `from __future__ import annotations`
- Lint: ruff (config in `pyproject.toml`)
- Naming: snake_case functions/vars, UPPER_CASE constants
- Follow existing `@tool` decorator pattern from `graph/tools.py`
- New tools must be imported in `graph/nodes/ai.py` and added to `create_agent` tools list
- TDD: write tests first, watch them fail, implement minimally

---

### Task 1: Create `graph/agents.py` — Registry infrastructure

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/graph/agents.py`

**Interfaces:**
- Produces:
  - `AGENT_REGISTRY: dict[str, dict]` — `{name: {"description": str, "handler": Callable}}`
  - `AgentHandler = Callable[[str, int], Coroutine[Any, Any, str]]`
  - `register_agent(name: str, description: str, handler: AgentHandler) -> None`
  - `get_agent_list() -> list[dict[str, str]]` — returns `[{"name": ..., "description": ...}, ...]`
  - `get_agent_handler(name: str) -> AgentHandler | None`

- [ ] **Step 1: Write the test**

Create `tests/test_agent_allocate.py`:

```python
"""Tests for agent_allocate tool and agents registry."""
from __future__ import annotations

import pytest


class TestAgentRegistry:
    """Tests for graph/agents.py registry functions."""

    def test_register_and_get_agent_list(self):
        """get_agent_list returns all registered agents."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
            register_agent,
            get_agent_list,
            get_agent_handler,
        )

        # Clear registry for isolated test
        original = dict(AGENT_REGISTRY)
        AGENT_REGISTRY.clear()
        try:
            async def dummy_handler(task: str, user_id: int) -> str:
                return f"done: {task}"

            register_agent("test_agent", "A test agent", dummy_handler)

            agent_list = get_agent_list()
            assert len(agent_list) == 1
            assert agent_list[0]["name"] == "test_agent"
            assert agent_list[0]["description"] == "A test agent"

            handler = get_agent_handler("test_agent")
            assert handler is not None
            assert handler is dummy_handler
        finally:
            AGENT_REGISTRY.clear()
            AGENT_REGISTRY.update(original)

    def test_get_agent_handler_unknown_returns_none(self):
        """get_agent_handler returns None for unknown agent name."""
        from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_handler

        result = get_agent_handler("nonexistent_agent")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_allocate.py::TestAgentRegistry -xvs`
Expected: FAIL — `ModuleNotFoundError: No module named 'hatsume.plugins.hatsume_plugin.graph.agents'`

- [ ] **Step 3: Create `graph/agents.py`**

```python
"""Built-in agent registry for agent_allocate tool."""

from __future__ import annotations

from typing import Any, Callable, Coroutine

# Handler: async (task: str, user_id: int) -> str
AgentHandler = Callable[[str, int], Coroutine[Any, Any, str]]

AGENT_REGISTRY: dict[str, dict] = {}


def register_agent(name: str, description: str, handler: AgentHandler) -> None:
    """Register a built-in agent."""
    AGENT_REGISTRY[name] = {"description": description, "handler": handler}


def get_agent_list() -> list[dict[str, str]]:
    """Return list of registered agents with name and description."""
    return [
        {"name": name, "description": info["description"]}
        for name, info in AGENT_REGISTRY.items()
    ]


def get_agent_handler(name: str) -> AgentHandler | None:
    """Return the handler for a registered agent, or None if not found."""
    info = AGENT_REGISTRY.get(name)
    return info["handler"] if info else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_register.py::TestAgentRegistry -xvs`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add graph/agents.py tests/test_agent_allocate.py
git commit -m "feat: add agent registry infrastructure

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Register built-in agent handlers

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/agents.py`

**Interfaces:**
- Consumes: `register_agent`, `AgentHandler` (from Task 1)
- Produces: `_run_web_browser_agent(task: str, user_id: int) -> str`, `_run_video_agent(task: str, user_id: int) -> str`

- [ ] **Step 1: Write the test**

Append to `tests/test_agent_allocate.py`:

```python
class TestBuiltinAgents:
    """Tests for built-in agent registration."""

    def test_builtin_agents_are_registered(self):
        """web_browser and generate_video are in the registry."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            get_agent_list,
            get_agent_handler,
        )

        agent_list = get_agent_list()
        names = [a["name"] for a in agent_list]

        assert "web_browser" in names
        assert "generate_video" in names

        web_handler = get_agent_handler("web_browser")
        assert web_handler is not None
        assert callable(web_handler)

        video_handler = get_agent_handler("generate_video")
        assert video_handler is not None
        assert callable(video_handler)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_allocate.py::TestBuiltinAgents -xvs`
Expected: FAIL — `AssertionError: assert 'web_browser' in []`

- [ ] **Step 3: Add handler implementations and register them at module bottom**

Append to `graph/agents.py`:

```python
# ---------------------------------------------------------------------------
# Built-in agent handler implementations
# ---------------------------------------------------------------------------

async def _run_web_browser_agent(task: str, user_id: int) -> str:
    """Execute web browser agent task using shell_executor + WEB_BROWSER_AGENT_PROMPT.

    Returns the final report text (after advance-model rephrasing).
    """
    from langchain.agents import create_agent
    from langchain.messages import HumanMessage, SystemMessage

    from ..models import get_code_model, get_advance_model
    from ..prompts import WEB_BROWSER_AGENT_PROMPT, build_web_result_rephrase_prompt, role_sys_prompt
    from ..tools import shell_executor

    browser_agent = create_agent(
        get_code_model(),
        [shell_executor],
        system_prompt=WEB_BROWSER_AGENT_PROMPT,
    )

    report = ""
    try:
        response = await browser_agent.ainvoke(
            {"messages": [HumanMessage(task)]},
            {"recursion_limit": 50},
        )
        report = str(response["messages"][-1].content)
    except Exception:
        import traceback
        print("❌ _run_web_browser_agent failed")
        traceback.print_exc()
        return "网络检索任务执行失败。"

    if report.strip() == "":
        return "报告生成失败，网络搜查任务没有返回有效结果。"

    chat_model = get_advance_model(True)
    response = await chat_model.ainvoke(
        [
            SystemMessage(role_sys_prompt),
            HumanMessage(build_web_result_rephrase_prompt(task)),
            HumanMessage(report),
        ]
    )
    return str(response.content)


async def _run_video_agent(task: str, user_id: int) -> str:
    """Execute video generation task.

    Returns a status message string (success with url or failure).
    """
    from ..models import generate_video_for, choose_video_model

    model = choose_video_model()

    url = None
    try:
        url = await generate_video_for(task, image_url=None, model=model)
    except Exception:
        import traceback
        print("❌ _run_video_agent failed")
        traceback.print_exc()

    if url is None:
        return f"视频生成失败（模型 Seedance {model} Pro）。"
    else:
        return f"视频已生成成功（模型 Seedance {model} Pro）。"


# Register built-in agents (module-level, before any imports from this module)
register_agent(
    name="web_browser",
    description="网络浏览器 Agent，访问指定网站或 API 并返回检索结果报告",
    handler=_run_web_browser_agent,
)
register_agent(
    name="generate_video",
    description="AI 视频生成 Agent，根据文字描述生成短视频",
    handler=_run_video_agent,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_allocate.py::TestBuiltinAgents -xvs`
Expected: PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `python -m pytest tests/ -xvs`
Expected: all existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add graph/agents.py tests/test_agent_allocate.py
git commit -m "feat: add built-in agent handlers for web_browser and generate_video

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add `agent_allocate` tool to `graph/tools.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

**Interfaces:**
- Consumes: `get_agent_handler`, `get_agent_list` from `.agents` (Task 2)
- Produces:
  - `_AGENT_LIST_STR: str` — formatted agent list for tool description
  - `agent_allocate(notified_user_id: int, agent_name: str, task: str) -> str`
  - `_agent_notification_callback: Callable | None` — set via `configure_agent_notification_callback`
  - `configure_agent_notification_callback(cb: Callable) -> None`

- [ ] **Step 1: Write the test**

Append to `tests/test_agent_allocate.py`:

```python
class TestAgentAllocateTool:
    """Tests for the agent_allocate tool function."""

    @pytest.mark.asyncio
    async def test_agent_allocate_unknown_agent_returns_error(self):
        """agent_allocate returns error for unknown agent name."""
        from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate

        result = await agent_allocate.ainvoke({
            "notified_user_id": 123456,
            "agent_name": "nonexistent",
            "task": "do something",
        })
        assert "错误" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_agent_allocate_known_agent_returns_confirmation(self):
        """agent_allocate returns confirmation for known agent name."""
        from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate

        result = await agent_allocate.ainvoke({
            "notified_user_id": 123456,
            "agent_name": "web_browser",
            "task": "test task",
        })
        assert "web_browser" in result
        assert "已开始执行" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_allocate.py::TestAgentAllocateTool -xvs`
Expected: FAIL — `ImportError: cannot import name 'agent_allocate'`

- [ ] **Step 3: Add imports and `_AGENT_LIST_STR` near top of `graph/tools.py`**

After line 26 (`from ..memory.retrieval import query_mems`), add:

```python
from .agents import get_agent_list, get_agent_handler
```

After line 86 (`_current_group_id: int | None = None`), add:

```python
# Agent notification callback (set by chat.py)
_agent_notification_callback: Callable[[int, str], None] | None = None

_AGENT_LIST_STR: str = ""  # populated below after get_agent_list is imported
```

- [ ] **Step 4: Add `configure_agent_notification_callback` after `set_current_group_id`**

After line 93 (`_current_group_id = group_id`), add:

```python
def configure_agent_notification_callback(cb: Callable[[int, str], None]) -> None:
    """Register callback for starting conversation when agent finishes outside active chat."""
    global _agent_notification_callback
    _agent_notification_callback = cb
```

- [ ] **Step 5: Add `agent_allocate` tool at end of file + populate `_AGENT_LIST_STR`**

After the last `membersearch` tool (line 899), add:

```python
# ---------------------------------------------------------------------------
# Agent allocate tool
# ---------------------------------------------------------------------------
# Build agent list string at module level (agents.py registered on import)
_AGENT_LIST_STR = "\n".join(
    f"- **{a['name']}**: {a['description']}" for a in get_agent_list()
)

@tool(description=f"""分配任务给内置 Agent 后台执行。Agent 完成后会自动 @ 通知用户。

## 参数：
- agent_name: 内置 Agent 名称
- notified_user_id: 需要通知的用户 QQ ID
- task: 要执行的任务描述

## 可用 Agent：
{_AGENT_LIST_STR}""")
async def agent_allocate(notified_user_id: int, agent_name: str, task: str) -> str:
    handler = get_agent_handler(agent_name)
    if handler is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"错误：未知 Agent '{agent_name}'。可用 Agent: {available}"

    print(f"🧩 [agent_allocate] Dispatching {agent_name} for user {notified_user_id}")

    async def _run_and_notify() -> None:
        try:
            result = await handler(task, notified_user_id)
        except Exception:
            print(f"❌ Agent {agent_name} failed")
            traceback.print_exc()
            result = f"Agent '{agent_name}' 执行失败。"

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

    asyncio.create_task(_run_and_notify())
    return f"✅ Agent '{agent_name}' 已开始执行，完成后将自动通知用户。"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_allocate.py::TestAgentAllocateTool -xvs`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add graph/tools.py tests/test_agent_allocate.py
git commit -m "feat: add agent_allocate tool with dynamic agent list description

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add `inject_agent_notification` + NOTIFY_MARK detection in `ai_node`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Consumes: `_state` (ConversationState bound via `bind_state`), `conversation_state.ai_answer_with_at`
- Produces:
  - `NOTIFY_MARK: str = "__agent_notify__"`
  - `inject_agent_notification(user_id, agent_name, result, start_conversation_cb) -> None`

- [ ] **Step 1: Write the test**

Append to `tests/test_agent_allocate.py`:

```python
class TestNotifyMarkDetection:
    """Tests for NOTIFY_MARK detection logic."""

    def test_extract_notified_uid_from_str_content(self):
        """Extract notified_uid from string content starting with NOTIFY_MARK."""
        from hatsume.plugins.hatsume_plugin.graph.nodes.ai import NOTIFY_MARK

        content = f"{NOTIFY_MARK}:123456:web_browser\nresult text here"

        assert content.startswith(NOTIFY_MARK)
        _, uid_str, _ = content.split(":", 2)
        assert int(uid_str) == 123456

    def test_extract_notified_uid_from_list_content(self):
        """Extract notified_uid from list content, last mark wins."""
        from hatsume.plugins.hatsume_plugin.graph.nodes.ai import NOTIFY_MARK

        content_list = [
            {"type": "text", "text": "some prefix text"},
            {"type": "text", "text": f"{NOTIFY_MARK}:111111:video\nfirst result"},
            {"type": "text", "text": "middle text"},
            {"type": "text", "text": f"{NOTIFY_MARK}:222222:web\nsecond result"},
        ]

        notified_uid = None
        for part in reversed(content_list):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(NOTIFY_MARK):
                _, uid_str, _ = text.split(":", 2)
                notified_uid = int(uid_str)
                break

        assert notified_uid == 222222  # last one wins

    def test_notify_mark_not_present_uid_is_none(self):
        """notified_uid stays None when no NOTIFY_MARK in content."""
        from hatsume.plugins.hatsume_plugin.graph.nodes.ai import NOTIFY_MARK

        content_list = [
            {"type": "text", "text": "normal message 1"},
            {"type": "text", "text": "normal message 2"},
        ]

        notified_uid = None
        for part in reversed(content_list):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(NOTIFY_MARK):
                _, uid_str, _ = text.split(":", 2)
                notified_uid = int(uid_str)
                break

        assert notified_uid is None


class TestInjectAgentNotification:
    """Tests for inject_agent_notification function."""

    def test_inject_agent_notification_message_format(self):
        """inject_agent_notification produces correctly formatted message."""
        from hatsume.plugins.hatsume_plugin.graph.nodes.ai import (
            NOTIFY_MARK,
            inject_agent_notification,
        )

        # We only test the message format, not the state mutation
        user_id = 123456
        agent_name = "web_browser"
        result = "search result text"

        expected_prefix = f"(SYSTEM) Agent '{agent_name}' 已执行完毕"
        expected_mark = f"{NOTIFY_MARK}:{user_id}:{agent_name}"

        # Build the message the same way inject_agent_notification does
        notify_msg = (
            f"(SYSTEM) Agent '{agent_name}' 已执行完毕，"
            f"以下是该 Agent 返回的结果，请以你的口吻告知用户结果：\n"
            f"{NOTIFY_MARK}:{user_id}:{agent_name}\n"
            f"{result}"
        )

        assert expected_prefix in notify_msg
        assert expected_mark in notify_msg
        assert result in notify_msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_allocate.py::TestNotifyMarkDetection -xvs`
Expected: FAIL — `AttributeError: module '...ai' has no attribute 'NOTIFY_MARK'`

- [ ] **Step 3: Add `NOTIFY_MARK` constant and `inject_agent_notification` to `graph/nodes/ai.py`**

After line 33 (`membersearch` import), the NOTIFY_MARK should already be importable. Add after line 44 (`_memory_record_source_map`):

```python
NOTIFY_MARK = "__agent_notify__"


def inject_agent_notification(
    user_id: int,
    agent_name: str,
    result: str,
    start_conversation_cb: Any = None,
) -> None:
    """Inject agent result into the conversation flow with a special mark prefix.

    If currently chatting (_state.is_chatting), appends to human_queue and
    adds the notified user to chat_peers.
    Otherwise, calls start_conversation_cb to launch a new graph conversation.
    """
    notify_msg = (
        f"(SYSTEM) Agent '{agent_name}' 已执行完毕，"
        f"以下是该 Agent 返回的结果，请以你的口吻告知用户结果：\n"
        f"{NOTIFY_MARK}:{user_id}:{agent_name}\n"
        f"{result}"
    )

    if _state and _state.is_chatting:
        _state.human_queue.append({"type": "text", "text": notify_msg})
        _state.chat_peers.add(str(user_id))
        print(f"🧩 [inject_agent_notification] Injected {agent_name} result into human_queue")
    else:
        if start_conversation_cb is not None:
            print(f"🧩 [inject_agent_notification] Starting new conversation for {agent_name} result")
            start_conversation_cb(user_id, notify_msg)
        else:
            print("❌ inject_agent_notification: no active chat and no callback")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_allocate.py::TestNotifyMarkDetection -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add graph/nodes/ai.py tests/test_agent_allocate.py
git commit -m "feat: add NOTIFY_MARK constant and inject_agent_notification function

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Wire NOTIFY_MARK detection + @-send in `ai_node`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:111-224`

**Interfaces:**
- Consumes: `NOTIFY_MARK` (Task 4), `_state.ai_answer_with_at`, `_state.ai_answer`
- Produces: modified `ai_node` that detects NOTIFY_MARK and routes to `ai_answer_with_at`

- [ ] **Step 1: Modify `ai_node` — detect NOTIFY_MARK before invoking LLM**

In `ai_node()`, after line 143 (`t_mem_end = time.time()`), add NOTIFY_MARK detection:

```python
    # ── Detect agent notification mark in the last message ──
    last_content = state["messages"][-1].content
    notified_uid: int | None = None

    if isinstance(last_content, list):
        for part in reversed(last_content):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(NOTIFY_MARK):
                _, uid_str, _ = text.split(":", 2)
                notified_uid = int(uid_str)
                break
    elif isinstance(last_content, str) and last_content.startswith(NOTIFY_MARK):
        _, uid_str, _ = last_content.split(":", 2)
        notified_uid = int(uid_str)
```

- [ ] **Step 2: Modify `ai_node` — use `ai_answer_with_at` when NOTIFY_MARK detected**

Replace lines 204-208 (`ai_msg = ... if _ai_answer: await _ai_answer(ai_msg)`) with:

```python
    ai_msg = MessageSegment.text(ai_text)
    if notified_uid is not None:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, notified_uid)
            print(f"🧩 [ai_node] Sent agent result via ai_answer_with_at to user {notified_uid}")
    else:
        _ai_answer = _get_ai_answer()
        if _ai_answer:
            await _ai_answer(ai_msg)
```

- [ ] **Step 3: Run existing tests to check no regressions**

Run: `python -m pytest tests/ -xvs`
Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add graph/nodes/ai.py
git commit -m "feat: detect NOTIFY_MARK in ai_node and route to ai_answer_with_at

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Register tool in `ai_node` + Export from nodes `__init__.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:26-32` (imports)
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:164-170` (create_agent tools list)
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py`

- [ ] **Step 1: Add `agent_allocate` to imports in `ai_node`**

Replace lines 26-32 (the `from ..tools import` block):

```python
from ..tools import (
    search_web, web_browser, shell_executor, find_memory, query_memory,
    capture_html_shot, generate_image, generate_video,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate,
)
```

- [ ] **Step 2: Add `agent_allocate` to `create_agent` tools list**

Replace lines 164-170 (the `create_agent` call):

```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory, capture_html_shot,
         generate_image, generate_video, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 3: Export `NOTIFY_MARK` and `inject_agent_notification` from `__init__.py`**

In `graph/nodes/__init__.py`, replace the `from .ai import` block (lines 3-17) with:

```python
from .ai import (
    ai_node,
    get_role_sys_prompt,
    append_auxiliary_message,
    append_memory_record_sources,
    reset_memory_record_context,
    bind_state,
    set_current_query_user_id,
    get_retrieved_keys,
    auxiliary_messages_queue,
    auxiliary_source_queue,
    _retrieved_mem_keys,
    _memory_record_transcript,
    _memory_record_source_map,
    NOTIFY_MARK,
    inject_agent_notification,
)
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -xvs`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add graph/nodes/ai.py graph/nodes/__init__.py
git commit -m "feat: register agent_allocate tool in ai_node and export from nodes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Wire `_agent_notification_callback` in `handlers/chat.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py`

**Interfaces:**
- Consumes: `conv_state`, `handle_ai_message`, `start_new_conversation`, `configure_agent_notification_callback`
- Produces: `_start_conv_for_agent(user_id: int, notify_msg: str)` — registered as callback

- [ ] **Step 1: Add module-level matcher storage and callback registration**

After line 34 (`_wire_conv_state(conv_state)`), add:

```python
# Store last known matcher for agent notification conversations
_last_user_chat_matcher: Any = None


def _start_conv_for_agent(user_id: int, notify_msg: str) -> None:
    """Start a new conversation to handle agent notification when not currently chatting."""
    global _last_user_chat_matcher, conv_state

    if _last_user_chat_matcher is None:
        print("❌ _start_conv_for_agent: no matcher available")
        return

    from ..graph.tools import configure_tool_callbacks as configure_tools

    ai_cb = lambda msg, at_id=None: handle_ai_message(
        msg, at_id=at_id, matcher=_last_user_chat_matcher
    )
    conv_state.ai_answer = ai_cb
    conv_state.ai_answer_with_at = ai_cb

    asyncio.create_task(
        start_new_conversation(
            conv_state, ai_cb, configure_tools,
            user_id=user_id,
            messages=[{"type": "text", "text": notify_msg}],
        )
    )


# Register the callback with tools.py (must happen after imports resolve)
from ..graph.tools import configure_agent_notification_callback
configure_agent_notification_callback(_start_conv_for_agent)
```

- [ ] **Step 2: Update `_last_user_chat_matcher` in `user_chat_handle`**

In `user_chat_handle()`, after line 141 (`conv_state.ai_answer_with_at = ai_cb` in the `send()` closure, also store the matcher):

```python
    global _last_user_chat_matcher
    _last_user_chat_matcher = user_chat_matcher
```

And in `_auto_respond()`, after `conv_state.ai_answer_with_at = ai_cb`, also:

```python
    global _last_user_chat_matcher
    _last_user_chat_matcher = user_chat_matcher
```

Wait — `_auto_respond` has `user_chat_matcher` from the outer scope closure. Let me check the exact code...

Actually, the `_auto_respond` is defined inside `user_chat_handle` so it has access to `user_chat_matcher` via closure. But we still need `global _last_user_chat_matcher` in both places.

Actually, since both are in the same function scope, one `global` declaration at the top of `user_chat_handle` is enough:

In `user_chat_handle()`, add after `print("call user_chat")` (line 138):

```python
    global _last_user_chat_matcher
    _last_user_chat_matcher = user_chat_matcher
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -xvs`
Expected: all tests PASS

- [ ] **Step 4: Run ruff lint**

Run: `python -m ruff check hatsume/plugins/hatsume-plugin/`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add handlers/chat.py
git commit -m "feat: wire agent notification callback in chat.py

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Integration verification

**Files:**
- Verify: all changed files

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -xvs`
Expected: all tests PASS (no regressions)

- [ ] **Step 2: Run ruff lint on all changed files**

Run: `python -m ruff check hatsume/plugins/hatsume-plugin/graph/agents.py hatsume/plugins/hatsume-plugin/graph/tools.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py hatsume/plugins/hatsume-plugin/handlers/chat.py`
Expected: no errors

- [ ] **Step 3: Verify imports resolve correctly**

Run: `python -c "from hatsume.plugins.hatsume_plugin.graph.agents import AGENT_REGISTRY, get_agent_list, get_agent_handler; print('agents.py OK'); print(get_agent_list())"`
Expected: prints agent list

Run: `python -c "from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate; print('agent_allocate tool OK'); print(agent_allocate.description)"`
Expected: prints tool description with agent list

Run: `python -c "from hatsume.plugins.hatsume_plugin.graph.nodes.ai import NOTIFY_MARK, inject_agent_notification; print('NOTIFY_MARK:', NOTIFY_MARK); print('ai_node exports OK')"`
Expected: prints NOTIFY_MARK value
