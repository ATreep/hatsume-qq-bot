# Implementation Plan: Simplify Plugin Architecture

**Branch**: `032-simplify-plugin-arch` | **Date**: 2026-07-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/032-simplify-plugin-arch/spec.md`

## Summary

Pure structural refactor of the hatsume-plugin codebase: merge tightly-coupled modules in `handlers/` (7→4 files) and `memory/` (5→3 files), remove ~300 lines of dead code (22 constants, 11 functions, 6 TypedDicts, 6 state paths), consolidate 2 redundant patterns, and update all import sites + test stubs to new module paths. Zero logic changes. All 280 tests must pass.

**Companion implementation plan**: `docs/superpowers/plans/2026-07-15-merge-handlers-memory.md` (16 bite-sized tasks with exact commands).

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, LangGraph, LangChain OpenAI, volcenginesdkarkruntime, jieba, rank-bm25, numpy, pytest, ruff

**Storage**: SQLite (memory.db, timer.db), JSON (likes.json). No schema changes — only code structure changes.

**Testing**: pytest (~280 tests across 25 files, restored from git HEAD)

**Target Platform**: Linux/macOS server running NoneBot2 via OneBot V11

**Project Type**: NoneBot2 plugin (QQ chatbot)

**Performance Goals**: No change — refactor is structural only. Import-time overhead slightly reduced (fewer modules to load, fewer lazy imports).

**Constraints**: Zero logic changes. All 280 tests pass. `ruff check` clean. Module import ordering critical (dependencies before consumers in merged files).

**Scale/Scope**: ~2,600 lines of production code affected. 12→7 files in handlers+memory. 11 import sites updated. ~78 test stub paths rewritten.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution is a template (not customized). No explicit principles to gate on. This refactor is inherently compliant with standard software engineering principles:

| Principle | Compliance |
|-----------|-----------|
| **Test-First (implicit)** | Tests restored from HEAD, all 280 must pass after refactor |
| **Simplicity (YAGNI)** | 300 lines of dead code removed; module count halved |
| **No behavior changes** | Pure structural refactor — identical runtime behavior |
| **Code quality** | `ruff check` clean after refactor |

**Gate result**: PASS — no violations, no complexity to justify.

## Project Structure

### Documentation (this feature)

```text
specs/032-simplify-plugin-arch/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── tasks.md             # Phase 2 output (/speckit-tasks)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── __init__.py              # Event router (import paths updated)
├── config.py               # Constants (22 dead removed, ocgo provider removed)
├── models.py               # LLM/Image/Video factories (1 dead function removed)
├── state.py                # ConversationState (6 dead TypedDicts removed, last_image_time removed)
├── prompts.py              # System prompts (4 dead functions removed)
├── infra.py                # Docker sandbox (1 dead function removed)
├── handlers/
│   ├── __init__.py          # Thin facade
│   ├── dialogue.py          # NEW: chat + pipeline + forward (~720 loc)
│   ├── tools.py             # NEW: commands + poke (~432 loc)
│   └── social.py            # NEW: likes renamed (83 loc)
├── memory/
│   ├── __init__.py          # Thin facade
│   ├── engine.py            # NEW: db + store + retrieval (~600 loc)
│   └── tokenizer.py         # jieba tokenizer (unchanged)
├── graph/
│   ├── builder.py           # StateGraph (unchanged)
│   ├── nodes.py             # Graph nodes (import paths updated, 1 dead function removed)
│   ├── agents.py            # Agent registry (unchanged)
│   └── tools.py             # LLM tools (dead state removed)
├── timer/
│   ├── __init__.py          # Scheduler init (commented-out call removed)
│   ├── executor.py          # Task executor (1 dead function removed)
│   └── store.py             # SQLite store (2 dead methods removed, dead branch removed)
├── utils/
│   ├── __init__.py          # QQ message utilities
│   └── md_to_image.py       # Markdown rendering
└── skills/
    ├── __init__.py
    └── manager.py           # Skill download/install
```

**Structure Decision**: The existing plugin structure is preserved. The refactor only changes module names and internal organization within `handlers/` and `memory/`. No new directories, no file relocations outside the affected packages.

## Complexity Tracking

No violations to justify. The refactor *reduces* complexity: fewer files, fewer imports, fewer dead code paths, zero circular dependencies in the memory engine.

## Implementation Tasks Reference

The detailed implementation plan at `docs/superpowers/plans/2026-07-15-merge-handlers-memory.md` contains 16 tasks organized as:

| Phase | Tasks | Description |
|-------|-------|-------------|
| Setup | 1 | Restore tests from git HEAD |
| Dead code removal | 2-10 | Remove 22 constants, 6 TypedDicts, 11 functions, 6 state paths (parallelizable) |
| Consolidation | 11 | Merge `_start_conv_for_agent` + `_start_conv_for_timer` |
| Module merge | 12-13 | Create dialogue.py, tools.py, social.py, engine.py |
| Import update | 14 | Update 11 production import sites |
| Test update | 15 | Rewrite ~78 test stub paths |
| Verification | 16 | Run full test suite, fix issues, lint |

Tasks 2-10 are independent and can run in parallel. Tasks 11→12→14→15→16 form a serial chain.
