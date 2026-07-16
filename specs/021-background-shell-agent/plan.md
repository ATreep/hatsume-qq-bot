# Implementation Plan: Background Shell Agent

**Branch**: `021-background-shell-agent` | **Date**: 2026-06-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/021-background-shell-agent/spec.md`

## Summary

Add a `background_shell` built-in agent that executes interactive or time-consuming shell commands in the background. The agent spawns processes with output redirected to a tmp file, polls periodically using the code model to decide next actions (DONE/KILL/CONTINUE:N/NOTIFY:N), and can inject mid-progress output into the main conversation without stopping itself. All existing agent infrastructure (`agent_allocate`, `_AGENT_STATES`, `inject_agent_notification`, `/agents` command) is reused zero-change. Three files are modified: `prompts.py`, `infra.py`, and `graph/agents.py`.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, LangGraph, LangChain (ChatOpenAI), subprocess, asyncio

**Storage**: Tmp files for process output (transient, no persistence)

**Testing**: pytest + unittest.mock

**Target Platform**: Linux server (Docker sandbox for shell execution)

**Project Type**: QQ chat bot plugin (NoneBot2 plugin)

**Performance Goals**: Poll intervals as low as 15s; command output relayed within one poll cycle (~60s max for auth URL)

**Constraints**: No blocking of main conversation graph; zero changes to existing agent infrastructure

**Scale/Scope**: Single background_shell instance at a time (non-concurrent per agent); 3 files changed

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No constitution principles defined — project constitution is in template placeholder state. All gates pass by default.

## Project Structure

### Documentation (this feature)

```text
specs/021-background-shell-agent/
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
├── prompts.py           # +BACKGROUND_SHELL_DECISION_PROMPT
├── infra.py             # +start_background_cmd, +read_background_output, +kill_background_cmd
└── graph/
    └── agents.py        # +_run_background_shell handler, +register_agent("background_shell", ...)

tests/
├── test_background_shell_infra.py      # New: infra function tests
└── test_background_shell_agent.py      # New: agent handler tests
```

**Structure Decision**: Single-project structure following existing NoneBot2 plugin layout. Three existing files modified in-place; two new test files added.

## Complexity Tracking

> No constitution violations exist — this section is intentionally blank.
