# Chat Agent Reply-by-Message-ID Design

- Date: 2026-07-25
- Status: approved

## Background

Hatsume normalizes received QQ messages into JSON before placing them in the
idle, pending, human, and auxiliary conversation queues. The normalized JSON
contains the sender, time, content, and optional quoted-message context, but it
does not contain the received OneBot `message_id`.

`get_human_message()` already stores the ID indirectly as
`source_entry["source_id"] = "m<message_id>"`. That field belongs to memory
source attribution and is not included in the JSON shown to `chat_agent`.
Consequently, the Agent cannot select an earlier human message as the target of
a native QQ reply. AI responses are currently sent as text, image, or CQ-at
segments without a `reply` segment.

## Goal

Expose the real OneBot message ID on every top-level QQ group message supplied
to `chat_agent`, then allow the Agent to attach one optional leading directive:

```text
[reply: 12345]确实，这条说得有道理
```

The program validates the ID against the exact human-message history supplied
to that Agent invocation, removes the directive from visible text, and sends
the main response with `MessageSegment.reply(12345)`.

## Confirmed Decisions

1. IDs are the real `GroupMessageEvent.message_id` values, not temporary
   per-invocation sequence numbers.
2. One AI output can target at most one message.
3. Unknown, malformed, duplicated, or otherwise invalid reply directives are
   removed and the remaining response is sent as an ordinary message.
4. Only top-level received group messages expose `message_id`.
5. Nested merged-forward nodes do not expose synthetic or best-effort IDs.
6. The quoted message inside a top-level message's `reply_to` object does not
   expose its own ID.
7. No database or persistent runtime-state change is required.

## Non-Goals

- Replying to nested nodes inside a merged-forward message.
- Replying to the quoted `reply_to` message when that message is not itself a
  top-level history item.
- Supporting multiple reply targets or splitting one Agent response into
  multiple QQ messages by directive.
- Replacing the directive with a chat tool.
- Changing message debounce, graph routing, end detection, memory persistence,
  or forward parsing beyond the new top-level field.

## Normalized Input Schema

### Normal message

`message_to_json()` gains an optional `message_id: int | None` parameter. When
present, the result is:

```json
{
  "type": "message",
  "message_id": 12345,
  "time": "2026/07/25 12:00:00",
  "user": {"id": 10001, "name": "群友"},
  "content": "消息内容",
  "reply_to": null
}
```

When no real OneBot ID exists, the field is omitted rather than set to `null`.
This preserves compatibility for synthetic system messages, AI transcript
entries, memory context, placeholders, and forward nodes.

### Top-level merged forward

`build_forward_json()` gains the same optional parameter. A received merged
forward is replyable as one top-level QQ message:

```json
{
  "type": "forward",
  "message_id": 12346,
  "time": "2026/07/25 12:01:00",
  "user": {"id": 10001, "name": "群友"},
  "messages": []
}
```

The recursive objects inside `messages` remain unchanged. The `reply_to`
object in a normal message also remains unchanged.

### OneBot boundary

`handlers/dialogue.py::get_human_message()` passes `event.message_id` into the
normal or top-level-forward JSON builder. The existing source entry remains
unchanged so memory attribution continues to use `source_id` independently.

## Replyable-ID Allowlist

`ai_node` builds the final LangChain message list for `chat_agent` exactly as it
does today, including transient auxiliary history and optional memory context.
Before invocation, a helper extracts replyable IDs from that exact list.

The extractor follows these rules:

1. Inspect only `HumanMessage` content.
2. For multimodal content, inspect only text parts whose complete text parses
   as one normalized JSON object.
3. Accept `message_id` only from that parsed top-level object.
4. Do not recurse into `reply_to`, `messages`, `content`, or arbitrary embedded
   JSON supplied by a user.
5. Treat the observed OneBot ID as an opaque integer and compare it exactly.

This approach does not require a long-lived `replyable_message_ids` field in
`ConversationState`. It also ensures that an ID removed by auxiliary
compaction is no longer replyable because it is no longer visible to the
Agent.

## Agent Prompt and Output Contract

`prompts.py` adds a short reply section near the existing input-format and
CQ-at instructions:

- Each top-level human message may contain `message_id`.
- To reply natively to one visible human message, put exactly one
  `[reply: <message_id>]` directive at the beginning of the response.
- Use only an ID visible in the supplied human history.
- Omit the directive when a native reply is unnecessary.
- Never invent or copy an ID from nested forward content or `reply_to`.

The directive is optional. Existing plain-text output remains valid.

## Directive Parsing

Reply parsing occurs in `ai_node` after the Agent returns and before face and
memory tags are processed.

1. Detect bracketed `[reply: ...]` control tags.
2. A reply is eligible only when there is exactly one control tag, it is the
   leading non-whitespace item, its payload is an integer, and that integer is
   in the invocation allowlist.
3. Remove all recognized reply control tags from user-visible text regardless
   of validity.
4. If eligibility fails, set the reply target to `None` and continue with the
   remaining text as an ordinary response.
5. If no visible text remains, do not send an empty reply-only message.

The reply directive is also removed from the `AIMessage` stored in LangGraph
history. Existing face and memory tag history behavior remains unchanged. This
prevents an old reply directive from being replayed or copied in later turns.

## Sending Flow

The existing answer callback gains an optional reply target while preserving
the default behavior for all current callers:

```python
await ai_answer(message, reply_to_message_id=None)
```

For a valid reply target, `ai_node` sends the cleaned main response through the
callback once instead of pre-splitting it into independent output segments.
The dialogue layer performs the existing secret masking, CQ-at rendering, and
Markdown/image conversion, then prepends:

```python
MessageSegment.reply(reply_to_message_id)
```

Because a QQ reply segment must belong to the same outgoing message as its
content, the reply segment and all main-response segments are sent as one
`Message`. This applies equally to plain text, CQ-at output, and content rendered
as an image. Without a reply target, current segment-by-segment behavior remains
unchanged.

The face image selected by `[hatsumeface:...]`, if any, is a later auxiliary
send and does not repeat the reply segment.

Both matcher-based sends and direct group sends used by Agent or Timer-triggered
conversations accept the optional callback argument, so the callback contract
is consistent across graph entry paths.

## OneBot Failure Fallback

An ID can be valid in the Agent input yet become unusable before sending, for
example if the original message is deleted or the adapter rejects an expired
reference.

When a send containing `MessageSegment.reply()` fails:

1. Log the reply-target failure.
2. Retry the same cleaned response once without the reply segment.
3. If the ordinary send also fails, continue through the existing bounded
   retry/error behavior.

Malformed and out-of-context directives never reach OneBot. They are stripped
and sent normally on the first attempt.

## Auxiliary-History Preservation

During an active graph, batched received messages are stored as multiple text
parts inside one `HumanMessage`. `finish_conversation_node()` currently flattens
all text parts into one string before testing whether it is JSON. Multiple JSON
objects therefore become invalid as a combined string and are wrapped as one
synthetic message, which would discard their individual `message_id` fields.

The finish path will preserve each human text part independently:

1. For every text part that parses as normalized JSON, append that part to the
   auxiliary transcript unchanged.
2. Wrap only non-JSON fallback text with `message_to_json()`.
3. Continue serializing AI messages without a `message_id`.

This retains replyable IDs when a completed conversation becomes auxiliary
history. Existing auxiliary compaction may later replace old entries with a
summary; summarized messages intentionally cease to be replyable.

## Component Changes

### `hatsume/plugins/hatsume-plugin/utils/__init__.py`

- Add optional `message_id` parameters to `message_to_json()` and
  `build_forward_json()`.
- Emit the field only when supplied.

### `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`

- Pass the top-level event ID into normalized JSON.
- Extend response-building and answer callbacks with the optional reply target.
- Prepend the OneBot reply segment and force one combined message when present.
- Fall back to an ordinary send if OneBot rejects the reply reference.

### `hatsume/plugins/hatsume-plugin/graph/nodes.py`

- Extract the invocation-scoped allowlist.
- Parse, validate, and remove the Agent reply directive.
- Pass the optional target through the answer callback.
- Store AI history without reply control tags.
- Preserve individual human JSON parts when rebuilding auxiliary history.

### `hatsume/plugins/hatsume-plugin/prompts.py`

- Document the optional input field and reply directive contract.

### `docs/arch.md`

- Update the normalized message schema.
- Document reply-target validation and the outgoing reply-segment flow.

## Testing

### JSON and input-boundary tests

- `message_to_json()` emits a supplied ID and omits an absent ID.
- `build_forward_json()` emits a supplied top-level ID.
- `get_human_message()` preserves the event ID for normal and merged-forward
  events.
- `reply_to` objects and nested forward nodes remain unchanged.

### Allowlist and parser tests

- Extract IDs from separate top-level human JSON text parts.
- Extract the top-level ID of a merged-forward event without recursing into its
  children.
- Ignore AI entries, memory prompts, nested objects, arbitrary text, and JSON
  embedded inside a user's `content` string.
- Accept one valid leading directive.
- Strip and downgrade unknown, malformed, non-leading, or duplicated
  directives.
- Avoid an empty send when only a directive remains.

### Sending tests

- Prepend `MessageSegment.reply()` to plain text.
- Preserve CQ-at conversion with the reply segment first.
- Preserve Markdown/image conversion and send the reply-bearing result as one
  message.
- Retry once without the reply segment when the reply send fails.
- Keep existing ordinary response behavior when no target is selected.
- Do not attach the reply segment to a later face image.

### Graph and lifecycle tests

- `ai_node` validates against IDs from the exact Agent invocation input.
- The answer callback receives the cleaned response and selected target.
- Invalid directives call the callback without a target.
- LangGraph AI history does not retain reply directives.
- Multiple human JSON parts retain their individual IDs after finish and
  auxiliary-queue reuse.
- End-conversation suppression and queue cleanup remain unchanged.

Focused tests run before the repository-wide required checks:

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

## Acceptance Criteria

1. Every top-level human QQ message shown to `chat_agent` carries its real
   OneBot message ID while synthetic and nested messages do not.
2. The Agent can select one visible human message with a leading reply
   directive and the user receives a native QQ reply to that message.
3. Invalid targets never cause the response to be lost solely because of the
   directive.
4. Existing text, CQ-at, Markdown-image, face, memory, Timer, Agent notification,
   and end-conversation behavior continues to work.
5. Completed human history retains individual message IDs until normal
   auxiliary compaction removes the underlying entries.
