# Research: Agent Dispatch Context

**Feature**: 028-agent-dispatch-context  
**Date**: 2026-07-06

## Research Topics

### 1. Context storage mechanism

**Decision**: Store context in the existing in-memory `_AGENT_STATES` dictionary in `agents.py`.

**Rationale**:
- Existing agent state tracking already stores `status`, `task`, `user_id`, `started_at`, `result` — `context` is a natural addition.
- No database migration needed — follows the same pattern as all other agent state fields.
- `inject_agent_notification()` already reads from `get_agent_state()`; adding `get_agent_context()` is a trivial extension.
- Handlers don't need context during execution, so passing it through the handler signature is unnecessary.

**Alternatives considered**:
- A) Pass context through handler → rejected: requires changing `AgentHandler` signature and all handler implementations
- B) Store in a separate global dict → rejected: fragments state management without benefit
- C) Store in ConversationState → rejected: would require changing graph state shape and passing it through multiple layers

### 2. Injection message format

**Decision**: Use `📋 派发背景：{context}` on its own line in the notify message, placed between the SYSTEM header and the task reference.

**Rationale**:
- Chinese-language prefix consistent with existing notification format (`(SYSTEM) Agent '...' 执行完毕。`)
- Placed early in the message so the LLM reads context before task details (recency bias avoidance)
- Emoji prefix makes the context line visually scannable for human readers
- Omitted entirely when context is empty (no dangling header)

**Alternatives considered**:
- A) Plain text prefix → rejected: less visually distinct in message flow
- B) JSON-structured context block → rejected: over-engineered for a single string

### 3. Context parameter requirement

**Decision**: `context` is a required parameter (no default value) on the `agent_dispatch` tool.

**Rationale**:
- Forces the LLM to always provide context, ensuring consistent injection message quality
- Simplifies the injection logic: no need to handle None vs empty string differently
- The tool description explicitly instructs the LLM to provide context

**Alternatives considered**:
- A) Optional with default `""` → rejected: would result in missing context for many dispatches as the LLM may omit it

### 4. Tool rename scope

**Decision**: Rename `agent_allocate` → `agent_dispatch` in all active source files. Do NOT rename in historical spec documents under `specs/024-agent-allocate-*`.

**Rationale**:
- Historical spec documents are immutable records of past work
- Renaming them would break internal links and commit history references
- Only active code, tests, prompts, and current documentation need the new name
