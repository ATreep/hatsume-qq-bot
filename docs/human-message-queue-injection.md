# human_queue 注入事件与 chat_peers

本文记录所有会把非普通群消息写入每群 `ConversationState.human_queue` 的入口，以及这些消息在图内的来源标记和通知对象处理方式。

## 统一处理规则

- 队列条目由 `make_system_trigger_message(text, trigger_type)` 构造，使用 `_hatsume_system_trigger` 保存来源。
- `human_node` 取出队列后清空队列，记录本轮是否包含系统触发，再移除内部标记后交给模型。
- 注入消息中明确指定、需要被通知的 QQ 号会立即加入当前群的 `chat_peers`，键格式为 `group_<group_id>_<user_id>`。
- Bot 自身、`0`、非正整数和重复 QQ 号不会加入 `chat_peers`。
- 最终回复中的 `[CQ:at,qq=...]` 和合法回复目标仍由 `send_text` 在发送后登记；这与系统消息注入时的预登记是两条互补路径。

## 事件清单

| 事件 | 注入入口 | 活跃图 | 非活跃图 | `trigger_type` | 通知对象加入 `chat_peers` |
| --- | --- | --- | --- | --- | --- |
| Agent 完成回调 | `inject_agent_notification()` | 追加 `human_queue`，重复结果去重 | 启动新图；无 Bot 路由时先排队 | `agent` | `user_id`（若有效） |
| Timer 到期 | `inject_timer()` | 追加 `human_queue` | 启动新图；无 Bot 路由时先排队 | `timer` | `user_id`（`0` 表示匿名任务） |
| Heartbeat Hook | `inject_hook()`，由 `hooks/executor.py` 调用 | 追加 `human_queue` | 启动新图；无 Bot 路由时先排队 | `hook` | Hook 的 `notified_user_ids` |
| Message-match Hook | `dispatch_message_hooks()` → `inject_hook()` | 同上 | 同上 | `hook` | 触发消息发送者由 `activate_trigger_peer()` 登记；Message-match Hook 不允许配置 `notified_user_ids` |
| Sandbox Channel | `handle_sandbox_channel_message()` | 追加 `human_queue` 和来源记录 | 启动新图 | `sandbox_channel` | 协议没有结构化通知对象；`user_id` 仅作为来源信息 |
| 群成员加入 | `handle_group_increase()` | 先 `activate_chat(event.get_session_id())`，再追加 `human_queue` | 先激活新成员，再启动新图 | `group_increase` | 新成员 QQ 号 |
| 普通用户消息 | `user_chat_handle()` 等入口 | 进入 `human_queue` 或待处理队列 | 按 @ 入口启动会话 | 无系统标记 | 发送者按普通聊天激活规则登记 |

## 关键行为

Agent、Timer 和 Heartbeat Hook 在注入时就登记通知对象，因此即使当前图尚未发送最终回复，被通知用户的后续群消息也会按 `chat_peers` 规则进入主对话。系统任务使用 `user_id=0` 时不会虚构成员，也不会加入任何 peer。

`human_node` 只消费和规范化队列，不负责解析 CQ at；系统注入入口负责登记已知的结构化目标，`send_text` 负责登记模型最终回复里动态生成的 @ 目标和回复目标。会话结束时 `ConversationState.end_conversation()` 清空 `chat_peers`。

## 代码位置

- `hatsume/plugins/hatsume-plugin/graph/nodes.py`：系统消息构造、Agent/Timer/Hook 注入和统一 peer 登记。
- `hatsume/plugins/hatsume-plugin/hooks/message_trigger.py`：Message-match Hook 命中与触发者激活。
- `hatsume/plugins/hatsume-plugin/hooks/sandbox_channel_handler.py`：Sandbox Channel 队列注入。
- `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`：群成员加入、普通消息入口和非活跃图启动。
- `hatsume/plugins/hatsume-plugin/state.py`：`chat_peers` 生命周期和 `peer_session_id()`。
