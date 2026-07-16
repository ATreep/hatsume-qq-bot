# Implementation Plan: Random ACG Photo Tool

**Branch**: `030-random-acg-photo-tool` | **Date**: 2026-07-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/030-random-acg-photo-tool/spec.md`

## Summary

Add an LLM-callable `random_acg_photo` tool to the NoneBot2 QQ chatbot. The tool uses `osascript` to export a random photo from the Apple Photos "ACG" album to a macOS temp directory, copies it to the Docker sandbox container with `docker cp`, and returns the sandbox absolute path. The existing `send_image` tool handles delivery. Two files modified: `tools.py` (tool definition ~60 lines) and `ai.py` (import + registration 2 lines).

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, LangChain/LangGraph (existing), subprocess (stdlib), osascript (macOS built-in)

**Storage**: N/A (stateless tool, transient filesystem usage in /tmp)

**Testing**: pytest (existing framework, test_tools.py patterns)

**Target Platform**: macOS (host) + Linux Docker sandbox (container)

**Project Type**: NoneBot2 plugin (QQ chatbot)

**Performance Goals**: Photo export → send under 15 seconds end-to-end; error responses under 5 seconds

**Constraints**: No new Python dependencies; must use existing `ensure_container_running()` and `send_image` infrastructure

**Scale/Scope**: Single tool, ~60 lines of implementation, 4 test cases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution template is unfilled — no project-specific gates. Proceeding with standard quality expectations:
- Follows existing code patterns (task 1 in existing tools.py, task 2 in existing ai.py)
- TDD: tests written first, implementation second
- No new dependencies
- No architectural changes

## Project Structure

### Documentation (this feature)

```text
specs/030-random-acg-photo-tool/
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
│   ├── tools.py              # MODIFY: add random_acg_photo @tool
│   └── nodes/
│       └── ai.py             # MODIFY: import + register in chat_agent
└── config.py                 # (read CONTAINER_NAME, no changes)

tests/
└── test_random_acg_photo.py  # CREATE: 4 test cases
```

**Structure Decision**: Follows existing project layout. Tool added to existing `tools.py` (not a new file) to match all other tools. Tests in dedicated file per existing pattern.

## Complexity Tracking

No violations. Feature adds one tool function to existing files — the simplest possible change that achieves the goal.
