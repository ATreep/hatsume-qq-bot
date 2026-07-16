# Quickstart: Agent Notification Detection Skip

**Feature**: 016-agent-notify-detect-skip
**Date**: 2026-06-26

## Overview

When a dispatched agent (via `agent_allocate`) completes and injects its result into the conversation, the chat end-detection node now skips its normal "should we end?" logic and always routes to the AI response node. This prevents agent results from being lost due to premature conversation termination.

## How It Works

1. `detect_agent_notification(state)` scans the last message for `__agent_notify__` prefix
2. If found → `chat_end_detect_node` returns `{"messages": []}` (continue)
3. If not found → normal detection logic runs unchanged

## Verification

```bash
# Run the new tests
python -m pytest tests/test_graph_nodes.py -k "test_detect_agent_notification or test_chat_end_detect_node_skips" -xvs

# Run full suite for regressions
python -m pytest tests/ -xvs
```

## Files Changed

| File | Change |
|------|--------|
| `graph/nodes/ai.py` | Add `detect_agent_notification()`; refactor `ai_node` |
| `graph/nodes/detect.py` | Import + early-return guard |
| `graph/nodes/__init__.py` | Export new function |
| `tests/test_graph_nodes.py` | 4 new test functions |
