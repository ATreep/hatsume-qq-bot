# Data Model: 调试 API 数据采集层

**Feature**: 005-debug-api-server | **Date**: 2026-06-04

## Entity Overview

```
ServerStatus (bot_status, is_chatting, is_graph_running, ...)
├── QueueSnapshot[8] (name, count, messages[])
│   └── QueueMessage (user_name, content_preview, time, source_id)
├── MemoryStatus (total_memories, bm25_dirty, bm25_loaded, ...)
├── ToolStatus (call_counts, rate_limits, ...)
├── ConfigSnapshot (provider, models, thresholds, keys_present)
└── HealthMetrics (uptime, error_count, ...)
```

## 1. ServerStatus

对应 `/debug/api/state`。来源：`ConversationState` + graph nodes 模块级变量。

| Field | Type | Source |
|-------|------|--------|
| `bot_status` | `str` | derived: `"idle"` / `"chatting"` / `"conversing"` |
| `is_chatting` | `bool` | `ConversationState.is_chatting` |
| `is_graph_running` | `bool` | `ConversationState.is_graph_running` |
| `has_respond_recently` | `bool` | `ConversationState.has_respond_recently` |
| `chat_peers` | `list[str]` | `ConversationState.chat_peers` |
| `current_query_user_id` | `int\|null` | `ConversationState.current_query_user_id` |
| `face_cooling_count` | `int` | `ai._face_cooling_count` |
| `debounce_active` | `bool` | derived from `_debounce_cancel` |

## 2. QueueSnapshot

对应 `/debug/api/queues`。8 个队列的快照。

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | 队列名称 |
| `count` | `int` | 消息数量 |
| `messages` | `list[QueueMessage]` | 最近 20 条摘要 |

### QueueMessage

| Field | Type | Description |
|-------|------|-------------|
| `user_name` | `str` | 发送者昵称 |
| `content_preview` | `str` | 内容前 30 字 + "..." |
| `time` | `str` | 消息时间 |
| `source_id` | `str` | 来源编号 (e.g. `"m123"`) |

## 3. MemoryStatus

对应 `/debug/api/memory`。来源：`memory/store.py` + `memory/retrieval.py`。

| Field | Type | Source |
|-------|------|--------|
| `total_memories` | `int` | `len(all_mem_list)` |
| `bm25_dirty` | `bool` | `store.bm25_dirty` |
| `bm25_loaded` | `bool` | `retrieval.bm25 is not None` |
| `embedding_vectors_loaded` | `bool` | `retrieval.embedding_vectors is not None` |
| `embedding_vectors_shape` | `list[int]\|null` | shape tuple |
| `tokenized_corpus_size` | `int` | `len(tokenized_corpus)` |
| `last_index_rebuild_time` | `float\|null` | tracked |
| `active_memory_sources_count` | `int` | `len(active_memory_sources)` |

## 4. ToolStatus

对应 `/debug/api/tools`。来源：`graph/tools.py` + `ConversationState`。

| Field | Type | Description |
|-------|------|-------------|
| `tool_call_counts` | `dict[str, int]` | 本轮工具调用次数 |
| `capture_html_shot_used` | `bool` | HTML 截图已用 |
| `generate_image_used` | `bool` | AI 图片已生成 |
| `image_rate_limited` | `bool` | 图片限流中 |
| `video_rate_limited` | `bool` | 视频限流中 |
| `image_rate_remaining` | `float` | 距下次可生成秒数 |
| `video_rate_remaining` | `float` | 距下次可生成秒数 |

## 5. ConfigSnapshot

对应 `/debug/api/config`。来源：`config.py` 模块常量。

| Field | Type |
|-------|------|
| `provider` | `str` |
| `is_omni` | `bool` |
| `advance_model_name` | `str` |
| `lite_model_name` | `str` |
| `mini_model_name` | `str` |
| `embedding_model` | `str` |
| `context_queue_len` | `int` |
| `memory_top_k` | `int` |
| `score_threshold` | `float` |
| `embedding_weight` | `float` |
| `memory_expiry_days` | `int` |
| `image_rate_limit_seconds` | `int` |
| `video_rate_limit_seconds` | `int` |
| `message_max_length` | `int` |
| `shell_timeout` | `int` |
| `max_forward_depth` | `int` |
| `keys` | `dict[str, bool]` (presence only, no values) |

## 6. HealthMetrics

对应 `/debug/api/health`。自维护计数器。

| Field | Type | Description |
|-------|------|-------------|
| `uptime_seconds` | `float` | 运行时长 |
| `conversation_count` | `int` | 累计对话次数 |
| `message_count` | `int` | 累计消息数 |
| `error_count` | `int` | 累计错误数 |
| `json_parse_failures` | `int` | JSON 解析失败次数 |
| `last_error` | `str\|null` | 最近错误 |
| `last_error_at` | `float\|null` | 最近错误时间 |

## Validation Rules

- `bot_status` MUST be one of: `"idle"`, `"chatting"`, `"conversing"`
- `content_preview` ≤ 30 chars + "..." if truncated
- `user_name` non-empty, fallback to `str(user_id)`
- Config `keys` MUST NOT expose API key values (bool presence only)
- Queue message list default limit 20, overridable via `?limit=N`
