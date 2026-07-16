# Data Model: 调试面板 v2

## QueueMessage

| Field | Type | Description |
|-------|------|-------------|
| `user` | `string` | 发送者昵称 |
| `content` | `string` | 截断内容（≤50 字） |
| `time` | `number` | Unix 时间戳（秒） |

## DashboardStatus

| Field | Type | Description |
|-------|------|-------------|
| `label` | `string` | 中文标签 |
| `value` | `string\|number` | 当前值 |
| `status` | `'normal'\|'warning'\|'error'\|'disconnected'` | 状态档位 |
| `icon` | `string` | emoji |

## Updated StateSnapshot (v2)

队列值从 `number` 变为 `QueueMessage[]`：

```json
{
  "conv_state": {
    "pending_queue": [
      {"user":"小明","content":"帮我写首诗","time":1717254195}
    ],
    "is_chatting": true
  }
}
```
