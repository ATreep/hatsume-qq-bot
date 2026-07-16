# Data Model: 合并转发消息解析

**Date**: 2026-05-31

## Entities

### MessageJSON (Input to LLM)

每条输入给 LLM 的消息的 JSON 表示。

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"message"` \| `"forward"` | Yes | 消息类型 |
| `time` | string | Yes | 消息时间，格式 `YYYY/MM/DD HH:mm:ss` |
| `user` | `{id: int, name: string}` | Yes | 消息发送者/转发者 |
| `content` | string \| ContentPart[] | Yes | 消息文本（纯文本）或多模态数组 |
| `reply_to` | `{user: {...}, content: string}` \| null | No | 回复引用的消息（仅 `type: "message"`） |
| `messages` | MessageJSON[] | No | 子消息数组（仅 `type: "forward"`） |
| `depth` | int | No | 嵌套深度（仅嵌套 forward 中的消息/子 forward） |

**ContentPart** (when `content` is an array):

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"text"` | Text content part |
| `text` | string | Text content |
| `type` | `"image_url"` | Image content part |
| `image_url` | `{url: string}` | Base64 data URL |

**Examples:**

```json
// 普通消息
{
  "type": "message",
  "time": "2026/05/31 18:30:00",
  "user": {"id": 123456, "name": "张三"},
  "content": "今天天气真好",
  "reply_to": null
}

// 回复消息
{
  "type": "message",
  "time": "2026/05/31 18:32:00",
  "user": {"id": 789012, "name": "李四"},
  "content": "好啊我请客",
  "reply_to": {
    "user": {"id": 123456, "name": "张三"},
    "content": "晚上去吃饭吗？"
  }
}

// 合并转发（顶层）
{
  "type": "forward",
  "time": "2026/05/31 18:35:00",
  "user": {"id": 111111, "name": "王五"},
  "messages": [
    {"user": {"id": 222, "name": "赵六"}, "content": "消息1"},
    {
      "type": "forward",
      "depth": 1,
      "user": {"id": 333, "name": "钱七"},
      "messages": [
        {"user": {"id": 444, "name": "孙八"}, "content": "嵌套消息"}
      ]
    }
  ]
}
```

### ForwardNode (API Response)

`get_forward_msg` API 返回的原始消息节点（OneBot 11 array format）。

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | int | 原始消息发送者 QQ 号 |
| `nickname` | string | 原始消息发送者昵称 |
| `content` | Segment[] | 消息段数组，可能包含 text, image, face, forward 等类型 |

**Segment**:

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | 消息段类型：text, image, face, forward, ... |
| `data` | dict | 消息段数据，随 type 变化 |

### LLMOutputJSON (LLM Output)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | 机器人回复文本 |

```json
{"message": "哎呀你怎么才来啊！我都等好久了！"}
```

### SourceEntry (Existing, Extended)

现有的 source_entry 结构，用于记录消息发起者和参与者信息。Forward 消息中需递归收集所有发言人。

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | string | 消息唯一标识 `m{message_id}` |
| `text` | string | 消息文本摘要 |
| `people` | PersonEntry[] | 所有参与者（递归收集） |

## State Transitions

No new state transitions. Forward message parsing is stateless — it operates on individual messages during the pipeline phase. The existing `ConversationState` and LangGraph state machine remain unchanged.
