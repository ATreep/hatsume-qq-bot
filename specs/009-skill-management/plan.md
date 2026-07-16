# Implementation Plan: Skill Management System

**Branch**: `009-skill-management` | **Date**: 2026-06-08 | **Updated**: 2026-06-09 — Added `/skills` command, `skill_download`, unlimited invocation | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-skill-management/spec.md`

## Summary

Add a skill management subsystem that lets operators extend the bot's LLM capabilities by dropping Anthropic-style markdown skill files into a directory. A `SkillManager` class scans, caches, loads, and removes skills. Three new LangChain tools (`skill_loader`, `skill_remove`, `skill_download`) are registered in the chat agent. A new `/skills` NoneBot command lets users list available skills. A whitelist mechanism exempts utility tools from the single-invocation restriction.

**New in this update (2026-06-09)**:
- `/skills` command (US4): Any user can list available skills via NoneBot command
- `skill_download` tool (US5): Download skills from raw URLs into the skills directory
- Unlimited tool invocation whitelist (US6): Utility tools bypass `check_tool_call` restriction

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, LangGraph (`create_agent`), LangChain Core (`@tool`), PyYAML (frontmatter parsing), pathlib (file I/O), `urllib.request` or `httpx` (HTTP download for `skill_download`)

**Storage**: Filesystem (`.md` files in `data/hatsume-plugin/skills/`) + in-memory dict cache

**Testing**: pytest

**Target Platform**: Linux server (NoneBot2 runtime, fish shell)

**Project Type**: NoneBot2 plugin sub-module

**Performance Goals**: `load_skill()` returns full content in <100ms for files <10KB; `list_skills()` (frontmatter scan of 50 files) <50ms; `/skills` command returns in <500ms; `skill_download` completes in <10s for files <50KB

**Constraints**: In-memory only (no database); global scope (all groups share skills); singleton pattern

**Scale/Scope**: ~50 skill files expected; each <50KB typical, no hard limit enforced

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution template not yet filled — no project-specific gates apply. Standard quality practices apply:
- Tests written before/alongside implementation (pytest)
- Follow existing module patterns (timer/ sub-package)
- Minimal changes to existing files

## Project Structure

### Documentation (this feature)

```text
specs/009-skill-management/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── skill-tools-api.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── skills/                   # (existing) sub-package
│   ├── __init__.py           # Exports SkillManager, get_skill_manager()
│   └── manager.py            # SkillManager class — MODIFY: expose cache clear method
├── handlers/
│   └── commands.py           # MODIFY: add handle_list_skills()
├── __init__.py               # MODIFY: register skills_cmd matcher + handler
├── graph/
│   ├── nodes/
│   │   ├── ai.py             # MODIFY: add skill_download to agent tools
│   │   └── finish.py         # (unchanged, already calls reset_conversation)
│   └── tools.py              # MODIFY: add skill_download tool, add _UNLIMITED_TOOLS whitelist

data/hatsume-plugin/
└── skills/                   # (existing) directory
    └── *.md                  # Skill files

tests/
└── test_skill_manager.py     # MODIFY: add tests for skill_download, /skills command, unlimited invocation
```

**Structure Decision**: All new additions integrate into existing files following established patterns. The `/skills` command follows `handle_timer`'s pattern in `handlers/commands.py`. The `skill_download` tool follows the `skill_loader` pattern in `graph/tools.py`. The unlimited whitelist is a minimal set addition in `tools.py`.

## Complexity Tracking

No violations. These additions follow existing patterns (timer/ for commands, skill_loader/ for tools) and add minimal surface area.
