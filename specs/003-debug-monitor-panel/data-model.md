# Data Model: 实时调试监控面板

**Feature**: 003-debug-monitor-panel
**Date**: 2026-06-01

## Entities

### StateCollector

状态采集器 —— 代表一组相关运行时变量的采集逻辑。

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | 模块唯一标识，如 `"conv_state"`, `"ai_node"` |
| `collect` | `Callable[[], dict[str, Any]]` | 同步/异步采集函数，返回 `{var_name: value}` |

**Constraints**:
- `name` 在注册表中唯一
- `collect` 必须快速返回 (<1ms)，不得阻塞事件循环

### StateSnapshot

状态快照 —— 某一时刻所有采集器的状态全集。

```text
StateSnapshot = dict[str, dict[str, Any]]
# { module_name: { var_name: value, ... }, ... }
```

Example:
```json
{
  "conv_state": {
    "is_chatting": false,
    "pending_queue#": 0,
    "face_cooling": 2
  },
  "ai_node": {
    "auxiliary_q#": 3,
    "tool_call_counts": {"shell": 1, "memory": 5}
  }
}
```

**Lifecycle**: 每次采集循环重新生成，不保留历史。

### StateDiff

状态变更 —— 相邻两轮快照之间的差异。

```text
StateDiff = dict[str, Any]
# { "module.var_name": new_value, ... }
# 扁平化 key，使用 "." 分隔模块名和变量名
```

**规则**:
- 仅包含值发生变化的 key
- 值使用 Python `==` 比较
- 如果所有值不变 → 空 dict `{}`

### WebSocketMessage

WebSocket 通信帧。

| Type | Structure | Direction |
|------|-----------|-----------|
| `snapshot` | `{ "type": "snapshot", "data": StateSnapshot }` | Server → Client |
| `diff` | `{ "type": "diff", "data": StateDiff }` | Server → Client |
| `ping` | `{ "type": "ping" }` | Client → Server |
| `pong` | `{ "type": "pong" }` | Server → Client |

### Module Registry (注册表)

运行时维护的采集器集合。

| Field | Type | Description |
|-------|------|-------------|
| `_collectors` | `list[StateCollector]` | 有序采集器列表 |
| `_last_snapshot` | `StateSnapshot \| None` | 上一轮快照（用于 diff 计算） |

**Operations**:
- `register(collector: StateCollector) -> None`: 追加采集器
- `collect_all() -> StateSnapshot`: 遍历所有采集器，合并结果
- `compute_diff(current: StateSnapshot, previous: StateSnapshot) -> StateDiff`: 计算差异
