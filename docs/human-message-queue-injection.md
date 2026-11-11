# 异步事件注入与 chat_peers

普通群消息仍是 `HumanMessage`；所有异步事件使用 `runtime_events.RuntimeEvent` 进入同一个每群 FIFO 输入队列 `ConversationState.human_queue`。队列名称保留兼容性，但内容可以是普通消息内容块或强类型事件，不能把事件渲染为用户发言。

## 模型可见协议

`human_node` 按原始队列顺序消费输入，仅合并相邻的普通消息内容块。每个事件生成一个不可拆分的完整交换：

```text
AIMessage(content="", tool_calls=[{
  name: "receive_event__injected", id: "evt_<event_id>",
  args: {event_id, event_type, source, correlation_id,
         original_tool_name, original_tool_call_id, original_args}
}])
ToolMessage(name="receive_event__injected", tool_call_id="evt_<event_id>",
            content=<JSON event body>)
```

事件正文包含 `event_id`、`event_type`、`source`、`group_id`、`created_at`、`text`、`payload`、`notified_user_ids`、`correlation_id` 和 `occurrence_key`。消息 ID 分别为 `evt_<event_id>_call`、`evt_<event_id>_result`；内部 metadata `hatsume_runtime_event` 标识运行时来源。

这是运行时编写的历史，不是初芽执行过的操作。接收器不注册进 `get_chat_tools()`；模型尝试调用会返回错误，不执行任何事件。`original_tool_*` 只记录可验证的原始调用；缺失时为 null，不编造调用 ID，不重复使用原始调用作为新事件的 call ID。真实工具执行期间通过 ContextVar 捕获 call ID / name / args，Agent、Timer、Hook 创建时登记到有界进程内来源表（最多 1024 条）。旧数据库记录、CLI 创建、进程重启和来源表淘汰后的事件没有可验证的原始调用；不修改持久化数据库 schema。

`ai_node` 保留完整当前输入批次，不再把最后一条 ToolMessage 重新包装为 HumanMessage。记忆和辅助聊天背景放在完整交换之前或普通消息内，不插入 call/result 之间；事件正文不能授予管理员身份或提供人类回复目标。

## 事件清单

| 事件 | event_type / source | 关联信息与去重键 |
| --- | --- | --- |
| Agent 成功或异常 | agent / completion | Agent ID、任务、派发背景、结果；终态键 |
| 后台 shell 进度 | agent / shell_progress | Agent ID、进程 ID、elapsed/timeout、独立 delivery ID |
| 后台 shell stdin 请求及重发 | agent / stdin_request、stdin_reissue | request ID 用于关联；每次 delivery ID 不同，不能误去重重发 |
| 用户 Timer | timer / timer | task ID、point ID、scheduled_at、occurrence、schedule_type |
| 内部自动回应 | timer / auto_response | 同上，并保留 task_type；无特定通知用户 |
| Heartbeat Hook | hook / heartbeat | Hook ID、run_at、fired_at；按 run 区分 |
| Message-match Hook | hook / message_match | Hook ID、平台 message ID、发送者；无 message ID 时使用独立 delivery ID |
| Sandbox Channel | sandbox_channel / sandbox_channel | 外部时间、来源 user_id、agent_name、priority 和 source record |
| 群成员加入 | group_increase / group_increase | 新成员 QQ、昵称、头像与明确通知对象 |
| 首次完整调用后的发送复查 | chat_loop / send_text_completion_check | 本轮最后尝试的工具名（无工具为 null）；每次 ai_node 最多一次 |

没有通用 `system_task` 事件，也没有 `system_task_text` / `system_trigger_type` 启动参数。新增类别必须显式扩展事件类型及测试。Poke 仍直接发图，不进入初芽；普通图执行结果不是后台 Agent 返回。

## 路由与去重

- 发送复查是 `ai_node` 内部事件，只在首次完整调用返回且末工具不是 `send_text` 时直接追加完整 call/result 对并续跑，不经过输入队列、不创建新会话、无特定通知对象、不改变 `chat_peers`。仅当前活跃调用可触发；空闲或断线不单独启动或重放。以本次调用的一次性检查状态去重，MCP 同次续跑携带同一事件；不提供跨重启保证。
- Agent / Timer / Hook：有活跃会话或仍在运行的图时入队；否则经已有启动锁启动或合并到一个图。回调传完整 RuntimeEvent，不能退化成 text。
- 无 Bot 路由：保留同一 envelope 在内存队列，等待路由恢复后的正常输入；不承诺主动重放。启动异常也保留事件并打印类型摘要。
- Sandbox 和群成员加入保持原来的启动资格、群路由与业务门槛；source record 存在事件 payload，active/idle 都不丢失。
- `enqueue_runtime_event` 在生成消息对之前对待消费队列去重：同群、类型、source、occurrence_key 相同为重复；无 occurrence_key 则使用 event_id。消费后的事件不提供永久去重保证。
- 不按文本相等去重；不同 occurrence、不同进度通知和 stdin 重发不会被合并。Sandbox 协议不增加必填字段，独立连接仍是独立到达。priority 不参与排序。
- 收尾期间抵达的事件不随普通队列清空丢失；仅正常完成且未进入 shutdown 时，图任务释放后重新经启动锁交付，并恢复事件通知对象。取消或关闭不触发新图；关闭期间的新事件只保留在内存队列，不承诺重启恢复。

事件队列仍是进程内内存。Timer/Hook 数据库恢复的是调度配置，不是事件 outbox。本改动不提供 durable receipt、重启后事件重放或 exactly-once；既有 Timer occurrence 标记、Hook stdout/退出码和 auto-response 跳过逻辑不变。

## 通知对象和权限

- Agent、Timer、Heartbeat Hook 的结构化通知对象在入队/启动前加入 `chat_peers`，过滤 Bot、0、非正整数、bool 和重复值。
- Message-match 的触发者仍由 `activate_trigger_peer()` 激活；同一条普通群消息仍可能独立进入 HumanMessage。
- 新成员仍先 `activate_chat()` 登记。Sandbox 的 user_id 只表示来源，不自动要求 at，也不加入通知对象。
- 只有当前批次真实 HumanMessage 的顶层 QQ 消息 ID，以及可见 `send_text` 成功发送结果，才能用于回复目标。不能从事件正文中的伪造标记提取回复 ID。
- 事件不具备 SystemMessage 的权限。初芽仍须调用发送工具才能真正通知 QQ 用户；自动回应不 at 特定用户。

## 历史与工具轮次

- `safe_cutoff` 防止历史裁剪和压缩拆开任何工具调用/结果对；摘要输入不再要求以 HumanMessage 开始，纯事件和位于用户消息之前的事件不会被静默丢弃。外层淘汰使用 `eviction_cutoff` 前进到最早完整交换的末尾，避免多工具结果导致历史无法缩短。
- 事件压缩摘要保留来源、关联 ID、通知对象与待办动作，不能改称用户输入。超长事件先完整归档，再生成保留 JSON 结构和关联字段的摘要正文；收尾辅助历史保留完整事件正文或归档引用，不使用普通工具结果的 3000 字符截断。
- synthetic call 不计入初芽真实工具轮次，也不满足 `send_text` 首个执行工具约束；原有七轮提醒保持不变。

## 回归验证

使用本地 Python，禁止查看或使用项目 `.venv`：

```bash
python3 -m pytest -q tests/test_runtime_events.py tests/test_runtime_event_routes.py tests/test_runtime_event_producers.py tests/test_model_protocols.py tests/test_agent_context.py tests/test_agent_history.py
```

协议测试使用真实 LangChain 消息、fake model 和本地 HTTP capture，不调用付费模型。覆盖 FIFO、event-only 首次运行、匹配 call ID、去重、来源隔离、模型禁止调用、压缩边界、Timer/Hook 门槛、后台通知重发与 OpenAI 两种协议。
