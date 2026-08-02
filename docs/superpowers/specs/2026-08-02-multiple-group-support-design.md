# Multiple Group Support Design

**Date:** 2026-08-02

## Summary

Hatsume will support concurrent conversations in multiple QQ groups within one
NoneBot process. Each group will have one serialized conversation graph, while
graphs belonging to different groups may run in parallel.

The implementation will introduce a process-level `GroupRuntimeRegistry` keyed by
positive QQ `group_id`. Every registry entry owns the mutable conversation,
character-proxy, Skill, Agent-routing, media-limit, and sandbox state for one
group. A task-local `ContextVar` will make the current runtime available to graph
nodes and LangChain tools without retaining the existing process-global mutable
state.

Long-term memories, mutable Skills, social statistics, Agent instances, and
Docker files and processes will also be isolated by group. Existing common Skills
will remain available to every group but cannot be modified by an Agent. Timers
and Todos will retain their existing group-scoped persistence.

## Goals

- Let messages from different groups run through independent LangGraph
  invocations concurrently.
- Preserve one graph, one debounce stream, and ordered message delivery within
  each group.
- Prevent messages, replies, auxiliary context, tool callbacks, end requests,
  memory, Skills, Agents, proxy state, media limits, or sandbox resources from
  crossing group boundaries.
- Give every group a Docker container named
  `hatsume-space-kali-<group-id>`.
- Preserve one common model/configuration layer, immutable graph topology,
  immutable tool and Agent definitions, common read-only Skills, scheduler, and
  storage engines.
- Migrate existing unscoped memories and like counters to
  `AUTO_RESPONSE_GROUP_ID`, which represents the original single group.
- Keep all isolation behavior deterministic and testable without live QQ,
  models, Docker, Milvus, or network access.

## Non-Goals

- No separate operating-system process or NoneBot instance per group.
- No parallel graph invocations within the same group.
- No per-group model provider, API credential, advanced-model selection, graph
  definition, Timer scheduler, or immutable container image.
- No private-message conversation support.
- No automatic copying of common Skills into group-local directories.
- No cross-group memory search, common long-term memory pool, or local Skill
  shadowing of a common Skill.
- No expansion of auto-response beyond its existing configured target group.
- No `/clear` or `/video` slash command; the chat tools
  `end_conversation` and `generate_video` remain available.

## Chosen Architecture

### Group Runtime Registry

A new `group_runtime.py` module will own the process-level registry and task-local
binding. The conceptual interfaces are:

```python
class GroupRuntimeRegistry:
    def get_or_create(self, group_id: int) -> GroupRuntime: ...
    def get_existing(self, group_id: int) -> GroupRuntime | None: ...
    async def shutdown(self) -> None: ...

@contextmanager
def bind_group_runtime(runtime: GroupRuntime): ...

def get_current_group_runtime() -> GroupRuntime: ...
```

`get_or_create()` accepts only positive integer group IDs and returns one stable
runtime per group. It is used only for real group events and explicit Timer or
Agent triggers. Cross-group inspection commands use `get_existing()` or the
relevant persistent store directly, so inspection cannot start a graph or
container.

The registry itself is common infrastructure. All mutable fields within each
entry are unique to that group. Registry creation must not suspend between the
lookup and insertion, ensuring that simultaneous first events cannot create two
runtimes for the same group.

### Group Runtime Contents

Each `GroupRuntime` owns:

- one `ConversationState`;
- one graph-start lock and at most one active graph task;
- idle, pending, human, and auxiliary message and source queues;
- active chat peers, end-request state, transcript, and source map;
- the debounce cancellation event and graph-running flags;
- the outgoing answer callback and current query user;
- face cooldown and per-round image/video usage counters;
- image/video rate-limit timestamps and callbacks;
- one optional character proxy and its termination handle;
- one group-local Skill manager overlay and per-conversation load-dedup state;
- references or identifiers for group-owned Agent and container resources.

The compiled LangGraph, node functions, decorated tools, model factories,
`AGENT_REGISTRY`, prompts, scheduler, and database engines remain common.

### Task-Local Binding

Handlers bind the target `GroupRuntime` in a `ContextVar` before calling graph,
tool, model, Skill, Agent, or sandbox code. The binding is reset in `finally`.
Async tasks inherit the binding at task creation, but delayed work must not rely
only on that inheritance.

Every Timer trigger, Agent instance, background process, stdin request, delayed
callback, and notification permanently records an explicit `group_id`. The
`ContextVar` is a lookup convenience, not the source of ownership for work that
can outlive the current call stack.

Missing group context fails closed. Group-dependent APIs must never fall back to
the most recently active group, `AUTO_RESPONSE_GROUP_ID`, group zero, or a
process-global callback.

## Conversation And Graph Flow

### Group Message Flow

1. A `GroupMessageEvent` resolves its runtime from `event.group_id`.
2. The handler binds that runtime for message normalization and image storage.
3. Mentions and character-proxy activation update only that group's peer set.
4. A non-peer message is appended only to that group's auxiliary context.
5. A peer message enters only that group's pending queue and resets only that
   group's debounce event.
6. After debounce, the graph-start lock rechecks the group graph task.
7. If a graph is running, messages enter that group's human queue.
8. Otherwise, one graph starts using that group's state and answer callback.

Different groups can reach step 8 concurrently. Within one group, the graph-start
lock and single graph task preserve serialization and message order.

### Reply Routing

The answer callback closes over the target `group_id` and bot instance. It does
not consult mutable process-global routing state. Text, reply segments, CQ at
rendering, images, faces, retries, and the conversation-end sentinel therefore
remain bound to the originating group.

A failure while sending to one group retries only that target. It cannot cause a
fallback send to any other active group.

### Timer And Agent Injection

Timer and Agent notification entry points receive an explicit `group_id` and
resolve that runtime directly:

- If the target group has an active conversation, append the marked system
  message to that group's human queue.
- If the group has no active graph, acquire its graph-start lock and start one
  graph for that group.
- If another trigger wins the start race, append to the graph it started.

Two triggers for one inactive group cannot create two graphs. Triggers for
different groups may start graphs concurrently.

Agent progress, stdin requests, completion, and failure notifications use the
group captured when `agent_dispatch` created the instance. A changed ambient
context cannot redirect them.

### Finish And End Semantics

Normal finish and `end_conversation` operate on only the current group:

- stop delivery and update end-request state only for that runtime;
- clear only its human queues and transient system-trigger flags;
- return completed round content only to its auxiliary context;
- reset only its Skill load-dedup state;
- release only its graph task slot;
- leave every other group graph and queue untouched.

There is no `/clear` command. The existing conversation finish path and
`end_conversation` chat tool remain the lifecycle controls.

## Module Ownership

### Modules Requiring Changes

| Module | Required group-isolation change |
|---|---|
| `group_runtime.py` (new) | Own `GroupRuntimeRegistry`, `GroupRuntime`, validation, task-local binding, and shutdown |
| `state.py` | Add required group identity to each conversation state; keep its existing queues, graph task, callbacks, transcript, rate limits, and cleanup group-owned |
| `__init__.py` | Bind group events, remove `/clear` and `/video`, pass events/arguments to group-selectable commands, and register registry shutdown cleanup |
| `handlers/dialogue.py` | Replace the single `conv_state` with registry lookup; isolate debounce, queues, graph startup, triggers, and replies |
| `handlers/tools.py` | Remove clear/video handlers; group-scope Shell, proxy, Skills, Agents, media, sandbox, and command targets |
| `handlers/social.py` | Store and display likes by group; support optional target group |
| `graph/nodes.py` | Resolve queues, flags, callbacks, proxy, Skills, memory, face state, finish, and trigger injection from the current runtime |
| `graph/tools.py` | Replace current-group and callback globals with runtime access; isolate media counters, persistence scope, Agent routing, stdin, Skills, and sandbox calls |
| `graph/agents.py` | Add group ownership to instances, queries, notifications, stdin, processes, and Skill/container access |
| `character_proxy.py` | Store proxy and termination state per group |
| `infra.py` | Manage container, process, file, refcount, lock, stop, and reset state per group |
| `config.py` | Define common/local Skill paths and the container-name base while retaining common model configuration |
| `skills/__init__.py` | Replace the mutable global singleton with common plus group-local resolution |
| `skills/manager.py` | Enforce read-only common Skills, local mutations, collision rules, and per-group deduplication |
| `memory/__init__.py` | Export group-scoped memory APIs |
| `memory/engine.py` | Add group ownership to schema, writes, exact/BM25 retrieval, user profiles, expiry, and migration |
| `memory/vector_store.py` | Add and require `group_id` for vector CRUD and search |
| `virtual/launch_image.sh` | Accept a validated group container name and eliminate the shared script channel |
| `virtual/stop_container.sh` | Stop only the supplied group container |
| `virtual/delete_container.sh` | Delete only the supplied group container |

### Unchanged Common Modules

| Module | Reason it remains common |
|---|---|
| `graph/__init__.py` | Package metadata only |
| `graph/builder.py` | Immutable compiled graph topology supports concurrent invocations |
| `handlers/__init__.py` | Package metadata only |
| `handlers/forward.py` | Stateless normalization with explicit event/bot inputs |
| `models.py` | Common model factories and protocol patches; sandbox calls resolve through bound infrastructure |
| `prompts.py` | Static prompts and pure builders |
| `memory/tokenizer.py` | Pure tokenization rules |
| `timer/__init__.py` | Common scheduler/store startup |
| `timer/schedule.py` | Pure schedule calculation |
| `timer/store.py` | Normal Timer records and operations are already keyed by `group_id` |
| `timer/executor.py` | Trigger execution already carries explicit `group_id`; updated injection performs runtime routing |
| `todo/__init__.py` | Common store singleton |
| `todo/store.py` | Capacity, visibility, creation, and completion are already keyed by `group_id` |
| `utils/__init__.py` | QQ helpers use explicit groups and the member cache is already group-keyed |
| `utils/md_to_image.py` | Stateless rendering service |
| `utils/security.py` | Pure credential masking |
| `virtual/image/Dockerfile` | All groups use the same immutable image |
| `virtual/image_pack.sh` | Builds the common image |
| `virtual/install_necessaries.sh` | Defines common image dependencies |

Updated modules are still common Python code. The distinction is that they will
own, resolve, or enforce group-isolated data after the change. Intentionally
common mutable state is limited to operator model selection, provider
configuration, scheduler infrastructure, and storage connections whose records
are group-partitioned.

## Command Surface

The following commands accept zero or one positive integer group ID:

| Command | No argument | With `group_id` | Authorization |
|---|---|---|---|
| `/agents [group_id]` | Current group's running Agents | Selected group's running Agents | Current group: everyone; another group: admin only |
| `/skills [group_id]` | Common plus current group Skills | Common plus selected group Skills | Current group: everyone; another group: admin only |
| `/likerank [group_id]` | Current group leaderboard | Selected group leaderboard | Current group: everyone; another group: admin only |
| `/resetsandbox [group_id]` | Reset current group container | Reset selected group container | Admin only for every invocation |

Omitted IDs always mean `event.group_id`. Invalid, extra, zero, or negative
arguments return a usage error. Non-admin cross-group requests are rejected
before reading target data.

Cross-group inspection does not create a runtime, graph, local Skill directory,
or container. A target with no resources returns an empty or not-running result.
`/resetsandbox` reports that no sandbox exists and does not create one.

The `/clear` and `/video` matchers and their dedicated handlers are removed.
Video generation remains available through the group-scoped `generate_video`
chat tool.

## Long-Term Memory Isolation

### SQLite Metadata

The `memories` table gains a positive, non-null `group_id`. Every new
`[memoryrecord]` write obtains the current group from the bound runtime. Exact
query candidates, user-ID candidates, recent-user memories, BM25 candidates,
record lookup, expiry, and deletion operate with group ownership.

The daily 150-day retention job may delete eligible rows across all groups in one
maintenance transaction because it does not return data to a conversation.
Conversation-driven reads and mutations always include the current group.

The SQLite memory ID remains the persistent identity and remains globally unique.
Associated users keep the existing shape:

```json
{"user_id": 123, "user_name": "name"}
```

The same QQ user may have unrelated memories in multiple groups. Character proxy
profile generation reads only memories for the proxy's group and user ID.

### Milvus Vectors

Milvus records gain a scalar `group_id` field alongside `memory_id` and the
embedding. Every vector search includes an equality filter for the current group.
Upsert, lookup, and delete verify or receive group ownership as well.

The existing hybrid retrieval invariant remains: preserve all qualifying exact
SQLite hits from the current group, then supplement them with temporary BM25 and
Milvus cosine results from only that group, preserving content deduplication.
Milvus Lite clients continue to exist only for one vector operation and must be
closed before Shell/Docker fork paths.

### Legacy Migration

Migration is idempotent and transactional at the SQLite boundary:

1. Detect the legacy schema without `group_id`.
2. Require a positive `AUTO_RESPONSE_GROUP_ID` if any legacy rows exist.
3. Add or rebuild the schema and assign all legacy rows to that group.
4. Add indexes beginning with `group_id` for retrieval paths.
5. Reconcile Milvus records by SQLite memory ID and assign the same group.
6. Record vector reconciliation completion only after every row succeeds.

The SQLite schema and backfill commit atomically before vector reconciliation.
If Milvus reconciliation fails, memory initialization fails closed and a later
startup retries the idempotent vector phase from SQLite. No memory query or write
is served while the two stores are in that incomplete initialization state, and
the SQLite memory content and IDs are never rewritten by the vector phase.

New groups begin with no memories. There is no global-memory fallback.

## Skill Isolation

The current `SKILLS_DIR` contents are the common Skill set. They are visible to
all groups and read-only to runtime tools. Group-local Skills are stored under:

```text
SKILLS_DIR/groups/<group-id>/*.md
```

The effective Skill view for a group is the union of common Skills and its local
Skills. `skill_create`, `skill_download`, and `skill_remove` operate only on the
local directory selected by the current runtime.

If a requested local name matches a common Skill name, creation or download is
rejected. Removal of a common name is also rejected, even if no local file exists.
This prevents a group from shadowing or changing common instructions.

Common content may use a shared read-only cache. Local content caches and the
loaded-this-conversation set are group-owned. Finishing one graph resets only
that group's deduplication state.

Coding Agents receive the same effective common-plus-local Skill view as the
group that dispatched them. Their Skill mutations remain local to that group.

## Agent Isolation

`AGENT_REGISTRY` remains common because Agent definitions are immutable.
`_AGENT_STATES` may remain one process registry, but every instance includes a
required `group_id` and every consumer filters by it.

An Agent instance captures at dispatch time:

- group ID;
- task and handoff context;
- notified user ID and group-resolved name;
- start time and status;
- result or failure;
- process and stdin ownership identifiers.

`build_agent_state_prompt()`, `/agents`, duplicate-task checks, progress
notification, and completion notification show only instances owned by the
selected group.

Each stdin request records its group. `respond_to_shell_prompt` requires the
current group to match before removing or writing the queue. A request ID from
another group behaves as unavailable and discloses no request details.

Background process maps and temporary log records include group ownership.
Cancellation, timeout, completion, Agent failure, or sandbox reset wakes and
removes only that group's waiters and processes.

## Character Proxy Isolation

Each runtime has at most one `CharacterProxy` and one termination handle. Different
groups may proxy different users concurrently. Creation, status, termination,
automatic timeout, at-target peer activation, alias matching, role-prompt
injection, and end-detection bypass resolve only the current group's proxy.

The proxy remains RAM-only and is not persisted. It continues to reuse the
group's existing conversation pipeline rather than creating a separate Agent or
task manager.

## Timer And Todo Isolation

Timer and Todo database engines remain process-level singletons. Their records
already contain `group_id`, and their group-dependent create, list, update,
delete, capacity, and completion operations keep their existing checks.

The change is at the graph boundary: current-group tool lookup comes from the
bound runtime, and Timer execution routes the explicit stored `group_id` to that
runtime. Timer IDs and Todo IDs may remain globally unique; an ID never grants
cross-group access.

Auto-response remains a single special task for `AUTO_RESPONSE_GROUP_ID` and now
uses that group's runtime without blocking conversations in other groups.

## Likes Isolation

`likes.json` changes from a flat user counter map to a group-keyed structure. All
legacy counters are assigned once to `AUTO_RESPONSE_GROUP_ID`. Like accumulation
and `/likerank` then read and write only the selected group.

The migration is idempotent. A missing or invalid original group with non-empty
legacy data fails without replacing the file. Writes continue to use a complete
replacement of the small JSON document and must not expose another group's user
IDs or counters in command output.

## Docker And File Isolation

### Container Identity

The container name is derived only from a validated positive integer group ID:

```text
hatsume-space-kali-<group-id>
```

All groups use the same immutable `hatsume-space-kali:1.0` image. No container
filesystem or writable volume is shared between groups.

### Container Runtime State

Infrastructure maintains independent per-group state for:

- startup lock and active flag;
- foreground/background subprocess registry;
- subprocess reference count and lock;
- delayed-stop task;
- temporary logs and stdin ownership;
- user image and generated file paths;
- reset and shutdown state.

Concurrent attempts to start the same group container coalesce behind its startup
lock. Starting or using another group's container proceeds independently. The
five-minute delayed stop is scheduled and cancelled per group.

### Command Transport

`virtual/script.sh` is no longer used as a shared command channel. Each foreground
or background invocation transfers its command directly to the selected
container through invocation-local arguments or stdin. This prevents concurrent
groups, and concurrent commands within a group, from overwriting a host script.

Temporary host files use unique secure names and are deleted in `finally`.
User-image copies explicitly target the selected container. Identical QQ message
IDs in different groups remain isolated because their paths exist in different
container filesystems.

### Reset

`/resetsandbox [group_id]` performs this sequence for the selected group only:

1. Validate authorization and group ID.
2. Look up existing container state without starting it.
3. Cancel tracked foreground/background processes and stdin waiters.
4. Cancel its delayed-stop task and clear its refcount.
5. Remove only `hatsume-space-kali-<group-id>`.
6. Remove its in-process container state.

Other groups continue running. A missing container returns a clear no-sandbox
result.

## Lifecycle And Failure Handling

Group runtimes remain in the registry for the process lifetime so their bounded
auxiliary context survives between conversations. Each queue keeps the existing
per-conversation limits; activity in one group cannot evict another group's
context.

Failures are contained by group:

- A graph or model exception releases only that group's graph slot.
- A send failure retries only the captured target group.
- A container failure marks only that group's sandbox unavailable.
- An Agent result is retained on its owning instance if QQ delivery fails and is
  never rerouted.
- A memory or local Skill failure disables only that operation for the current
  invocation; it cannot fall back to another group's data.
- Concurrent first messages or triggers for one group queue behind the graph-start
  lock; different groups remain concurrent.

On plugin shutdown, the registry signals all debounce cancellation events,
cancels and awaits all group graph tasks, cancels proxy timeouts, terminates Agent
processes, wakes stdin waiters, and cancels delayed container-stop tasks before
common database resources close. Cleanup must produce no pending-task or
unclosed-resource warnings.

## Testing

Tests remain offline and deterministic. Async concurrency tests use
`asyncio.Event` barriers instead of sleeps or scheduler timing assumptions.

### Runtime And Conversation Tests

- Stable same-group registry lookup and distinct mutable objects for different
  groups.
- Positive group validation, non-creating inspection, and task-local binding
  reset, nesting, and isolation across awaits.
- Two graph invocations from different groups simultaneously blocked at a test
  barrier, proving parallel execution.
- Concurrent first messages or triggers in one group creating exactly one graph.
- Independent debounce, peers, pending/human/auxiliary queues, source queues,
  callbacks, replies, finish, end request, face state, and Skill reset.
- A failure in one graph leaving another graph active.

### Memory And Persistence Tests

- Empty schema, legacy schema, repeated migration, invalid original group,
  interrupted vector reconciliation, and unchanged source on failure.
- Legacy SQLite rows and Milvus vectors assigned to
  `AUTO_RESPONSE_GROUP_ID` exactly once.
- Exact, BM25, vector, user-profile, write, expiry, and delete operations unable
  to see or mutate another group's memories.
- The same user ID carrying unrelated memories in two groups.
- Timer and Todo regression tests retaining existing group ownership.
- Flat likes migrating once and rankings and accumulation remaining group-local.

### Skill, Proxy, And Agent Tests

- Common Skills visible in every group but impossible to overwrite or remove.
- Local create/download/remove affecting only one group and rejecting common-name
  collisions.
- Local content cache and conversation dedup isolated by group.
- Concurrent proxies with independent matching, peer activation, prompts, and
  timeout cleanup.
- Same Agent type running concurrently in two groups with filtered status,
  context, notifications, and results.
- Agent group captured before `asyncio.create_task`, even if another group binds
  before completion.
- Cross-group stdin request rejected without consuming the owning queue.
- Timeout, cancellation, reset, and shutdown cleaning only the owner's Agent
  resources.

### Container And Command Tests

- Every Docker command receiving exactly
  `hatsume-space-kali-<group-id>`.
- Independent start locks, active flags, reference counts, stop tasks, processes,
  logs, files, and user-image copy targets.
- No read or write of `virtual/script.sh` during concurrent foreground or
  background commands.
- Reset removing only one group and never creating a missing container.
- `/clear` and `/video` matcher registrations absent.
- Optional command group IDs defaulting to the current group.
- Invalid IDs, extra arguments, non-admin cross-group access, and admin access.
- `/resetsandbox` remaining admin-only even for the current group.
- Timer, Agent progress, stdin, Agent completion, and auto-response reaching the
  correct graph while another group graph is active.

### Required Verification

Run focused tests while implementing each ownership boundary, followed by:

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Collection errors, type errors, resource warnings, pending tasks, and unclosed
Milvus or subprocess resources are failures and must not be ignored.

## Documentation Updates

Implementation must update `docs/arch.md` to describe:

- the group runtime registry and task-local binding;
- one graph per group and parallel graph execution across groups;
- explicit Timer and Agent routing;
- memory and vector group ownership and migration;
- common versus group-local Skills;
- per-group Agent, proxy, likes, and Docker lifecycle;
- the revised slash-command surface;
- the updated module and test indexes.

No runtime database, Skill, face, image, `virtual/script.sh`, or private data
artifact is modified as part of the main-repository implementation.
