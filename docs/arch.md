# Hatsume 架构与运行逻辑

本文档以 2026-07-31 的源码为准，是完整功能、运行流程、模块职责与测试索引的当前真源。specs/ 与 docs/superpowers/ 保存功能规格和历史设计决策，不代表所有内容仍与当前实现一致。

## 1. 功能总览

Hatsume 是一个 Python 3.12+ 的 NoneBot2 插件，通过 OneBot V11 接入 QQ 群聊。插件在单个 Bot 进程内运行，LangGraph 管理多轮对话，SQLite 保存长期记忆元数据与定时任务，Milvus Lite 保存记忆向量；外部边界包括 OneBot、模型和媒体供应商、网络搜索、macOS Photos 与 Docker。

~~~mermaid
flowchart LR
    User[QQ 群用户] --> OB[OneBot V11 实现]
    OB --> NB[NoneBot2 OneBot 适配器]
    NB --> Entry[插件入口与 matcher]
    Entry --> Handlers[消息和命令处理]
    Handlers --> State[共享 ConversationState]
    Handlers --> Graph[LangGraph 对话图]
    Graph --> Models[LLM 与媒体模型]
    Graph --> Tools[聊天工具]
    Tools --> Memory[(记忆 SQLite 与 Milvus Lite)]
    Tools --> Timers[(Timer SQLite 与 APScheduler)]
    Tools --> Todos[(Todo SQLite)]
    Tools --> Skills[Markdown Skills]
    Tools --> Agents[后台 Agents]
    Tools --> Sandbox[Docker 沙盒]
    Graph --> Send[QQ 回复回调]
    Send --> NB
~~~

| 功能 | 用户入口或触发方式 | 核心说明 | 主要实现 |
|---|---|---|---|
| QQ 群聊接入 | OneBot V11 群消息 | matcher 注册、事件绑定和插件初始化 | `hatsume/plugins/hatsume-plugin/__init__.py` |
| @ 识别增强 | 任意消息段中的 @机器人 | 修补默认只检查特定消息段的问题，可识别图片与文本之间的 @ | `__init__.py` |
| 多轮对话 | @机器人、提及“初芽 / hatsume / 出芽” | LangGraph 驱动连续追问、结束判断、工具调用与上下文压缩 | handlers/dialogue.py、graph/builder.py、graph/nodes.py |
| 群聊旁听上下文 | 不属于当前 chat_peers 的群消息 | 持续保留为辅助上下文，超限时压缩 | handlers/dialogue.py、graph/nodes.py |
| 回复消息解析 | QQ 回复消息 | 保存被回复者、文本、图片和合并转发摘要 | handlers/dialogue.py |
| 合并转发解析 | QQ 合并转发消息 | 兼容 OneBot 标准与常见厂商变体，递归解析嵌套节点并保留发送者 | handlers/forward.py |
| 图片理解输入 | 普通消息或回复中的图片 | 下载并校验后按消息 ID 与图片顺序保存到沙盒，JSON 内记录绝对路径；合并转发仍保留临时 URL | handlers/dialogue.py、infra.py |
| 长文本与 Markdown 图片化 | AI 回复超过阈值或含富 Markdown | 渲染标题、代码、表格和公式，并额外保留可点击链接 | utils/md_to_image.py |
| 长期记忆写入 | 模型输出 [memoryrecord: ...] | 提取显式记忆标签，可关联 QQ 用户后写入 SQLite | graph/nodes.py、memory/engine.py |
| 长期记忆检索 | 每轮自动检索或 find_memory | SQLite LIKE 精确命中优先，临时 BM25 与 Milvus Lite/BGE-M3 向量结果补足 | graph/tools.py、memory/engine.py、memory/vector_store.py、memory/tokenizer.py |
| 单一角色代理 | create_character_proxy、/proxy；群成员 @ 被代理用户或在对话中提到其昵称/外号 | 进程内只保存一个代理；一次生成行为画像与外号，@ 时激活 peer，昵称/外号命中时跳过结束检测 | character_proxy.py、handlers/dialogue.py、graph/nodes.py |
| 记忆迁移与清理 | 显式迁移命令、每日 04:30 | SQLite legacy 向量只读复制到 Milvus；同步清理 150 天前的 SQLite/Milvus 记录 | memory/engine.py、memory/vector_store.py、scripts/migrate_memory_vectors.py |
| 联网搜索 | search_web | 通过 DuckDuckGo 获取简要网络结果 | graph/tools.py |
| QQ 头像 | get_avatar | 返回指定 QQ 号的头像 URL | graph/tools.py、`utils/__init__.py` |
| 图片查看 | view_image | 使用轻量模型描述 HTTP/HTTPS 或沙盒 file:// 图片 | graph/tools.py、models.py、infra.py |
| 随机 ACG 图片 | 戳一戳或 random_acg_photo | 从 macOS Photos 的 ACG 相册导出，可直接发送或复制到沙盒 | handlers/tools.py、graph/tools.py |
| 图片发送 | send_image | 支持 HTTP、base64 和沙盒 file:// 文件，每轮最多三张 | graph/tools.py |
| 图片生成 | generate_image | 在 Seedream 与兼容图像接口之间选择，支持参考图和限流 | graph/tools.py、models.py、state.py |
| 视频发送 | send_video | 支持 HTTP URL、沙盒绝对路径和沙盒 file:// 文件，每轮最多一个 | graph/tools.py |
| 视频生成 | /video 或 generate_video | Seedance 1.0/1.5 文生视频或图生视频，并轮询任务结果；聊天工具返回 URL，由 send_video 发送 | handlers/tools.py、graph/tools.py、models.py |
| 高级模型切换 | 管理员 /model [模型名] | 查看或切换当前进程的高级模型名，不改变供应商、Base URL 或 API Key | handlers/tools.py、models.py、config.py |
| ADMIN MODE | `ADMIN_QQ_ID` 本人发送含大写 `WORLDSKY` 的普通消息 | 程序校验顶层发送者和当前消息正文；本轮 chat_agent 使用 `DEEPSEEK_V4_FLASH`、防御性移除历史 `image_url`/`img_url` 输入段并注入完整沙盒操作授权，下一轮恢复普通模型和未过滤输入 | graph/nodes.py、models.py、prompts.py |
| Docker Shell | 管理员 /ccsh、/cc 或 shell_executor | 在持久化 Kali 容器执行命令，包含超时、ANSI 清理、引用计数和延迟停止 | handlers/tools.py、graph/tools.py、infra.py |
| 后台长任务 | agent_dispatch(background_shell, ...) | 后台运行长时间或交互式命令，周期判断继续、通知、输入、结束或终止 | graph/agents.py、infra.py |
| 编码 Agent | agent_dispatch(coding_agent, ...) | 使用代码模型与 Shell、Skill、搜索、图像工具处理复杂开发任务 | graph/agents.py、prompts.py |
| Agent 通知 | 后台 Agent 中间输出或完成 | 注入当前对话；无活跃对话时为目标群启动新图 | graph/tools.py、graph/nodes.py、handlers/dialogue.py |
| Agent stdin | respond_to_shell_prompt | 把用户回复交回等待输入的后台进程 | graph/tools.py、graph/agents.py |
| 定时任务创建 | daily、weekly、monthly、at 四个聊天工具 | 频率任务每周期最多 5 个 `HH:MM:SS` 时间点、正整数间隔且由结束时间限定；指定时刻最多 10 个 | graph/tools.py、timer/schedule.py、timer/store.py |
| 定时任务管理 | /timer 或聊天工具 | 按群显示完整频率规则或全部指定时刻，支持删除；命令更新兼容为最多 10 个指定时刻 | handlers/tools.py、graph/tools.py |
| 定时任务恢复与清理 | Bot 连接完成、每日 03:00 | 恢复原生 point 作业、补偿五分钟内漏触发，并清理已完成普通任务 | `timer/__init__.py`、timer/executor.py |
| 群聊待办 | create_todo、mark_todo、每轮自动检查 | 每群最多 15 条，当前聊天可触发主动创建；48 小时过期，条件满足后删除并 @ 发起人 | graph/tools.py、graph/nodes.py、prompts.py、todo/ |
| 自动回复 | auto_response 记录或 /autoresponse | 固定群主动参与话题，每 1 至 3 小时重新排期 | timer/、prompts.py |
| 新成员欢迎 | `AUTO_RESPONSE_GROUP_ID` 的 OneBot `group_increase` 事件 | 激活新成员 peer，并向现有图注入欢迎任务或在无对话时启动新图 | `__init__.py`、handlers/dialogue.py |
| Skill 加载 | /skills、skill_loader | 扫描 Markdown 与 YAML frontmatter，按需加载并进行单轮去重 | skills/ |
| Skill 增删 | skill_create、skill_download、skill_remove | 运行时创建、下载、删除 Skill 并清理缓存 | graph/tools.py、skills/manager.py |
| 群成员搜索 | /membersearch 或 membersearch | 昵称和群名片子串优先，再按字符重叠排序；缓存五分钟 | handlers/tools.py、`utils/__init__.py` |
| 点赞与排行榜 | “赞我 / 互赞 / 点赞”、/likerank | 调用 QQ 点赞接口并在本地累计，展示前十名 | handlers/social.py |
| 凭证脱敏 | AI 文本回复与直接群发文本 | 遮盖常见 API Key 和 Token 形式 | utils/security.py、handlers/dialogue.py |
| 强制清理 | 管理员 /clear | 取消防抖与图任务，清理 ConversationState 拥有的队列和状态 | handlers/tools.py、state.py |
| 沙盒重置 | 管理员 /resetsandbox | 删除持久化容器并重置本地生命周期标记 | handlers/tools.py、infra.py |
| Agent 监控 | /agents | 列出运行中的 Agent 实例、开始时间和任务摘要 | handlers/tools.py、graph/agents.py |

## 2. 用户命令与消息触发

### 2.1 对话触发

- @机器人会激活共享对话状态。
- 消息包含“初芽”“hatsume”或“出芽”会激活对话。
- 同时 @ 与提及名称时，优先激活，再把该消息交给普通聊天处理器。
- 激活后的同一 session 消息进入十秒静默窗口；新消息会取消上一轮等待并重新计时。
- 不属于当前 chat_peers 的群消息不会打断主对话，而是进入辅助上下文。
- 当前实现只有一个进程级 conv_state，不是每个群或每个 session 独立创建一份 ConversationState。chat_peers 只记录哪些 session 可向当前对话继续输入。

### 2.2 命令清单

| 命令或事件 | 权限 | 作用 | 实现 |
|---|---|---|---|
| /video <提示词> [图片] | 所有人 | 生成视频，首张图片可作为参考 | handlers/tools.py |
| /timer list | 所有人 | 列出当前群任务的完整频率规则或全部指定时刻及状态 | handlers/tools.py |
| /timer delete <id> | 所有人 | 删除当前群指定任务 | handlers/tools.py |
| /timer update <id> <内容> @ <ISO时间,...> | 所有人 | 把任务替换为最多 10 个指定时刻 | handlers/tools.py |
| /skills | 所有人 | 列出有效 Skill 名称与描述 | handlers/tools.py |
| /membersearch <关键词> | 所有人 | 模糊搜索当前群成员，最多返回五个 | handlers/tools.py |
| /likerank | 所有人 | 展示累计点赞前十名 | handlers/social.py |
| /agents | 所有人 | 展示当前运行中的后台 Agent | handlers/tools.py |
| /model [模型名] | 管理员 | 无参数查看高级模型；有参数时只切换当前进程使用的模型名 | handlers/tools.py |
| /ccsh <命令>、/cc <命令> | 管理员 | 在 Docker 沙盒执行 Shell | handlers/tools.py |
| /resetsandbox | 管理员 | 删除并重置 Docker 沙盒 | handlers/tools.py |
| /clear | 管理员 | 强制结束当前共享对话并清理状态队列 | handlers/tools.py |
| /proxy create <QQ号> [分钟]、/proxy terminate、/proxy status | 所有人 | 创建、终止或查看单一 RAM 角色代理、完整角色 Prompt 与自动结束时间 | handlers/tools.py、graph/tools.py |
| /autoresponse [提示词\|prod] | 管理员 | 一次性调试自动回复，不写数据库 | handlers/tools.py |
| 赞我、互赞、点赞 | 所有人 | 尝试点赞至当日接口上限 | handlers/social.py |
| 戳一戳机器人 | 所有人 | 从 macOS Photos 的 ACG 相册发送随机图片 | handlers/tools.py |
| 新成员加入 `AUTO_RESPONSE_GROUP_ID` | 新成员 | 获取群名片与头像，要求机器人 at 欢迎、自我介绍并说明其他能力 | handlers/dialogue.py |

图片生成只作为对话内工具提供，没有独立的 /img matcher。

### 2.3 matcher 顺序

~~~mermaid
sequenceDiagram
    participant QQ as OneBot 事件
    participant E as 插件入口
    participant H as Handler
    QQ->>E: 群消息或 Notice
    E->>E: priority 10 命令、戳一戳与新成员 Notice
    E->>E: priority 20 to_me + keyword
    E->>E: priority 30 to_me 或 keyword
    E->>E: priority 100 catch-all message
    E->>H: 调用对应处理函数
~~~

插件入口还会替换 OneBot 适配器进程级的 _check_at_me，使其扫描所有消息段。这个 monkey patch 会影响同一适配器进程中的其他插件。

## 3. 对话管理逻辑

### 3.1 启动顺序

1. NoneBot 导入插件入口。
2. 入口立即调用 init_memory_system()，初始化记忆数据库、执行必要迁移并加载索引。
3. 入口注册 matcher，并安装全消息段 @ 检测补丁。
4. 入口通过 on_bot_connect 注册 init_scheduler()。
5. OneBot 连接完成后只初始化 timer-v2 数据库、恢复 APScheduler 作业、确保 auto_response 有未来任务，并注册每日 03:00 清理；旧 Timer 任务迁移由开发完成后的显式脚本负责。

### 3.2 消息标准化

handlers/dialogue.py 的 get_human_message() 把 OneBot 事件转换为单个统一 JSON 文本块：

1. 查询群名片或昵称，加入消息来源人员。
2. 解析回复中的发送者、文本、图片和合并转发摘要。
3. 把 @某人 转换为带昵称与 QQ 号的文本，并加入来源人员。
4. 普通消息生成以下结构：

~~~json
{
  "type": "message",
  "message_id": 123456,
  "time": "2026/07/16 12:00:00",
  "user": {"id": 123, "name": "群友"},
  "content": "消息内容",
  "reply_to": null
}
~~~

5. `message_id` 只出现在真实收到的顶层普通消息或顶层合并转发中。合并转发内部节点、`reply_to`、AI 历史和系统合成消息不包含该字段；顶层合并转发仍可作为一个整体被回复。
6. 合并转发生成 type=forward 和递归 messages 数组。
7. 当前普通消息中的图片会同步下载，按实际格式校验 9 MiB 与 3600 万像素限制，再保存为沙盒 `/tmp/hatsume-user-images/<message_id>-<从1开始的图片序号>.<实际扩展名>`；JSON 在原图片段位置写入 `![图片](<绝对路径>)`，不再附加 `image_url` 或 `img_url` 多模态块。
8. 回复中的图片先按被回复消息的 `message_id` 与图片序号查找已有沙盒文件，未命中时从回复段的临时 URL 重新下载；任一保存流程失败时保留原临时 URL。合并转发中的图片不进入该流程，继续直接使用临时 URL。
9. 普通文本最多保留 2000 字，被回复内容最多保留 200 字。
10. 返回的 source_entry 包含 source_id、序列化文本和 people，用于记忆归因；`source_id` 与模型可见的 `message_id` 职责独立。

### 3.3 合并转发

handlers/forward.py 兼容 OneBot 标准 message -> node.data，以及常见 messages、nodes、content 等厂商包裹形式。

~~~mermaid
sequenceDiagram
    participant D as dialogue
    participant F as forward parser
    participant B as OneBot Bot
    D->>F: resolve_forward_content
    F->>B: get_forward_msg(id)，10 秒超时
    B-->>F: 标准或厂商变体
    F->>F: 规范化 envelope、sender、segments
    loop 保持原始顺序
        F->>F: 渲染文本、图片、@、表情、音视频、JSON/XML
        F->>F: 内联节点递归解析
        F->>B: 仅在无内联节点时按 id 获取嵌套 forward
    end
    F-->>D: 递归 message/forward JSON 树
~~~

深度 0 至 3 会被解析，更深层级返回明确占位。API 错误、超时、无效 envelope 和未知媒体不会被静默丢弃，而是转换为可见占位。

### 3.4 消息队列与状态所有权

handlers/dialogue.py 在模块级创建唯一 conv_state = ConversationState()。前三类队列归该实例所有，并各有一条平行来源队列；辅助队列归 graph/nodes.py 模块所有。

| 队列 | 所有者 | 进入时机 | 消费和清理 |
|---|---|---|---|
| idle_queue / idle_source_queue | ConversationState | 当前普通消息入口不再写入；保留给既有显式 flush 接口 | flush_idle_to_auxiliary() 返回快照并保留配置的 overlap |
| pending_queue / pending_source_queue | ConversationState | 活跃 peer 在十秒输入确认期发送消息 | flush_pending() 一次取出并清空 |
| human_queue / human_source_queue | ConversationState | pending 刷新、Agent 通知、Timer 通知、新成员欢迎任务 | human_node 轮询取出并清空，最长等待五分钟 |
| auxiliary_messages_queue / auxiliary_source_queue | graph/nodes.py | 所有非 peer 消息、显式空闲 flush、完成后的对话历史 | ai_node 每轮读取非破坏性快照；超过 CONTEXT_QUEUE_LEN 时尝试摘要，失败则保留配置数量的最新消息 |

ConversationState 还保存 chat_peers、图任务、生成限流时间和回复回调。graph/nodes.py 另有模块级辅助队列、表情冷却和若干状态；graph/tools.py 另有当前群号、工具回调与每轮调用计数。因此当前系统并不支持完全隔离的多群并发对话。

~~~mermaid
flowchart TD
    Event[GroupMessageEvent] --> Parse[get_human_message]
    Parse --> Peer{session in chat_peers?}
    Peer -- 否 --> Aux[auxiliary queues]
    Peer -- 是 --> Pending[pending queues]
    Pending --> Debounce[十秒静默窗口]
    Debounce --> Running{graph running?}
    Running -- 是 --> HumanQ[human queues]
    Running -- 否 --> Start[start_new_conversation]
    Start --> HumanQ
~~~

### 3.5 LangGraph 状态机

graph/builder.py 是图节点和条件边的唯一组装处。

~~~mermaid
stateDiagram-v2
    [*] --> human
    human --> finish: 五分钟超时或 __end__
    human --> chat_end_detect: 获得用户输入
    chat_end_detect --> chat_llm: 继续、Agent 或 Timer 通知
    chat_end_detect --> finish: 检测结果为 yes
    chat_llm --> human: AI 和工具执行完成
    finish --> [*]
~~~

- human_node 每 0.3 秒检查 human_queue，五分钟无输入时写入 __end__。
- chat_end_detect_node 在早期轮次或最后消息包含“初芽”时直接继续；其他情况随机选择轻量或迷你模型判断，也保留随机直接继续分支。
- 图历史超过 60 条 LangGraph 消息时，删除最早的一对 Human/AI 消息。
- ai_node 自动检索记忆，注入 Skill 列表、运行中 Agent 状态、当前群定时任务概览、当前群待办、可选表情提示和调用时的本地日期时间，再用 CHAT_TOOLS 创建 LangChain Agent。进入节点时先删除所有已满 48 小时的待办；Todo 数据库不可用时只注入不可用状态，不中断普通回复。主调用最多重试五次，递归上限为 60。
- ai_node 每轮读取辅助队列的非破坏性快照，临时放在当前 Human 内容之前；同一辅助上下文会持续进入后续轮次，直到新写入触发压缩。发送前移除 reply、memory 与 face 标签；图历史会移除 reply 控制标记，但保留现有 face 与 memory 标签历史语义。
- ai_node 只解析当前 HumanMessage 中顶层 `type=message` 的 JSON。发送者 QQ ID 等于非空 `ADMIN_QQ_ID` 且该消息的直接正文包含大小写敏感的 `WORLDSKY` 时，本轮本地 `sys_prompt` 追加 ADMIN MODE，chat_agent 改用 `get_code_model()` 所封装的 `DEEPSEEK_V4_FLASH`，并在不修改 LangGraph 历史的前提下从全部模型输入消息复制过滤历史 `image_url` 与 `img_url` 内容段；回复引用、合并转发、辅助上下文和历史消息均不能触发，下一轮重新使用高级模型、未过滤输入与基础角色 Prompt。普通消息与回复图片在所有模式下均以沙盒 Markdown 路径输入。
- chat_agent 调用 end_conversation 后，ConversationState 立即关闭聊天并清空 chat_peers；ai_node 抑制该轮文本和表情发送，human_node 随即路由到 finish。下一次主动提及通过 activate_chat() 解除结束标记。
- finish_conversation_node 清理图运行标记和 Human 队列，重置 Skill 单轮去重，把 Human/AI/Tool 历史规范化后放回辅助队列，最后发送 [CONVERSATION END]。

### 3.6 回复发送

- AI 文本经 mask_secret_keys() 脱敏。
- 普通短文本直接发送；超过 LONG_MSG_THRESHOLD=500 或包含代码块、标题、公式、粗体等特征时由 md_to_image.py 渲染。
- chat_agent 可在回复开头输出一个 `[reply: <message_id>]`。ai_node 只接受本次实际传入 Agent 的 HumanMessage 顶层 JSON 中存在的 ID；未知、格式错误、重复或非开头标记会被移除并降级为普通消息。
- 合法目标由发送层转换为首个 `MessageSegment.reply()`，并与文本、at 或渲染图片组成同一条 QQ 消息。若 OneBot 拒绝该引用，程序立即用相同正文重试一次普通发送，再进入原有重试策略。
- AI 输出中的 `[CQ:at,qq=123456]` 占位符由发送层转换为 QQ at 消息段；图片化发送时先发送 at 段再发送图片，图片内显示为 @用户名。
- 普通对话启动时捕获显式 Bot 与目标群号，后续 LangGraph 回调通过 `send_group_msg` 定向发送，不依赖 NoneBot matcher 的 `current_bot/current_event` 临时上下文。
- 发送失败最多尝试五次，每次间隔三秒。
- [hatsumeface:情绪] 会从运行数据 faces/ 中选择同前缀图片并单独发送。

~~~mermaid
flowchart LR
    Input[顶层人类消息 message_id] --> AgentInput[chat_agent 输入]
    AgentInput --> Allowlist[从本次 HumanMessage 顶层 JSON 提取合法 ID]
    AgentInput --> Output[Agent 输出可选 reply 标记]
    Output --> Validate{唯一、位于开头、ID 合法?}
    Validate -- 是 --> ReplySeg[MessageSegment.reply + 主回复]
    Validate -- 否 --> Plain[移除标记并普通发送]
    ReplySeg --> OneBot[OneBot V11]
    ReplySeg -. 发送失败 .-> Plain
~~~

Agent/Timer 从 handlers/dialogue.py 启动的新对话复用同一直接群发送 helper。graph/nodes.py 的 `_start_direct_conv()` 继续通过既有的 lazy import 调用该 helper，避免新增另一套回复拼装逻辑；该导入只在 fallback 启动路径运行。当前对话与新对话的系统触发消息都会在 `human_queue` 中携带内部来源标记；`human_node` 消费时移除该标记，`chat_end_detect_node` 据此跳过结束检测模型并直接进入 `ai_node`。

### 3.7 当前清理边界

/clear 的真实范围是：

- 取消待处理的防抖 Event 和正在运行的图任务。
- 结束共享对话并清空 chat_peers。
- 清空 ConversationState 的 idle、pending、human 消息与来源队列。
- 清空 transcript、source_map，并重置部分运行标记。

/clear 不清空 graph/nodes.py 的模块级辅助队列，因此非 peer 消息和已结束对话的辅助上下文仍可进入后续 ai_node 轮次。辅助队列只在写入后超过 CONTEXT_QUEUE_LEN 时被压缩或在压缩失败后裁剪。

### 3.8 新成员欢迎

- 插件入口用 `is_type(GroupIncreaseNoticeEvent)` 精确匹配 OneBot `group_increase`；仅当群号等于正数 `AUTO_RESPONSE_GROUP_ID` 且加入者不是 Bot 自身时处理。
- handler 通过 OneBot 查询新成员群名片，失败时沿用 QQ 号，并用 `get_qq_avatar_url()` 生成头像 URL。系统 Prompt 包含用户名、QQ 号与头像，要求 at 欢迎、简短自我介绍并说明聊天以外的能力。
- 新成员 session 总会通过 `ConversationState.activate_chat()` 加入 `chat_peers`。已有活跃对话或仍在收尾的图时，Prompt 以 `group_increase` 系统触发标记直接进入 `human_queue`，不启动第二个图；没有对话时复用 `_start_conv_for_trigger()` 启动现有 LangGraph 流程。
- 该系统触发标记由 `human_node` 消费并移除，同时让 `chat_end_detect_node` 跳过结束判断。欢迎回复继续使用统一的直接群发送、Markdown、at 与重试逻辑。

## 4. 记忆保存与检索

### 4.1 持久化边界

SQLite 是记忆 ID 与元数据真源，默认数据库为 data/hatsume-plugin/memory-db/memory.db，并启用 WAL。Milvus Lite 的 data/hatsume-plugin/memory-db/memory_vectors.db 目录保存运行时向量，主键 `memory_id` 与 SQLite `memories.id` 完全相同，使用 1024 维 BGE-M3 向量和 cosine 距离。两个记忆存储统一位于 memory-db/ 目录；新部署会按需创建该目录。进程内不保留全量记忆、分词语料、BM25 索引或向量矩阵。每次向量操作串行打开 Milvus，完成后关闭 PyMilvus 客户端并停止 embedded gRPC server，避免后续 Shell/Docker fork 继承 gRPC 文件描述符。

~~~text
memories
  id          INTEGER PRIMARY KEY
  content     TEXT
  time        INTEGER
  people      JSON text
  tokens      JSON text
  embedding   legacy float32 BLOB or NULL
  created_at  INTEGER
~~~

关联用户固定为：

~~~json
{"user_id": 123, "user_name": "群友"}
~~~

SQLite 的 `embedding` 列在过渡阶段保留为迁移与回滚来源。新记忆不会写该列，运行时检索也不会读取该列。

### 4.2 显式写入

Hatsume 不会把每轮聊天自动保存为长期记忆。

1. 模型在需要保存时输出 [memoryrecord: 记忆内容]。
2. 可选的 [memorykeyman: QQ号1, QQ号2] 指定关联用户。
3. graph/nodes.py 从发送文本中移除标签，并把 QQ 号解析为群昵称。
4. memory/engine.py 的 add_mem() 规范化用户、记录时间并使用参数化 SQL 写入 SQLite，显式 commit 后取得记忆 ID。
5. 随后生成 BGE-M3 向量，并以相同 ID upsert 到 Milvus Lite。
6. 若向量生成或 Milvus 写入失败，SQLite 元数据继续保留，精确检索和 BM25 仍可命中；显式迁移命令可再次补齐缺失向量。

### 4.3 精确优先的混合检索

自动检索发生在 ai_node，主动查询入口是 find_memory。

1. query 按空白拆分并按 casefold 去重。汉字计 2、ASCII 字母计 1，权重至少 5 的词启用精确子串检索；纯数字词不受长度限制。
2. 参数化 SQLite LIKE 直接匹配 `content` 与 `people` 原始 JSON 文本，不使用 SQLite JSON 函数。纯数字只匹配带数值边界的关联 `user_id`。
3. 每条记忆按命中的不同关键词数量降序排列，再按时间和 ID 降序排列；所有精确命中均保留，即使超过默认上限 50。
4. 精确结果不足上限时，从相关用户最近 24 小时记录及最新全局记录中各读取至多“剩余名额的三倍”候选，临时分词并构建 BM25。
5. 同时把完整 query 向量发送给 Milvus，读取“剩余名额的三倍”个 cosine 近邻，再按 ID 批量读取 SQLite 正文。
6. BM25 分数高于 0.1 时加入关键词分量；归一化向量相似度达到配置阈值时加入向量分量，并按 EMBEDDING_WEIGHT 融合。
7. 排除精确命中 ID，按融合分数、时间和 ID 排序，只补足到上限。
8. graph/tools.py 不维护跨调用去重集合；每次查询都把本次全部结果按时间和内容格式注入专用记忆 Prompt，同一记忆可以在同轮多次查询或后续轮次再次出现。

~~~mermaid
flowchart LR
    Query[空格关键词与当前用户] --> Exact[SQLite LIKE 全部精确命中]
    Query --> Bounded[SQLite 有限候选]
    Query --> Milvus[Milvus cosine 搜索]
    Bounded --> BM25[临时 BM25]
    BM25 --> Fusion[按 SQLite ID 融合]
    Milvus --> Fusion
    Exact --> Merge[精确优先合并]
    Fusion --> Merge
    Merge --> Dedup[单轮内容去重]
    Dedup --> Context[记忆上下文]
~~~

### 4.4 启动迁移与每日维护

- 插件导入时执行 init_memory_system()，只初始化 SQLite、Milvus 与必要的旧 JSON 迁移，不加载全表。
- `scripts/migrate_memory_vectors.py` 以 SQLite `mode=ro` 连接分批读取旧向量；合法 BLOB 原样 upsert，空或损坏 BLOB 从正文重建。迁移可重复执行，且不修改 memory.db 的记录或 schema。Milvus Lite 对目录加进程独占锁，因此执行显式迁移前必须停止 Bot。
- 每天亚洲/上海时区 04:30 删除 150 天前的 SQLite 记录，并 best-effort 删除相同 ID 的 Milvus 向量，不重建进程索引。
- Schema 与跨库迁移必须保持幂等，并使用已有数据库、部分失败和源文件哈希测试。

## 5. 定时任务

### 5.1 数据模型

活动数据库由 `nonebot_plugin_localstore.get_plugin_data_file("timer-v2-db/timer.db")` 定位；`LOCALSTORE_USE_CWD=true` 时为 data/hatsume-plugin/timer-v2-db/timer.db。数据库启用 WAL、外键和级联删除。

~~~text
timer_tasks
  id, group_id, user_id, prompt, task_type, schedule_type
  start_at, end_at, step
  total_occurrences, processed_occurrences
  created_at, updated_at

timer_schedule_points
  id, task_id, period_value, clock_time, exact_at
  first_fire_at, last_fire_at
  planned_occurrences, processed_occurrences, last_processed_at, job_id

~~~

- timer_tasks 保存用户规则和任务总进度；timer_schedule_points 保存每个请求的完整周期点及其进度，不展开每次递归触发。没有未来 occurrence 的描述性 point 使用 planned_occurrences=0 且 first_fire_at/last_fire_at 为 NULL，不注册作业也不计入任务总进度，但仍供 list_timers 完整显示。
- schedule point 的 task_id 外键使用 ON DELETE CASCADE，job_id 为稳定的 timer_v2_point_<id>。
- task_type 只允许 normal 或 auto_response；普通群列表和每日清理均排除 auto_response。
- 初始化严格校验两张应用表及其列集合；不兼容 schema 会显式失败，不在运行时升级或回退旧路径。

### 5.2 创建、更新与删除

聊天 Agent 只有四个创建入口：create_daily_timer、create_weekly_timer、create_monthly_timer 和 create_at_timer。

- 频率任务使用含时区、边界包含的 start_at/end_at 与正整数 step。daily 的点为严格 `HH:MM:SS`；weekly 使用 weekday 1..7 与 time；monthly 使用 day 1..31 与 time，不存在目标日期的月份直接跳过。
- 每个频率任务原始时间点列表为 1..5 个，按起始日、起始周或起始月锚定间隔，并计算到包含边界的 end_at；不限制范围内的总触发次数。
- 指定时刻任务接受 1..10 个互不重复、含时区且在未来的 ISO 8601 时间戳。
- 四个工具的 docstring、LangChain 严格整数 schema 与 timer/schedule.py 的执行校验同时声明并落实上述限制；JSON boolean 不会被转换成 step、weekday 或 day，Prompt 仍要求非空且不超过 500 字符。
- daily 与 weekly 每个仍有多次 occurrence 的点注册 IntervalTrigger，monthly 注册 CalendarIntervalTrigger；频率 point 只剩最后一次时与 at 一样注册 DateTrigger，避免为无须执行的下一周期计算超大 step。所有作业使用 UTC+08:00、replace_existing=True 和 coalesce=False，并把 next_run_time 显式固定为数据库中的下一次 occurrence，防止注册跨过首个时刻时静默跳到下一周期。

/timer update 保留原有 `prompt @ timestamps` 语法，但统一调用 exact-time builder，验证最多 10 个时刻后才取消旧作业、事务替换 schedule points 并重新注册。delete 先取消任务的全部 point 作业，再删除任务并由外键级联删除 points。

list_timers 是唯一聊天工具读取入口，按“尚未完成”和“已完成”分组。频率任务展示模式、step、完整起止范围、全部周期点、计划/已处理次数和下一次触发；指定时刻任务展示每个时间戳及其状态。/timer list 和 ai_node system prompt 复用同一 get_timer_overview() 文本。`/timer list` 对所有成员显示当前群；`/timer list <group_id>` 只允许管理员跨群查看，正整数目标群通过显式参数传入 overview，不修改进程级当前群上下文。

### 5.3 启动恢复与清理

Bot 连接后 init_scheduler()：

1. get_store() 从 localstore 路径初始化并严格校验当前 schema。
2. reload_all_schedules() 按 point 已处理下标推导遗漏时间。五分钟容忍窗口以前的 occurrence 只推进进度；窗口内只补偿最近一次；剩余未来 occurrence 重新注册原生作业。
3. refresh_auto_response() 保留并注册一个未来内部任务，或创建 1 至 3 小时后的新任务。
4. 注册 UTC+08:00 每日 03:00:00 的稳定 cron 作业。清理 coroutine 留在事件循环线程，先防御性取消已完成 normal 任务的 point 作业，再删除任务；活动任务和 auto_response 不受影响。

### 5.4 触发与图注入

~~~mermaid
flowchart LR
    Job[APScheduler 原生 point 作业] --> Reconcile[核对 submitted/missed scheduled_at]
    Reconcile --> Execute[_execute_point]
    Execute --> Kind{task_type}
    Kind -- normal --> Inject[inject timer prompt]
    Kind -- auto_response --> Response[回复 Prompt + 1 至 3 小时重排]
    Inject --> Graph[当前或新 LangGraph 对话]
    Response --> Graph
    Execute --> Progress[更新 point 与 task 进度]
~~~

- normal 任务通过 inject_timer() 注入定时任务 Prompt。
- 有活跃对话时进入 human_queue；无活跃对话时通过 dialogue 注册的回调为目标群启动新图。
- Timer 注入的内部来源标记只用于绕过结束检测，进入聊天模型前会被移除。
- user_id 非零时，注入 Prompt 会告诉模型可用 `[CQ:at,qq=<user_id>]` 提醒用户，实际 at 由发送层转换。
- normal 路径在图注入尝试结束后原子推进 point 与 task 计数；即使注入抛出异常也视为已处理。
- APScheduler listener 按 point 保存 EVENT_JOB_SUBMITTED 的实际 scheduled_run_times；callback 先把超出五分钟容忍窗口的旧时刻推进为过期，再只注入当前有效时刻。全批次均过期时由 EVENT_JOB_MISSED 推进进度，避免 callback 用数据库下标重建时间而发生永久偏移。
- progress 以 scheduled_at 和 last_processed_at 幂等更新，重复恢复不会再次计数或注入同一 occurrence。
- auto_response 在执行提示前先推进其 exact point，并保证即使注入失败也排期下一条任务，不等待 LLM 完成。

### 5.5 自动任务

- auto_response 向 AUTO_RESPONSE_GROUP_ID 注入主动参与群聊的 Prompt，不 @ 用户，并在 1 至 3 小时后重新排期。启动时自动确保存在未来任务。
- 自动回复目标群号未配置或不大于 0 时禁止注入和重新排期；auto_response 启动恢复还会取消并清理残留待触发任务，避免向 group_id=0 发送消息。
- 调试命令默认使用命令所在群；参数 prod 才使用配置中的固定群。

## 6. 聊天工具、后台 Agent 与 Skill

### 6.1 CHAT_TOOLS

所有聊天工具只在 graph/tools.py 的 CHAT_TOOLS 注册一次。

| 工具 | 作用 |
|---|---|
| search_web | DuckDuckGo 联网搜索 |
| search_image | 通过 Pexels 搜索真实照片，返回图片 URL 与摄影师来源信息 |
| shell_executor | Docker 沙盒同步命令；普通聊天每轮最多三次 |
| find_memory | 主动检索长期记忆 |
| view_image | 使用轻量模型读取网络或沙盒图片并返回文字描述 |
| generate_image | 图片生成，支持参考图与 60 秒限流 |
| generate_video | 生成视频并返回临时 URL；每轮最多一次 |
| send_image | 发送 HTTP、base64 或沙盒文件；每轮最多三张 |
| send_video | 发送 HTTP URL、沙盒绝对路径或沙盒文件；每轮最多一个 |
| get_avatar | 获取 QQ 头像 URL |
| random_acg_photo | 从 macOS Photos 导出 ACG 图片到沙盒 |
| create_daily_timer | 创建含起止边界、1..5 个 `HH:MM:SS` 点和天间隔的任务 |
| create_weekly_timer | 创建含 weekday/time 周期点和周间隔的任务 |
| create_monthly_timer | 创建含 day/time 周期点和月间隔的任务 |
| create_at_timer | 创建含 1..10 个指定时间戳的任务 |
| create_todo | 为当前群创建最长保留 48 小时的待办，保存发起人群名片与严格完成条件 |
| mark_todo | 完成并删除当前群待办，返回必须 @ 发起人的完成通知信息 |
| list_timers | 按完成状态显示完整频率规则或全部指定时刻 |
| delete_timer | 删除当前群任务 |
| skill_loader | 加载 Skill 完整指令 |
| skill_remove | 删除 Skill |
| skill_download | 从 raw URL 下载 Skill |
| skill_create | 从完整 Markdown 创建 Skill |
| membersearch | 模糊搜索当前群成员 |
| agent_dispatch | 派发后台 Agent |
| respond_to_shell_prompt | 回复后台进程 stdin 请求 |
| end_conversation | 用户要求不再回复时立即结束当前对话，直到再次被主动提及 |
| create_character_proxy(proxied_user_id, during_time=180) / terminate_character_proxy | 根据 RAM 代理开关互斥提供；持续时间以分钟计，默认 180，范围 1 至 1440，超时自动终止 |

configure_tool_callbacks() 在每次新图启动时注入发送回调、当前用户、检索集合和媒体限流回调。当前群号、Agent 通知回调和部分工具计数仍是 graph/tools.py 的模块级状态；graph/nodes.py 通过 get_current_group_id() 动态读取群号，避免导入整数快照。Shell 次数使用 ContextVar 区分普通聊天与 coding_agent。get_chat_tools() 根据 character_proxy.py 的单一 RAM 状态过滤生命周期工具：关闭时只有 create_character_proxy，开启时只有 terminate_character_proxy。

### 6.2 群聊待办

todo/store.py 通过 nonebot_plugin_localstore 定位 `todo-db/todo.db`，只保存 `todo_items` 表。每条记录包含 ID、群号、发起人 QQ ID、创建时解析得到的群名片、待办内容、创建时间和完成条件。完成条件固定由 `Permitted finisher` 与 `Completion event` 两个自由文本子句组成；内容和每个子句均不能为空且最多 500 字符。

容量、可见性和完成操作均按群隔离。create_todo 在 `BEGIN IMMEDIATE` 事务内先清理过期行，再检查相同群、发起人、内容和条件的精确重复，最后检查该群是否已有 15 条；重复时返回已有 ID，满额时拒绝且不驱逐旧项。mark_todo 同样在事务内重做过期清理，只按当前群与 ID 查询，成功后立即硬删除，不保留历史。

ai_node 每次进入时全局删除 `created_at <= now - 48h` 的记录，再按 `created_at, id` 读取当前群。prompts.py 把活动记录以结构化数据注入 role system prompt，并明确规定：可从当前聊天主动创建、不得仅从背景聊天创建、避免语义重复、允许结合近期上下文判断完成、必须同时满足允许完成人与完成事件。mark_todo 成功结果要求 chat_agent 在同一自然回复中使用 `[CQ:at,qq=...]` 提及发起人，并说明完成来自条件满足而非过期。过期只删除，不发送通知。

TodoStore 使用进程级惰性单例、WAL、参数化 SQL、显式 commit 和 busy timeout。初始化失败会关闭候选连接并允许下次重试；ai_node 捕获读取失败并继续聊天。运行时没有 Todo 调度器、QQ 命令、编辑/手动删除工具或完成历史表。

### 6.3 角色代理

character_proxy.py 只维护一个进程级 CharacterProxy 和一个自动终止 TimerHandle，包含被代理用户 ID、昵称、外号、一次生成的行为 Prompt 和带时区的自动结束时间，不写入 SQLite，进程重启即丢失。创建时通过 memory.get_recent_user_memories() 从 SQLite 按需读取该用户最新最多 100 条关联记忆，再用一次轻量模型调用以 JSON 同时生成行为 Prompt 和外号列表，并把包含外号的完整角色 Prompt 打印到控制台；持续时间默认 180 分钟且不得超过 1440 分钟，到期或手动终止时清空对象并取消定时句柄。

handlers/dialogue.py 在普通消息入口检查原始 at 消息段。其他群成员明确 @ 被代理用户时，只调用 ConversationState.activate_chat(session_id) 把该发送者加入 chat_peers；后续防抖、队列、LangGraph 和回复发送完全复用现有对话流程。

chat_end_detect_node 在调用结束检测模型前解析最新规范化消息的正文；正文包含当前被代理用户昵称或任一外号时直接继续对话。匹配不扫描发送者等元数据，避免同名发送者造成误判。

ai_node 在代理开启时把行为画像和带时区的自动结束时间附加到 role system prompt。该 Prompt 规定只有当前消息明确 @ 被代理用户时才模仿；与初芽的普通对话、Agent 通知和 Timer 通知继续使用初芽身份。终止工具执行后，下一次 ai_node 不再注入该 Prompt。

### 6.4 Agent 注册与通知

graph/agents.py 维护 AGENT_REGISTRY 和 _AGENT_STATES。

~~~mermaid
sequenceDiagram
    participant L as Chat LLM
    participant T as agent_dispatch
    participant R as AGENT_REGISTRY
    participant A as 后台 Agent
    participant N as 图通知
    L->>T: agent_name、task、context、user
    T->>R: 查找 handler
    T->>A: asyncio.create_task
    T-->>L: 已启动
    A->>A: 更新实例、进程与 stdin 状态
    A-->>T: 中间或最终结果
    T->>N: inject_agent_notification
    N->>N: 当前 human_queue 或新对话
~~~

- coding_agent 使用代码模型，可调用 shell_executor、Skill 工具、网页与 Pexels 图片搜索、图片生成；它把 Shell 上限设为无限制。
- background_shell 先把任务解析为单条命令、终止条件和总超时，然后后台启动进程并增量读取日志。
- 后台决策支持 DONE、KILL、CONTINUE:N、NOTIFY:N 与 INPUT_NEEDED:<timeout>:<description>。
- 每次派发生成唯一 instance_id，保存任务、上下文、用户、开始时间、状态和结果。
- 中间通知与最终结果作为普通系统提示进入当前或新图；需要提醒用户时由模型输出 `[CQ:at,qq=...]` 占位符。
- stdin 请求使用 request_id -> asyncio.Queue 保存。聊天模型调用 respond_to_shell_prompt() 后，后台 Agent 再用代码模型把原始回复转换为最终进程输入。
- Agent 状态与当前群号只保存在内存中，进程重启后不会恢复。

### 6.5 Skill

- skills/manager.py 扫描配置目录中的 Markdown 文件并解析 YAML frontmatter。
- 有效 Skill 至少需要名称、描述和正文。
- list_skills() 只把名称与描述注入系统 Prompt；需要完整指令时由 skill_loader 按需加载。
- 同一对话内记录已加载名称，避免重复加载；finish 会重置该集合。
- skill_create、skill_download 与 skill_remove 修改运行时 Skill 文件并清理缓存，新 Skill 无需重启即可使用。

### 6.6 高级模型运行时切换

- config.py 的 ADVANCE_MODEL_NAME 保存当前进程使用的高级模型名，初始值由源码配置决定。
- 管理员发送 /model 可查看当前值；/model <模型名> 会原样保留模型标识的大小写和标点，只去除首尾空白。
- get_advance_model() 每次创建客户端时读取最新值，并继续调用未改动的 get_standard_api_model()。因此 PROVIDER、Base URL、API Key、Responses API 和上下文压缩配置都不会随命令变化。
- 该选择只保存在当前进程内，不写入 .env.prod、SQLite 或其他持久化文件；进程重启后恢复源码默认值。多进程部署需要分别设置每个进程。

## 7. Docker、媒体与输出

### 7.1 Docker 生命周期

- infra.py 通过 virtual/launch_image.sh 进入名为 hatsume-space-kali 的持久化容器。
- run_cmd() 把命令写入 virtual/script.sh，通过异步子进程合并 stdout/stderr，并移除 ANSI 控制符。
- 前台默认超时为 300 秒；shell_executor 也允许调用方显式传入 timeout。
- 后台命令把 stdout/stderr 合并到临时日志，通过 offset 增量读取，并支持 stdin。
- 活跃命令使用引用计数。最后一个进程释放后等待五分钟再停止容器；新任务会取消待执行的停止任务。
- /resetsandbox 调用容器删除脚本并重置进程内活动标记。
- 容器构建脚本位于 virtual/image/ 与 virtual/*.sh，但公开仓库不包含预构建镜像归档和可直接运行的容器。

### 7.2 图片与视频

- 输入图片使用 requests 同步下载，限制为 9 MiB 和 3600 万像素。
- 普通消息与回复图片使用 Pillow 检测实际格式，并通过 infra.py 的 Docker 边界复制到 `/tmp/hatsume-user-images`；路径由 QQ 消息 ID 与消息内图片序号确定。应用不会主动清理这些文件，容器环境或 `/resetsandbox` 可按既有生命周期移除它们。
- 回复图片优先复用沙盒中的确定性路径，缺失时从 OneBot 临时 URL 恢复；合并转发图片保持临时 URL。主聊天模型只接收包含 Markdown 路径的 JSON 文本块，需要理解图片时通过 `view_image(file://...)` 读取。
- search_image 使用固定的 Pexels Search API，通过 PIXELS_API_KEY 鉴权；网络请求在线程中执行，最多返回十条带来源信息的候选结果，再由聊天 Agent 复用 send_image 发送。
- view_image 将 HTTP/HTTPS 图片 URL 直接交给轻量模型；沙盒 file:// 绝对路径先检测图片 MIME 并转换为 data URI，再返回模型生成的文字描述。
- generate_image 在 Seedream 和兼容图像接口之间选择；有参考图时使用支持参考图的路径。
- 沙盒绝对路径会先在 Docker 内读取并转换为 data URI。
- generate_video 在 Seedance 1.0 与 1.5 之间选择，轮询供应商任务直至完成或失败。
- random_acg_photo 通过 AppleScript 从 macOS Photos 的 ACG 相册导出到宿主临时目录，再用 docker cp 放入沙盒。
- 戳一戳路径直接读取宿主导出文件并以 base64 图片发送；失败时静默返回。

### 7.3 Markdown 渲染与脱敏

utils/md_to_image.py 在文本超过 500 字或包含富 Markdown 时：

- 使用 Python Markdown、Pymdown 扩展和代码高亮生成 HTML。
- 支持表格、任务列表、KaTeX 公式、明暗主题和随机角色印章。
- 使用 nonebot-plugin-htmlrender 截图。
- 把原文 URL 作为额外文本段保留，使图片中的链接仍可点击。
- 渲染失败时回退为纯文本。

utils/security.py 在文本发送边界遮盖常见 OpenAI、GitHub、Ark、AK 与 NVIDIA 等凭证形式。图片、视频和其他非文本消息段不会被文本正则处理。

## 8. 项目结构与运行时模块

### 8.1 目录与依赖方向

~~~text
hatsume/plugins/hatsume-plugin/
├── __init__.py
├── config.py
├── infra.py
├── models.py
├── prompts.py
├── state.py
├── graph/
├── handlers/
├── memory/
├── skills/
├── timer/
├── utils/
└── virtual/
~~~

~~~mermaid
flowchart TD
    Entry[__init__.py] --> Dialogue[handlers/dialogue.py]
    Entry --> Commands[handlers/tools.py]
    Entry --> Social[handlers/social.py]
    Entry --> Memory[memory]
    Entry --> Timer[timer]
    Dialogue --> Forward[handlers/forward.py]
    Dialogue --> State[state.py]
    Dialogue --> Builder[graph/builder.py]
    Builder --> Nodes[graph/nodes.py]
    Nodes --> Tools[graph/tools.py]
    Nodes --> Models[models.py]
    Nodes --> Prompts[prompts.py]
    Nodes --> Skills[skills]
    Tools --> Agents[graph/agents.py]
    Tools --> Memory
    Tools --> Timer
    Tools --> Todo
    Tools --> Infra[infra.py]
    Timer --> Nodes
    Commands --> Infra
~~~

graph/tools.py、graph/agents.py、graph/nodes.py 与 handlers/dialogue.py 之间存在为回调和通知服务的延迟导入。新增依赖时应避免扩大循环，并在本文档记录初始化顺序。

### 8.2 完整运行时 Python 模块

| Python 模块 | 职责说明 |
|---|---|
| `hatsume/plugins/hatsume-plugin/__init__.py` | 唯一插件入口；初始化记忆；Bot 连接后恢复 Timer；修补 @ 检测；注册命令、聊天 matcher、戳一戳与新成员事件。 |
| hatsume/plugins/hatsume-plugin/config.py | 加载 .env.prod；定义机器人身份、模型和供应商配置读取器，以及队列、限流、图片、记忆、Todo、Timer、Docker 与 Skill 常量。文档只记录变量名，不记录真实值。 |
| hatsume/plugins/hatsume-plugin/state.py | 定义 ConversationState。当前由 dialogue 创建一份进程级共享实例，拥有 chat_peers、idle/pending/human 队列、图任务、限流时间、回复回调和记录上下文。 |
| hatsume/plugins/hatsume-plugin/models.py | 修补 LangChain OpenAI 消息转换以保留 reasoning_content 与 thought_signature；按运行时 ADVANCE_MODEL_NAME 创建高级模型，并创建轻量、迷你、代码模型和 Embedding；封装图片与视频供应商。 |
| hatsume/plugins/hatsume-plugin/prompts.py | 保存角色、Skill、Agent 状态、辅助上下文压缩、表情、结束检测、记忆、Todo、角色代理、编码 Agent、自动任务和后台 Shell Prompt。 |
| hatsume/plugins/hatsume-plugin/character_proxy.py | 保存全局唯一的 RAM 角色代理，一次生成行为画像与外号，匹配正文称呼，识别 @ 目标并通过 ConversationState 激活 chat peer。 |
| hatsume/plugins/hatsume-plugin/infra.py | 管理 Docker 容器启动、停止和删除；前台命令、后台进程、日志读取、stdin、超时、引用计数与延迟停止。 |
| `hatsume/plugins/hatsume-plugin/handlers/__init__.py` | handlers 包说明。 |
| hatsume/plugins/hatsume-plugin/handlers/dialogue.py | 标准化 OneBot 消息为 LLM JSON 和多模态内容；维护共享 ConversationState；把所有非 peer 消息路由到 auxiliary，把 peer 消息路由到 pending/human；处理新成员欢迎任务；启动图并发送、重试 AI 回复；注册 Agent 与 Timer 新对话回调。 |
| hatsume/plugins/hatsume-plugin/handlers/forward.py | 规范化 get_forward_msg 的标准与厂商返回结构；递归解析 forward/node；渲染消息段并收集用户。 |
| hatsume/plugins/hatsume-plugin/handlers/social.py | 执行 QQ 点赞、把累计次数保存到 likes.json，并生成排行榜。 |
| hatsume/plugins/hatsume-plugin/handlers/tools.py | 实现戳一戳、Shell、视频、Timer、Skill 列表、成员搜索、/model、沙盒重置、Agent 查询、/clear 和自动任务调试命令；共享状态由 dialogue 注入。 |
| `hatsume/plugins/hatsume-plugin/graph/__init__.py` | graph 包说明。 |
| hatsume/plugins/hatsume-plugin/graph/builder.py | 构建并编译 human -> chat_end_detect -> chat_llm -> human 图，连接 finish 与 END。 |
| hatsume/plugins/hatsume-plugin/graph/nodes.py | 实现 Human、Detect、AI、Finish；拥有模块级辅助队列与表情状态；处理记忆标签、Skill/Agent/Timer/Todo 注入、@ 回复和对话结束。 |
| hatsume/plugins/hatsume-plugin/graph/tools.py | 定义并唯一注册 CHAT_TOOLS；维护工具回调、当前群号、媒体与发送次数、Shell 上限；负责 Todo 操作、Agent 派发和 stdin 回复。 |
| hatsume/plugins/hatsume-plugin/graph/agents.py | 维护 AGENT_REGISTRY、并发实例状态和 stdin 队列；实现 coding_agent 与 background_shell。 |
| `hatsume/plugins/hatsume-plugin/memory/__init__.py` | 统一导出记忆数据库、规范化、检索和分词 API。 |
| hatsume/plugins/hatsume-plugin/memory/engine.py | 管理 memories SQLite、原文 LIKE、有限候选 BM25、显式写入、JSON 迁移、Milvus 结果融合和每日过期清理。 |
| hatsume/plugins/hatsume-plugin/memory/vector_store.py | 封装 Milvus Lite collection、ID 向量 CRUD、cosine 搜索和 SQLite 只读向量迁移。 |
| hatsume/plugins/hatsume-plugin/memory/tokenizer.py | 使用 Jieba 词性标注过滤并保留有意义的中文词，供临时 BM25 查询使用。 |
| `hatsume/plugins/hatsume-plugin/todo/__init__.py` | 暴露 TodoStore 类型和可失败重试的进程级惰性单例。 |
| hatsume/plugins/hatsume-plugin/todo/store.py | 通过 localstore 定位 Todo SQLite，管理严格单表 schema、48 小时过期、每群 15 条容量、精确去重和按群完成删除。 |
| `hatsume/plugins/hatsume-plugin/skills/__init__.py` | 暴露 SkillManager 并提供进程级单例。 |
| hatsume/plugins/hatsume-plugin/skills/manager.py | 扫描 Markdown Skill、解析 frontmatter、缓存内容、单轮加载去重、保存覆盖、删除和目录创建。 |
| `hatsume/plugins/hatsume-plugin/timer/__init__.py` | 提供 TimerStore 单例，并按 recovery -> auto_response -> cleanup 顺序启动。 |
| hatsume/plugins/hatsume-plugin/timer/schedule.py | 严格解析四类 schedule、生成 occurrence，并按下标推导触发时间。 |
| hatsume/plugins/hatsume-plugin/timer/store.py | 通过 localstore 定位数据库，严格校验 timer_tasks 与 timer_schedule_points，执行任务 CRUD、原子进度、exact replacement、完成清理和 auto_response。 |
| hatsume/plugins/hatsume-plugin/timer/executor.py | 构建和管理原生 APScheduler triggers，执行/恢复 point、注入图、维护 auto_response，并注册每日 03:00 清理。 |
| `hatsume/plugins/hatsume-plugin/utils/__init__.py` | QQ 昵称查询、时间、头像 URL、统一消息 JSON、forward JSON 和带五分钟缓存的成员模糊搜索。 |
| hatsume/plugins/hatsume-plugin/utils/md_to_image.py | Markdown、代码、公式和表格到 HTML 与图片的转换，包含主题、角色印章、链接提取和纯文本回退。 |
| hatsume/plugins/hatsume-plugin/utils/security.py | 无框架依赖的敏感凭证正则识别与脱敏。 |

virtual/ 下是 Shell 和 Docker 构建、启动、停止、删除脚本，不是 Python 模块。
## 9. 测试模块索引

测试必须离线且可重复，不得依赖真实 QQ、模型 API、Docker、Apple Photos 或网络。目录级规则见 tests/AGENTS.md。

| 测试模块 | 覆盖内容 |
|---|---|
| tests/test_agent_dispatch.py | Agent 注册、处理器查找与上下文读取。 |
| tests/test_agent_monitor.py | Agent 状态写入、运行判断、字段保留与开始时间。 |
| tests/test_agents_command.py | /agents 在无任务、运行中、完成与混合状态下的输出。 |
| tests/test_ai_json_output.py | 角色 Prompt 不再要求旧 JSON 输出格式、ADMIN MODE 动态 Prompt，以及 AI JSON 与非 JSON 兼容行为。 |
| tests/test_auto_response.py | v2 自动回复随机时间范围、目标群禁用、启动单例、执行前进度与后继排期。 |
| tests/test_background_shell_agent.py | 后台 Shell 注册、任务解析和 DONE/CONTINUE/NOTIFY/TIMEOUT/KILL 决策。 |
| tests/test_background_shell_infra.py | 后台日志增量读取与进程终止清理。 |
| tests/test_background_shell_prompts.py | Shell 决策 Prompt 和 stdin 解析 Prompt 约束。 |
| tests/test_background_shell_stdin.py | stdin 写入、换行补齐、退出进程处理与队列清理。 |
| tests/test_background_shell_stdin_integration.py | stdin 请求、用户回复、模型转换与进程输入集成链路。 |
| tests/test_chat_send.py | AI 文本、图片、视频发送、@、重试、分段与边界行为。 |
| tests/test_character_proxy.py | 单一 RAM 状态、终止销毁、@ 目标 peer 激活、行为画像与身份作用域。 |
| tests/test_container_lifecycle.py | Docker 引用计数、延迟停止、取消停止与清理。 |
| tests/test_conversation.py | ConversationState、对话激活与结束、队列刷新、启动流程及目标群新成员欢迎。 |
| tests/test_forward.py | OneBot 标准与厂商变体、嵌套 forward、异常占位和用户收集。 |
| tests/test_graph_nodes.py | Human、AI、Detect、Finish、辅助上下文、记忆标签、ADMIN MODE、通知与清理。 |
| tests/test_md_to_image.py | Markdown 特征检测、链接保留、渲染与纯文本回退。 |
| tests/test_membersearch.py | 成员缓存、子串匹配、字符重叠排序、命令与工具结果。 |
| tests/test_memory_db.py | 记忆 SQLite 建表、原文 LIKE、精确排序、按需混合检索、写入与生命周期。 |
| tests/test_memory_utils.py | 每日过期清理及旧检索兼容测试。 |
| tests/test_memory_vector_store.py | 临时 Milvus Lite CRUD、cosine 搜索、只读迁移、幂等性与源 SQLite 哈希。 |
| tests/test_models_mimo.py | 模型工厂与特定兼容模型配置。 |
| tests/test_omni_model.py | 多模态或 Omni 模型选择判断。 |
| tests/test_pipeline_json.py | 普通消息与合并转发统一 JSON 格式。 |
| tests/test_random_acg_photo.py | ACG 相册导出、空相册、Photos 未运行和 Docker 复制失败。 |
| tests/test_reasoning_content.py | reasoning_content 在 LangChain 消息转换中的往返保留。 |
| tests/test_secret_gate.py | 多类 API Key 脱敏与误报边界。 |
| tests/test_skill_create.py | Skill 保存、覆盖、缓存失效与 frontmatter 校验。 |
| tests/test_skill_manager.py | Skill 扫描、加载去重、缓存、删除、目录创建与 Prompt 列表。 |
| tests/test_thought_signature.py | thought_signature 修补、捕获、恢复、缺失兼容，以及高级模型名向标准工厂的动态转发。 |
| tests/test_todo_prompt.py | Todo role prompt 的字段格式、创建/完成规则、低信任数据边界和不可用状态。 |
| tests/test_todo_startup.py | TodoStore 单例初始化失败关闭、重试恢复和复用。 |
| tests/test_todo_store.py | Todo localstore 路径、单表 schema、群隔离、48 小时边界、容量、去重、并发和硬删除。 |
| tests/test_timer_injection.py | Timer 标记检测、活跃或非活跃会话注入与完整投递上下文。 |
| tests/test_timer_schedule.py | 四种规则解析、严格时间格式、锚定间隔、超大正整数 step、无效月份跳过、5/10 限制和无频率总次数上限。 |
| tests/test_timer_store.py | localstore 路径、严格 v2 schema、任务/point CRUD、幂等进度、exact replacement、级联删除和完成清理。 |
| tests/test_timer_executor.py | 原生 trigger、最终 occurrence 降级、注册/取消、实际 scheduled_at 漏触发核对、执行后进度、启动恢复和 03:00 清理。 |
| tests/test_timer_startup.py | TimerStore 单例初始化失败重试及 recovery/auto_response/cleanup 启动顺序。 |
| tests/test_tools.py | 图片、视频、发送限流、头像、记忆格式、Todo、四类 Timer 工具与详细列表、/timer、/model、角色 Prompt 和 stdin。 |

常用验证：

~~~bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
~~~

先运行与改动模块直接相关的聚焦测试，再运行完整检查。不得屏蔽 collection error、resource warning 或类型错误。

## 10. 运行数据与开源边界

### 10.1 私有配置

config.py 会在本地加载 .env.prod，但公开仓库不提供该文件或任何真实值。生产联调至少需要由维护者按实际环境提供以下配置：

- Bot 与权限：BOT_QQ_ID、ADMIN_QQ_ID、AGENT_QQ_EMAIL。
- 自动任务目标：AUTO_RESPONSE_GROUP_ID。
- Agent 仓库身份：GITHUB_ACCOUNT、GITHUB_REPO。
- 模型与媒体供应商：ARK_PLAN_API_KEY、ARK_API_KEY、SILICONFLOW_API_KEY、OPENCODE_API_KEY、KEGEAI_API_KEY、ZHTH_API_KEY、PIXELS_API_KEY。
- Docker：DOCKER_ENV_PATH；未设置时指向源码内 virtual/ 目录。
- NoneBot 与 OneBot 连接配置，例如 DRIVER、LOCALSTORE_USE_CWD、ONEBOT_ACCESS_TOKEN。

身份和群号未配置时使用空字符串或 0，只用于让导入、静态检查和离线测试保持可执行，不代表可用的生产默认值。文档、测试和示例不得写入真实凭证或私人 QQ 标识。

### 10.2 运行数据

data/ 是运行时目录，常见内容包括：

- data/hatsume-plugin/memory-db/memory.db*：长期记忆数据库及 WAL/SHM。
- data/hatsume-plugin/memory-db/memory_vectors.db/：Milvus Lite 记忆向量数据库目录。
- data/hatsume-plugin/timer-v2-db/timer.db*：当前定时任务数据库及 WAL/SHM。
- data/hatsume-plugin/todo-db/todo.db*：每群对话待办数据库及 WAL/SHM。
- data/hatsume-plugin/likes.json：累计点赞数据。
- data/hatsume-plugin/skills/：运行时安装或创建的 Skill。
- data/hatsume-plugin/faces/：AI 表情和 Markdown 印章图片。
- 生成、下载或导出的媒体文件。
- data/nonebot_plugin_htmlrender/ 等插件缓存。

以下内容属于本地运行资产，不是公开源码的一部分：

- .env.prod 与任何真实 API Key。
- data/ 下的必要运行数据。
- hatsume-space-kali 的预构建 Docker 镜像归档和已创建容器。
- hatsume/plugins/hatsume-plugin/virtual/script.sh 这类运行时生成脚本。

因此公开仓库不能直接启动生产 Bot，但依赖安装、源码修改和离线单元测试不依赖这些私有资产。任何持久化、队列顺序、图边、模块所有权或外部集成变化，都必须同步更新本文档。
