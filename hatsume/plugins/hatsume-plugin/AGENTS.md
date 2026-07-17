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

- `state.py`: idle, pending, and human queues plus graph/rate-limit and explicit end-request state.
- `character_proxy.py`: one process-local proxy (including generated aliases) and one auto-termination handle only; no database or task manager.
- `graph/nodes.py`: transient auxiliary queues and graph-bound state.
- `graph/tools.py`: callbacks and context-local shell limits.
- `graph/agents.py`: background agent instances and stdin queues.
- `infra.py`: Docker subprocess reference count and delayed stop task.

Every new state field needs initialization, reset/cleanup, and concurrency tests.
Character-proxy activation must reuse `ConversationState.activate_chat()` and the
existing graph; do not add a separate reply pipeline or direct send path.

## Persistence

- Memory metadata: `memory/engine.py` and SQLite `memory.db`; no full resident index.
- Memory vectors: `memory/vector_store.py` and local Milvus `memory_vectors.db`, keyed by SQLite memory ID.
- Milvus Lite sessions must stop their embedded gRPC server after each operation; this process also forks Shell/Docker subprocesses.
- Timers: `timer/store.py`, SQLite `timer.db`, APScheduler jobs in `executor.py`.
- Skills: Markdown files under the configured skills directory.

Use parameterized SQL and explicit commits. Schema migrations must be idempotent
and tested against an existing database, not only an empty temporary database.

## Local Checks

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx pyright
.venv/bin/python -m pytest tests/test_graph_nodes.py tests/test_tools.py -q
```
