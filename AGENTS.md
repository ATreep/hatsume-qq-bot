# IMPORTANT
Update `AGENTS.md` and `README.md` automatically when there are massive changes applied before executing git commit and push.

# Hatsume Repository Guide

Hatsume 是 Python 3.12+ 的 QQ 群聊 AI 机器人，以 NoneBot2 插件运行并通过 OneBot V11 接入。LangGraph 负责多轮对话；每群 runtime 隔离对话和可变资源，不同群可并行；SQLite 保存长期记忆元数据和定时任务，Milvus Lite 保存记忆向量；聊天工具、后台 Agent、Docker 沙盒、运行时 Skill 与媒体生成提供扩展能力。

`AGENTS.md` 是本仓库唯一的仓库级 Agent 指令源。Codex 和 Claude Code 都必须读取本文件及目标目录内更具体的 `AGENTS.md`。

## Navigate First

1. 项目简介、开源限制与 Agent 开发入口：`README.md`
2. 完整功能、关键流程、当前架构与全部 Python 模块说明：`docs/arch.md`
3. 运行时插件局部规则：`hatsume/plugins/hatsume-plugin/AGENTS.md`
4. 测试规则：`tests/AGENTS.md`
5. NoneBot 入口：`hatsume/plugins/hatsume-plugin/__init__.py`
6. 功能规格与历史决策：`specs/`、`docs/superpowers/`

## Complete Capability Map

- 对话：@/关键词触发、每群单图串行、跨群并行、空闲旁听、10 秒输入合并、5 分钟等待、结束检测、辅助上下文压缩、Markdown 图片化。
- 消息：文本、回复、@、图片、多模态输入、OneBot 标准/厂商变体合并转发、嵌套 forward。
- 记忆：按群隔离的可重复 `[memory: ... MEMORYCONTENTEND, keyman: ...]` 记忆卡写入、SQLite LIKE、临时 BM25、Milvus Lite + BGE-M3、150 天清理。
- 工具：搜索、Shell、记忆、图片/视频生成、图片发送、QQ 头像、Timer、Skill、成员搜索、Agent 派发、stdin 回复。
- Agent：`coding_agent`、`background_shell`、实例状态、中间通知、完成通知、交互输入。
- Timer：普通多触发任务、群内管理、重启恢复、漏触发补偿、按非黑名单 activated group 独立自动回复。
- 社交：点赞、累计点赞排行榜、白名单群戳一戳随机图片。
- 运维：高级模型热切换、每群 Docker 容器与引用计数、延迟停止、沙盒重置、Agent 监控、凭证脱敏。

## Source Ownership

```text
hatsume/plugins/hatsume-plugin/
├── __init__.py       # matcher、生命周期、记忆/定时器启动
├── config.py         # 环境变量、模型名、行为常量
├── group_runtime.py  # 每群 runtime registry、ContextVar 与关机清理
├── state.py          # 每群 ConversationState 与会话可变状态
├── models.py         # LLM/Embedding/图片/视频模型工厂
├── prompts.py        # 角色、图节点、Agent 与自动任务 Prompt
├── infra.py          # Docker 与后台进程生命周期
├── handlers/         # OneBot 边界、消息解析、命令、社交功能
├── graph/            # LangGraph 节点、聊天工具、后台 Agent
├── memory/           # SQLite 元数据、Milvus 向量、分词与混合检索
├── character_proxy.py # 单一 RAM 角色代理、行为画像与 peer 激活
├── timer/            # SQLite 定时任务、APScheduler 执行
├── skills/           # Markdown Skill 扫描、缓存、增删
└── utils/            # QQ JSON、成员搜索、渲染、密钥脱敏
```

### Runtime Python Modules

- `hatsume/plugins/hatsume-plugin/__init__.py`：唯一 matcher 注册入口；不要在其他模块重复注册命令。
- `hatsume/plugins/hatsume-plugin/config.py`：配置与常量所有者；文档只记录变量名，禁止记录真实值。
- `hatsume/plugins/hatsume-plugin/group_runtime.py`：按正整数群号持有稳定 runtime 和目标 Bot 路由，并提供 OneBot 群发现、任务本地绑定、图启动锁和关机清理。
- `hatsume/plugins/hatsume-plugin/state.py`：每群 ConversationState 的消息队列、图任务、限流和回调所有者；新增状态必须定义初始化与清理。
- `hatsume/plugins/hatsume-plugin/models.py`：模型协议兼容、运行时高级模型选择和供应商 SDK 边界。
- `hatsume/plugins/hatsume-plugin/prompts.py`：所有长 Prompt 与动态 Prompt 构建器。
- `hatsume/plugins/hatsume-plugin/infra.py`：每群 Docker 容器、前台/后台进程、stdin、引用计数与停止策略。
- `hatsume/plugins/hatsume-plugin/handlers/__init__.py`：handlers 包说明。
- `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`：消息标准化、队列、防抖、图启动和回复发送。
- `hatsume/plugins/hatsume-plugin/handlers/forward.py`：OneBot forward 兼容层与递归解析。
- `hatsume/plugins/hatsume-plugin/handlers/qqface.py`：QQ 系统表情 ID 到文本描述的映射；未知 ID 不进入模型文本。
- `hatsume/plugins/hatsume-plugin/handlers/social.py`：点赞及本地排行榜。
- `hatsume/plugins/hatsume-plugin/handlers/tools.py`：命令和戳一戳处理；戳一戳先检查群白名单，群相关操作显式绑定或选择目标 runtime。
- `hatsume/plugins/hatsume-plugin/graph/__init__.py`：graph 包说明。
- `hatsume/plugins/hatsume-plugin/graph/builder.py`：图节点和条件边的唯一组装处。
- `hatsume/plugins/hatsume-plugin/graph/nodes.py`：Human/Detect/AI/Finish、辅助队列、记忆标签和通知注入。
- `hatsume/plugins/hatsume-plugin/graph/tools.py`：聊天工具定义与 `CHAT_TOOLS` 唯一注册点。
- `hatsume/plugins/hatsume-plugin/graph/agents.py`：`AGENT_REGISTRY`、实例状态、内置 Agent 与 stdin 队列。
- `hatsume/plugins/hatsume-plugin/memory/__init__.py`：记忆 API 统一导出。
- `hatsume/plugins/hatsume-plugin/memory/engine.py`：记忆 SQLite、activated-group RAM 集合、按需 BM25、写入、检索和每日维护。
- `hatsume/plugins/hatsume-plugin/memory/vector_store.py`：Milvus Lite 向量 CRUD、搜索和只读 SQLite 向量协调。
- `hatsume/plugins/hatsume-plugin/memory/tokenizer.py`：Jieba 词性分词规则。
- `hatsume/plugins/hatsume-plugin/character_proxy.py`：每群 RAM 角色代理、自动终止、群内记忆画像生成和 @ 目标 peer 激活。
- `hatsume/plugins/hatsume-plugin/timer/__init__.py`：TimerStore 单例与启动恢复。
- `hatsume/plugins/hatsume-plugin/timer/store.py`：任务/触发器数据模型、CRUD、特殊任务和验证。
- `hatsume/plugins/hatsume-plugin/timer/executor.py`：APScheduler 作业、恢复补偿和图注入。
- `hatsume/plugins/hatsume-plugin/skills/__init__.py`：公共只读 Skill manager 与每群本地 overlay。
- `hatsume/plugins/hatsume-plugin/skills/manager.py`：frontmatter、扫描、公共只读约束、群内缓存、单轮去重、保存和删除。
- `hatsume/plugins/hatsume-plugin/utils/__init__.py`：QQ 辅助、统一消息 JSON、成员模糊搜索。
- `hatsume/plugins/hatsume-plugin/utils/md_to_image.py`：Markdown/公式/代码到图片及链接保留。
- `hatsume/plugins/hatsume-plugin/utils/security.py`：纯文本凭证脱敏。

完整测试模块目录与逐文件说明见 `docs/arch.md` 的“测试模块索引”。

## Critical Logic Invariants

### Conversation

1. `GroupRuntimeRegistry` 按正整数 `group_id` 返回稳定 runtime；群相关 API 必须使用 task-local 绑定或显式群号，禁止回退到最近群或默认群。
2. 外部触发和群成员查询必须从 registry 取得目标群 Bot；群事件负责刷新绑定，Bot connect 必须先发现群路由再恢复 Timer，禁止使用无参数 `nonebot.get_bot()`。
3. 每群 `ConversationState` 必须继续拥有 `idle/pending/human` 消息与来源队列、图任务和限流状态；辅助队列属于同群 runtime，修改其生命周期时必须同步检查 finish 和压缩。
4. 入口消息先在 `handlers/dialogue.py` 或 `handlers/forward.py` 归一化，领域层不得依赖特定 OneBot 实现的原始结构。
5. Agent/Timer 标记必须绕过结束判断并进入 `ai_node`。
6. 对话结束把本轮内容放回辅助上下文，但长期记忆只由显式、可重复的 `[memory: ... MEMORYCONTENTEND]` 记忆卡写入；每张卡可内联可选 `keyman` QQ 号列表。
7. 角色代理每群只允许一个 RAM 对象，不得持久化、不得新增任务管理器；@ 被代理用户时只通过所属群的 `ConversationState.activate_chat()` 加入 peer 并复用现有图流程。
8. 角色代理关闭时 chat_agent 只暴露 `create_character_proxy`，开启时只暴露 `terminate_character_proxy`；行为 Prompt 与外号仅在 RAM 中保存并仅在开启期间注入 role system prompt；最新消息正文命中代理昵称或外号时跳过结束检测。
9. `end_conversation` 必须通过 `ConversationState` 停止消息投递并让当前图尽快进入 finish；调用后的当前轮不得继续发送文本或表情，直到新的主动提及重新激活对话。
10. 戳一戳只允许 `POKE_GROUP_WHITELIST` 中的群；白名单检查必须早于图片导出、runtime 绑定和消息发送，其他群静默返回。
11. 新成员欢迎只允许 memory 层 activated-group RAM 集合中的群；集合在启动时从 `memory.db` 的 distinct 正整数群号加载，并随成功写入和最后一条记忆清理而更新。

### Memory

1. SQLite 是记忆 ID、正文、时间、群所有权与关联用户的持久化真源；Milvus Lite 以同一 SQLite ID 和 `group_id` 保存运行时检索向量。
2. 不得把全部记忆、分词语料、BM25 或向量矩阵常驻内存；关键词从 SQLite 按需查询，BM25 只为有限候选临时构建。
3. 关联用户结构固定为 `{"user_id": int, "user_name": str}`。
4. 查询必须限定当前群，先保留全部合格的 SQLite LIKE 精确命中，再用同群临时 BM25 与 Milvus cosine 结果补足，并保持单轮内容去重。
5. SQLite 的 `embedding` 列仅作当前 schema 的向量协调来源；新写入和运行时查询不得读写该列。
6. SQLite 到 Milvus 的协调只接受带显式 `group_id` 的当前 schema，必须使用 SQLite 只读连接、以 ID 幂等 upsert，并测试已有数据库、失败恢复和源文件不变。
7. Milvus Lite 客户端只允许在单次向量操作期间存在，结束后必须关闭客户端并停止 embedded server；不得让 gRPC 线程跨越 Shell/Docker 等 fork 路径。

### Timers

1. `timer_tasks` 保存任务，`timer_schedule_points` 保存规则时间点与进度；删除任务必须级联删除时间点。
2. 数据库记录与 APScheduler 作业必须同步：创建/更新后注册，删除/更新前取消。
3. 启动恢复必须区分未来、容忍窗口内漏触发和过期触发。
4. 普通 Timer 与 auto-response 最终都使用记录中的显式 `group_id` 注入对应群图，不另建独立聊天 Agent。
5. memory 层 activated-group 集合是 `auto_response` 的候选群集合；不在 `AUTO_RESPONSE_GROUP_BLACKLIST` 中的 activated group 启动时自动保证只有一个未来 exact point。记忆写入和最后一条记忆清理必须通过同一 activated-group callback 幂等补建或删除所属群任务，失败更新保留并在下次刷新重试；黑名单群不得持有任务；未取得显式 Bot 路由的群只保留持久任务，不注册、恢复或消费 APScheduler 作业，Bot 断开时必须取消对应运行中注册但保留持久 point。
6. 活动数据库必须通过 `nonebot_plugin_localstore` 定位到插件数据目录，schema 只包含当前 `timer_tasks` 与 `timer_schedule_points`，不得加入旧路径或旧 schema 兼容逻辑。
7. auto_response 执行后的资格同步必须由 memory 层在 activated-group lock 内读取当前状态并调用 Timer callback，禁止用锁外快照写回；TimerStore 的共享 SQLite connection 必须以 reentrant operation lock 串行化跨事件循环与 APScheduler worker 的读写和事务。

## Extension Rules

### Add a Chat Tool

1. 在 `hatsume/plugins/hatsume-plugin/graph/tools.py` 定义 decorated tool。
2. 只在同文件 `CHAT_TOOLS` 注册一次。
3. 若工具依赖群号、回复回调或限流，把生命周期接入 `configure_tool_callbacks()`。
4. 添加工具级和图节点集成测试。

### Add a Background Agent

1. 在 `hatsume/plugins/hatsume-plugin/graph/agents.py` 实现 `async (task: str, user_id: int) -> str`。
2. 使用 `register_agent()` 注册名称、描述和 handler。
3. 测试并发实例、状态变更、通知、取消、stdin/进程清理。

### Add a QQ Command or Event

1. 对话入口放 `handlers/dialogue.py`，命令/事件工具放 `handlers/tools.py`，社交功能放 `handlers/social.py`。
2. 在插件 `__init__.py` 注册 matcher，并明确 priority、block 和权限规则。
3. 测试 handler 逻辑，不要求真实 QQ 连接。

### Change Persistence

1. 使用参数化 SQL、显式 commit、WAL 和幂等迁移。
2. 更新 `docs/arch.md` 的关键逻辑说明和模块目录。
3. 若表结构、恢复策略、队列顺序或图边变化，同时更新同一文档中的数据流说明。

## Runtime Artifacts

不要为完成代码任务而重写以下运行时文件，也不得将它们提交到 Hatsume 主仓库：

- `data/hatsume-plugin/*.db*`
- `data/hatsume-plugin/memory-db/*.db*`
- `data/hatsume-plugin/memory-db/memory_vectors.db/`
- `data/hatsume-plugin/timer-v2-db/*.db*`
- `data/hatsume-plugin/timer_db/*.db*`
- `data/hatsume-plugin/likes.json`
- `data/hatsume-plugin/skills/`
- `data/hatsume-plugin/faces/` 与生成图片
- `hatsume/plugins/hatsume-plugin/virtual/script.sh`

`data/hatsume-plugin` 是独立的私有 Git 仓库。只在执行下方同步提交规则时快照其已有变更；不得为了制造快照而修改运行时内容。

修改前后运行 `git status --short`，保留所有无关工作树改动。

## Setup and Checks

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci
```

必需验证：

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

先运行聚焦测试，再运行完整检查。不得忽略 collection error、resource warning 或类型错误来制造绿色结果。

## Git

- 功能分支命名为 `NNN-feature-name`。
- 除非用户明确要求，否则不要提交。
- 提交前检查整个工作树，并严格遵循用户指定的 staging 范围。
- Claude Code 或 Codex 被明确要求为 Hatsume 主仓库创建提交时，必须在同一次操作中检查独立仓库 `data/hatsume-plugin`。如果该工作树有变更，使用 `git -C data/hatsume-plugin add -A` 并提交其当前快照；如果工作树干净，不创建空提交。
- 主仓库与数据仓库的 staging 和提交必须保持分离；完成后报告两者的提交结果。除非用户明确要求，否则不推送任何一个仓库。
- 不得丢弃、覆盖或顺手格式化无关修改。
