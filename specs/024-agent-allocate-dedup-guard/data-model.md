# Data Model: Agent Allocate Deduplication Guard

No new entities. Uses existing data structures:

- **Agent Instance** (`_AGENT_STATES[name]`): list of dicts with fields `instance_id`, `name`, `status`, `task`, `user_id`, `started_at`. Existing in `graph/agents.py`.
- **_check_agent_used** (bool): module-level flag in `graph/tools.py`. Lifecycle: set `True` by `check_agent()`, reset `False` by `reset_capture_flag()` at start of each AI node turn.
