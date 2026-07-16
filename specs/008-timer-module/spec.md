# Feature Specification: Timer Module (定时任务模块)

**Feature Branch**: `008-timer-module`

**Created**: 2026-06-07

**Status**: Draft

## Clarifications

### Session 2026-06-07

- Q: `/timer update` 的具体命令格式是什么？ → A: 位置参数格式 `/timer update <id> <新prompt> @ <新时间1>, <新时间2>, ...`。格式不对时输出帮助信息。
- Q: 定时任务是否需要接入 Debug API？ → A: 新增 `GET /debug/api/timers` 端点，返回所有定时任务及其触发状态。同时写入 `docs/debug-api-contract.md`。

**Input**: User description: "Add a timer module. User can set a timer task with chat_agent (the time range of timers is limited in the future 7 days i.e. 7*24h). You can record every timer task in a sqlite datatable. A timer task can have multiple trigger timings (such as user wants alarm him to get up at seven everyday, but because the range is limited in the future 7d, you actually set the timer at seven everyday during the future 7 days). The timer task content is a prompt. If you will execute a timer task, input the task prompt with role system prompt into the chat_agent (has the same tools as the chat_agent in langgraph). When the nonebot starting, it will load all timer tasks in the sqlite datatable and set the timers. When a timer is triggered, it will execute the timer task prompt with role system prompt into the chat_agent. The user can also query all timer tasks, delete a timer task, or update a timer task."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create Timer via Natural Language Chat (Priority: P1)

群成员在聊天中通过自然语言告诉机器人设置定时提醒（如 "@初芽 明早8点提醒我开会"），机器人理解意图后创建定时任务并回复确认。

**Why this priority**: 这是定时任务功能的核心入口——用户最自然的使用方式。没有它，定时模块需要用户记忆命令格式，体验差。

**Independent Test**: 在群聊中发送带时间要求的自然语言消息，验证机器人回复确认信息且定时任务被正确记录。

**Acceptance Scenarios**:

1. **Given** 群成员在聊天中发送 "@初芽 明早8点提醒我开会"，**When** 机器人处理该消息，**Then** 机器人创建一条 trigger_at 为明天 08:00 的定时任务，提示词为"提醒用户开会"，并回复用户确认信息（包含任务 ID 和触发时间）。
2. **Given** 群成员发送 "@初芽 每天早上7点叫我起床"，当前时间为 6/7 20:00，**When** 机器人处理该消息，**Then** 机器人创建包含 7 个触发时刻的定时任务（6/8 至 6/14 每天 07:00），并回复确认。
3. **Given** 群成员发送触发时间已过期或超过 7 天的请求，**When** 机器人处理该消息，**Then** 机器人回复错误提示，说明时间范围限制。
4. **Given** 群成员发送的请求不包含定时意图，**When** 机器人处理该消息，**Then** 机器人正常进入对话流程，不创建定时任务。

---

### User Story 2 - Timer Triggers and Executes Results (Priority: P1)

定时器到期时，机器人自动执行任务，将任务 prompt 配合系统角色设定输入 chat_agent，产出结果后发送到群聊并 @ 任务创建者。

**Why this priority**: 定时任务能创建但不会执行就没有意义。这是核心功能闭环。

**Independent Test**: 手动创建一个 1 分钟后触发的定时任务，等待触发后验证群里收到 @ 创建者的回复消息。同时验证执行结果与任务 prompt 相关。

**Acceptance Scenarios**:

1. **Given** 存在一个触发时间为当前时间后 1 分钟的定时任务，**When** 触发时间到达，**Then** 机器人在群中发送一条 @ 任务创建者的消息，消息内容与任务 prompt 相关（由 chat_agent 生成）。
2. **Given** 定时任务创建者已退出群聊，**When** 触发时间到达，**Then** 机器人在群成员列表中查不到该用户，取消该任务并删除所有相关触发器和数据库记录，不发送任何消息。
3. **Given** 定时任务触发时机器人正在与其他人进行 LangGraph 对话，**When** 触发时间到达，**Then** 定时任务使用独立的 chat_agent 实例执行，不影响正在进行中的对话，两条线各自往群里发消息。
4. **Given** 定时任务触发时，chat_agent 执行 prompt 利用了最近 5 条群消息作为上下文，**When** 触发时间到达，**Then** agent 的回复包含对当前群聊语境的理解（如接续最近的聊天话题）。

---

### User Story 3 - Manage Timer Tasks via Commands (Priority: P2)

群成员通过 `/timer` 命令管理本群已有的定时任务，包括查看列表、删除和更新。

**Why this priority**: 提供精确的任务管理手段——自然语言可以做但不一定能精准匹配。命令提供确定性操作。

**Independent Test**: 创建若干定时任务后，分别执行 `/timer list`、`/timer delete <id>`、`/timer update <id>`，验证操作结果和反馈。

**Acceptance Scenarios**:

1. **Given** 当前群存在 3 个定时任务，**When** 用户发送 `/timer list`，**Then** 机器人回复任务列表，包含每个任务的 ID、prompt 摘要、触发时间、已触发/未触发状态。
2. **Given** 当前群存在 ID 为 1 的定时任务，**When** 用户发送 `/timer delete 1`，**Then** 机器人删除该任务及其所有触发器，回复确认信息。
3. **Given** 当前群存在 ID 为 1 的定时任务，**When** 用户发送 `/timer update 1 提醒吃药 @ 2026-06-09T08:00:00+08:00, 2026-06-10T08:00:00+08:00`，**Then** 机器人更新任务内容和触发时间，原有触发器取消并重新注册，回复确认。
4. **Given** 当前群没有任何定时任务，**When** 用户发送 `/timer list`，**Then** 机器人回复"当前群没有定时任务"。
5. **Given** 用户尝试删除一个不存在的任务 ID，**When** 用户发送 `/timer delete 999`，**Then** 机器人回复"任务 ID 999 不存在"。

---

### User Story 4 - Startup Recovery and Fault Tolerance (Priority: P2)

机器人重启后自动恢复所有在有效期内的定时任务，并补偿执行宽容期内错过的任务。

**Why this priority**: 机器人在生产环境中会因更新、崩溃等原因重启。定时任务不能因重启而丢失。

**Independent Test**: 创建若干定时任务后重启机器人，验证所有未过期任务被重新加载并正常触发。

**Acceptance Scenarios**:

1. **Given** 数据库中存有 5 个未触发的定时任务（均在当前时间之后），**When** 机器人启动，**Then** 所有 5 个触发器被重新注册为定时 job。
2. **Given** 数据库中存有 2 个触发时间在当前时间前 3 分钟内的未触发任务（宽容期内），**When** 机器人启动，**Then** 这 2 个任务被立即补偿执行。
3. **Given** 数据库中存有 3 个触发时间在当前时间前 1 小时的未触发任务（超出宽容期），**When** 机器人启动，**Then** 这 3 个任务被标记为已触发（不补偿执行），对应的 APScheduler job 不注册。
4. **Given** 数据库文件不存在（首次启动），**When** 机器人启动，**Then** 自动创建数据库和表，不产生任何错误。

---

### User Story 5 - LLM Tools for Timer Management (Priority: P3)

chat_agent 在自然对话中可以通过内置 tools 执行定时任务的查询和删除操作，无需用户发 `/timer` 命令。

**Why this priority**: 进一步提升自然语言体验。用户说"帮我把明天的闹钟取消了"时，LLM 可以先 list 再 delete。

**Independent Test**: 在聊天对话中自然表达查询/删除意图，验证 LLM 调用了对应的 tool 并正确操作。

**Acceptance Scenarios**:

1. **Given** 当前群有 2 个定时任务，**When** 用户在聊天中说"帮我看看我设了哪些定时任务"，**Then** chat_agent 调用 `list_timers` tool 获取列表并向用户汇报。
2. **Given** 当前群有 ID 为 1 的定时任务，**When** 用户在聊天中说"把我那个开会的定时取消了"，**Then** chat_agent 先调用 `list_timers` 找到目标，再调用 `delete_timer(1)` 删除，回复确认。

---

### Edge Cases

- 用户设置触发时间为此时此刻（0 秒后）怎么处理？→ 拒绝创建，提示时间必须在当前时间之后。
- 一个任务的所有触发时间都已完成（fired=1）后任务本身怎么处理？→ 保留任务记录，/timer list 中显示"已完成"，用户可主动删除。
- LLM 通过 tool call 创建的定时任务中，trigger_times 包含重复时间怎么处理？→ 去重后写入。
- 同一个到达时间的多个不同触发器同时触发怎么处理？→ 逐一顺序执行（asyncio 单线程保证不会并发冲突）。
- 定时器触发后 chat_agent 调用失败（如 LLM API 错误）怎么处理？→ 标记 trigger 为 fired（不重试），向群发 "@用户 抱歉，定时任务执行失败"。
- 如果用户设置任务时用了极长的 prompt（如 5000 字）怎么处理？→ 限制 prompt 最大长度（默认 500 字符），超长返回错误。
- `/timer` 命令格式错误或省略子命令怎么处理？→ 输出完整的使用帮助信息，包含所有子命令及其格式示例。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须支持群成员通过自然语言聊天创建定时任务，LLM 通过 tool call 将解析后的触发时间和任务 prompt 提交到后台。
- **FR-002**: 系统必须支持通过 `/timer` 命令管理定时任务。子命令格式：
  - `/timer list` — 列出当前群所有定时任务
  - `/timer delete <id>` — 删除指定任务
  - `/timer update <id> <新prompt> @ <新时间1>, <新时间2>, ...` — 更新指定任务（时间和 prompt 用 `@` 分隔，多个时间用逗号分隔）
  - 格式错误或省略子命令时，系统必须输出完整的使用帮助。
- **FR-003**: 定时任务必须持久化存储，机器人重启不丢失数据。
- **FR-004**: 定时任务的时间范围限制在未来 7 天（168 小时）之内。
- **FR-005**: 一个定时任务可以包含多个触发时刻（如"每天早上7点"在未来 7 天内展开为多个时间点）。
- **FR-006**: 定时器触发时，系统必须用独立于当前对话的 chat_agent 实例执行任务 prompt，使用与主对话 agent 相同的角色系统提示词和工具集。
- **FR-007**: 定时器触发时，执行结果必须以群消息形式发送到对应群聊，并 @ 任务创建者。
- **FR-008**: chat_agent 执行定时任务时，系统必须向其提供任务创建前最近 5 条群消息作为上下文。
- **FR-009**: 定时器触发时，如果任务创建者已退出群聊，系统必须自动删除该任务及其所有触发器和调度 job。
- **FR-010**: 机器人启动时必须加载数据库中所有未触发且未过期的定时任务，重新注册调度器。
- **FR-011**: 机器人启动时必须补偿执行触发时间在宽容期（5 分钟）内的未触发任务，超过宽容期的直接标记为已触发。
- **FR-012**: 系统必须提供 LLM tool：`create_timer(prompt, trigger_times)`，用于自然语言创建定时任务。LLM 负责将自然语言时间表达式计算为具体的 ISO 8601 时间（含时区）。
- **FR-013**: 系统必须提供 LLM tool：`list_timers()`，用于列出当前群的所有定时任务。
- **FR-014**: 系统必须提供 LLM tool：`delete_timer(task_id)`，用于删除指定的定时任务。
- **FR-015**: `create_timer` tool 必须验证：trigger_times 中每个时间不得早于当前时间，不得超过未来 7 天。
- **FR-016**: 定时任务执行时因 LLM 调用失败等情况导致无法产出结果，系统必须在群中发送 @ 创建者的失败通知。
- **FR-017**: 删除定时任务时必须级联删除所有关联触发器，同时取消对应的调度 job。
- **FR-018**: 系统必须提供 `GET /debug/api/timers` 端点，返回所有群的定时任务列表（任务 ID、群 ID、创建者 ID、prompt、触发器详情及触发状态），供调试面板使用。

### Key Entities

- **TimerTask（定时任务）**: 表示一个由群成员创建的定时提醒。属性包括：任务 ID、所属群 ID、创建者用户 ID、任务 prompt 内容、创建时间、更新时间。一个任务关联多个触发时刻。
- **TimerTrigger（触发时刻）**: 表示定时任务的一个具体触发时间点。属性包括：触发 ID、所属任务 ID、触发时间戳、是否已触发、关联的调度 job ID。触发器与任务之间存在级联删除关系。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户通过自然语言（不依赖 /timer 命令）成功创建定时任务的成功率达到 90% 以上（在合理的时间表达范围内）。
- **SC-002**: 定时器触发后的执行结果在触发时间 60 秒内发送到群聊。
- **SC-003**: 机器人重启后，100% 的未过期定时任务在 30 秒内完成重新加载和调度注册。
- **SC-004**: 定时任务模块的运行不影响主对话流程——在定时器触发的同时进行中的对话，用户感知不到卡顿或延迟。
- **SC-005**: /timer 命令的子命令（list/delete/update）能 100% 正确返回对应操作的结果或错误提示。

## Assumptions

- 机器人所在群聊支持消息发送和 @ 功能。
- NoneBot 运行时，`nonebot_plugin_apscheduler` 插件已正常加载。
- chat_agent 使用的 LLM 能正确理解自然语言时间表达式并将其展开为具体时间点。
- 创建定时任务时用户在当前群的群名片与触发时的群名片保持一致（触发时实时查询）。
- 最近 5 条群消息可以通过 NoneBot 的消息历史记录 API 获取。
- 定时任务的 prompt 为纯文本，不包含图片或其他富媒体。
