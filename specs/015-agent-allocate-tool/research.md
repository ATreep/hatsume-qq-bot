# Research: Agent Allocate Tool

**Date**: 2026-06-26

## Decisions

### 1. Agent Registry Architecture

**Decision**: Module-level `dict` registry in `graph/agents.py` with `register_agent()` calls at module bottom.

**Rationale**: Zero startup cost, no external dependencies. Registration at import time means the registry is always populated before any tool uses it. Follows the project's existing pattern of module-level configuration (e.g., `configure_tool_callbacks` in `tools.py`).

**Alternatives considered**:
- Class-based registry with decorator registration — more ceremony for identical functionality
- External config file (YAML/JSON) — unnecessary for 2 built-in agents; adds file I/O
- Dynamic plugin discovery — overengineered for current scope

### 2. Tool Description Injection

**Decision**: f-string in `@tool(description=f"...{_AGENT_LIST_STR}")` evaluated at module import.

**Rationale**: Simple, zero-runtime-overhead. The agent list is static at runtime (no hot-reloading of built-in agents). If new agents are added to `agents.py`, they appear in the description on next restart.

**Alternatives considered**:
- Dynamic description via `StructuredTool.from_function()` — adds complexity, rebuilds tool object each time
- Inject via system prompt instead of tool description — tool description is the standard LangChain mechanism

### 3. Notification Mechanism

**Decision**: `__agent_notify__:<user_id>:<agent_name>` prefix in human_queue messages. Detected in `ai_node` by reverse-scanning the last message's content list. Last mark wins when multiple exist.

**Rationale**: Simple string prefix — no new data structures needed. Reverse scan + break ensures the last (most recent) notification takes priority. The SYSTEM prompt prefix tells the LLM to relay results naturally.

**Alternatives considered**:
- Separate metadata field — requires changing message format across all nodes
- Direct callback to `ai_answer_with_at` — bypasses the LLM's ability to contextualize the result

### 4. Idle-State Agent Notification

**Decision**: Store last known `user_chat_matcher` in chat.py module-level variable. Register a callback with `tools.py` via `configure_agent_notification_callback()`. When `is_chatting=False`, start a new conversation via `start_new_conversation()`.

**Rationale**: Uses existing `start_new_conversation` infrastructure. Matcher persists beyond event handling (NoneBot matchers don't expire). Falls back gracefully if no matcher is available.

**Alternatives considered**:
- Use `nonebot.get_bot().send_group_msg()` directly — bypasses conversation context entirely
- Skip notification when not chatting — violates FR-009

### 5. Agent Handler Signature

**Decision**: `async def handler(task: str, user_id: int) -> str` — returns the agent's output text.

**Rationale**: Task string comes from LLM (the `task` parameter of `agent_allocate`). User ID is passed through for potential future use (e.g., accessing user-specific data). Async because agents do I/O (network requests, API calls).

**Alternatives considered**:
- Return structured dict with status/success fields — overkill; string allows the LLM to process naturally
- Pass only task (user_id via closure) — closures add complexity for no benefit
