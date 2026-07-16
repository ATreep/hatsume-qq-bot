# Design: Debug API GET /debug/api/queues Enhancement

**Date:** 2026-06-05
**Status:** Approved
**Context:** Branch `006-auto-reply-context-window`

## Problem

The `GET /debug/api/queues` endpoint currently returns minimal message information:

- `user_name` — only the first person's name from the `people` list
- `content_preview` — text truncated to 30 characters
- `time` — always an empty string
- `source_id` — the only useful field

However, the underlying `text` field in each source entry is already a JSON-serialized message in `message_to_json()` format, containing the full message structure. This data is being discarded instead of exposed.

## Goal

Parse the `text` field of each source entry and return the full `message_to_json` structure, augmented with `source_id`. This gives the debug panel access to complete message content, timestamps, user identities, and reply chains.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Parse `text` as JSON | The data is already there; no new data collection needed |
| Add `source_id` alongside `message_to_json` fields | `source_id` is debug-critical and not part of `message_to_json` output |
| Remove `content_preview` | Frontend can truncate `content` as needed |
| Remove separate `people` list | User info is in `user: {id, name}` |
| Forward messages: full nested expansion | Matches the "return full content" goal |
| JSON parse failure: fallback with raw text | Graceful degradation preserves observability |

## Response Schema

### QueueMessage (new)

```typescript
interface QueueMessage {
  source_id: string;       // "m{message_id}", from source entry
  type: "message" | "forward";
  time: string;            // formatted timestamp from message_to_json
  user: {
    id: number;            // QQ ID
    name: string;          // nickname
  };
  content?: string | object;   // present for "message" type
  messages?: QueueMessage[];   // present for "forward" type (nested)
  reply_to?: {                 // optional, present when replying to another message
    user: { id: number; name: string };
    content: string;
  } | null;
  depth?: number | null;       // optional forward depth
}
```

### Full Response

```typescript
interface QueuesResponse {
  queues: QueueSnapshot[];
}

interface QueueSnapshot {
  name: string;            // e.g. "idle_queue", "idle_source_queue"
  count: number;           // total entries
  messages: QueueMessage[];
}
```

### Example: regular message

```json
{
  "queues": [
    {"name": "idle_queue", "count": 1, "messages": []},
    {"name": "idle_source_queue", "count": 1, "messages": [
      {
        "source_id": "m123",
        "type": "message",
        "time": "2026-06-05 22:30:00",
        "user": {"id": 111, "name": "小明"},
        "content": "今天天气真好啊适合出去玩",
        "reply_to": null
      }
    ]}
  ]
}
```

### Example: forward message

```json
{
  "source_id": "m456",
  "type": "forward",
  "time": "2026-06-05 22:31:00",
  "user": {"id": 111, "name": "小明"},
  "messages": [
    {
      "type": "message",
      "time": "2026-06-04 10:00:00",
      "user": {"id": 222, "name": "小红"},
      "content": "你好",
      "reply_to": null
    }
  ]
}
```

## Implementation

### Modified code (`debug.py`)

```python
def collect_queues(limit: int = 20) -> dict[str, Any]:
    # ... queue_pairs and loop setup unchanged ...
    
    for s in srcs[-limit:]:
        # Parse text as JSON (it's already message_to_json output)
        raw_text = str(s.get("text", ""))
        try:
            parsed = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            # Fallback: return raw text as content
            parsed = {"type": "message", "time": "", "user": {"id": 0, "name": "unknown"}, "content": raw_text}
        
        parsed["source_id"] = str(s.get("source_id", "unknown"))
        src_previews.append(parsed)
```

### Modified docs (`docs/debug-api-contract.md`)

- Update Section 5 QueueMessage schema
- Update example response
- Update 8 fixed snapshots description

### Modified tests (`tests/test_debug_api.py`)

- Update `test_queue_message_has_required_fields` to verify new fields
- Add test for JSON parse fallback
- Add test for forward message structure

## Files Changed

| File | Change |
|------|--------|
| `hatsume/plugins/hatsume-plugin/debug.py` | Rewrite message extraction in `collect_queues()` |
| `docs/debug-api-contract.md` | Update Section 5 schema, examples, and field descriptions |
| `tests/test_debug_api.py` | Update test assertions to match new schema |
