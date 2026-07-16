# Feature Specification: 调试 API 数据采集层与服务器

**Feature Branch**: `005-debug-api-server`

**Created**: 2026-06-04

**Status**: Draft

**Input**: User description: "开始实现 debug.py 的数据采集层，在 nonebot 启动的时候自动启动调试 API 接口服务器"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 通过 API 查看机器人实时状态 (Priority: P1)

作为开发者或运维人员，我希望在浏览器或 HTTP 客户端中访问调试 API 端点，获取机器人的当前运行状态（是否在聊天、队列长度、记忆数量等），以便在不登录 QQ 的情况下快速诊断问题。

**Why this priority**: 这是调试服务器的核心价值——提供一条独立于 QQ 协议的带外诊断通道，让开发者在机器人出问题时仍然能获取状态信息。

**Independent Test**: 机器人启动后，用 `curl http://localhost:XXXX/debug/api/summary` 即可获得 JSON 格式的状态摘要，无需 QQ 客户端参与。

**Acceptance Scenarios**:

1. **Given** 机器人已启动并空闲, **When** 访问 `/debug/api/summary`, **Then** 返回 JSON 包含 `bot_status: "idle"`、各队列长度、记忆总数
2. **Given** 机器人正在对话中且消息队列有积压, **When** 访问 `/debug/api/summary`, **Then** 返回 JSON 包含 `bot_status: "conversing"`、`is_graph_running: true`、各队列当前长度
3. **Given** 机器人未启动, **When** 访问调试 API, **Then** 连接被拒绝或返回服务不可用

---

### User Story 2 - 按模块查看详细状态 (Priority: P2)

作为开发者，我希望调试 API 按功能模块（会话状态、消息队列、记忆系统、工具调用、配置快照、健康指标）分组暴露端点，以便我只关注当前排查问题所需的特定数据。

**Why this priority**: 分组端点减少单次请求的数据量，提升排查效率；相比 P1 的全量摘要，这是精细化的诊断能力。

**Independent Test**: 单独访问 `/debug/api/queues` 验证返回各队列的消息摘要列表（含发送者、内容截断、时间），不包含记忆或配置信息。

**Acceptance Scenarios**:

1. **Given** 消息队列中有消息, **When** 访问 `/debug/api/queues`, **Then** 返回每个队列的名称、消息数量、每条消息的 `user_name` / `content_preview` / `time` / `source_id`
2. **Given** 记忆索引需要重建, **When** 访问 `/debug/api/memory`, **Then** 返回 `bm25_dirty: true`、`total_memories`、`embedding_vectors_loaded` 等字段
3. **Given** 机器人已生成过图片, **When** 访问 `/debug/api/tools`, **Then** 返回各工具调用次数、速率限制剩余时间

---

### User Story 3 - 调试服务器随机器人自动启停 (Priority: P1)

作为运维人员，我希望调试 API 服务器在 NoneBot 启动时自动启动、在 NoneBot 关闭时自动停止，无需任何手动操作或额外配置。

**Why this priority**: 与 P1 同优先级——自动启停是"零运维负担"的基础保障，如果每次需要手动启动调试服务器，实用价值大打折扣。

**Independent Test**: 启动 NoneBot 后直接访问调试 API，无需任何额外启动命令；关闭 NoneBot 后调试 API 不可访问。

**Acceptance Scenarios**:

1. **Given** NoneBot 正常启动, **When** 启动过程完成, **Then** 调试 API 服务器已在配置的端口上监听，无需手动干预
2. **Given** 调试服务器正在运行, **When** NoneBot 执行正常关闭流程, **Then** 调试服务器随之一同关闭，端口释放
3. **Given** 配置的端口被占用, **When** NoneBot 启动, **Then** 机器人正常启动但输出警告日志说明调试服务器启动失败，不影响核心功能

---

### User Story 4 - 配置化端口与访问控制 (Priority: P3)

作为部署者，我希望调试 API 服务器的监听端口和主机地址可通过配置文件设置，且默认仅监听本地回环地址以保证安全性。

**Why this priority**: 安全性和灵活性是生产部署的基本要求，但默认值（仅 localhost）已能满足本地调试场景，所以优先级稍低。

**Independent Test**: 修改配置文件中的端口号后重启机器人，调试 API 在新端口上可用。

**Acceptance Scenarios**:

1. **Given** 配置文件未设置调试端口, **When** 机器人启动, **Then** 调试服务器使用默认端口（如 8899）并仅监听 `127.0.0.1`
2. **Given** 配置文件设置 `debug_host: "0.0.0.0"` 和 `debug_port: 8080`, **When** 机器人启动, **Then** 调试服务器在 8080 端口对所有网络接口可用
3. **Given** 配置文件设置 `debug_enabled: false`, **When** 机器人启动, **Then** 调试服务器不启动

---

### Edge Cases

- 多个 NoneBot 实例同时运行在同一台机器上：端口冲突时后续实例应优雅降级，输出警告日志
- 调试 API 请求在机器人高负载时到达：API 响应时间可能增加但不影响机器人核心对话功能
- 采集器访问的共享状态在被并发修改：采集器应做快照读取或使用线程安全的方式访问状态，避免竞态条件
- 记忆数量极大（数千条）时请求 `/debug/api/memory`：只返回统计摘要而非全部记忆内容，避免响应过大
- API 端点收到非法请求方法：返回 405 Method Not Allowed
- 访问不存在的端点：返回 404 并附带可用端点列表

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 在 NoneBot 启动时自动启动一个 HTTP 调试 API 服务器
- **FR-002**: 系统 MUST 在 NoneBot 关闭时自动停止调试 API 服务器并释放端口
- **FR-003**: 调试服务器 MUST 提供 `/debug/api/summary` 端点，返回包含机器人整体状态摘要的 JSON 响应（含 bot_status、is_chatting、is_graph_running、各队列长度、记忆总数、运行时长）
- **FR-004**: 调试服务器 MUST 提供 `/debug/api/state` 端点，返回核心会话状态（ConversationState 全部字段）
- **FR-005**: 调试服务器 MUST 提供 `/debug/api/queues` 端点，返回所有消息队列的实时内容摘要（每条消息含发送者、内容截断、时间、来源编号）
- **FR-006**: 调试服务器 MUST 提供 `/debug/api/memory` 端点，返回记忆系统状态（总数、索引状态、脏标记、最近一次维护时间）
- **FR-007**: 调试服务器 MUST 提供 `/debug/api/tools` 端点，返回工具调用状态（各工具调用计数、速率限制状态、资源使用标记）
- **FR-008**: 调试服务器 MUST 提供 `/debug/api/config` 端点，返回运行时配置快照（不含 API 密钥明文，仅显示是否已配置）
- **FR-009**: 调试服务器 MUST 提供 `/debug/api/health` 端点，返回健康指标（累计错误计数、运行时长、连接状态）
- **FR-010**: 所有 API 响应 MUST 为 `application/json` 格式，结构稳定可被程序化解析
- **FR-011**: 调试服务器启动失败 MUST NOT 阻止 NoneBot 正常启动和运行
- **FR-012**: 调试服务器的监听地址和端口 MUST 可通过配置项设置，默认为 `127.0.0.1:8899`
- **FR-013**: 提供 `debug_enabled` 配置项，设置为 `false` 时跳过调试服务器启动
- **FR-014**: 队列内容返回时 MUST 正确转义 JSON 特殊字符，防止响应格式损坏
- **FR-015**: 数据采集层 MUST 以只读方式访问共享状态（快照读取），不修改任何运行时状态

### Key Entities

- **ServerStatus**: 机器人整体运行状态摘要，含 `bot_status`（idle/chatting/conversing）、`uptime_seconds`、`total_conversations`、`total_messages_processed`
- **QueueSnapshot**: 单个消息队列的快照，含队列名称、消息数量、消息摘要列表（每条含 `user_name`、`content_preview`、`time`、`source_id`）
- **MemoryStatus**: 记忆系统状态，含 `total_memories`、`bm25_dirty`、`bm25_loaded`、`embedding_vectors_loaded`、`last_index_rebuild_time`
- **ToolStatus**: 工具调用状态，含各工具调用次数、速率限制剩余时间、资源使用标记
- **ConfigSnapshot**: 运行时配置快照，含 LLM provider、模型名称、各阈值参数、API 密钥配置状态（仅显示是否已配置）
- **HealthMetrics**: 健康指标，含运行时长、累计对话/消息数、错误计数、最近错误信息

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 开发者能在机器人启动后 5 秒内通过 HTTP 请求获取状态摘要
- **SC-002**: 单个 API 端点响应时间在 50ms 以内（本地 localhost 访问）
- **SC-003**: 调试服务器启动或运行失败不影响机器人核心对话功能的可用性
- **SC-004**: 所有 7 个 API 端点在机器人正常运行时均返回 200 状态码
- **SC-005**: 配置更改后重启机器人，新配置在 10 秒内生效
- **SC-006**: 队列消息摘要中包含的 JSON 特殊字符不会导致 API 响应格式损坏

## Assumptions

- 调试服务器使用 NoneBot 自身的异步事件循环，不需要独立的进程或线程管理
- HTTP 服务器框架使用项目已有的 FastAPI 依赖（基于 `004-debug-panel-v2` 的技术上下文）
- 默认仅监听 `127.0.0.1`，部署者如需远程访问需显式配置 `debug_host` 为 `0.0.0.0`
- 数据采集不引入新的外部依赖——直接读取已有的模块级变量和 dataclass 实例
- 配置项定义在现有的 `config.py` 中，遵循已有命名惯例
- 调试服务器与 `004-debug-panel-v2` 的 HTML 面板共用同一数据采集层，两者独立演进
