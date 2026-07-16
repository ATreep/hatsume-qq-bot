# Implementation Plan: 自动回复上下文窗口优化

**Branch**: `006-auto-reply-context-window` | **Date**: 2026-06-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-auto-reply-context-window/spec.md`

## Summary

Modify the auto-reply message assembly logic to split the 30-message context into two distinct layers before passing to the AI model:
- **Current chat** (last N=10 messages): what the bot should directly reply to
- **Historical chat** (up to M=20 messages before current): background context only

The existing `human_node` already supports the "## 历史聊天记录：" / "## 当前聊天记录：" pattern. The change is in the auto-reply trigger path in `user_chat_handle()` — instead of passing all messages to `human_queue`, split them and put history into the auxiliary queue before invoking the LangGraph conversation.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: NoneBot2, LangChain/LangGraph, onebot v11 adapter

**Storage**: N/A (no new storage; config values added to existing config.py)

**Testing**: pytest (existing test framework at `tests/`)

**Target Platform**: Linux server (QQ bot via NoneBot2 + onebot v11)

**Project Type**: chatbot plugin (NoneBot2 plugin)

**Performance Goals**: No additional latency beyond trivial list slicing (< 1ms)

**Constraints**: Must not break the @-triggered conversation flow; must preserve existing auxiliary queue behavior

**Scale/Scope**: 2 files modified (config.py + handlers/chat.py), ~20 lines changed

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status**: ✅ No gates enforced — the project constitution is an uninitialized template. No violations to justify.

Post-design re-check: ✅ Still passes — this is a minimal, focused change that does not introduce new architectural patterns, dependencies, or complexity.

## Project Structure

### Documentation (this feature)

```text
specs/006-auto-reply-context-window/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (N/A — internal change)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── config.py            # ← Add AUTO_REPLY_CURRENT_MSG_COUNT, AUTO_REPLY_HISTORY_MSG_COUNT
├── handlers/
│   └── chat.py          # ← Modify auto-reply message splitting in user_chat_handle()
└── graph/
    └── nodes/
        └── human.py     # (read-only reference — existing pattern reused)
```

**Structure Decision**: Single project (NoneBot2 plugin). Changes are localized to the existing plugin structure. No new directories or modules needed.

## Complexity Tracking

> No violations to justify — constitution is uninitialized.
