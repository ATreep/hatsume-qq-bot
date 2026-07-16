# Timer Graph Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the standalone `_run_timer_agent` in `timer/executor.py` with a graph injection pattern that mirrors `agent_allocate` → `inject_agent_notification`.

**Architecture:** Add `TIMER_MARK = "__timer__"` detection alongside the existing `NOTIFY_MARK = "__agent_notify__"` pattern. When a timer fires, build a `__timer__:{user_id}` marked message and inject it into the conversation graph (append to `human_queue` if chatting, start new conversation if not). The existing LangGraph handles everything — human_node picks it up, detect_node routes it to continue, ai_node @-mentions the timer creator.

**Tech Stack:** Python 3.12+, LangGraph MessagesState, langchain.messages, asyncio, APScheduler, pytest

## Global Constraints

- Python 3.12+ with `from __future__ import annotations`
- ruff lint compliance (config in `pyproject.toml`)
- snake_case functions, PascalCase classes, UPPER_CASE constants
- Use `# ----` separator comments matching existing file style
- Each task ends with a commit
- TDD: write failing test → verify fail → implement → verify pass → commit

---

## File Structure

```
timer/executor.py          — Replace _run_timer_agent with _inject_timer_to_graph; remove tool isolation
graph/nodes/ai.py           — Add TIMER_MARK, detect_timer_notification, inject_timer; wire into ai_node
graph/nodes/detect.py       — Add timer check alongside agent notification check
graph/nodes/__init__.py     — Export new timer functions
handlers/chat.py            — Add _start_conv_for_timer callback; register with executor
```

---

### Task 1: Add TIMER_MARK, detect_timer_notification, inject_timer to ai.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Produces: `TIMER_MARK = "__timer__"`, `detect_timer_notification(state) -> int | None`, `inject_timer(user_id, timer_prompt, context, start_conversation_cb) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_timer_injection.py`:

```python
"""Tests for timer graph injection: TIMER_MARK detection and injection."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODES_PKG_DIR = ROOT / "hatsume/plugins/hatsume-plugin/graph/nodes"


class MockMessage:
    """Lightweight stand-in for LangChain message objects."""
    def __init__(self, content="", msg_type="human", msg_id=None):
        self.content = content
        self.type = msg_type
        self.id = msg_id or f"msg-{id(self)}"


class MockState:
    """Minimal state object matching ai.py's _state interface."""
    def __init__(self):
        self.is_chatting = False
        self.human_queue: list[dict] = []
        self.chat_peers: set[str] = set()


def _load_ai_module():
    """Load graph/nodes/ai.py with all external dependencies stubbed."""
    pkg_prefixes = [
        "hatsume", "hatsume.plugins", "hatsume.plugins.hatsume_plugin",
        "hatsume.plugins.hatsume-plugin",
    ]
    for name in list(sys.modules):
        if any(name.startswith(p) for p in pkg_prefixes) or name in (
            "nonebot", "nonebot_plugin_localstore",
            "nonebot.adapters", "nonebot.adapters.onebot",
            "nonebot.adapters.onebot.v11",
            "langchain", "langchain.messages", "langchain.agents",
            "langchain_core", "langchain_core.messages",
            "langchain_community", "langchain_community.tools",
            "langgraph", "langgraph.graph", "openai",
        ):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for stub_name, stub_path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
        ("hatsume.plugins.hatsume-plugin.graph", base / "graph"),
        ("hatsume.plugins.hatsume-plugin.memory", base / "memory"),
        ("hatsume.plugins.hatsume-plugin.timer", base / "timer"),
        ("hatsume.plugins.hatsume-plugin.skills", base / "skills"),
    ]:
        mod = types.ModuleType(stub_name)
        mod.__path__ = [str(stub_path)]
        sys.modules[stub_name] = mod

    # Stub langchain
    langchain_mod = types.ModuleType("langchain")
    langchain_mod.__path__ = []
    sys.modules["langchain"] = langchain_mod

    class _AIMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "ai"

    class _HumanMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "human"

    class _SystemMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "system"

    lc_msgs = types.ModuleType("langchain.messages")
    lc_msgs.AIMessage = _AIMessage
    lc_msgs.HumanMessage = _HumanMessage
    lc_msgs.SystemMessage = _SystemMessage
    sys.modules["langchain.messages"] = lc_msgs

    lc_agents = types.ModuleType("langchain.agents")
    lc_agents.create_agent = lambda *a, **kw: None
    sys.modules["langchain.agents"] = lc_agents

    sys.modules["langchain_core"] = types.ModuleType("langchain_core")
    sys.modules["langchain_core.messages"] = types.ModuleType("langchain_core.messages")
    sys.modules["langgraph"] = types.ModuleType("langgraph")
    sys.modules["langgraph.graph"] = types.ModuleType("langgraph.graph")

    # Stub nonebot
    sys.modules["nonebot"] = types.ModuleType("nonebot")
    adapters = types.ModuleType("nonebot.adapters")
    sys.modules["nonebot.adapters"] = adapters
    onebot = types.ModuleType("nonebot.adapters.onebot")
    sys.modules["nonebot.adapters.onebot"] = onebot
    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.MessageSegment = types.SimpleNamespace(text=lambda s: s)
    sys.modules["nonebot.adapters.onebot.v11"] = v11

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = lambda name: types.SimpleNamespace(
        iterdir=lambda: [], absolute=lambda: Path("/tmp"),
    )
    sys.modules["nonebot_plugin_localstore"] = localstore

    # Stub sibling modules
    stub_defs = {
        "hatsume.plugins.hatsume-plugin.models": {
            "get_advance_model": lambda thinking=True: None,
            "get_lite_model": lambda thinking=True: None,
            "get_mini_model": lambda thinking=True: None,
        },
        "hatsume.plugins.hatsume-plugin.prompts": {
            "role_sys_prompt": "test role prompt",
            "build_face_emotion_classifier_prompt": lambda e: "",
            "build_memory_context_prompt": lambda m: "",
            "build_skill_prompt": lambda s: "",
            "AUXILIARY_COMPACTION_PROMPT": "",
        },
        "hatsume.plugins.hatsume-plugin.skills": {
            "get_skill_manager": lambda: types.SimpleNamespace(list_skills=lambda: []),
        },
        "hatsume.plugins.hatsume-plugin.graph": {},
        "hatsume.plugins.hatsume-plugin.graph.tools": {
            "search_web": None, "shell_executor": None, "find_memory": None,
            "query_memory": lambda *a, **kw: "", "capture_html_shot": None,
            "generate_image": None, "reset_capture_flag": lambda: None,
            "get_avatar": None, "create_timer": None, "list_timers": None,
            "delete_timer": None, "skill_loader": None, "skill_remove": None,
            "skill_download": None, "skill_create": None, "membersearch": None,
            "agent_allocate": None, "_capture_html_shot_used": False,
            "_generate_image_used": False, "_last_capture_html_demand": "",
        },
    }
    for name, attrs in stub_defs.items():
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod

    import importlib.util
    full_name = "hatsume.plugins.hatsume-plugin.graph.nodes.ai"
    spec = importlib.util.spec_from_file_location(full_name, NODES_PKG_DIR / "ai.py")
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDetectTimerNotification:
    """T001: detect_timer_notification extracts user_id from __timer__ mark."""

    def test_detects_string_content(self):
        """Returns user_id when last message content is a string with __timer__ mark."""
        ai_mod = _load_ai_module()
        messages = [
            MockMessage(content="hello"),
            MockMessage(content="__timer__:12345"),
        ]
        result = ai_mod.detect_timer_notification(messages)
        assert result == 12345

    def test_detects_list_content(self):
        """Returns user_id when content is a list with __timer__ text part."""
        ai_mod = _load_ai_module()
        messages = [
            MockMessage(content=[
                {"type": "text", "text": "__timer__:67890\n定时任务内容..."},
            ]),
        ]
        result = ai_mod.detect_timer_notification(messages)
        assert result == 67890

    def test_returns_none_for_regular_message(self):
        """Returns None for regular messages without __timer__ mark."""
        ai_mod = _load_ai_module()
        messages = [MockMessage(content="hello world")]
        result = ai_mod.detect_timer_notification(messages)
        assert result is None

    def test_returns_none_for_agent_notify(self):
        """Returns None for __agent_notify__ messages (different mark)."""
        ai_mod = _load_ai_module()
        messages = [
            MockMessage(content="__agent_notify__:123:coding_agent\nresult"),
        ]
        result = ai_mod.detect_timer_notification(messages)
        assert result is None


class TestInjectTimer:
    """T001: inject_timer builds correct message and injects into state."""

    def test_injects_into_human_queue_when_chatting(self):
        """Appends to human_queue and adds peer when _state.is_chatting."""
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        ai_mod._state = mock_state

        ai_mod.inject_timer(
            user_id=123,
            timer_prompt="提醒开会",
            context="System: test\nContext: ...",
        )

        assert len(mock_state.human_queue) == 1
        msg = mock_state.human_queue[0]
        assert msg["type"] == "text"
        assert "__timer__:123" in msg["text"]
        assert "提醒开会" in msg["text"]
        assert "123" in mock_state.chat_peers

    def test_calls_start_conversation_cb_when_not_chatting(self):
        """Calls start_conversation_cb when not chatting."""
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = False
        ai_mod._state = mock_state

        cb_called = {"called": False, "user_id": 0, "msg": ""}

        def cb(uid, msg):
            cb_called["called"] = True
            cb_called["user_id"] = uid
            cb_called["msg"] = msg

        ai_mod.inject_timer(
            user_id=456,
            timer_prompt="喝水提醒",
            context="",
            start_conversation_cb=cb,
        )

        assert cb_called["called"]
        assert cb_called["user_id"] == 456
        assert "__timer__:456" in cb_called["msg"]
        assert "喝水提醒" in cb_called["msg"]

    def test_no_callback_when_not_chatting_no_cb(self):
        """Does not crash when not chatting and no callback provided."""
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = False
        ai_mod._state = mock_state

        # Should not raise
        ai_mod.inject_timer(user_id=789, timer_prompt="test", context="")


class TestTimerInjectionRoundTrip:
    """T005: _inject_timer_to_graph integration with inject_timer."""

    def test_inject_timer_to_graph_builds_correct_context(self):
        """Full message format includes timer mark, context, and task prompt."""
        ai_mod = _load_ai_module()
        mock_state = MockState()
        mock_state.is_chatting = True
        ai_mod._state = mock_state

        ai_mod.inject_timer(
            user_id=111,
            timer_prompt="定时提醒：喝水",
            context=(
                "系统上下文：test sys prompt\n\n"
                "最近的群聊消息：\n"
                "[Alice]: 你好\n"
                "[Bob]: 今天天气不错"
            ),
            start_conversation_cb=None,
        )

        msg = mock_state.human_queue[0]
        assert "__timer__:111" in msg["text"]
        assert "定时提醒：喝水" in msg["text"]
        assert "[Alice]: 你好" in msg["text"]
        assert "[Bob]: 今天天气不错" in msg["text"]
        assert "111" in mock_state.chat_peers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timer_injection.py -v`
Expected: FAIL — `detect_timer_notification` and `inject_timer` not yet defined

- [ ] **Step 3: Implement TIMER_MARK, detect_timer_notification, inject_timer**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, add after line 47 (`NOTIFY_MARK = "__agent_notify__"`):

```python
TIMER_MARK = "__timer__"
```

Add after `detect_agent_notification` (after line 74):

```python
def detect_timer_notification(state: MessagesState) -> int | None:
    """Scan state["messages"][-1].content for TIMER_MARK.

    Returns the notified user_id (int) if the last message contains
    a __timer__ mark, or None otherwise.
    """
    last_content = state["messages"][-1].content

    if isinstance(last_content, list):
        for part in reversed(last_content):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(TIMER_MARK):
                _, uid_str = text.split(":", 1)
                print(f"⏰ [detect_timer_notification] Detected timer notification for user {uid_str}")
                return int(uid_str)
    elif isinstance(last_content, str) and last_content.startswith(TIMER_MARK):
        _, uid_str = last_content.split(":", 1)
        print(f"⏰ [detect_timer_notification] Detected timer notification for user {uid_str}")
        return int(uid_str)

    return None
```

Add after `inject_agent_notification` (after line 110):

```python
def inject_timer(
    user_id: int,
    timer_prompt: str,
    context: str,
    start_conversation_cb: Any = None,
) -> None:
    """Inject a timer prompt into the conversation flow with a __timer__ mark.

    Builds a timer notification message and injects it into the graph:
    - If currently chatting (_state.is_chatting), appends to human_queue
      and adds the notified user to chat_peers.
    - Otherwise, calls start_conversation_cb to launch a new graph conversation.
    """
    timer_msg = (
        f"{TIMER_MARK}:{user_id}\n"
        f"(SYSTEM) 定时任务已触发。以下是定时任务的上下文和内容，"
        f"请以你的口吻告知用户：\n\n"
        f"{context}\n\n"
        f"定时任务内容：{timer_prompt}"
    )

    print(f"⏰ [inject_timer] Timer message for user {user_id}: {timer_prompt[:80]}...")

    if _state and _state.is_chatting:
        _state.human_queue.append({"type": "text", "text": timer_msg})
        _state.chat_peers.add(str(user_id))
        print(f"⏰ [inject_timer] Injected timer into human_queue for user {user_id}")
    else:
        if start_conversation_cb is not None:
            print(f"⏰ [inject_timer] Starting new conversation for timer (user {user_id})")
            start_conversation_cb(user_id, timer_msg)
        else:
            print("❌ inject_timer: no active chat and no callback")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timer_injection.py -v`
Expected: ALL TESTS PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_timer_injection.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: add TIMER_MARK, detect_timer_notification, inject_timer to ai.py

Mirrors existing agent notification pattern for timer trigger messages.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Wire timer detection into detect.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py`

**Interfaces:**
- Consumes: `detect_timer_notification` from `graph.nodes.ai` (Task 1)
- Produces: Updated `chat_end_detect_node` that prevents conversation end on timer messages

- [ ] **Step 1: Update the import**

In `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py`, change line 15:

```python
from .ai import detect_agent_notification
```

to:

```python
from .ai import detect_agent_notification, detect_timer_notification
```

- [ ] **Step 2: Add timer check in chat_end_detect_node**

In `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py`, after line 22-23:

```python
    # Agent notification: always route to chat_llm, never end conversation
    if detect_agent_notification(state) is not None:
        return {"messages": []}
```

Add:

```python
    # Timer notification: always route to chat_llm, never end conversation
    if detect_timer_notification(state) is not None:
        return {"messages": []}
```

- [ ] **Step 3: Run existing tests to verify no regression**

Run: `python -m pytest tests/test_graph_nodes.py -v`
Expected: ALL TESTS PASS

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/detect.py
git commit -m "feat: prevent conversation end on timer notification messages

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add _start_conv_for_timer callback to chat.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py`

**Interfaces:**
- Consumes: `_last_user_chat_matcher`, `conv_state`, `handle_ai_message`, `start_new_conversation` (existing)
- Produces: `_start_conv_for_timer(user_id, notify_msg) -> None`

- [ ] **Step 1: Add _start_conv_for_timer function**

In `hatsume/plugins/hatsume-plugin/handlers/chat.py`, add after line 67 (after `_start_conv_for_agent` function closing):

```python
def _start_conv_for_timer(user_id: int, notify_msg: str) -> None:
    """Start a new conversation to handle timer trigger when not currently chatting.

    Mirrors _start_conv_for_agent exactly — same pattern. The only difference
    is the caller (timer executor vs agent_allocate tool).
    """
    global _last_user_chat_matcher, conv_state

    if _last_user_chat_matcher is None:
        print("❌ _start_conv_for_timer: no matcher available")
        return

    from ..graph.tools import configure_tool_callbacks as configure_tools

    ai_cb = lambda msg, at_id=None: handle_ai_message(
        msg, at_id=at_id, matcher=_last_user_chat_matcher
    )
    conv_state.ai_answer = ai_cb
    conv_state.ai_answer_with_at = ai_cb

    conv_state.activate_chat(str(user_id))

    asyncio.create_task(
        start_new_conversation(
            conv_state, ai_cb, configure_tools,
            user_id=user_id,
            messages=[{"type": "text", "text": notify_msg}],
        )
    )
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `python -m pytest tests/test_conversation.py -v`
Expected: ALL TESTS PASS

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/handlers/chat.py
git commit -m "feat: add _start_conv_for_timer callback for timer conversations

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Update ai_node to @mention timer creator

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Consumes: `detect_timer_notification` from same file (Task 1)
- Produces: `ai_node` sends responses with @mention for timer messages

- [ ] **Step 1: Add timer detection variable in ai_node**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, change line 212-213:

```python
    # ── Detect agent/timer notification mark in the last message ──
    notified_uid = detect_agent_notification(state)
    timer_uid = detect_timer_notification(state)
```

(replaces the single line `notified_uid = detect_agent_notification(state)`)

- [ ] **Step 2: Add timer @mention in ai_node response**

At lines 269-277, change from:

```python
    ai_msg = MessageSegment.text(ai_text)
    if notified_uid is not None:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, notified_uid)
            print(f"... Sent agent result via ai_answer_with_at to user {notified_uid}")
    else:
        _ai_answer = _get_ai_answer()
        if _ai_answer:
            await _ai_answer(ai_msg)
```

to:

```python
    ai_msg = MessageSegment.text(ai_text)
    if notified_uid is not None:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, notified_uid)
            print(f"🧩 [ai_node] Sent agent result via ai_answer_with_at to user {notified_uid}")
    elif timer_uid is not None:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, timer_uid)
            print(f"⏰ [ai_node] Sent timer result via ai_answer_with_at to user {timer_uid}")
    else:
        _ai_answer = _get_ai_answer()
        if _ai_answer:
            await _ai_answer(ai_msg)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_timer_injection.py -v`
Expected: ALL TESTS PASS

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: ai_node @mentions timer creator on timer responses

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Replace _run_timer_agent with _inject_timer_to_graph in executor.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py`

**Interfaces:**
- Consumes: `inject_timer` from `graph.nodes.ai` (Task 1), `_timer_start_conv_cb` set by `chat.py` (Task 6)
- Produces: `set_timer_conv_callback(cb)`, `_inject_timer_to_graph(user_id, group_id, sys_prompt, task_prompt, context_msgs)`, updated `_execute_timer`
- Removes: `_run_timer_agent`, `_save_tools_globals`, `_restore_tools_globals`

- [ ] **Step 1: Remove _run_timer_agent, _save_tools_globals, _restore_tools_globals**

Delete lines 242-347 in `timer/executor.py` — the three functions `_run_timer_agent`, `_save_tools_globals`, `_restore_tools_globals`.

- [ ] **Step 2: Add _inject_timer_to_graph function and callback setter**

Add after `_fetch_recent_messages` (after line 239):

```python
# Lazy reference to the timer start-conversation callback (set by chat.py)
_timer_start_conv_cb: Any = None


def set_timer_conv_callback(cb: Any) -> None:
    """Set the callback used to start a conversation when a timer fires
    and no conversation is active. Called by handlers/chat.py at import time."""
    global _timer_start_conv_cb
    _timer_start_conv_cb = cb


async def _inject_timer_to_graph(
    user_id: int, group_id: int, sys_prompt: str,
    task_prompt: str, context_msgs: list[dict],
) -> None:
    """Inject a timer prompt into the conversation graph.

    Mirrors the agent_allocate -> inject_agent_notification pattern.
    Builds a __timer__:{user_id} marked message and injects it via
    inject_timer() in graph/nodes/ai.py. The existing LangGraph handles
    everything: human_node picks it up, detect_node routes to continue,
    ai_node @mentions the timer creator.
    """
    from ..graph.nodes.ai import inject_timer

    context_text = ""
    if context_msgs:
        context_text = "\n".join(
            m["text"] for m in context_msgs if isinstance(m, dict)
        )

    inject_timer(
        user_id=user_id,
        timer_prompt=task_prompt,
        context=(
            f"系统上下文：{sys_prompt}\n\n"
            f"最近的群聊消息：\n{context_text}"
        ),
        start_conversation_cb=_timer_start_conv_cb,
    )
```

- [ ] **Step 3: Update _execute_timer to use injection instead of standalone agent**

Replace lines 170-208 in `timer/executor.py` (from "# 3. Build system prompt..." through "# 6. Deliver") with:

```python
    # 3. Build system prompt with creator identity
    creator_info = f"{user_name} (QQ: {user_id})" if user_name else f"QQ: {user_id}"
    timer_sys_prompt = build_timer_system_prompt(creator_info, group_id, prompt)

    # 4. Inject into the conversation graph (replaces standalone _run_timer_agent)
    t_start = time.time()
    try:
        await _inject_timer_to_graph(
            user_id, group_id, timer_sys_prompt, prompt, context_msgs,
        )
        elapsed = time.time() - t_start
        print(
            f"⏰ [timer] Timer injected into graph OK: task={task_id} "
            f"elapsed={elapsed:.1f}s"
        )
    except Exception:
        elapsed = time.time() - t_start
        print(f"❌ [timer] Timer injection FAILED: task={task_id} elapsed={elapsed:.1f}s")
        traceback.print_exc()

    # 5. Mark fired (delivery is handled by the graph's ai_node)
    store.mark_trigger_fired(trigger_id)
```

This removes the old:
- `result_text = await _run_timer_agent(...)` block
- `bot.send_group_msg(...)` delivery block
- Duplicate `store.mark_trigger_fired(trigger_id)` call

- [ ] **Step 4: Run existing tests to verify no regression**

Run: `python -m pytest tests/test_timer_store.py -v`
Expected: ALL TESTS PASS (storage layer unchanged)

- [ ] **Step 5: Ruff lint check**

Run: `ruff check hatsume/plugins/hatsume-plugin/timer/executor.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/timer/executor.py
git commit -m "feat: replace _run_timer_agent with _inject_timer_to_graph

Timer triggers now inject into graph via same pattern as agent_allocate.
Removes ~100 lines of standalone agent setup, replaces with ~30 line
injection function. Delivery handled by the graph's ai_node.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Register timer callback in chat.py (wiring)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py`

**Interfaces:**
- Consumes: `_start_conv_for_timer` from same file (Task 3), `set_timer_conv_callback` from `timer.executor` (Task 5)
- Produces: Wiring complete — timer executor can start conversations when not chatting

- [ ] **Step 1: Add import and callback registration**

In `hatsume/plugins/hatsume-plugin/handlers/chat.py`, after line 72 (`configure_agent_notification_callback(_start_conv_for_agent)`), add:

```python
# Register timer callback with executor (mirrors agent notification registration above)
from ..timer.executor import set_timer_conv_callback
set_timer_conv_callback(_start_conv_for_timer)
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/test_timer_injection.py tests/test_timer_store.py tests/test_graph_nodes.py tests/test_conversation.py -v`
Expected: ALL TESTS PASS

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/handlers/chat.py
git commit -m "feat: wire timer callback between executor and chat handler

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Update graph/nodes/__init__.py exports

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py`

- [ ] **Step 1: Read current __init__.py and add timer exports**

First check what's currently exported, then add `detect_timer_notification`, `inject_timer`, `TIMER_MARK` alongside existing `detect_agent_notification`.

- [ ] **Step 2: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py
git commit -m "feat: export timer detection and injection from graph.nodes

Co-Authored-By: Claude <noreply@anthropic.com>"
```
