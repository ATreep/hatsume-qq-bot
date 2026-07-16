# Implementation Plan: Agent Notification Detection Skip

**Branch**: `016-agent-notify-detect-skip` | **Date**: 2026-06-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/016-agent-notify-detect-skip/spec.md`

## Summary

Extract the NOTIFY_MARK detection logic currently inline in `ai_node` into a reusable pure function `detect_agent_notification(state) -> int | None`. Call this function from `chat_end_detect_node` as an early-return guard to skip end-detection when an agent notification is present, ensuring agent results always route to `chat_llm`. Refactor `ai_node` to use the same function, eliminating code duplication.

## Technical Context

**Language/Version**: Python 3.12+ (from `__future__ import annotations`)

**Primary Dependencies**: LangGraph `MessagesState` (the state type used by the function signature)

**Storage**: N/A

**Testing**: pytest (existing test harness in `tests/test_graph_nodes.py` — uses `MockMessage` + `_load_nodes_module()`)

**Target Platform**: Linux server (NoneBot2)

**Project Type**: Plugin module (nonebot2 plugin)

**Performance Goals**: O(n) scan of last message content parts (typically 1-3 parts); no measurable overhead

**Constraints**: Zero API changes — purely internal refactor + guard logic. No new dependencies.

**Scale/Scope**: 3 files modified, 0 files created, ~40 lines of net-new code

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution file is a placeholder template — no specific gates defined. This feature:
- Follows existing code patterns (no new architectural patterns)
- Adds no new dependencies
- Is scoped to 3 existing files
- Includes unit tests following existing test conventions

✅ Gate passed by default.

## Project Structure

### Documentation (this feature)

```text
specs/016-agent-notify-detect-skip/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/graph/nodes/
├── ai.py                # Add detect_agent_notification(); refactor ai_node to use it
├── detect.py            # Import + early-return guard in chat_end_detect_node
└── __init__.py          # Export detect_agent_notification

tests/
└── test_graph_nodes.py  # 4 new test functions
```

**Structure Decision**: No new files — all changes are modifications to existing nodes in the graph package. The function lives in `ai.py` alongside `NOTIFY_MARK` for co-location.

## Complexity Tracking

> No constitution violations — no entries needed.
