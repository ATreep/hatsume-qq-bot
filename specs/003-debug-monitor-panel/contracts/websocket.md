# WebSocket Contract: 调试面板实时通道

**Feature**: 003-debug-monitor-panel
**Endpoint**: `ws://<host>:6999/hatsume-debug/ws`

## Connection Lifecycle

```
Client                          Server
  |                               |
  |-- WS Connect ---------------->|
  |                               |-- Send snapshot (full state)
  |<-- {type:"snapshot", data} ---|
  |                               |
  |       [every 500ms]           |-- Collect state
  |                               |-- Compute diff
  |<-- {type:"diff", data} -------|
  |                               |
  |-- WS Disconnect ------------->|
```

## Message Types

### 1. Snapshot (Server → Client, on connect)

First message after WebSocket handshake. Contains ALL state for ALL modules.

```json
{
  "type": "snapshot",
  "data": {
    "conv_state": {
      "is_chatting": false,
      "is_graph_running": true,
      "pending_queue#": 3,
      "idle_queue#": 0,
      "human_queue#": 1,
      "auxiliary_queue#": 2,
      "face_cooling": 2,
      "last_image_age": 42.5,
      "last_video_age": null
    },
    "ai_node": {
      "auxiliary_q#": 3,
      "retrieved_keys#": 5,
      "transcript#": 12,
      "tool_call_counts": {"shell": 1, "memory": 5, "web_search": 0}
    },
    "tools": {
      "html_shot_used": false,
      "image_gen_used": true,
      "tool_call_counts": {"shell": 1, "memory": 5, "web_search": 0}
    },
    "memory": {
      "total_records": 1523,
      "bm25_dirty": false,
      "active_sources#": 0,
      "corpus_size": 1520
    },
    "infra": {
      "container_active": false
    },
    "night_comic": {
      "retry_count": 0
    }
  }
}
```

### 2. Diff (Server → Client, periodic)

Only changed values since last send. Flattened keys: `module.variable`.

```json
{
  "type": "diff",
  "data": {
    "conv_state.is_chatting": true,
    "conv_state.pending_queue#": 5,
    "ai_node.tool_call_counts": {"shell": 2, "memory": 5, "web_search": 1}
  }
}
```

### 3. Ping (Client → Server)

Keep-alive or manual refresh trigger.

```json
{ "type": "ping" }
```

### 4. Pong (Server → Client)

```json
{ "type": "pong" }
```

## Key Naming Convention

- Flat values: `module.variable` (e.g., `conv_state.is_chatting`)
- Collection counts: suffix `#` (e.g., `pending_queue#`, `total_records`)
- Nested dicts: inline as sub-object (e.g., `tool_call_counts`)
- Time values: seconds (float), `null` if never triggered

## Error Handling

- If collector throws → that module omitted from current round, log warning
- If WebSocket drops → client shows disconnected state, auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s)
- If client tab hidden → WebSocket stays open, on visibility regain re-render from last data
