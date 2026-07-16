# Agent Notification Detection Skip — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an agent_allocate-spawned agent injects its result into human_queue, skip chat_end_detect_node's end-detection logic so the graph always routes the notification to chat_llm.

**Architecture:** Extract the NOTIFY_MARK scanning loop from ai_node into a pure function `detect_agent_notification(state) -> int | None` in ai.py. Call it from chat_end_detect_node as an early-return guard, and refactor ai_node to use the same function. 3 files changed, zero new files.

**Tech Stack:** Python 3.12+, LangGraph MessagesState, pytest (existing test harness)

## Global Constraints

- Python 3.12+, `from __future__ import annotations`
- Lint: ruff (config in pyproject.toml)
- Follow existing test patterns in tests/test_graph_nodes.py (MockMessage, _load_nodes_module)
- Type hints on all new functions
- NOTIFY_MARK constant must remain in ai.py (co-located with detect_agent_notification)

---

### Task 1: Add `detect_agent_notification()` function to ai.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Produces: `detect_agent_notification(state: MessagesState) -> int | None` — scans `state["messages"][-1].content` for NOTIFY_MARK prefix, returns notified user_id (int) if found, None otherwise

- [ ] **Step 1: Insert the function into ai.py**

Insert immediately after the `NOTIFY_MARK` constant definition (after line 47) and before `inject_agent_notification` (line 49). The function is pure — no side effects, no module-level state access.

```python
def detect_agent_notification(state: MessagesState) -> int | None:
    """Scan state["messages"][-1].content for NOTIFY_MARK.

    Returns the notified user_id (int) if the last message contains
    a __agent_notify__ mark, or None otherwise.
    """
    last_content = state["messages"][-1].content

    if isinstance(last_content, list):
        for part in reversed(last_content):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(NOTIFY_MARK):
                _, uid_str, _ = text.split(":", 2)
                return int(uid_str)
    elif isinstance(last_content, str) and last_content.startswith(NOTIFY_MARK):
        _, uid_str, _ = last_content.split(":", 2)
        return int(uid_str)

    return None
```

- [ ] **Step 2: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: add detect_agent_notification() reusable function

Extracts NOTIFY_MARK scanning logic from ai_node into a pure function
for reuse by chat_end_detect_node.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Export `detect_agent_notification` from `__init__.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py:3-19`

**Interfaces:**
- Consumes: `detect_agent_notification` from `.ai`
- Produces: `detect_agent_notification` available as `nodes.detect_agent_notification`

- [ ] **Step 1: Add to the import from `.ai` block**

Change the existing import block (lines 3-19) to include `detect_agent_notification`:

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
    detect_agent_notification,
)
```

- [ ] **Step 2: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/__init__.py
git commit -m "feat: export detect_agent_notification from nodes package

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Refactor ai_node to use `detect_agent_notification()`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:184-201`

**Interfaces:**
- Consumes: `detect_agent_notification(state) -> int | None` (defined in Task 1)
- Produces: ai_node behavior unchanged — `notified_uid` still set to int or None

- [ ] **Step 1: Replace inline detection block with function call**

Replace lines 184-201:

```python
    # ── Detect agent notification mark in the last message ──
    last_content_in = state["messages"][-1].content
    notified_uid: int | None = None

    if isinstance(last_content_in, list):
        for part in reversed(last_content_in):
            text = ""
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text", ""))
            elif isinstance(part, str):
                text = part
            if text.startswith(NOTIFY_MARK):
                _, uid_str, _ = text.split(":", 2)
                notified_uid = int(uid_str)
                break
    elif isinstance(last_content_in, str) and last_content_in.startswith(NOTIFY_MARK):
        _, uid_str, _ = last_content_in.split(":", 2)
        notified_uid = int(uid_str)
```

With:

```python
    # ── Detect agent notification mark in the last message ──
    notified_uid = detect_agent_notification(state)
```

- [ ] **Step 2: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "refactor: use detect_agent_notification() in ai_node

Replace inline NOTIFY_MARK detection with the new reusable function.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add early return to `chat_end_detect_node`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py:17-18`

**Interfaces:**
- Consumes: `detect_agent_notification` from `.ai` (imported via `from .ai import detect_agent_notification`)
- Produces: detect node returns `{"messages": []}` (continue) when NOTIFY_MARK is present

- [ ] **Step 1: Add import**

Add `detect_agent_notification` to the existing imports at the top of `detect.py`. Change line 14 from:

```python
from .human import _last_was_auxiliary_only
```

To:

```python
from .ai import detect_agent_notification
from .human import _last_was_auxiliary_only
```

- [ ] **Step 2: Add early return guard**

Insert immediately after `print("Enter chat_end_detect_node")` (line 18), before any existing logic:

```python
async def chat_end_detect_node(state: MessagesState) -> dict:
    print("Enter chat_end_detect_node")
    # Agent notification: always route to chat_llm, never end conversation
    if detect_agent_notification(state) is not None:
        return {"messages": []}
    from openai import APITimeoutError
    # ... rest of existing logic unchanged ...
```

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/detect.py
git commit -m "feat: skip end-detection when agent notification is present

chat_end_detect_node now checks for NOTIFY_MARK in the last message
and returns 'no' (continue) immediately, ensuring agent results
always reach chat_llm for processing.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Write and run unit tests

**Files:**
- Modify: `tests/test_graph_nodes.py` (append new test functions)

**Interfaces:**
- Consumes: `detect_agent_notification` from loaded nodes module (via `_load_nodes_module()`)
- Produces: 4 test functions covering the new function and the detect node guard

- [ ] **Step 1: Write the failing tests**

Append the following test functions to `tests/test_graph_nodes.py` before the final line:

```python
# -----------------------------------------------------------------------
# detect_agent_notification — NOTIFY_MARK extraction
# -----------------------------------------------------------------------


def test_detect_agent_notification_returns_uid_for_notify_mark_in_list_content():
    """detect_agent_notification extracts user_id from NOTIFY_MARK in list content."""
    nodes = _load_nodes_module()

    state = {
        "messages": [
            MockMessage(
                content=[
                    {"type": "text", "text": f"{nodes.NOTIFY_MARK}:12345:web_browser\nresult text"}
                ]
            )
        ]
    }

    result = nodes.detect_agent_notification(state)
    assert result == 12345


def test_detect_agent_notification_returns_uid_for_notify_mark_in_string_content():
    """detect_agent_notification extracts user_id from NOTIFY_MARK in string content."""
    nodes = _load_nodes_module()

    state = {
        "messages": [
            MockMessage(
                content=f"{nodes.NOTIFY_MARK}:67890:generate_video\nvideo result"
            )
        ]
    }

    result = nodes.detect_agent_notification(state)
    assert result == 67890


def test_detect_agent_notification_returns_none_when_no_notify_mark():
    """detect_agent_notification returns None for normal messages."""
    nodes = _load_nodes_module()

    state = {
        "messages": [
            MockMessage(
                content=[{"type": "text", "text": "hello world"}]
            )
        ]
    }

    result = nodes.detect_agent_notification(state)
    assert result is None


def test_chat_end_detect_node_skips_detection_when_notify_mark_present():
    """chat_end_detect_node returns {"messages": []} immediately when NOTIFY_MARK found."""
    nodes = _load_nodes_module()

    state = {
        "messages": [
            MockMessage("msg1", "human"),
            MockMessage("msg2", "ai"),
            MockMessage("msg3", "human"),
            MockMessage(
                content=[{"type": "text", "text": f"{nodes.NOTIFY_MARK}:11111:web_browser\nsome result"}]
            ),
        ]
    }

    result = asyncio.run(nodes.chat_end_detect_node(state))
    # Should return {"messages": []} (continue) without calling any model
    assert result == {"messages": []}
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
python -m pytest tests/test_graph_nodes.py -k "test_detect_agent_notification or test_chat_end_detect_node_skips" -xvs
```

Expected: 4 tests collected, all PASS.

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -xvs
```

Expected: All existing tests still pass (no regressions from the refactor).

- [ ] **Step 4: Commit**

```bash
git add tests/test_graph_nodes.py
git commit -m "test: add unit tests for detect_agent_notification and detect node skip

Co-Authored-By: Claude <noreply@anthropic.com>"
```
