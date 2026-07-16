# Implementation Plan: Consolidate LLM Prompts

**Branch**: `012-consolidate-llm-prompts` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-consolidate-llm-prompts/spec.md`

## Summary

Relocate all 15 LLM prompt strings currently scattered across 7 files into `prompts.py` as named constants and parameterized builder functions. Pure refactoring — zero behavioral change. Each consumer file removes its inline prompt definition and imports the centralized version instead.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: langchain_core (SystemMessage, HumanMessage), NoneBot2

**Storage**: N/A (no data layer changes)

**Testing**: pytest

**Target Platform**: Linux server (QQ bot runtime)

**Project Type**: QQ bot plugin (NoneBot2 plugin)

**Performance Goals**: No change — identical runtime behavior

**Constraints**: Zero behavioral change; all existing tests must pass; ruff lint must be clean

**Scale/Scope**: 8 files modified (~15 prompts relocated)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution template not yet populated — no active gates to validate. **PASS** (no violations).

## Project Structure

### Documentation (this feature)

```text
specs/012-consolidate-llm-prompts/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # N/A — no new interfaces
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── prompts.py                   # MODIFY: add 15 prompt definitions
├── config.py                    # No change
├── state.py                     # No change
├── graph/
│   ├── nodes/
│   │   ├── ai.py                # MODIFY: replace 3 inline prompts
│   │   ├── detect.py            # MODIFY: replace 1 inline prompt
│   │   ├── finish.py            # MODIFY: replace 1 inline prompt
│   │   └── human.py             # No change
│   ├── builder.py               # No change
│   └── tools.py                 # MODIFY: replace 5 inline prompts
├── handlers/
│   ├── chat.py                  # No change (imports role_sys_prompt already)
│   ├── commands.py              # No change
│   ├── likes.py                 # MODIFY: replace 2 inline prompts
│   ├── night_comic.py           # MODIFY: replace 2 inline prompts
│   └── pipeline.py              # No change
├── memory/                      # No change
├── skills/                      # No change
└── timer/
    └── executor.py              # MODIFY: replace 3 inline prompts
```

**Structure Decision**: Following existing single-project structure. No new files created — only modifications to existing files.

## Complexity Tracking

No violations to justify.
