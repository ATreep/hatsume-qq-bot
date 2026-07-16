# Quickstart: Timer Graph Injection

**Feature**: 017-timer-graph-injection
**Date**: 2026-06-28

## How It Works

1. User sets a timer: `@初芽 timer 10分钟后 提醒我喝水`
2. APScheduler fires at the scheduled time
3. `_execute_timer` fetches the task, user info, and recent chat context
4. `_inject_timer_to_graph` builds a `__timer__:{user_id}` marked message
5. Message is injected into the conversation graph (human_queue if chatting, starts conversation if idle)
6. The graph processes it: human_node picks it up → detect_node routes to continue → ai_node responds with @-mention

## Files Changed

| File | Change |
|------|--------|
| `timer/executor.py` | Remove `_run_timer_agent` + `_save/_restore_tools_globals`. Add `_inject_timer_to_graph` + `set_timer_conv_callback`. Update `_execute_timer`. |
| `graph/nodes/ai.py` | Add `TIMER_MARK`, `detect_timer_notification()`, `inject_timer()`. Wire into `ai_node` for @-mention. |
| `graph/nodes/detect.py` | Add `detect_timer_notification` check in `chat_end_detect_node`. |
| `graph/nodes/__init__.py` | Export new timer functions. |
| `handlers/chat.py` | Add `_start_conv_for_timer()` callback. Register with executor. |
| `tests/test_timer_injection.py` | New tests for detection and injection. |

## Testing

```bash
# Run timer injection tests
python -m pytest tests/test_timer_injection.py -v

# Run existing timer tests (no regression)
python -m pytest tests/test_timer_store.py -v

# Run all relevant tests
python -m pytest tests/test_timer_injection.py tests/test_timer_store.py tests/test_graph_nodes.py tests/test_conversation.py -v
```

## Rollback

If issues arise, restore the standalone agent:
1. Revert `executor.py` to restore `_run_timer_agent`
2. Remove `TIMER_MARK` detection from `ai.py` and `detect.py`
3. Remove `_start_conv_for_timer` from `chat.py`

Timer storage and APScheduler integration are unchanged, so the core timer infrastructure is unaffected.
