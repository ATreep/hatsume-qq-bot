# 关于 AGENTS.md 的记录规则
此文件仅记录 **源码中没有提及或表达的项目规则**，此文件中的规则仅作为项目补充说明，帮助 AI Agents 快速了解项目。

# 关于 venv
无论任何时候，禁止修改此项目的虚拟环境 .venv 目录内的任何文件。
如果你需要使用 pytest 测试，请使用本地的 python 环境进行测试，不要尝试查看或运行 .venv 环境。

# 文档同步

实现或修改代码时，必须同步更新 `docs/` 中的相关文档以及 AGENTS.md 的相关内容。

# GUI 自动化

桌面 GUI 自动化、AT-SPI/CDP 控件操作、GUI 截图命令和 `sandbox_computer_use` 已从项目移除；不要重新添加相关工具、模块、配置变量或镜像启动脚本。网页内容处理继续使用现有的无头浏览器/网络工具链。

# 调试日志

新增或修改功能时，必须在关键执行路径打印可读的调试日志到控制台，便于运行时确认入口、参数摘要、结果和错误；日志不得输出 API Key、密码、Token 或其他敏感信息。

# 项目专业术语

- `chat_agent` 只作为项目源码中的实现名称使用。
- 编写发送给 `chat_agent` 的系统提示词、工具描述、运行时提示词、Skill 或其他模型可见文本时，必须把
  `chat_agent` 称为“初芽”。初芽不知道自己的源码实现名是 `chat_agent`，只知道自己叫“初芽”。
- 编写发送给 `coding_agent` 或其他子 Agent 的提示词时，也使用“初芽”指代接收结果和发起任务的主 Agent；
  只有需要引用源码符号、文件路径、日志字段或调试接口时，才保留反引号中的 `chat_agent`。

# 建议频繁 git commit

当你完成一次任务修改时，必须进行一次 `git commit`，但无需 push。


# Global Skills (全局技能)

**定义**: Global Skill 是一个无群组隔离的技能（Skill），保存在 `data/hatsume-plugin/skills/` 目录的根目录下，对所有群组通用。

**特点**：
- 路径：`data/hatsume-plugin/skills/<skill_name>.md`
- 无群组隔离（与群组特定技能相对）
- 所有群组的初芽都可以加载使用
- 用于教学/通用工具，如”如何发送Sandbox Channel”

**用途**:
- 教程和指南（如调用API、使用特定工具）
- 公共代码片段和工具库
- 跨群组共享的最佳实践

# Sandbox Channel (沙箱通道系统)

Sandbox Channel 允许在沙箱中运行的代码或服务通过 Unix Domain Socket 与初芽通信。

**机制**：
- 沙箱代码连接到 `/tmp/hatsume_channel.sock` Unix 域套接字
- 发送 JSON 格式的 Sandbox Channel 消息
- 机器人接收并将消息注入到初芽的消息队列
- 如果初芽运行中则直接加入队列，否则触发新对话

**Sandbox Channel 消息结构**（简化，仅chat_injection模式）:
```json
{
  "timestamp": 1634567890.5,
  "group_id": 123456789,
  "content": "消息内容",
  "user_id": 0,
  "agent_name": "service_name",
  "priority": "normal"
}
```

详见 `docs/sandbox-channel.md` 和全局技能 `sandbox-channel-guide.md`


# 初芽触发事件分类（源码标识：`chat_agent`）

初芽的输入来源必须按“来源类型”和“图内触发标记”区分记录。图内系统消息使用
`hatsume/plugins/hatsume-plugin/graph/nodes.py` 中的
`SYSTEM_TRIGGER_KEY = "_hatsume_system_trigger"` 标记；标记值通常是
`agent`、`timer`、`hook`、`group_increase` 或 `sandbox_channel`。普通用户消息没有这个标记。

## 1. 普通群消息（human message）

- 入口：`user_chat_handle()`，由 `user_chat`、`start_chat_by_at`、`start_chat_by_mentioned`
  等 NoneBot 消息处理器进入。
- 消息先进入当前群的 `human_queue`；只有发送者已经是 `chat_peers`，或通过 `@` 入口激活会话后，
  才会启动或继续 LangGraph 对话。
- 这是用户输入，不属于系统触发事件，不添加 `_hatsume_system_trigger`。
- 消息匹配 Hook 在普通消息处理前执行，因此同一条群消息可能同时保留为普通用户输入，并触发一个或多个
  `message_match` Hook。

## 2. 持久化 Hook

Hook 数据保存在 `hooks/hooks.db`，数据库字段 `trigger_type` 目前只有两种值：

### 2.1 Heartbeat Hook（`trigger_type="heartbeat"`）

- 由 APScheduler 按 `interval_seconds` 周期执行；间隔不得小于 300 秒，只对已启用且有 Bot 路由的群注册任务。
- 执行脚本返回退出码 `10` 且 stdout 非空时，才表示“有事件”，调用 `inject_hook()` 注入。
- 退出码 `0` 且 stdout 为空表示本轮无事件；超时、非法输出、其他退出码只记录失败，不注入对话。
- 事件进入会话时使用 `_hatsume_system_trigger="hook"`；活跃会话追加到 `human_queue`，非活跃会话以
  `trigger_type="hook"` 启动新对话。

### 2.2 Message-match Hook（`trigger_type="message_match"`）

- 在每条群文本消息进入普通聊天逻辑前检查，扫描文本前 2,000 个字符。
- 使用 `match_pattern` 正则匹配，可用 `match_user_id` 限定触发人；`0` 表示不限定触发人。
- 命中后构造包含群号、发送者、正则和原文的事件说明，并复用 `inject_hook()`，因此图内标记同样是
  `_hatsume_system_trigger="hook"`。
- 一条消息可以命中多个启用的 Message-match Hook；单个 Hook 的失败不能阻断其他 Hook 或普通聊天。

两种 Hook 在图内都显示为 `hook`，需要通过数据库的 `trigger_type`、Hook 名称和事件说明区分具体来源。

## 3. 定时任务（Timer）

### 3.1 用户创建的 timer-v2 任务

- 创建工具：`create_daily_timer`、`create_weekly_timer`、`create_monthly_timer`、`create_at_timer`。
- `schedule_type` 分别为 `daily`、`weekly`、`monthly`、`at`；每个计划拆成可持久化、可幂等处理的
  schedule point。
- 到期后调用 `inject_timer()`，图内标记为 `_hatsume_system_trigger="timer"`。
- `user_id > 0` 时附带被通知用户信息；`user_id=0` 时不要求 @ 用户。活跃会话直接入队，非活跃会话以
  `trigger_type="timer"` 启动。
- 重启恢复时只补偿容忍窗口内最近一次到期点，已经处理的 occurrence 不重复执行。

### 3.2 内部 Auto-response 定时任务

- `task_type="auto_response"`，由系统为已激活群生成未来的随机 exact-time 任务。
- 同样通过 `inject_timer()`、`_hatsume_system_trigger="timer"` 进入会话，但 `user_id` 固定为 `0`。
- 群未激活、没有路由、处于免打扰时间或已有活跃会话时会跳过本次发送，并同步下一次计划。

Timer 的 `schedule_type` 与 Hook 的 `trigger_type` 是不同层级的字段，不要把 `timer`、`heartbeat` 或
`message_match` 混写。

## 4. Sandbox Channel

- 外部沙盒程序通过 `/tmp/hatsume_channel.sock` 发送一行 JSON，由
  `SandboxChannelMessage` 校验后交给 `handle_sandbox_channel_message()`。
- 活跃图运行时，消息通过 `make_system_trigger_message(..., "sandbox_channel")` 追加到
  `human_queue`，携带 `_hatsume_system_trigger="sandbox_channel"`；非活跃会话启动时使用
  `trigger_type="sandbox_channel"`。
- 这类消息的来源应记录为 Sandbox Channel，不要误记为普通用户消息、Heartbeat Hook 或 Timer。
- 发送协议、字段和错误响应详见 `docs/sandbox-channel.md` 与
  `data/hatsume-plugin/skills/sandbox-channel-guide.md`。

## 5. Agent 执行返回

- `agent_dispatch()` 创建后台 Agent 实例，状态经历 `running`、`done` 或 `cancelled`；成功或异常都会形成
  一条最终结果记录。
- Agent 完成后由 `inject_agent_notification()` 将 Agent 名称、Agent ID、原始任务、派发背景和执行结果
  组合成系统消息。
- 活跃会话把结果追加到 `human_queue`，并使用 `_hatsume_system_trigger="agent"`；非活跃会话以
  `trigger_type="agent"` 启动新对话。
- 同一结果在当前会话队列中不会重复注入。主初芽负责读取结果、决定是否调用发送工具并向用户汇报；
  后台 Agent 本身不直接向 QQ 用户发送回复。
- `agent_work_history()` 只读取 Agent 的工具调用和输出历史，不会产生新的初芽触发事件。

## 6. 群成员加入

- 入口：`GroupIncreaseNoticeEvent` → `handle_group_increase()`。
- 仅对已激活群处理；活跃会话追加带 `_hatsume_system_trigger="group_increase"` 的欢迎消息，非活跃会话以
  `trigger_type="group_increase"` 启动。
- 该事件使用新成员 QQ 号和头像生成欢迎提示，属于系统通知，不属于普通群消息或 Agent 返回。

## 7. human_queue 注入与 chat_peers

- Agent 回调、Timer、Heartbeat Hook 的结构化通知对象在写入 `human_queue` 或启动新图前，立即加入目标群的 `chat_peers`；无通知对象的 `user_id=0` 不加入。
- Hook 的 `notified_user_ids`、Timer/Agent 的 `user_id` 都会过滤 `0`、非正整数、Bot 自身和重复值；Sandbox Channel 的 `user_id` 只表示来源，不代表需要 @ 的对象。
- Message-match Hook 的触发者由 `activate_trigger_peer()` 加入，群成员加入由 `activate_chat()` 加入；最终回复中的 CQ at 和回复目标仍由 `send_text` 登记。
- 详细队列入口、系统标记和分支行为见 `docs/human-message-queue-injection.md`。

## 8. 其他内部标记与非初芽事件

- `start_new_conversation()` 的 `system_trigger_type` 默认值为 `system_task`，供未归类的内部启动调用使用；
  新增调用点必须明确写出实际来源，不能默认丢失分类。
- `PokeNotifyEvent` 当前只触发随机图片发送，不进入初芽会话队列，因此不记录为上述任何一种
  初芽触发类型。
- `ai_node` 完成本轮模型调用只是一次普通图执行结果，不等同于“Agent 执行返回”；只有
  `agent_dispatch()` 创建的后台 Agent 完成后回注，才使用 `agent` 触发分类。


# Agent ID、历史和停止

- Agent ID 为分发时间戳、进程内递增序号和 Agent 类型的哈希；运行状态与完成通知携带 ID。
- 全局内存历史按 ID 保存列表：整数分发时间戳、元信息字符串、工具输入/返回或错误、
  最终输出。中断 Agent 不追加最终输出；仅保留最新分发的至多 5 个 Agent。
- 初芽使用 `agent_work_history(agent_id, length=5)` 查看最新进度；`-1` 返回全部
  工作记录，正整数返回最后指定条数，始终排除前两项时间戳和元信息。
- `agent_history_list` 列出当前群仍保留且不在运行的历史 Agent ID、元信息及分发时间。
- `agent_stop` 仅停止当前群正在运行的 Agent，且本轮 conversation 必须先成功查看
  相同 ID 的工作历史；取消任务并等待清理完成，释放运行状态。conversation 结束
  或新图运行开始时清空查看记录，不能使用上一轮的查看记录绕过检查。

# 初芽工具循环

- 每次 `ai_node` 调用独立统计初芽已完成的工具轮次，一条带工具调用的 AIMessage
  计为一轮；同轮多个工具不重复计数，历史对话不计入，MCP 动态工具加载后的第二次
  调用延续当前计数。
- 第 7 轮工具返回后、下次模型调用前，插入一次 HumanMessage：
  `[SYSTEM] 你不应该调用太多次工具，请你立即将当前任务分发给 Agent，然后使用 send_text 工具向用户说明情况。`
- 提醒仅注入一次；任务分发与用户通知由模型继续执行。初芽的递归限制为 40，
  为计数中间件和提醒后的工具调用保留执行空间。

# 工具 description 撰写方法论

新增或修改 `hatsume/plugins/hatsume-plugin/graph/tools.py` 中的 `@tool` 时，必须把函数内的多行 docstring 当作给初芽阅读的操作契约，而不是普通代码注释。先用一句话说明工具做什么、作用于哪里，以及返回的是数据、临时路径、发送结果还是状态变化；描述要与实际实现和工具名称一致，不得承诺代码没有提供的能力。

description 应按模型实际决策所需的信息组织，通常包含以下内容：

- **使用时机**：说明什么用户意图必须调用、什么相近意图应使用其他工具，以及明确禁止或不适用的情况。涉及 `send_*`、生成、搜索、Hook、Timer 等工具时，要说明工具是否直接面向用户产生副作用，还是只返回中间结果。
- **参数契约**：逐项写出参数含义、单位、格式、是否必填、默认值、允许范围、长度上限和特殊值（例如 `0`、空列表、ISO 8601、`file://` 绝对路径）。不要只重复参数名；要告诉初芽如何构造合法值。
- **调用顺序与工具协作**：当结果必须交给另一个工具时，明确写出下一步工具及参数形式，例如生成图片后调用 `send_image`、生成语音后调用 `send_voice`。同时说明哪些内容已经由前一个发送工具发出，避免重复发送。
- **边界与业务规则**：把实现中的配额、当前群/当前用户范围、权限、去重、并发、时间窗口、格式限制和角色约束写出来。跨群、管理员、当前会话、当前群历史等范围必须明确，不能让模型自行猜测。
- **返回值与失败行为**：说明成功时返回什么、返回内容是否用户可见、路径或 URL 如何继续使用；说明常见失败条件和工具会返回错误还是抛出异常。对“只记录/不发送”“用户看不到输出”等容易误判的行为必须直说。
- **示例与结构化格式**：参数复杂、正则、时间点、JSON、CQ at 或路径格式时，提供一个最小可复制示例；需要固定字段或枚举值时列出精确值，不使用模糊示例。

撰写时遵循这些风格规则：使用简洁中文和短段落，优先使用 `## 参数`、`## 注意`、`## 使用场景`、`## 返回`、`## 示例` 等标题；先写模型必须知道的决策规则，再写补充背景；把“必须”“只能”“不要”“仅支持”等强约束写成明确句子；不要泄露 API Key、密码、Token、内部绝对路径或不应暴露给用户的实现细节；不要把源码函数名 `chat_agent` 写给初芽，模型可见文本统一称其为“初芽”。

完成 description 后，逐项对照实现检查：参数名和限制是否真实存在，返回值是否与代码一致，副作用和发送链路是否完整，错误/权限/范围规则是否覆盖，示例是否能直接调用。若工具会随着配置、模型或平台行为变化，描述只写当前代码已经保证的行为，并同步更新 `docs/` 中受影响的说明。
