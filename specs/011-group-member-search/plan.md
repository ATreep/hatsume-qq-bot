# Implementation Plan: Group Member Fuzzy Search

**Branch**: `011-group-member-search` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/011-group-member-search/spec.md`

## Summary

Add fuzzy group member search as both an LLM-callable tool and a `/membersearch` slash command. Core search logic lives in `utils.py`, shared by both interfaces. Two-pass matching: substring-first, character-overlap fallback, max 5 results. 300s TTL member list cache per group.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2 (aiohttp + FastAPI), OneBot V11 adapter, LangGraph, LangChain OpenAI

**Storage**: In-memory TTL cache (module-level dict in utils.py); no persistent storage

**Testing**: pytest (with importlib.module_from_spec stub pattern)

**Target Platform**: Linux server (NoneBot2 bot runtime)

**Project Type**: QQ bot plugin (NoneBot2 plugin)

**Performance Goals**: `/membersearch` responds within 3 seconds; member list cached for 300s

**Constraints**: Max 5 results; single tool call per conversation turn

**Scale/Scope**: Single group at a time; groups typically <500 members

## Constitution Check

Constitution template is unfilled (all placeholders) — no gates to enforce. PASS by default.

## Project Structure

### Documentation

```text
specs/011-group-member-search/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code

```text
hatsume/plugins/hatsume-plugin/
├── utils.py             # + search_group_members() core function + cache
├── graph/tools.py       # + membersearch @tool
├── handlers/commands.py # + handle_membersearch() handler
└── __init__.py          # + on_command("membersearch") registration

tests/
└── test_membersearch.py # New test file
```

**Structure Decision**: Single project structure following existing plugin layout. No new directories.

## Complexity Tracking

No constitution violations.
