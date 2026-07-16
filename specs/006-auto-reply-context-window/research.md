# Research: 自动回复上下文窗口优化

**Feature**: 006-auto-reply-context-window
**Date**: 2026-06-04

## Research Items

### 1. Where does auto-reply message assembly happen?

**Decision**: The auto-reply trigger and message assembly happens in `handlers/chat.py:user_chat_handle()`, lines 146-167.

**Rationale**: This is the only code path where `idle_queue` flush triggers an auto-reply via `start_new_conversation()`. The @-triggered flow (lines 170+) is a separate path that already correctly separates idle history (via `flush_idle=True`) from current pending messages.

**Alternatives considered**:
- Modifying `start_new_conversation()` to accept separate history/current params — rejected because it would add complexity to a function also used by the @-triggered flow, which already handles context separation correctly.
- Modifying `human_node` to do the splitting — rejected because `human_node` is a generic node used by both auto-reply and @-triggered flows; it should remain a simple message assembler.

### 2. How does the existing "## 历史聊天记录" / "## 当前聊天记录" pattern work?

**Decision**: The `human_node` in `graph/nodes/human.py` already implements this pattern. When `auxiliary_messages_queue` is non-empty, it prepends them as "## 历史聊天记录：" before the `human_queue` messages marked as "## 当前聊天记录：". The split is already visually distinct for the AI.

**Rationale**: We can reuse this existing mechanism without modifying `human_node` at all. Simply populate `auxiliary_messages_queue` with history messages before `start_new_conversation()` puts current messages into `human_queue`.

**Alternatives considered**:
- Adding new markers or a different split format — rejected because the existing pattern is already established and works.

### 3. What are the correct default values for N (current) and M (history)?

**Decision**: N=10 (current messages), M=20 (history messages). Total = 30, matching the existing `CONTEXT_QUEUE_LEN`.

**Rationale**: The user explicitly specified these values. They provide:
- 10 messages of focused context for direct reply targeting
- 20 messages of background for understanding conversation flow
- Total of 30 matches existing queue size, so no change to trigger behavior

**Alternatives considered**:
- N=5, M=25 — too little current context for meaningful replies
- N=15, M=15 — dilutes the focus on recent messages
- Dynamic sizing based on message timestamps — adds complexity without clear benefit for v1

### 4. How should edge cases be handled?

**Decision**:
- When total messages < N: all messages go to current, no history
- When total messages < N+M: prioritize current (N), remaining go to history
- Non-text messages (images, forwards) count as 1 message each

**Rationale**: These match the edge cases defined in the spec. The priority rule (current first) ensures the bot always has something recent to reply to.

### 5. Should config values be in config.py or environment variables?

**Decision**: Add to `config.py` as module-level constants, consistent with existing constants like `CONTEXT_QUEUE_LEN` and `CONTEXT_QUEUE_OVERLAP_LEN`.

**Rationale**: All behavioral constants in this project are defined in `config.py`. Environment variables are only used for secrets and provider configuration. Consistency with existing patterns is preferred.

**Alternatives considered**:
- Environment variables — rejected because these are tuning parameters, not secrets or deployment-specific config
- Runtime-configurable via commands — could be a future enhancement, out of scope for v1
