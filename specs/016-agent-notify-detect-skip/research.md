# Research: Agent Notification Detection Skip

**Feature**: 016-agent-notify-detect-skip
**Date**: 2026-06-26

## Decision 1: Function placement — ai.py vs new module

**Decision**: Place `detect_agent_notification()` in `ai.py` alongside `NOTIFY_MARK` and `inject_agent_notification`.

**Rationale**: Co-location with the `NOTIFY_MARK` constant reduces indirection. The function is a pure stateless utility that reads only `MessagesState`. A new module (`notify.py`) would add import complexity and risk circular dependencies (since `inject_agent_notification` depends on `_state` in `ai.py`).

**Alternatives considered**:
- New `notify.py` module: Over-engineered for a single function; requires reworking imports in ai.py's `inject_agent_notification` which accesses module-level `_state`.

## Decision 2: Early return value in chat_end_detect_node

**Decision**: Return `{"messages": []}` when NOTIFY_MARK detected.

**Rationale**: In the LangGraph builder routing, `{"messages": []}` causes `_chat_end_detect_condition` to return `"continue"` (since no `__end__` message is produced and `_last_was_auxiliary_only` is unchanged), routing to `chat_llm`. This is the simplest path — no new routing logic needed.

**Alternatives considered**:
- Returning a special SystemMessage: Adds complexity with no benefit; the empty dict already produces the desired routing.

## Decision 3: Test approach

**Decision**: Use existing `_load_nodes_module()` + `MockMessage` infrastructure in `tests/test_graph_nodes.py`.

**Rationale**: The test harness already stubs all external dependencies (LangChain, NoneBot, models, tools) and loads the real module code. This provides true integration-level testing of the function against real code. No mocking of `detect_agent_notification` needed — test the actual function.

**Alternatives considered**:
- New test file: Unnecessary for 4 test functions; the existing file already tests node functions.
- Mocking the function in detect node tests: Wouldn't test the integration of the function with the detect node.
