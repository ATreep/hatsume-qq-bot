# Implementation Plan: Agent Allocate Tool

**Branch**: `015-agent-allocate-tool` | **Date**: 2026-06-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/015-agent-allocate-tool/spec.md`

## Summary

Add an `agent_allocate` tool to the QQ bot that dispatches built-in background agents (web browser, video generation) via a unified registry. The tool accepts a target user ID, agent name, and task description; runs the agent asynchronously; and on completion injects the result back into the conversation flow with a special notification mark (`__agent_notify__:<user_id>:<agent_name>`). The conversation system detects this mark and routes the response through @-mention notification. A new `graph/agents.py` file maintains the agent registry, and the tool description dynamically lists available agents via an f-string evaluated at module import time.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: LangChain (tool framework), LangGraph (StateGraph), NoneBot2 (QQ adapter), asyncio

**Storage**: Agent registry is in-memory (Python dict at module level). No persistent storage needed.

**Testing**: pytest

**Target Platform**: Linux server running NoneBot2 with OneBot V11 protocol

**Project Type**: NoneBot2 plugin (Python package)

**Performance Goals**: Tool dispatch response <100ms; agent-to-notification delivery <5s after agent completion

**Constraints**: No blocking the main conversation loop; agents run via `asyncio.create_task`

**Scale/Scope**: 2 initial built-in agents (web_browser, generate_video); add new agents in one file

## Constitution Check

*GATE: Must pass before Phase 0 research.*

No constitution file configured — gates automatically pass.

## Project Structure

### Documentation (this feature)

```text
specs/015-agent-allocate-tool/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A — no external interfaces)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── graph/
│   ├── agents.py           # NEW — Agent registry + handler implementations
│   ├── tools.py            # MODIFY — agent_allocate tool, callback wiring
│   ├── builder.py          # (unchanged)
│   └── nodes/
│       ├── __init__.py     # MODIFY — export NOTIFY_MARK, inject_agent_notification
│       └── ai.py           # MODIFY — mark detection, @-notification routing, tool registration
├── handlers/
│   └── chat.py             # MODIFY — callback registration, matcher storage
└── ...
tests/
└── test_agent_allocate.py  # NEW — unit tests for registry, tool, mark detection
```

**Structure Decision**: Single project (Python plugin). Follows existing `graph/` + `handlers/` pattern. New file `graph/agents.py` follows the separation-of-concerns model already used by `graph/tools.py` and `graph/nodes/`.

## Complexity Tracking

No violations — no tracking needed.
