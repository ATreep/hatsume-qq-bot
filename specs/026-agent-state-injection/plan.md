# Implementation Plan: Agent State Prompt Injection

**Branch**: `026-agent-state-injection` | **Date**: 2026-07-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/026-agent-state-injection/spec.md`

## Summary

Remove the `check_agent` tool and its associated `_check_agent_used` flag and dedup gate from `agent_allocate`. Replace the tool's functionality by passively injecting running background agent states into the chat_agent system prompt at each turn, using the same pattern as `build_skill_prompt()`.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: LangChain (`langchain_core`, `langchain.agents`), NoneBot2

**Storage**: In-memory (`_AGENT_STATES` dict in `graph/agents.py`)

**Testing**: pytest

**Target Platform**: Linux server (NoneBot2 runtime)

**Project Type**: QQ bot plugin (NoneBot2 plugin)

**Performance Goals**: N/A — purely structural refactoring; prompt injection cost is negligible (string concatenation)

**Constraints**: Must avoid circular imports between `prompts.py` and `graph/agents.py` (use lazy import)

**Scale/Scope**: 3 production files changed, 2 test files changed. No new files created.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution is in placeholder state (no principles defined). No gates to evaluate. Proceeding.

## Project Structure

### Documentation (this feature)

```text
specs/026-agent-state-injection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks command)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── prompts.py                   # MODIFY: add build_agent_state_prompt()
├── graph/
│   ├── agents.py                # (unchanged — get_running_instances() exists)
│   ├── tools.py                 # MODIFY: remove check_agent, _check_agent_used, dedup gate
│   └── nodes/
│       └── ai.py                # MODIFY: remove check_agent, inject agent state prompt

tests/
├── test_graph_nodes.py          # MODIFY: remove check_agent stub
└── test_agent_allocate.py       # MODIFY: remove TestAgentAllocateDedupGuard
```

**Structure Decision**: No structural changes. Modifications follow existing file organization. The new `build_agent_state_prompt()` function lives in `prompts.py` alongside `build_skill_prompt()` which it mirrors.

## Complexity Tracking

> No violations — constitution is placeholder.
