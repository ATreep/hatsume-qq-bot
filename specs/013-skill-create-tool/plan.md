# Implementation Plan: Skill Create Tool

**Branch**: `013-skill-create-tool` | **Date**: 2026-06-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-skill-create-tool/spec.md`

## Summary

Add a `skill_create` tool to the chat agent that accepts raw skill markdown content (with YAML frontmatter), parses `name` and `description` from the frontmatter, and saves the file to `data/hatsume-plugin/skills/`. The tool delegates to a new `save_skill()` method on the existing `SkillManager`, reusing `parse_frontmatter_text()` for validation.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: LangChain (@tool decorator, create_agent), NoneBot2, PyYAML

**Storage**: Filesystem — `data/hatsume-plugin/skills/{name}.md`

**Testing**: pytest

**Target Platform**: NoneBot2 bot server (Linux/macOS)

**Project Type**: Plugin (NoneBot2 plugin)

**Performance Goals**: Tool invocation <100ms (simple file write)

**Constraints**: Must not break existing skill tools (`skill_download`, `skill_loader`, `skill_remove`)

**Scale/Scope**: Single new tool + one new method on SkillManager

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No constitution principles defined — all gates pass by default.

## Project Structure

### Documentation (this feature)

```text
specs/013-skill-create-tool/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A — no external interfaces)
└── tasks.md             # Phase 2 output (speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── skills/
│   └── manager.py           # ADD save_skill() method
├── graph/
│   ├── tools.py             # ADD skill_create @tool
│   └── nodes/
│       └── ai.py            # IMPORT skill_create, ADD to chat agent tools

tests/
└── test_skill_create.py     # NEW — unit tests
```

**Structure Decision**: Follows existing plugin structure — tools in `graph/tools.py`, skill management in `skills/manager.py`, agent registration in `graph/nodes/ai.py`.

## Complexity Tracking

No violations — feature follows existing patterns exactly.
