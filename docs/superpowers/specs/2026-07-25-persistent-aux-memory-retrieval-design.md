# Persistent Auxiliary Context and Repeatable Memory Retrieval Design

## Goal

Keep recent non-peer chat context available to every AI round and allow the
same long-term memories to be retrieved whenever they match a query. Auxiliary
context remains bounded through the existing model-based compaction path.

## Memory Retrieval

Memory retrieval no longer tracks content that was returned by earlier calls.
Every `query_memory()` call formats and returns all results supplied by
`query_mems()`, including results returned by another query in the same
`ai_node` round or an earlier round of the active conversation.

The change removes both existing deduplication stores:

- the module-level `_retrieved_mem_keys` in `graph/tools.py`;
- the obsolete module-level `_retrieved_mem_keys` in `graph/nodes.py`.

`ConversationState.retrieved_mem_keys`, `reset_memory_context()`, the
`retrieved_keys` argument to `configure_tool_callbacks()`, and accessors or
cleanup code that exist only for those sets are also removed. `/clear` keeps its
other conversation, queue, task, and process cleanup behavior.

No replacement per-round deduplication is introduced. If multiple text parts
in one Human message independently retrieve the same memory, that memory may
appear more than once in the assembled memory prompt.

## Auxiliary Queue Reads

`ai_node` takes a shallow snapshot of `auxiliary_messages_queue` when building
the current Agent input. Reading the snapshot does not remove messages from
`auxiliary_messages_queue` or entries from `auxiliary_source_queue`.

The retained snapshot is temporary Agent input. It does not replace or mutate
the latest Human message in LangGraph state, so the existing graph history
continues to contain only the active conversation's Human and AI messages.

Because auxiliary messages remain queued, every later `ai_node` round receives
the current retained auxiliary context until compaction replaces it with a
summary.

## Non-Peer Message Routing

`user_chat_handle()` checks the sender's session against
`ConversationState.chat_peers` before branching on whether a conversation is
active. A message from a session that is not a current peer is normalized with
`get_human_message()` and appended directly to the module-level auxiliary
queue. This behavior is the same when:

- no conversation is active;
- a conversation is active for another peer;
- LangGraph is currently running or waiting for the next Human message.

Non-peer messages do not activate a conversation, enter the pending or Human
queues, or interrupt the active graph. Peer messages keep the existing debounce
and graph-delivery behavior.

The existing idle queue fields are not removed as part of this focused change,
but ordinary non-peer messages no longer enter them. Existing startup APIs keep
their signatures to avoid unrelated lifecycle changes.

## Queue Bounds and Compaction

`append_auxiliary_message()` remains the single write path for auxiliary
messages. After appending, it compares the message count with
`CONTEXT_QUEUE_LEN`.

When the queue exceeds the configured limit, the existing mini/lite model
compaction runs over the accumulated messages. A successful compaction replaces
the queue with one history-summary message and clears source entries because
individual sources cannot be mapped reliably to generated summary text.

If compaction raises an exception, the queue drops only enough oldest messages
to retain the newest `CONTEXT_QUEUE_LEN` entries. This fallback uses the
configured limit instead of a hard-coded value. Source entries are cleared in
the failure path for the same mapping reason.

Reading the auxiliary snapshot never triggers compaction. Compaction occurs
only after a write pushes the queue over its configured bound.

## Failure Handling

Message-normalization failures keep the handler's existing failure behavior and
do not append partial entries. Compaction failures are logged and fall back to
deterministic FIFO trimming, leaving the queue usable and bounded.

Memory queries retain their current error behavior. This change only removes
result filtering and tracking; it does not add retries or suppress retrieval
errors.

## Tests

Focused tests verify:

- repeated `query_memory()` calls can return the same memory;
- duplicate memories may appear across multiple queries in one AI round;
- no retrieved-memory set remains in graph state or callback configuration;
- `ai_node` snapshots auxiliary messages without clearing either queue;
- retained auxiliary messages are included in successive AI rounds;
- non-peer messages enter the auxiliary queue with and without an active
  conversation;
- non-peer messages do not enter pending or Human queues;
- successful overflow compacts the auxiliary queue to a summary;
- failed compaction retains the newest `CONTEXT_QUEUE_LEN` messages;
- peer message debounce and graph delivery remain unchanged;
- `/clear` retains its remaining cleanup behavior after memory-dedup state is
  removed.

After focused tests, Ruff, Pyright, and the complete Pytest suite must pass
without ignored collection errors, resource warnings, or type errors.

## Documentation

`docs/arch.md` is updated to describe repeatable memory retrieval,
non-destructive auxiliary snapshots, direct non-peer routing, and compaction as
the queue's bounding mechanism. Historical design and plan documents remain
unchanged.
