# Research: Agent Monitor & Deepseek Provider

**Date**: 2026-06-28

## Decision 1: In-Memory State Storage

- **Decision**: Use a module-level `dict[str, dict]` in `graph/agents.py`
- **Rationale**: Single-process asyncio event loop — no concurrency concerns. Matching existing patterns (AGENT_REGISTRY is also a module-level dict). Simplicity trumps persistence for MVP.
- **Alternatives considered**: SQLite (overkill for 2 agents, adds table management), JSON file (unnecessary I/O for transient state)

## Decision 2: ChatOpenAI for Deepseek

- **Decision**: Use `ChatOpenAI(base_url=..., model=..., api_key=...)` directly
- **Rationale**: Deepseek provides an OpenAI-compatible API. LangChain's `ChatOpenAI` works out of the box. The existing `reasoning_content` monkey-patch in `models.py` already handles Deepseek-compatible response formats.
- **Alternatives considered**: Custom `ChatDeepseek` class (unnecessary — OpenAI compat), separate httpx client (loses LangChain integration)

## Decision 3: State Transitions

- **Decision**: `idle → running → done` with no separate error state
- **Rationale**: Even failed tasks produce output (error message stored as result). Simplifies state machine. Chat agent can inspect result to determine success.
- **Alternatives considered**: 4-state (idle/running/done/error) — adds complexity without benefit; failures are still "done" from a scheduling perspective
