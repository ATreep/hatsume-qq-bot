# Implementation Plan: Agent Allocate Deduplication Guard

**Branch**: `024-agent-allocate-dedup-guard` | **Date**: 2026-07-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/024-agent-allocate-dedup-guard/spec.md`

## Summary

Add a guard in the `agent_allocate` tool that checks whether an agent of the same name already has a running instance. If so, refuse the allocation unless the LLM has already called `check_agent` in the same turn. This prevents accidental duplicate agent creation.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: LangChain (langchain_core.tools), existing `graph/agents.py` module

**Storage**: In-memory only (`_AGENT_STATES` dict, `_check_agent_used` flag) — no persistent storage changes

**Testing**: pytest (existing `tests/test_agent_allocate.py`)

**Target Platform**: Linux server (NoneBot2 runtime)

**Project Type**: QQ chat bot plugin (NoneBot2)

**Performance Goals**: N/A (guard adds only a dict lookup + boolean check, sub-microsecond overhead)

**Constraints**: Must not break existing agent allocation flow; must follow existing tool conventions (Chinese error messages, print-debugging pattern)

**Scale/Scope**: Single tool modification (~10 lines added), ~3 new test cases

## Constitution Check

*Constitution template has no project-specific gates — no violations.*

No constitution gates applicable to this feature.

## Project Structure

### Documentation (this feature)

```text
specs/024-agent-allocate-dedup-guard/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/graph/
├── tools.py             # [MODIFY] Add import + guard block in agent_allocate
└── agents.py            # [READ-ONLY] is_agent_running() already exists

tests/
└── test_agent_allocate.py  # [MODIFY] Add TestAgentAllocateDedupGuard class
```

**Structure Decision**: Single-project layout matching existing codebase. No new files created — only modifications to `tools.py` and `test_agent_allocate.py`.

## Complexity Tracking

No violations. Change is a single guard condition added to an existing function.
