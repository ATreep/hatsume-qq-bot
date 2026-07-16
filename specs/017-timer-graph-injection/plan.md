# Implementation Plan: Timer Graph Injection

**Branch**: `017-timer-graph-injection` | **Date**: 2026-06-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/017-timer-graph-injection/spec.md`

## Summary

Replace the standalone `_run_timer_agent` in `timer/executor.py` with a graph injection pattern that mirrors the existing `agent_allocate` → `inject_agent_notification` flow. When a timer fires, build a `__timer__:{user_id}` marked message and inject it into the conversation graph. The existing LangGraph handles everything — human_node picks it up, detect_node routes to continue, ai_node @-mentions the timer creator.

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2, LangGraph (MessagesState), LangChain (ChatOpenAI, create_agent), APScheduler, OneBot V11 adapter

**Storage**: SQLite (timer_triggers/timer_tasks — unchanged schema)

**Testing**: pytest, ruff

**Target Platform**: Linux server (QQ bot via NoneBot2)

**Project Type**: NoneBot2 plugin (QQ group chat bot)

**Performance Goals**: Timer delivery within 30s of trigger; no regression on normal conversation response time

**Constraints**: Must not create a standalone chat agent; must reuse existing graph infrastructure; must use same injection pattern as agent_allocate

**Scale/Scope**: Single plugin module change (~5 files, net -40 lines of code)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No constitution gates defined (template only). Proceeding.

## Project Structure

### Documentation (this feature)

```text
specs/017-timer-graph-injection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A — internal module)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── timer/
│   └── executor.py      # Replace _run_timer_agent with _inject_timer_to_graph
├── graph/
│   └── nodes/
│       ├── ai.py         # Add TIMER_MARK, detect_timer_notification, inject_timer
│       ├── detect.py     # Add timer notification check
│       └── __init__.py   # Export new timer functions
└── handlers/
    └── chat.py           # Add _start_conv_for_timer callback + wiring

tests/
└── test_timer_injection.py  # New tests for timer detection + injection
```

**Structure Decision**: Following existing project layout. No new directories or packages needed — all changes are within the existing `hatsume/plugins/hatsume-plugin/` module structure.

## Complexity Tracking

> No constitution violations. This change simplifies the codebase (removes ~100 lines of standalone agent, adds ~30 lines of injection). No complexity tracking needed.
