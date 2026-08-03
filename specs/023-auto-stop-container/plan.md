# Implementation Plan: Auto-Stop Docker Container When Idle

**Branch**: `023-auto-stop-container` | **Date**: 2026-07-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/023-auto-stop-container/spec.md`

## Summary

Add a subprocess reference counting mechanism to `infra.py` with a 5-minute asyncio grace timer. When the last active Docker subprocess (from `run_cmd` or `start_background_cmd`) finishes and no new subprocess starts for 5 minutes, the container `hatsume-space` is automatically stopped via `docker stop`. Integration points: `run_cmd` (try/finally), `start_background_cmd` (acquire), `kill_background_cmd` (release), and `cleanup_persistent_container` (cancel timer). A `threading.Lock` protects the refcount since `run_cmd` is synchronous; `_release_subprocess` handles both sync and async contexts via `RuntimeError` fallback.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: stdlib only — `asyncio`, `threading`, `subprocess`, `pathlib`

**Storage**: N/A (all state is in-memory module-level variables)

**Testing**: pytest (existing framework), 13 new test cases across 5 test classes

**Target Platform**: Linux server (macOS for dev), Docker required

**Project Type**: NoneBot2 plugin (QQ chatbot)

**Performance Goals**: Refcount operations <1ms (lock acquire + integer increment/decrement); grace timer resolution ~1s (asyncio.sleep precision)

**Constraints**: Must not break existing `run_cmd`, background shell, or `/resetsandbox` behavior; must be exception-safe (refcount correctness on all error paths)

**Scale/Scope**: ~60 lines added to `infra.py`, ~200 lines new test file, no changes to other modules

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status |
|------|--------|
| Test-First (TDD) | ✅ 13 tests defined before implementation |
| Follow existing patterns | ✅ Uses same package hierarchy setup as existing tests |
| Minimal scope | ✅ Single-file change (`infra.py`) + 1 new test file |
| No new dependencies | ✅ stdlib only |

## Project Structure

### Documentation (this feature)

```text
specs/023-auto-stop-container/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
└── infra.py             # +60 lines: refcount state, 3 helpers, 4 integration points

tests/
└── test_container_lifecycle.py   # New: ~200 lines, 13 test cases
```

**Structure Decision**: Single-file feature — `infra.py` is the only source file modified. Existing project structure followed; new test file mirrors the pattern from `test_background_shell_infra.py`.

## Complexity Tracking

> No violations — all gates pass.
