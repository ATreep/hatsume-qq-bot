# Data Model: Debug API Queue Message Full Detail

**Date**: 2026-06-05

## QueueMessage

A single message entry in a queue snapshot. Built by parsing the source entry's `text` JSON and adding `source_id`.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `source_id` | `string` | source entry | Queue-level identifier, e.g. `"m12345"` |
| `type` | `"message" \| "forward"` | parsed `text` JSON | Message type |
| `time` | `string` | parsed `text` JSON | Formatted timestamp, e.g. `"2026-06-05 22:30:00"` |
| `user` | `{id: number, name: string}` | parsed `text` JSON | Sender identity (QQ ID + nickname) |
| `content` | `string \| object` | parsed `text` JSON | Full message content (present for `type: "message"`) |
| `messages` | `QueueMessage[]` | parsed `text` JSON | Nested sub-messages (present for `type: "forward"`) |
| `reply_to` | `{user: {id, name}, content: string} \| null` | parsed `text` JSON | Referenced message when this is a reply |
| `depth` | `number \| null` | parsed `text` JSON | Nesting depth (for forward chains) |

### Fallback (JSON parse failure)

When `text` is not valid JSON:

| Field | Fallback Value |
|-------|---------------|
| `source_id` | `s.get("source_id", "unknown")` |
| `type` | `"message"` |
| `time` | `""` |
| `user` | `{id: 0, name: "unknown"}` |
| `content` | raw `text` string |

## QueueSnapshot

Unchanged from existing schema.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Queue name, e.g. `"idle_source_queue"` |
| `count` | `number` | Total entries in queue |
| `messages` | `QueueMessage[]` | Message entries (empty for non-source queues) |

## QueuesResponse

Unchanged from existing schema.

| Field | Type | Description |
|-------|------|-------------|
| `queues` | `QueueSnapshot[]` | 8 fixed snapshots (4 message queues + 4 source queues) |
