# Feature Specification: 调试面板 v2 — 增强功能与 UX 重设计

**Feature Branch**: `004-debug-panel-v2`

**Created**: 2026-06-01

**Status**: Draft

**Input**: User description: "为调试面板新增 v2 增强功能：消息队列实时内容查看、非技术人员友好的 Dashboard 概览、前端 JSDoc 类型注解、UX 改进。保持单文件 HTML 零外部依赖。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 查看消息队列实时内容 (Priority: P1)

作为开发者或运维人员，我希望在调试面板中不仅看到队列长度计数，还能看到每条消息的发送者、内容摘要和时间。

**Why this priority**: 核心价值——从"看数字"升级为"看内容"，大幅提升问题诊断效率。

**Independent Test**: 触发机器人对话，打开调试面板，选中"会话状态"模块，验证队列显示为消息列表而非纯数字。

**Acceptance Scenarios**:

1. **Given** 机器人收到消息进入队列, **When** 打开面板查看模块, **Then** 队列显示为消息气泡列表，可见发送者昵称、内容摘要（前 30 字）、相对时间
2. **Given** 队列为空, **When** 查看对应变量, **Then** 显示友好空状态提示
3. **Given** 队列消息超过 20 条, **When** 查看队列, **Then** 默认显示最近 20 条，提供"查看全部"展开选项

---

### User Story 2 - 快速浏览机器人整体状态 (Priority: P2)

作为非技术团队成员，我希望页面顶部有一个一目了然的状态概览栏，用自然语言告诉我机器人"正在做什么"。

**Why this priority**: 降低使用门槛，让非开发者也能参与调试和状态监控。

**Independent Test**: 打开调试面板后，顶部 Dashboard 概览栏用图标和一句话描述显示关键状态。

**Acceptance Scenarios**:

1. **Given** 机器人空闲, **When** 打开面板, **Then** Dashboard 显示"🟢 机器人空闲中"
2. **Given** 机器人正在对话, **When** 打开面板, **Then** Dashboard 显示"💬 正在与用户对话"
3. **Given** 记忆索引需要重建, **When** bm25_dirty 为 true, **Then** Dashboard 记忆指示器显示黄色警告状态

---

### User Story 3 - UX 增强：搜索、响应式、类型安全 (Priority: P3)

作为频繁使用面板的开发者，我希望有搜索筛选、移动端适配、代码类型注解。

**Why this priority**: 增强日常体验和代码质量，不阻塞核心功能交付。

**Independent Test**: 搜索框输入关键词后变量列表即时筛选；手机浏览器打开面板布局自适应。

**Acceptance Scenarios**:

1. **Given** 面板显示所有变量, **When** 在搜索框输入"queue", **Then** 仅显示名字匹配的变量卡片
2. **Given** 手机竖屏（<768px）, **When** 页面渲染, **Then** 侧栏折叠为底部 Tab 栏，卡片单列排列

---

### Edge Cases

- 消息内容含 HTML/emoji/换行：正确转义，不破坏布局
- Dashboard 在 WebSocket 断开时：指示器转为灰色"未连接"
- 搜索无匹配："无匹配变量"提示
- 极长消息（>1000 字）：截断显示，提供展开选项
- 消息跨天：显示日期而非仅时间

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 采集器 MUST 返回队列消息的内容摘要数组（含发送者、内容、时间）
- **FR-002**: 前端 MUST 将队列渲染为消息列表，每条显示发送者、内容摘要、相对时间
- **FR-003**: 顶部 MUST 提供 Dashboard 概览栏，用图标+自然语言描述关键状态
- **FR-004**: Dashboard 指示器 MUST 根据数据自动更新颜色和文字
- **FR-005**: 前端 MUST 提供搜索筛选功能，即时过滤变量卡片
- **FR-006**: 面板 MUST 在 <768px 视口自适应布局
- **FR-007**: JS 代码 MUST 使用 JSDoc 类型注解
- **FR-008**: 空队列/空列表 MUST 显示友好提示文字
- **FR-009**: 单文件 HTML 零外部依赖，不超过 20KB
- **FR-010**: 消息内容 MUST 正确转义 HTML 特殊字符

### Key Entities

- **QueueMessage**: 队列消息摘要，含 `user`（发送者）、`content`（截断文本）、`time`（时间戳）
- **DashboardStatus**: 仪表盘状态指示器，含 `label`、`value`、`status`（normal/warning/error/disconnected）、`icon`
- **SearchFilter**: 搜索过滤器，含搜索文本和匹配结果集

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 非技术用户 10 秒内能从 Dashboard 判断机器人状态
- **SC-002**: 开发者 2 次点击内从队列计数到浏览消息内容
- **SC-003**: 搜索筛选 200ms 内更新结果
- **SC-004**: iPhone SE (375px) 上文字可读、按钮可点击、无水平滚动
- **SC-005**: 队列采集单轮不超过 15ms
- **SC-006**: HTML 总大小不超过 20KB

## Assumptions

- 消息队列原始数据含发送者名称和文本内容，采集器可直接访问
- JSDoc 注解不影响运行时性能
- 移动端目标为现代浏览器（iOS Safari 14+、Chrome Android 90+）
- Dashboard 状态基于已有采集数据派生，无需新增采集器
- 搜索筛选为纯前端实现
