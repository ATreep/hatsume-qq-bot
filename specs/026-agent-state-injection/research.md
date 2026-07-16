# Research: Agent State Prompt Injection

**Feature**: 026-agent-state-injection
**Date**: 2026-07-05

## Research Items

### 1. Circular Import Avoidance: prompts.py ↔ agents.py

**Decision**: Use lazy import — import `get_running_instances` inside the `build_agent_state_prompt()` function body, not at module level.

**Rationale**: `prompts.py` currently has no dependencies on `graph/agents.py`. Adding a top-level import would risk circular imports since `agents.py` imports from `prompts.py` (for `CODING_AGENT_PROMPT`, `BACKGROUND_SHELL_DECISION_PROMPT`, etc.). Lazy import is the established pattern in this codebase (used elsewhere for similar cross-module dependencies).

**Alternatives considered**:
- Move `build_agent_state_prompt()` to `agents.py` — rejected because it's a prompt-building function and belongs alongside `build_skill_prompt()`, `build_face_injection_prompt()`, etc.
- Pass agent states as a parameter — rejected because it adds complexity to the call chain (ai_node → prompts.py → agents.py → back). Lazy import is simpler.

### 2. Agent State Injection Format

**Decision**: Markdown list with agent name, task (truncated to 200 chars), and elapsed time.

**Rationale**: Mirrors the `build_skill_prompt()` format (markdown list with name + description). 200-char truncation prevents overly long prompts when tasks contain detailed instructions. Elapsed time gives the LLM a sense of how long the agent has been running.

**Alternatives considered**:
- Table format — rejected as overkill for the small number of agents (typically 0-2).
- JSON format — rejected as less LLM-friendly than markdown in this codebase's prompt style.

### 3. Scope: Running vs. All Agent Instances

**Decision**: Inject only agents with `status == "running"`.

**Rationale**: Completed/done agents already notify the chat_agent via `inject_agent_notification()`. Idle agents have no useful state. Injecting only running agents keeps the prompt concise while providing exactly the information the LLM needs to avoid duplicate allocations.

**Alternatives considered**:
- All instances (including done/idle) — rejected as noisy; the LLM doesn't need to see historical completions in the system prompt.

### 4. Is `is_agent_running()` Still Needed?

**Decision**: Keep `is_agent_running()` in `agents.py` but remove the gate that uses it in `agent_allocate`.

**Rationale**: `is_agent_running()` is a general-purpose utility that could be useful for future features (e.g., a different tool, monitoring, or internal consistency checks). Removing only the gate, not the utility, follows YAGNI in reverse — don't delete code that may have legitimate future use just because one consumer was removed.
