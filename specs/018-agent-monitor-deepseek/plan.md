# Implementation Plan: Agent Monitor & Deepseek Provider

**Branch**: `019-agent-monitor-deepseek` | **Date**: 2026-06-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/018-agent-monitor-deepseek/spec.md`

## Summary

Add in-memory agent state monitoring with duplicate-allocation prevention, and add Deepseek as a new model provider for code-related tasks. The agent monitor tracks subagent states (idle/running/done) in a process-memory dictionary and exposes a query interface. The Deepseek provider replaces `get_code_model()` internals to route directly to Deepseek's official API via `ChatOpenAI`.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: LangChain (`ChatOpenAI`), NoneBot2, pytest, asyncio

**Storage**: In-memory dict for agent states (no persistence). Config via `.env.prod`.

**Testing**: pytest with `unittest.mock.patch` for env var isolation

**Target Platform**: macOS/Linux server running NoneBot2

**Project Type**: QQ bot plugin (NoneBot2 plugin)

**Performance Goals**: Agent status queries <1s, model instantiation <100ms

**Constraints**: Single-process asyncio event loop, no external dependencies beyond LangChain

**Scale/Scope**: 2 built-in agents (coding_agent, generate_video), 1 new model provider

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No constitution gates defined (template constitution). No violations.

## Project Structure

### Documentation (this feature)

```text
specs/018-agent-monitor-deepseek/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── config.py                    # Modify: add Deepseek constants
├── models.py                    # Modify: rewrite get_code_model()
└── graph/
    ├── agents.py                # Modify: add _AGENT_STATES + state functions
    ├── tools.py                 # Modify: agent_allocate guard + check_agent tool
    └── nodes/
        └── ai.py                # Modify: register check_agent in chat_agent

.env.prod                        # Modify: append DEEPSEEK_API_KEY=

tests/
├── test_deepseek_provider.py    # Create: Deepseek config + get_code_model tests
└── test_agent_monitor.py        # Create: state tracking + tool tests
```

**Structure Decision**: Follow existing project layout. No new directories needed — all changes are modifications to existing files plus two new test files.

## Complexity Tracking

No violations — no justification needed.
