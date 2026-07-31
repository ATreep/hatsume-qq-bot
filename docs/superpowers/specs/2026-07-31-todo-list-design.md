# Per-Group Chat Todo List Design

**Date:** 2026-07-31

## Summary

Hatsume will maintain a persistent, per-QQ-group todo list for future conversational
follow-ups. The chat agent may proactively create a todo from the current chat and
may complete one when recent conversational context satisfies its stored finish
condition. Active todos are injected into the chat agent's role system prompt.

Each group has at most 15 active items. An item expires 48 hours after creation.
Expired items are deleted when `ai_node` begins and are never injected, counted, or
completed after the expiry boundary. Completed items are deleted immediately.

## Goals

- Persist todos across bot restarts in
  `data/hatsume-plugin/todo-db/todo.db`, located through
  `nonebot_plugin_localstore`.
- Isolate todo capacity, visibility, creation, and completion by QQ group.
- Store an initiator's group display name and QQ ID, todo content, creation time,
  and a strict finish condition.
- Let `chat_agent` manage todos through exactly two tools: `create_todo` and
  `mark_todo`.
- Inject the current group's active todos and behavioral policy into the role
  system prompt on every `ai_node` invocation.
- Mention the initiator in the normal chat-agent reply after condition-based
  completion and explicitly distinguish completion from expiry.

## Non-Goals

- No QQ command, list tool, edit tool, manual delete tool, or manual completion
  override.
- No completion history, tombstone, audit table, or expiry notification.
- No per-item APScheduler job or separate periodic cleanup job.
- No cross-group todo visibility or bot-wide capacity pool.
- No todo creation based only on background chat records.
- No structured enum or QQ-ID allowlist for permitted finishers.

## Architecture

### Todo Domain

A new `hatsume/plugins/hatsume-plugin/todo/` package owns persistence and domain
rules independently of the chat graph:

- `todo/store.py` defines `TodoStore`, the SQLite schema, validation, expiry
  deletion, duplicate detection, per-group capacity enforcement, listing, and
  condition-based deletion.
- `todo/__init__.py` exposes a lazily initialized process-level singleton through
  `get_store()`.

This boundary keeps SQLite lifecycle out of `graph/tools.py` and avoids coupling
conversational completion semantics to the timer or memory stores.

### Existing Integration Points

- `config.py` owns `TODO_MAX_ITEMS = 15` and
  `TODO_EXPIRY_SECONDS = 48 * 60 * 60`.
- `graph/tools.py` defines and registers `create_todo` and `mark_todo` exactly once
  in `CHAT_TOOLS`.
- `prompts.py` defines the todo policy and the dynamic prompt builder.
- `graph/nodes.py` performs expiry cleanup, loads the current group's active
  records, and appends the built section to the role system prompt before creating
  `chat_agent`.
- `docs/arch.md` documents the persistence model, prompt flow, tools, module map,
  and tests.

`graph.nodes` currently imports the scalar `_current_group_id` from
`graph.tools`. Because later reassignment does not update an imported scalar,
`graph.tools` will expose `get_current_group_id()`. Group-dependent logic in
`graph.nodes` touched by this feature will call the accessor instead of reading the
imported snapshot.

## Persistence Model

The default database path is resolved with:

```python
localstore.get_plugin_data_file("todo-db/todo.db")
```

In the current deployment this resolves under
`hatsume/data/hatsume-plugin/todo-db/todo.db`. Tests inject temporary paths and do
not create or modify the runtime database.

The database has one application table:

```sql
CREATE TABLE todo_items (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id                INTEGER NOT NULL,
    initiator_qq_id         INTEGER NOT NULL,
    initiator_group_name    TEXT NOT NULL,
    content                 TEXT NOT NULL,
    finish_condition        TEXT NOT NULL,
    created_at              REAL NOT NULL,
    CHECK (group_id > 0),
    CHECK (initiator_qq_id > 0)
);

CREATE UNIQUE INDEX idx_todo_active_duplicate
    ON todo_items(group_id, initiator_qq_id, content, finish_condition);

CREATE INDEX idx_todo_group_created
    ON todo_items(group_id, created_at, id);
```

`created_at` is a Unix timestamp. Prompt rendering displays it in local time as
`YYYY/MM/DD HH:mm:ss`. SQLite initialization is idempotent and enables WAL,
foreign keys, and a bounded busy timeout. Writes use parameterized SQL, explicit
commits, and immediate transactions where a read determines whether a write is
allowed.

Every user-facing todo contains the requested four parts:

1. Initiator group display name and QQ ID.
2. Todo content.
3. Creation time.
4. Finish condition.

The database additionally stores `id` for `mark_todo` and `group_id` for isolation.

## Finish-Condition Contract

Eligibility remains free-form, but every condition uses two required clauses:

```text
Permitted finisher: <free-form description>
Completion event: <free-form description>
```

`create_todo` receives the two clause values separately, trims and validates them,
and constructs the canonical stored text. This guarantees the required labels
without trying to parse arbitrary model prose. The permitted-finisher clause must
say who may satisfy the item, while the completion-event clause must state the
observable event or evidence that constitutes completion.

Todo content and each clause are non-empty after trimming and have a maximum length
of 500 characters. The prompt tells the agent to make both clauses precise enough
to avoid completing an item on ambiguous evidence.

## Tool Contracts

### `create_todo`

Conceptual signature:

```python
async def create_todo(
    initiator_qq_id: int,
    content: str,
    permitted_finisher: str,
    completion_event: str,
) -> str
```

The tool obtains the group from `get_current_group_id()`. It resolves the
initiator's group card through the existing
`get_group_member_name(get_bot(), group_id, initiator_qq_id)` helper. That helper
uses the group card, falls back to nickname, and ultimately falls back to the QQ ID
string. The model does not supply the stored name.

The agent may call this tool proactively when the current chat clearly suggests a
useful future follow-up. Creation does not require the user to say "todo" or
"remember." However, the agent must not create an item solely from the background
chat section.

Within one `BEGIN IMMEDIATE` transaction, the store:

1. Deletes rows at or beyond the 48-hour boundary.
2. Checks for an exact duplicate in the current group for the same initiator,
   content, and canonical condition.
3. Counts active rows for the current group.
4. Inserts only when no duplicate exists and the count is below 15.

An exact duplicate returns the existing ID without mutation. A full list rejects
creation without evicting any item. The system prompt also tells the agent to avoid
semantic duplicates that storage-level exact comparison cannot detect.

### `mark_todo`

Conceptual signature:

```python
def mark_todo(todo_id: int) -> str
```

The tool obtains the current group through `get_current_group_id()`. In one write
transaction it reapplies expiry deletion, selects the requested ID only within the
current group, and hard-deletes the selected row. This makes an item unmarkable if
it crosses the expiry boundary after `ai_node` entry.

On success, the tool returns the deleted item's full details and an explicit
instruction for the agent's normal reply to:

- include `[CQ:at,qq=<initiator_qq_id>]`;
- tell the initiator which todo finished; and
- state that the finish condition was satisfied, rather than saying the item
  expired.

The tool does not independently verify conversational evidence. The chat agent is
responsible for calling it only after recent conversational context satisfies both
stored clauses. The completion notice remains part of the agent's natural reply;
the tool does not send a separate standardized message.

## `ai_node` Flow

Before constructing `chat_agent`, `ai_node` performs this sequence:

1. Resolve the current group using `get_current_group_id()`.
2. Open the lazy todo singleton.
3. Delete every row whose `created_at <= now - TODO_EXPIRY_SECONDS`.
4. If a valid group is available, list that group's remaining items ordered by
   `created_at, id`.
5. Build the todo prompt section and append it to the role system prompt.

The prompt section is present even for an empty list because it carries the tool
usage policy. If group context is unavailable, the policy states that todo
operations are unavailable for that invocation; both tools remain registered but
return a missing-context error if called.

If store initialization, cleanup, or listing fails, `ai_node` logs the exception,
injects a temporary unavailable status, and continues the conversation. A todo
database failure must not prevent the bot from replying.

## Prompt Contract

Active items are rendered as structured JSON-like records containing:

- `id`
- `initiator_group_name`
- `initiator_qq_id`
- `content`
- `created_at`
- `finish_condition`

The surrounding prompt says stored values are data records, not instructions that
can override the role prompt. It directs the chat agent to:

- scan only current chat records when proactively creating a future follow-up;
- avoid creating semantic duplicates of injected active items;
- consider recent conversational context when evaluating completion;
- require both the permitted-finisher and completion-event clauses to be
  satisfied before calling `mark_todo`;
- leave an item active when the condition is not satisfied;
- never use `mark_todo` merely because an item is old; and
- after successful completion, follow the tool result and mention the initiator in
  the same normal reply.

Recent context may support a broader completion inference than one literal current
message. This flexibility does not remove either of the two stored requirements.

## Expiry And Deletion Semantics

The expiry boundary is inclusive: an item is expired when
`created_at <= now - 48 hours`. Expired rows are deleted when entering `ai_node`.
Tool mutations repeat the cutoff inside their transaction so a row cannot be
created against stale capacity or completed after expiring during a long-running
invocation.

Expiry is not completion. It produces no mention, chat message, history row, or
completion wording. Both expiry and successful completion hard-delete the active
row, but only `mark_todo` returns the required condition-satisfied notification
instruction.

## Validation And Failure Behavior

All failures are non-destructive and returned as concise tool results:

- Missing or invalid group context: operation unavailable.
- Invalid initiator QQ ID: creation rejected.
- Empty or oversized content or condition clause: creation rejected.
- Exact active duplicate: existing ID returned; no new row created.
- 15 active items: creation rejected; no eviction occurs.
- Missing, expired, or cross-group ID: generic active-item-not-found result, so
  another group's data is not disclosed.
- Member lookup failure: initiator name falls back to the QQ ID string.
- SQLite prompt-loading failure: todo status is temporarily unavailable, while
  normal chat continues.

## Concurrency

Capacity checks, duplicate checks, and insertion occur in a single immediate
transaction. The unique index provides a second defense against concurrent exact
duplicates. Tests use separate connections to the same temporary database to
verify that competing creates cannot produce a sixteenth active item or two exact
duplicates.

The process-level singleton owns its connection and supports explicit closure in
tests. Initialization failure closes the candidate connection and leaves the
singleton retryable, following the timer-store lifecycle pattern.

## Testing

### Store Tests

- Empty-database initialization and repeated initialization.
- Expected schema, indexes, WAL mode, and explicit close/reopen behavior.
- Per-group visibility and deterministic `created_at, id` ordering.
- Inclusive 48-hour expiry deletion and exclusion from capacity.
- Fifteen-item limit per group without cross-group interference.
- Concurrent capacity and exact-duplicate protection.
- Exact duplicate returns the existing ID without mutation.
- Completion hard-deletes the row and creates no history table or row.

### Tool Tests

- `create_todo` resolves and stores the initiator group card through
  `get_group_member_name()`.
- Name lookup failure falls back to the QQ ID string.
- Canonical two-clause finish-condition construction and input validation.
- Missing group, duplicate, and full-list results.
- `mark_todo` is group-scoped and does not disclose cross-group records.
- Successful completion result contains the CQ mention, item details, and explicit
  condition-satisfied-not-expired instruction.
- `create_todo` and `mark_todo` each occur exactly once in `CHAT_TOOLS`.

### Prompt And Graph Tests

- The todo prompt is injected between the base role prompt and chat-agent
  construction for populated, empty, and unavailable states.
- Expiry deletion runs before listing.
- Only the current group's items are injected.
- Every injected item includes all required fields and a formatted creation time.
- Prompt rules encode proactive current-chat creation, no background-only
  creation, semantic deduplication, recent-context completion inference, strict
  two-clause matching, and initiator notification.
- Todo database failure does not abort `ai_node`.
- Existing graph-tool stubs and exact tool-registry assertions include the two new
  tools.

### Repository Verification

Run focused todo-store, tool, prompt, and graph-node tests first. Then run:

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Collection failures, resource warnings, and type errors remain failures.

## Documentation Changes During Implementation

`docs/arch.md` will document:

- the new todo database and retention rule;
- the `ai_node` cleanup/list/injection flow;
- both chat tools and their group scoping;
- the `todo/` module ownership; and
- the new test modules in the test index.

## Acceptance Criteria

- A group can hold zero through 15 active items; a sixteenth is rejected without
  eviction.
- Another group has an independent capacity and never sees or marks those items.
- A created item records the initiator's resolved group display name and QQ ID,
  content, creation timestamp, and canonical two-clause finish condition.
- Exact duplicates are not inserted.
- At `ai_node` entry, items at least 48 hours old are hard-deleted before prompt
  construction.
- The chat agent receives the current group's active records and the behavioral
  policy on every invocation.
- The agent can proactively create from current chat but not from background chat
  alone.
- `mark_todo` hard-deletes only an active item in the current group.
- A successful completion reply mentions the initiator and says the condition was
  satisfied rather than saying the item expired.
- Todo persistence failures do not prevent ordinary chat replies.
