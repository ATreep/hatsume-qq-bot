# Research: Agent Allocate Deduplication Guard

**Date**: 2026-07-02

## Decision: Use existing `is_agent_running()` + `_check_agent_used` mechanism

**Rationale**: Both mechanisms already exist in the codebase:

- `is_agent_running(name)` in `graph/agents.py:75` — returns `True` if any instance of the named agent has `status == "running"`
- `_check_agent_used` flag in `graph/tools.py:81` — set to `True` by `check_agent()`, reset by `reset_capture_flag()` each turn

No new infrastructure needed. The guard is a simple AND of two conditions.

**Alternatives considered**:
- New dedicated "allocation lock" flag — rejected as over-engineered; the existing `_check_agent_used` flag already captures the semantic of "LLM inspected running state"
- Separate function in agents.py — rejected; the guard is tool-layer logic, not agent-layer logic
