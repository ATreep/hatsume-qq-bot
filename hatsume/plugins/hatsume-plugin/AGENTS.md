# Runtime Plugin Guide

These instructions apply to all code under this plugin.

## Dependency Direction

```text
__init__ -> handlers -> graph -> domain/infrastructure
                         |       ├── memory
                         |       ├── timer
                         |       ├── skills
                         |       ├── models/prompts
                         |       └── infra/utils
                         └── graph.tools <-> graph.agents (lazy runtime links)
```

Avoid new imports from lower layers back into handlers. Existing lazy imports in
`graph/` break deliberate runtime cycles around callbacks and agent notification;
do not add more without documenting the initialization order in `docs/arch.md`.

## Extension Points

### Add a Chat Tool

1. Define the decorated function in `graph/tools.py`.
2. Add it to `CHAT_TOOLS` in the same module.
3. Add focused tests, including callback/rate-limit state when applicable.

### Add a Background Agent

1. Implement `async (task: str, user_id: int) -> str` in `graph/agents.py`.
2. Register it with `register_agent(name, description, handler)`.
3. Test state transitions, concurrent instances, completion notification, and
   cleanup of subprocess/stdin resources.

### Add a QQ Handler or Command

1. Put conversation parsing/orchestration in `handlers/dialogue.py`, command and
   event tools in `handlers/tools.py`, or social behavior in `handlers/social.py`.
2. Register the matcher in the plugin `__init__.py` with explicit priority/blocking.
3. Test matcher-independent handler logic; do not require a live QQ connection.

### Change Message Parsing

The normalized LLM input schema is:

```json
{"type":"message|forward","time":"...","user":{"id":1,"name":"..."},"content":"...","messages":[]}
```

Forward messages must accept the official OneBot `message -> node.data` schema and
documented vendor variants. Preserve sender identity, segment order, nesting depth,
and explicit failure placeholders. Never silently drop unknown media segments.

## State and Lifecycle

- `group_runtime.py`: stable positive-group registry, target-group Bot discovery/routing, task-local binding, one graph lock per group, and shutdown cleanup.
- `state.py`: per-group idle, pending, and human queues plus graph/rate-limit and explicit end-request state.
- `character_proxy.py`: at most one RAM-only proxy and auto-termination handle per group; no database or task manager.
- `graph/nodes.py`: per-group transient auxiliary queues and graph-bound state.
- `graph/tools.py`: per-group callbacks, media counters, and context-local shell limits.
- `graph/agents.py`: group-owned background Agent instances, tasks, processes, and stdin queues.
- `hooks/`: group-owned persistent heartbeats, bounded script processes, route-aware jobs, and dedicated chat injection.
- `infra.py`: local `/work/hatsume` foreground/background execution in the current bot container, with group-owned subprocess counts, stdin, cancellation, and delayed logical deactivation.

Every new state field needs initialization, reset/cleanup, and concurrency tests.
Character-proxy activation must reuse `ConversationState.activate_chat()` and the
existing graph; do not add a separate reply pipeline or direct send path.
Group-dependent APIs must use an explicitly validated group ID or the task-local
runtime binding and must never fall back to a recent or default group.
External triggers and group-member lookups must use the Bot registered for their
explicit target group; do not call parameterless `nonebot.get_bot()`. Local Shell
and sandbox-media call sites must pass their validated group ID into `infra.py`.
`infra.py` must not invoke Docker or stop/delete the bot's own container. Shared
local media paths must include the validated group ID.

## Self-Modification and Restart

After finishing a self-modification, before requesting a restart, check
whether any unfinished Agent (still-running sub-agent or background task)
exists. If any are still running, create or reuse one Todo named "重启等候".
The Todo is completed and `hatsume-restart` runs only when both conditions hold:
(1) an Agent completion report has been received; and (2) no Agent is currently
running. Until then leave the Todo unfinished and skip the restart. This is the
"all Agents finished -> automatically restart" completion event. If no Agent is
unfinished, restart directly.

## Persistence

- Memory metadata: `memory/engine.py` and SQLite `memory-db/memory.db`, with every row owned by a positive `group_id`; no full resident index.
- Memory vectors: `memory/vector_store.py` and local Milvus `memory-db/memory_vectors.db`, keyed by SQLite memory ID and filtered by `group_id`.
- Milvus Lite sessions must stop their embedded gRPC server after each operation; this process also forks local Shell subprocesses.
- Timers: `timer/store.py`, SQLite `timer.db`, APScheduler jobs in `executor.py`.
- Skills: common Markdown files are read-only; group-local mutations live under `SKILLS_DIR/groups/<group-id>`.
- Hooks: metadata and scripts live under `data/hatsume-plugin/hooks/`; tools are task-local, scripts stay under their owning positive group directory, and program limits are five enabled Hooks, intervals of at least 300 seconds, and timeouts of 1..60 seconds.

Use parameterized SQL and explicit commits. Schema migrations must be idempotent
and tested against an existing database, not only an empty temporary database.

## Local Checks

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx pyright
.venv/bin/python -m pytest tests/test_graph_nodes.py tests/test_tools.py -q
```
