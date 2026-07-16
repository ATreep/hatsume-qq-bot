# AI Node Auxiliary Queue Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `auxiliary_messages_queue` + `human_queue` concatenation logic out of `human_node` and into `ai_node`, so `human_node` returns only the current turn's raw human content, and the aux+human merge exists only as a temporary construction fed to `chat_agent.ainvoke()` — never written back into `state["messages"]`.

**Architecture:** `human_node` (`graph/nodes/human.py`) keeps waiting on `human_queue` and computing the `_last_was_auxiliary_only` routing flag, but stops touching `auxiliary_messages_queue` entirely. `ai_node` (`graph/nodes/ai.py`) gains a new helper, `_consume_auxiliary_queue()`, that snapshots + clears the module-level aux queues and archives the snapshot onto `ConversationState.auxiliary_queue` / `.auxiliary_source_queue` (existing, currently-unused dataclass fields). `ai_node` builds a throwaway merged `HumanMessage` for the `chat_agent.ainvoke()` call only when aux content exists; `state["messages"][-1]` itself is never mutated. `finish_conversation_node` (`graph/nodes/finish.py`) clears the archive fields when a conversation ends, so they don't grow unbounded across multiple conversations.

**Tech Stack:** Python 3.12+, LangGraph `MessagesState`, pytest (existing hand-rolled module-stubbing harness in `tests/test_graph_nodes.py`).

## Global Constraints

- No new third-party dependencies.
- Preserve the exact wording of the existing merge markers: `"## 历史聊天记录："` and `"## 当前聊天记录："`.
- `state["messages"]` (the LangGraph-persisted history) must never contain the aux-merge markers after this change — only `human_node`'s raw `human_queue` content.
- Memory-retrieval query content (`ai_node`'s `last_content` / `memory_summary` logic) must continue to use only the current turn's raw human content, not aux history — this is already true structurally once `human_node` stops merging, so no code change is needed there, only a regression test.
- Reuse the existing `ConversationState.auxiliary_queue` / `auxiliary_source_queue` dataclass fields (`state.py:67-68`) for archiving consumed aux content — do not add new fields.
- Archived aux content is cleared in `finish_conversation_node`, not on every turn — it accumulates across turns within one conversation, then resets when the conversation ends.
- All existing tests in `tests/test_graph_nodes.py` that don't involve auxiliary content must continue to pass unmodified.

---

### Task 1: `human_node` stops merging/clearing the auxiliary queue

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/human.py` (full file, 56 lines)
- Test: `tests/test_graph_nodes.py`

**Interfaces:**
- Consumes: `auxiliary_messages_queue: list[dict]` (module-level global in `graph/nodes/ai.py`, imported by `human.py` — read-only now)
- Produces: `human_node(state) -> {"messages": [HumanMessage(human_queue)]}` where `human_queue` is the raw, unmerged `human_queue` content (list of dicts). `_last_was_auxiliary_only: bool` module global in `human.py` is still set on every call, same semantics as before (`not human_queue and bool(auxiliary_messages_queue)`), but is now computed via a read-only check — `auxiliary_messages_queue` is left untouched by `human_node`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_graph_nodes.py`, in the `# Bug 3: auxiliary-only messages should skip chat_end_detect_node` section (after `test_human_node_clears_auxiliary_only_flag_when_human_queue_present`, around line 804):

```python
def test_human_node_does_not_merge_or_clear_auxiliary_queue():
    """human_node must return ONLY the raw human_queue content — no aux
    markers, no aux merge — and must leave auxiliary_messages_queue
    untouched. Consumption now happens in ai_node, not human_node."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "background chat"})
    nodes.auxiliary_source_queue.clear()
    nodes.auxiliary_source_queue.append(
        {"source_id": "aux-1", "text": "aux source", "people": []}
    )

    mock_state = types.SimpleNamespace(
        human_queue=[{"type": "text", "text": "hello bot"}],
        human_source_queue=[],
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    result = asyncio.run(nodes.human_node({"messages": []}))

    # Only the raw human content — no "## 历史聊天记录：" / "## 当前聊天记录：" markers
    assert result["messages"][0].content == [{"type": "text", "text": "hello bot"}]

    # aux queues must survive human_node completely untouched
    assert nodes.auxiliary_messages_queue == [{"type": "text", "text": "background chat"}]
    assert nodes.auxiliary_source_queue == [
        {"source_id": "aux-1", "text": "aux source", "people": []}
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph_nodes.py::test_human_node_does_not_merge_or_clear_auxiliary_queue -v`
Expected: FAIL — with the current `human.py`, `result["messages"][0].content` includes the `"## 历史聊天记录："` / `"## 当前聊天记录："` markers and the aux queue snapshot, and `auxiliary_messages_queue`/`auxiliary_source_queue` are cleared to `[]` by the end of the call.

- [ ] **Step 3: Rewrite `human.py`**

Replace the full contents of `hatsume/plugins/hatsume-plugin/graph/nodes/human.py`:

```python
"""Human node: wait for human input from the message queue."""

from __future__ import annotations

import asyncio
import time

from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import MessagesState

from .ai import (
    auxiliary_messages_queue,
    append_memory_record_sources,
    _get_human_queue,
    _get_human_sources,
    _clear_human_queue,
)

_last_was_auxiliary_only: bool = False


async def human_node(state: MessagesState) -> dict:
    global _last_was_auxiliary_only
    print("Enter human_node")

    t_start = time.time()
    while not _get_human_queue():
        await asyncio.sleep(0.3)
        if time.time() - t_start >= 60 * 5:
            _last_was_auxiliary_only = not _get_human_queue() and bool(auxiliary_messages_queue)
            return {"messages": [SystemMessage("__end__")]}

    human_queue = _get_human_queue().copy()
    human_sources = _get_human_sources().copy()
    _clear_human_queue()

    _last_was_auxiliary_only = not human_queue and bool(auxiliary_messages_queue)

    append_memory_record_sources(human_sources)

    return {"messages": [HumanMessage(human_queue)]}  # type: ignore
```

Note what changed from the original: the `auxiliary_source_queue` import is dropped (no longer used in this file), the `aux_queue`/`aux_sources` snapshot-and-clear block is removed, the `append_memory_record_sources(aux_sources)` call is removed (moved to `ai_node` in Task 2), and the `if aux_queue: human_queue = [...]` merge block is removed entirely.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph_nodes.py::test_human_node_does_not_merge_or_clear_auxiliary_queue -v`
Expected: PASS

- [ ] **Step 5: Run the full existing human_node test suite to check for regressions**

Run: `python -m pytest tests/test_graph_nodes.py -k human_node -v`
Expected: All PASS, including `test_human_node_returns_nonempty_content_when_queue_populated`, `test_human_node_queue_is_cleared_after_processing`, `test_human_node_sets_auxiliary_only_flag_when_no_human_queue`, `test_human_node_clears_auxiliary_only_flag_when_human_queue_present`.

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/human.py tests/test_graph_nodes.py
git commit -m "refactor: human_node returns only raw human_queue content, no aux merge"
```

---

### Task 2: `ai_node` consumes the auxiliary queue and builds a temporary merged message for `chat_agent`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:265-476` (add helper after `append_auxiliary_message`, modify `ai_node`)
- Test: `tests/test_graph_nodes.py`

**Interfaces:**
- Consumes: `auxiliary_messages_queue` / `auxiliary_source_queue` (module globals, same file); `_state: ConversationState | None` (module global, set via `bind_state()`, already used elsewhere in this file); `ConversationState.auxiliary_queue: list[dict]` / `.auxiliary_source_queue: list[dict]` (`state.py:67-68`, already exist).
- Produces: `_consume_auxiliary_queue() -> tuple[list[dict], list[dict]]` — new module-level function in `ai.py`, returns `(aux_queue, aux_sources)` snapshots, clears the module globals, and archives non-empty snapshots onto `_state.auxiliary_queue` / `_state.auxiliary_source_queue`. `ai_node` now builds `last_human_msg` (a `HumanMessage` with merged content, or the original `state["messages"][-1]` unchanged when aux is empty) and passes it to `chat_agent.ainvoke()` instead of `state["messages"][-1]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_graph_nodes.py`, in a new section after the `Bug 3` section (after the human_node tests, before `# -----\n# Bug 4: ai_node memory accumulation bounds check` — i.e. insert right before line 806-809's `test_ai_node_queries_backward_with_even_split` section header):

```python
# -----------------------------------------------------------------------
# Feature: ai_node consumes and merges the auxiliary queue
# -----------------------------------------------------------------------


def test_ai_node_merges_auxiliary_queue_for_chat_agent_only():
    """ai_node should temporarily merge auxiliary_messages_queue with the
    latest human message when invoking chat_agent, without mutating
    state["messages"][-1], and archive the consumed content onto
    ConversationState.auxiliary_queue."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "aux part"})
    nodes.auxiliary_source_queue.clear()
    nodes.auxiliary_source_queue.append(
        {"source_id": "aux-1", "text": "aux source text", "people": []}
    )

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    captured_invocations: list[dict] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, payload, *a, **kw):
            captured_invocations.append(payload)
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    original_create_agent = nodes._ai.create_agent
    nodes._ai.create_agent = lambda *a, **kw: _FakeAgent()

    human_msg = types.SimpleNamespace(
        content=[{"type": "text", "text": "current turn"}], type="human"
    )

    try:
        asyncio.run(nodes.ai_node({"messages": [human_msg]}))

        sent_last_msg = captured_invocations[0]["messages"][-1]
        assert sent_last_msg.content == [
            {"type": "text", "text": "## 历史聊天记录："},
            {"type": "text", "text": "aux part"},
            {"type": "text", "text": "## 当前聊天记录："},
            {"type": "text", "text": "current turn"},
        ]

        # The original state message must be untouched (no permanent mutation)
        assert human_msg.content == [{"type": "text", "text": "current turn"}]

        # Module-level aux queue must be cleared after consumption
        assert nodes.auxiliary_messages_queue == []
        assert nodes.auxiliary_source_queue == []

        # Consumed aux content archived onto ConversationState
        assert mock_state.auxiliary_queue == [{"type": "text", "text": "aux part"}]
        assert mock_state.auxiliary_source_queue == [
            {"source_id": "aux-1", "text": "aux source text", "people": []}
        ]
    finally:
        nodes._ai.create_agent = original_create_agent


def test_ai_node_skips_merge_when_auxiliary_queue_empty():
    """When auxiliary_messages_queue is empty, ai_node must pass
    state["messages"][-1] to chat_agent unchanged (no wrapping, no markers)."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    captured_invocations: list[dict] = []

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, payload, *a, **kw):
            captured_invocations.append(payload)
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    original_create_agent = nodes._ai.create_agent
    nodes._ai.create_agent = lambda *a, **kw: _FakeAgent()

    human_msg = types.SimpleNamespace(
        content=[{"type": "text", "text": "current turn"}], type="human"
    )

    try:
        asyncio.run(nodes.ai_node({"messages": [human_msg]}))

        sent_last_msg = captured_invocations[0]["messages"][-1]
        assert sent_last_msg is human_msg
        assert mock_state.auxiliary_queue == []
    finally:
        nodes._ai.create_agent = original_create_agent


def test_ai_node_memory_query_uses_only_human_content_not_auxiliary():
    """Memory retrieval must query using only the raw human content, even
    when auxiliary_messages_queue has pending history."""
    nodes = _load_nodes_module()

    nodes.auxiliary_messages_queue.clear()
    nodes.auxiliary_messages_queue.append({"type": "text", "text": "aux history"})
    nodes.auxiliary_source_queue.clear()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[],
        auxiliary_source_queue=[],
    )
    nodes.bind_state(mock_state)

    query_calls: list[str] = []

    def mock_query_memory(text, **kw):
        query_calls.append(text)
        return ""

    original_query_memory = nodes._ai.query_memory
    nodes._ai.query_memory = mock_query_memory

    original_create_agent = nodes._ai.create_agent

    class _FakeAgent:
        def with_retry(self, **kw):
            return self

        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="ok", type="ai")]}

    nodes._ai.create_agent = lambda *a, **kw: _FakeAgent()

    human_msg = types.SimpleNamespace(content="current turn text", type="human")

    try:
        asyncio.run(nodes.ai_node({"messages": [human_msg]}))
        assert query_calls == ["current turn text"]
        assert "aux history" not in query_calls
    finally:
        nodes._ai.query_memory = original_query_memory
        nodes._ai.create_agent = original_create_agent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_graph_nodes.py::test_ai_node_merges_auxiliary_queue_for_chat_agent_only tests/test_graph_nodes.py::test_ai_node_skips_merge_when_auxiliary_queue_empty tests/test_graph_nodes.py::test_ai_node_memory_query_uses_only_human_content_not_auxiliary -v`
Expected: `test_ai_node_merges_auxiliary_queue_for_chat_agent_only` FAILs (current `ai_node` passes `state["messages"][-1]` straight through with no merge, so `sent_last_msg.content` is just `[{"type": "text", "text": "current turn"}]`, and `mock_state.auxiliary_queue` stays `[]`). The other two should already PASS since they describe pre-existing behavior for the empty-aux case — confirm they pass so Step 2 establishes a clean baseline before Step 3's implementation.

- [ ] **Step 3: Implement `_consume_auxiliary_queue()` and wire it into `ai_node`**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, add a new function immediately after `append_auxiliary_message` (after line 300, before the `# ---` separator at line 303):

```python
def _consume_auxiliary_queue() -> tuple[list[dict], list[dict]]:
    """Snapshot and clear the module-level auxiliary queues.

    The snapshot is archived onto ConversationState.auxiliary_queue /
    auxiliary_source_queue (only when non-empty) so consumed aux content
    isn't silently discarded — it's available there until the conversation
    ends (finish_conversation_node clears it).
    """
    aux_queue = auxiliary_messages_queue.copy()
    aux_sources = auxiliary_source_queue.copy()
    auxiliary_messages_queue.clear()
    auxiliary_source_queue.clear()
    if _state is not None and (aux_queue or aux_sources):
        _state.auxiliary_queue.extend(aux_queue)
        _state.auxiliary_source_queue.extend(aux_sources)
    return aux_queue, aux_sources
```

Then, in `ai_node`, replace the block from `ai_text: str = ""` (line 397) through the `ainvoke(...)` call (lines 397-411):

```python
    ai_text: str = ""
    try:
        mem_msg = (
            []
            if memory_summary.strip() == ""
            else [
                HumanMessage(build_memory_context_prompt(memory_summary))
            ]
        )
        response = await chat_agent.with_retry(
            stop_after_attempt=5
        ).ainvoke(
            {"messages": state["messages"][:-1] + mem_msg + [state["messages"][-1]]},
            {"recursion_limit": 60},
        )
```

with:

```python
    aux_queue, aux_sources = _consume_auxiliary_queue()
    if aux_queue:
        append_memory_record_sources(aux_sources)
        merged_content = (
            [{"type": "text", "text": "## 历史聊天记录："}]
            + aux_queue
            + [{"type": "text", "text": "## 当前聊天记录："}]
            + state["messages"][-1].content
        )
        last_human_msg: Any = HumanMessage(merged_content)
    else:
        last_human_msg = state["messages"][-1]

    ai_text: str = ""
    try:
        mem_msg = (
            []
            if memory_summary.strip() == ""
            else [
                HumanMessage(build_memory_context_prompt(memory_summary))
            ]
        )
        response = await chat_agent.with_retry(
            stop_after_attempt=5
        ).ainvoke(
            {"messages": state["messages"][:-1] + mem_msg + [last_human_msg]},
            {"recursion_limit": 60},
        )
```

This block goes right after the `chat_agent = create_agent(...)` call (ends at line 395) and before the `ai_text: str = ""` line — it does not depend on `chat_agent`, `mem_msg`, or memory retrieval, so ordering relative to those is not load-bearing, but keep it in this position to minimize the diff.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_graph_nodes.py::test_ai_node_merges_auxiliary_queue_for_chat_agent_only tests/test_graph_nodes.py::test_ai_node_skips_merge_when_auxiliary_queue_empty tests/test_graph_nodes.py::test_ai_node_memory_query_uses_only_human_content_not_auxiliary -v`
Expected: All 3 PASS

- [ ] **Step 5: Run the full ai_node test suite to check for regressions**

Run: `python -m pytest tests/test_graph_nodes.py -k ai_node -v`
Expected: All PASS, including `test_ai_node_queries_backward_with_even_split`, `test_ai_node_single_text_part_gets_full_limit`, `test_generate_image_used_skips_face_injection`, `test_face_injection_when_flags_false`, `test_face_tag_stripped_from_user_text_preserved_in_aimessage`, `test_capture_html_transcript_recorded_in_ai_node`. These all leave `auxiliary_messages_queue` empty (fresh module reload per test), so `_consume_auxiliary_queue()` returns `([], [])` and never touches `mock_state.auxiliary_queue` — none of their `mock_state` constructions need updating.

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py tests/test_graph_nodes.py
git commit -m "feat: ai_node merges auxiliary queue into a temporary message for chat_agent"
```

---

### Task 3: `finish_conversation_node` clears the archived auxiliary queue

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py:16-34`
- Test: `tests/test_graph_nodes.py`

**Interfaces:**
- Consumes: `_clear_auxiliary_archive()` — new function from `ai.py` (Task 3 adds this).
- Produces: `finish_conversation_node` now also clears `ConversationState.auxiliary_queue` / `.auxiliary_source_queue` as part of its cleanup, alongside the existing `_clear_human_queue()` call.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_graph_nodes.py`, right after `test_finish_conversation_node_calls_cleanup_persistent_container` (after line 532, before the `# ---\n# Feature: Docker persistent container functions` section at line 535):

```python
def test_finish_conversation_node_clears_auxiliary_archive():
    """finish_conversation_node must clear the archived auxiliary_queue on
    ConversationState so it doesn't accumulate across conversations."""
    nodes = _load_nodes_module()

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
        auxiliary_queue=[{"type": "text", "text": "leftover aux"}],
        auxiliary_source_queue=[{"source_id": "s1", "text": "t", "people": []}],
    )
    nodes.bind_state(mock_state)

    original_create_agent = nodes._finish.create_agent

    async def _mock_ainvoke(*a, **kw):
        return {"messages": []}

    nodes._finish.create_agent = lambda *a, **kw: types.SimpleNamespace(
        ainvoke=_mock_ainvoke
    )

    messages = [
        MockMessage("hello", "human"),
        MockMessage("hi", "ai"),
    ]

    try:
        asyncio.run(nodes.finish_conversation_node({"messages": messages}))
        assert mock_state.auxiliary_queue == []
        assert mock_state.auxiliary_source_queue == []
    finally:
        nodes._finish.create_agent = original_create_agent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_graph_nodes.py::test_finish_conversation_node_clears_auxiliary_archive -v`
Expected: FAIL — `mock_state.auxiliary_queue` still contains `[{"type": "text", "text": "leftover aux"}]` because nothing clears it today.

- [ ] **Step 3: Add `_clear_auxiliary_archive()` to `ai.py` and wire it into `finish.py`**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, add this function immediately after `_consume_auxiliary_queue()` (added in Task 2, Step 3):

```python
def _clear_auxiliary_archive() -> None:
    if _state:
        _state.auxiliary_queue.clear()
        _state.auxiliary_source_queue.clear()
```

In `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py`, update the import block (lines 16-26):

```python
from .ai import (
    _set_graph_running,
    _clear_human_queue,
    _clear_auxiliary_archive,
    _get_ai_answer,
    _retrieved_mem_keys,
    _memory_record_transcript,
    _memory_record_source_map,
    reset_memory_record_context,
    append_auxiliary_message,
    _set_current_query_user_id,
)
```

And update the top of `finish_conversation_node` (lines 33-35):

```python
    _set_graph_running(False)
    _clear_human_queue()
    _clear_auxiliary_archive()
    _retrieved_mem_keys.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_graph_nodes.py::test_finish_conversation_node_clears_auxiliary_archive -v`
Expected: PASS

- [ ] **Step 5: Run the full finish_conversation_node test suite to check for regressions**

Run: `python -m pytest tests/test_graph_nodes.py -k finish_conversation_node -v`
Expected: All PASS, including `test_finish_conversation_node_calls_cleanup_persistent_container`.

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py hatsume/plugins/hatsume-plugin/graph/nodes/finish.py tests/test_graph_nodes.py
git commit -m "feat: finish_conversation_node clears archived auxiliary queue"
```

---

### Task 4: Full regression pass

**Files:**
- None (verification only)

**Interfaces:**
- None

- [ ] **Step 1: Run the full graph-nodes test file**

Run: `python -m pytest tests/test_graph_nodes.py -v`
Expected: All tests PASS (no regressions in any test not directly related to this change — `chat_end_detect_node`, docker/infra, face injection, capture-html, agent/timer notification detection tests all remain green).

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/ -x`
Expected: All tests PASS.

- [ ] **Step 3: Confirm no stray references to the removed merge logic remain**

Run: `grep -rn "aux_queue" hatsume/plugins/hatsume-plugin/graph/nodes/human.py`
Expected: No output (empty) — `human.py` no longer references `aux_queue` at all.

Run: `grep -n "auxiliary" hatsume/plugins/hatsume-plugin/graph/nodes/human.py`
Expected: Only the `auxiliary_messages_queue` import and its use in the `_last_was_auxiliary_only` computation — no merge/clear logic.

- [ ] **Step 4: Update the design doc status**

Edit `docs/superpowers/specs/2026-07-03-ai-node-aux-merge-design.md`, change the header:

```markdown
- 状态：待用户审阅
```

to:

```markdown
- 状态：已实现
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-03-ai-node-aux-merge-design.md
git commit -m "docs: mark aux-merge design as implemented"
```
