# Implementation Plan: Extract Links from Markdown-to-Image Messages

**Branch**: `029-extract-links-md-to-image` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/029-extract-links-md-to-image/spec.md`

## Summary

When `auto_convert_text` renders a message as an image (long text or Markdown-rich content), extract all URLs from the original text and append a formatted follow-up text message listing them under a "LINKS" header. Change the function's return type from `MessageSegment` to `list[MessageSegment]` and update both call sites to iterate the list.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: `re` (stdlib), `markdown` (existing), `anyio` (existing)

**Storage**: N/A

**Testing**: pytest (project standard, `tests/`)

**Target Platform**: Linux server (NoneBot2 + OneBot V11)

**Project Type**: QQ bot plugin (NoneBot2 plugin)

**Performance Goals**: Negligible overhead — regex extraction + string formatting on messages ~hundreds of chars

**Constraints**: Must not block the async event loop; link extraction is synchronous and trivial

**Scale/Scope**: 3 files changed, ~50 lines net new code

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution is a template (no project-specific principles defined). Refer to `CLAUDE.md` for project conventions. All conventions satisfied:

- Python 3.12+ with `from __future__ import annotations`
- Type annotations on all new functions
- snake_case naming
- `# ----` section separators
- ruff linting compatible

**Gate: PASS** — no violations.

## Project Structure

### Documentation (this feature)

```text
specs/029-extract-links-md-to-image/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── utils/
│   └── md_to_image.py          # MODIFY: add _extract_links, _format_links, change return type
├── graph/nodes/
│   └── ai.py                   # MODIFY: iterate list return, send each segment
└── handlers/
    └── chat.py                 # MODIFY: iterate list return, send each segment

tests/
└── test_md_to_image.py         # CREATE: unit tests for new helpers + integration tests
```

**Structure Decision**: No new files in production code. Existing module structure unchanged. Single new test file following project conventions.

## Complexity Tracking

No violations to justify.
