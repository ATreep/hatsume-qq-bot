# Addressed-Sender Chat Peer Design

- Date: 2026-09-15
- Status: implemented

## Background

`ConversationState.chat_peers` decides which members' messages join the active
conversation. A message whose `session_id` is **not** in `chat_peers` never
reaches `pending_queue`; it is collected into the auxiliary context instead
(`handlers/dialogue.py::user_chat_handle`).

The membership set only ever grows through explicit entry points:

- `activate_chat()` — @bot, name mention, `/startchat`, character proxy.
- `hooks/message_trigger.py::activate_trigger_peer()` — a fired message Hook.
- `handlers/dialogue.py` — new-member welcome.

The `chat_agent` output contract added a native reply directive
(`[reply: <message_id>]`) in the 2026-07-25 design. When the Agent replies to a
member, or @-mentions one with `[CQ:at,qq=...]`, it is unmistakably addressing
that person — but their `session_id` is still absent from `chat_peers`, so their
very next message is filed as background context rather than answered. The
Agent has to re-reply to drag them back into the conversation.

## Goal

Register the sender of the replied message, and every member the Agent
@-mentions in its visible response, into the owning group's `chat_peers`, so
those members keep participating in the conversation that the Agent already
started with them.

## Confirmed Decisions

1. Registration happens as soon as the reply directive validates and the
   visible text is final — **not** gated on send success. A failed delivery must
   not silently drop the relationship.
2. `@`-mentions count as addressing a member, exactly like a native reply.
3. Only members the Agent addresses are registered. Non-addressed messages keep
   flowing into the auxiliary context as before.
4. The Bot's own QQ is never registered, for either path.
5. Registration is group-scoped and lives on `ConversationState`, so it is
   cleared by `end_conversation()` like every other peer.

## Non-Goals

- Registering members who are merely quoted inside a `reply_to` object of an
  incoming message.
- Registering senders of merged-forward child nodes.
- Adding a second peer registry, a separate reply pipeline, or a new send path.
- Changing `chat_peers` clearing semantics, debounce, queue routing, or end
  detection.
- Telling the model that replying enrols a member (no prompt change).

## Design

### Replyable sender map

`_extract_replyable_message_ids()` already walks the exact `HumanMessage` list
handed to `chat_agent` and collects top-level `message_id` values. That walk is
refactored into one generator, `_iter_replyable_top_level_messages()`, which
yields `(message_id, sender_qq_id)` pairs, so the ID allowlist and the sender
map are derived from the same single pass and cannot drift apart:

- `_extract_replyable_message_ids()` → `set[int]` (unchanged behaviour, still
  includes IDs whose sender is unknown).
- `_extract_replyable_senders()` → `dict[int, int]`, omitting entries without a
  usable positive `user.id`.

Both keep the existing strictness: only `HumanMessage` content, only text parts
that parse as one complete normalized JSON object, and never recursion into
`reply_to`, `messages`, or embedded user JSON.

### Peer registration

`_register_chat_peer(conversation_state, user_id)` rejects a non-positive group
or user id and `BOT_QQ_ID`, then adds
`state.peer_session_id(group_id, user_id)` to `conversation_state.chat_peers`
and logs the change.

`_register_addressed_chat_peers()` calls it once for the validated
`reply_to_message_id` (resolved through the sender map) and once per
`CQ_AT_PATTERN` match in the final visible text. `ai_node` invokes it right
after `ai_text_clean` is finalised, i.e. after reply, face, and memory tags are
stripped and before the `end_requested` send decision. That ordering is
deliberate:

- A suppressed or failed send still registers the peer (decision 1).
- When the Agent ends the conversation, `finish_conversation_node()` sends
  `[CONVERSATION END]`, which routes through
  `handle_ai_message()`/`_send_to_group()` and calls `end_conversation()` again,
  clearing the set. The peer added moments earlier does not survive into the
  next conversation, so the `chat_peers` reset contract holds.

### Session-id ownership

`peer_session_id()` moved from `hooks/message_trigger.py` to `state.py`, the
module that owns `chat_peers`. `hooks/message_trigger.py` re-exports it for its
existing callers and tests, and `graph/nodes.py` imports it from `..state`.

The move avoids a `graph/` → `hooks/` import, which `AGENTS.md` forbids in
spirit: importing the `hooks` package executes `hooks/__init__.py` and therefore
`hooks/store.py` and the whole Hook persistence layer, while
`hooks/message_trigger.py` already depends on `graph.nodes.inject_hook` lazily.
`state.py` is a leaf that both layers already depend on, so exactly one
definition of the format remains and no new cycle is introduced.

## Component Changes

### `hatsume/plugins/hatsume-plugin/state.py`

- Own the canonical `peer_session_id(group_id, user_id)` helper.

### `hatsume/plugins/hatsume-plugin/hooks/message_trigger.py`

- Import and re-export `peer_session_id` instead of defining it.

### `hatsume/plugins/hatsume-plugin/graph/nodes.py`

- Add `_iter_replyable_top_level_messages()`, `_normalized_message_sender_id()`,
  and `_extract_replyable_senders()`; re-implement
  `_extract_replyable_message_ids()` on top of the generator.
- Add `_register_chat_peer()` and `_register_addressed_chat_peers()`.
- Call the registration helper in `ai_node` once the visible text is final.

### `tests/test_graph_nodes.py`

- Stub `BOT_QQ_ID` in the config stub; add an optional `user_id` to
  `_normalized_text()`.
- Cover the sender map, reply registration, `@`-mention registration, invalid
  targets, the Bot itself, send failure, and end-of-conversation suppression.

### `tests/test_hook_message_trigger.py`

- Add the three `state.py` config constants the re-exported helper now requires.

### `docs/arch.md`

- Record the new peer-registration rule.

## Testing

- `_extract_replyable_senders()` maps only top-level human JSON, keeps the
  merged-forward top-level sender, ignores AI entries, and omits entries whose
  sender is missing while those IDs stay in the ID allowlist.
- A valid reply directive registers the replied sender.
- An `@`-mention registers the mentioned member.
- An invalid reply target registers nobody.
- The Bot is never registered through either path.
- The peer is registered even when the send reports failure, and even when the
  reply is suppressed by `end_conversation`.

Focused checks:

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests/test_graph_nodes.py tests/test_hook_message_trigger.py -q
```

## Acceptance Criteria

1. Replying to a member's message adds that member to the group's `chat_peers`
   under the canonical `group_<group_id>_<user_id>` key.
2. `@`-mentioning a member does the same.
3. Invalid reply targets, unknown senders, and the Bot itself register nothing.
4. Registration does not depend on delivery success.
5. `chat_peers` is still emptied by `end_conversation()`, so no stale peer
   survives into the next conversation.
6. Existing reply sending, `@` rendering, face, memory, auxiliary-context, and
   Hook peer activation behaviour is unchanged.
