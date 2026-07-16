# Implementation Plan: Agent Dispatch Context

**Branch**: `028-agent-dispatch-context` | **Date**: 2026-07-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/028-agent-dispatch-context/spec.md`

## Summary

Add a `context` parameter to the subagent dispatch tool (`agent_dispatch`, renamed from `agent_allocate`) so the main chat agent can record why a subagent was dispatched. Context is stored in the existing in-memory agent instance state and injected back into the conversation when the subagent completes. A global rename of `agent_allocate` → `agent_dispatch` is performed across all project files.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: LangChain (tools, agents), LangGraph (StateGraph), asyncio

**Storage**: In-memory (existing `_AGENT_STATES` dict in `agents.py`)

**Testing**: pytest (existing test suite)

**Target Platform**: Linux server (NoneBot2 + OneBot V11)

**Project Type**: QQ bot plugin (NoneBot2 plugin)

**Performance Goals**: N/A (string parameter addition, no perf impact)

**Constraints**: Must not break existing agent dispatch flow; must pass existing test suite

**Scale/Scope**: 4 source files modified, ~10 test/reference files updated

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No constitution gates defined — project constitution is template-only. Proceeding.

## Project Structure

### Documentation (this feature)

```text
specs/028-agent-dispatch-context/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── graph/
│   ├── agents.py          # MODIFY: add get_agent_context(), store context in state
│   ├── tools.py           # MODIFY: rename agent_allocate→agent_dispatch, add context param
│   └── nodes/
│       └── ai.py          # MODIFY: inject_agent_notification context param, import rename
├── prompts.py             # MODIFY: agent_allocate→agent_dispatch in prompt text
└── timer/
    └── executor.py        # MODIFY: comment rename

tests/
├── test_agent_dispatch.py # RENAME from test_agent_allocate.py + add context tests
├── test_graph_nodes.py    # MODIFY: agent_allocate→agent_dispatch
├── test_timer_injection.py # MODIFY: agent_allocate→agent_dispatch
└── test_background_shell_agent.py # MODIFY: comment rename

CLAUDE.md                  # MODIFY: any agent_allocate references
```

**Structure Decision**: Follows existing project layout. No new files created; only modifications to existing files.

## Complexity Tracking

> No violations. Feature is a parameter addition + rename — simplest possible implementation.
