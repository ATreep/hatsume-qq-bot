# Implementation Plan: Background Shell Stdin Injection

**Branch**: `022-bg-shell-stdin-injection` | **Date**: 2026-06-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/022-bg-shell-stdin-injection/spec.md`

## Summary

Add stdin injection capability to the existing background_shell agent. When a background shell process needs interactive input (passwords, auth tokens, confirmations), the agent detects the prompt, notifies the chat agent, receives raw input via a new `respond_to_shell_prompt` tool bridged through `asyncio.Queue`, and uses the code model to mediate between the chat agent's raw text and the actual stdin bytes written to the process. Supports configurable timeouts with code-model-decided fallback behavior (auto-answer safe defaults, re-issue, or kill).

## Technical Context

**Language/Version**: Python 3.12+ with `from __future__ import annotations`

**Primary Dependencies**: NoneBot2 (QQ bot framework), LangGraph (conversation state machine), LangChain (tool/@tool definitions), asyncio (stdlib, Queue for stdin bridging), subprocess (stdlib, PIPE for stdin channel)

**Storage**: In-memory only — `asyncio.Queue[str | None]` per stdin request, module-level `_stdin_queues: dict[str, asyncio.Queue]`. No persistent storage needed.

**Testing**: pytest with `tests/test_background_shell_stdin.py` (unit), `tests/test_background_shell_prompts.py` (prompt validation), `tests/test_background_shell_stdin_integration.py` (integration), `tests/test_tools.py::TestRespondToShellPrompt` (tool)

**Target Platform**: Linux server (Docker sandbox via `launch_image.sh`, OneBot V11 QQ protocol)

**Project Type**: QQ chatbot plugin (NoneBot2 plugin)

**Performance Goals**: Stdin request delivery to chat within 5 seconds of prompt detection; stdin write completes in <100ms after receiving input

**Constraints**: Single background_shell agent instance at a time; default stdin timeout 300 seconds; subprocess stdin must have trailing `\n` appended if missing; UTF-8 encoding for all stdin writes

**Scale/Scope**: Single background shell per agent invocation; one stdin request active at a time (sequential by nature); extends 5 existing source files (~380 lines total change)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution template is not populated (all placeholders). No gates to enforce. The feature follows existing project patterns:
- Uses existing module structure (infra.py, prompts.py, agents.py, tools.py, ai.py)
- Follows existing tool/@tool pattern from `graph/tools.py`
- Matches existing agent notification pattern from `graph/nodes/ai.py`
- Uses existing testing patterns from `tests/test_background_shell_infra.py`

## Project Structure

### Documentation (this feature)

```text
specs/022-bg-shell-stdin-injection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── infra.py                         # MODIFY: start_background_cmd() adds stdin=PIPE
├── prompts.py                       # MODIFY: extend decision prompt + add resolution prompt
├── graph/
│   ├── agents.py                    # MODIFY: _stdin_queues, _write_stdin, _cleanup_stdin_queues, INPUT_NEEDED in poll loop
│   ├── tools.py                     # MODIFY: new respond_to_shell_prompt @tool
│   └── nodes/
│       └── ai.py                    # MODIFY: register respond_to_shell_prompt in chat_agent tools

tests/
├── test_background_shell_infra.py   # (existing, no changes needed)
├── test_background_shell_prompts.py # NEW
├── test_background_shell_stdin.py   # NEW
├── test_background_shell_stdin_integration.py  # NEW
└── test_tools.py                    # MODIFY: add TestRespondToShellPrompt
```

**Structure Decision**: No new modules or directories. Feature is an extension of the existing background_shell agent, fitting into the current 5-file module structure. All new tests follow the existing test file naming convention.

## Complexity Tracking

> No constitution violations. This feature extends an existing agent within the established module boundaries.


