# Research: Timer Graph Injection

**Feature**: 017-timer-graph-injection
**Date**: 2026-06-28

## Decision 1: Injection Pattern

**Decision**: Mirror `agent_allocate` → `inject_agent_notification` exactly.

**Rationale**: The `inject_agent_notification` function in `graph/nodes/ai.py` already handles the two-path injection (append to human_queue when chatting, start new conversation when not). This pattern is proven and tested. Adding a parallel `inject_timer` function alongside it minimizes risk and keeps the codebase consistent.

**Alternatives considered**:
- New dedicated graph node for timer — rejected: unnecessary complexity; the human_node → ai_node path already handles all message types
- Modify human_node to detect timers — rejected: breaks separation of concerns; detection belongs in ai.py alongside agent detection

## Decision 2: Message Mark Format

**Decision**: Use `__timer__:{user_id}` format (two colon-separated parts vs agent's three parts).

**Rationale**: Timer has no "agent name" component — only the user ID matters for @-mention. The simpler format avoids unnecessary payload while remaining compatible with the mark-prefix detection pattern.

**Alternatives considered**:
- `__timer__:{user_id}:timer` (three-part like agent) — rejected: redundant, no agent name needed
- No mark, just inject as regular message — rejected: breaks @-mention and detect_node routing

## Decision 3: Code Simplification

**Decision**: Remove `_run_timer_agent`, `_save_tools_globals`, `_restore_tools_globals` entirely.

**Rationale**: These functions exist solely to create a standalone agent with isolated tool globals. With graph injection, the existing graph agent handles tool calls naturally — no isolation needed. Removing these eliminates the most fragile part of the timer module.

**Alternatives considered**:
- Keep functions as fallback — rejected: dead code; injection is strictly better
- Merge patterns — rejected: the agent_allocate pattern is clean and self-contained

## Decision 4: Conversation Lifecycle

**Decision**: Timer follows same lifecycle as agent notifications — injected messages prevent conversation end (detect_node check), and the conversation continues naturally after the timer response.

**Rationale**: This is the existing behavior for agent_allocate. Users may want to follow up on timer responses (e.g., "remind me to buy milk" → "where should I buy it?"). Ending the conversation immediately after a timer response would be jarring.
