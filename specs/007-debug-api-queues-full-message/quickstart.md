# Quickstart: Debug API Queue Message Full Detail

**Date**: 2026-06-05

## Using the enhanced endpoint

Call `GET /debug/api/queues` as before. The response shape has changed for entries in `_source_queue` snapshots.

### Before (v1)

```json
{
  "source_id": "m123",
  "user_name": "小明",
  "content_preview": "今天天气真好啊适合出去玩...",
  "time": ""
}
```

### After (v2)

```json
{
  "source_id": "m123",
  "type": "message",
  "time": "2026-06-05 22:30:00",
  "user": {"id": 111, "name": "小明"},
  "content": "今天天气真好啊适合出去玩",
  "reply_to": null
}
```

### Key changes

| Old field | New field | Notes |
|-----------|-----------|-------|
| `user_name` (string) | `user.name` (in `user` object) | + `user.id` (QQ ID) |
| `content_preview` (≤30 chars) | `content` (full text) | No truncation |
| `time` (empty) | `time` (real timestamp) | From `message_to_json` |
| — | `type` | `"message"` or `"forward"` |
| — | `reply_to` | Reply context (or null) |
| — | `depth` | Forward nesting depth (or null) |

### Forward messages

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

### Limit parameter

`?limit=N` still works — controls entries per source queue (default 20).

### Summary endpoint

`GET /debug/api/summary` is unaffected — it only uses queue counts, not message details.
