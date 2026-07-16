# Feature Specification: 修复 JSON 输出格式与合并转发消息可见性

**Feature Branch**: `002-fix-json-output-forward-visibility`

**Created**: 2026-05-31

**Status**: Draft

**Input**: User description: "根据 001-forward-message-support spec 的改进，修复以下问题：1. LLM 输出 JSON 格式不稳定——需要在 chat_agent 的系统提示词中指定输出格式，而非通过角色提示词。2. 机器人能检测到合并转发消息，但转发内容未进入 LLM 上下文。"

**Parent Spec**: [001-forward-message-support](../001-forward-message-support/spec.md)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - LLM 稳定输出 JSON 格式回复 (Priority: P1)

机器人内部的 LLM（通过 LangChain `create_agent()` 创建的工具调用 agent）在每次回复时，最终输出必须是 `{"message": "..."}` JSON 格式，由 Python 代码解析后提取 `message` 内容发送给 QQ 用户。

**Why this priority**: LLM 输出格式不稳定导致 JSON 解析失败后 fallback 到原始文本，增加了回复格式错误的风险。这是对 001 spec 中 FR-012/FR-013 的修正——将输出格式指令从角色提示词中分离，放在 agent 创建处，提高指令遵循率。

**Independent Test**: 向机器人发送普通聊天消息 20 条，检查内部日志，验证 LLM 输出为有效 `{"message": "..."}` JSON 的比例 ≥ 98%。

**Acceptance Scenarios**:

1. **Given** 机器人需要生成回复，**When** chat_agent 被创建并调用，**Then** LLM 收到的 system prompt 末尾包含独立的 JSON 输出格式指令
2. **Given** LLM 输出 `{"message": "你好世界！"}`，**When** Python 代码解析，**Then** 提取 message 字段为 "你好世界！" 并发送
3. **Given** LLM 输出了非 JSON 格式的纯文本（如 "哎呀你怎么才来啊！"），**When** Python 代码尝试解析失败，**Then** 系统以原始文本作为 message 内容发送，不崩溃
4. **Given** 角色提示词（role_sys_prompt），**When** 查看其内容，**Then** 不包含任何输出格式指令（仅定义人设和对话规则）

---

### User Story 2 - 合并转发消息段在消息循环中显式处理 (Priority: P2)

群成员发送合并转发消息时，机器人的消息处理循环能显式识别 `"forward"` 类型的消息段，即使 API 调用失败，LLM 也能看到"有一条合并转发消息"的标记。

**Why this priority**: 当前消息段遍历循环（get_human_message 中的 match-case）未处理 `"forward"` case，在部分 OneBot 实现下可能导致转发内容静默丢失。这是防御性修复。

**Independent Test**: 构造一条包含 forward segment 的模拟消息，验证 plain_message 中包含 `[合并转发消息 id=xxx]` 标记。

**Acceptance Scenarios**:

1. **Given** 一条包含 `type: "forward"` segment 的消息，**When** 消息段遍历循环处理该 segment，**Then** plain_message 中追加 `[合并转发消息 id=xxx]` 标记
2. **Given** forward segment 被检测到但 API 调用失败，**When** LLM 收到该消息的 JSON，**Then** 至少能看到 `[合并转发消息]` 标记（而非完全空白）
3. **Given** 普通文本/图片/at 消息，**When** 遍历循环处理，**Then** 行为与修复前完全一致，不受影响

---

### User Story 3 - 转发处理全链路调试可见性 (Priority: P3)

开发者在排查合并转发问题时，能通过控制台日志追踪全链路状态：检测结果 → API 调用结果 → JSON 构建结果。

**Why this priority**: 当前缺少成功路径的日志，问题排查依赖盲猜。日志覆盖后，生产环境问题可快速定位。

**Independent Test**: 查看控制台输出，验证包含以下日志：`has_forward_segment result`、`resolve_forward_content returned`、`parse_forward_messages` 成功/失败信息。

**Acceptance Scenarios**:

1. **Given** 一条合并转发消息被处理，**When** 流程完成，**Then** 控制台输出包含检测、API、构建三阶段的日志
2. **Given** `get_forward_msg` API 调用成功，**When** 查看日志，**Then** 包含前 3 条子消息的预览信息

---

### Edge Cases

- 合并转发消息中除 forward segment 外同时包含 text segment 时，两者都应出现在 LLM 输入中
- 日志输出量控制：只打印前 3 条子消息预览，避免大量转发消息刷屏

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须将 LLM 输出格式指令从角色提示词（role_sys_prompt）中移除
- **FR-002**: 角色提示词（role_sys_prompt）必须仅包含角色人设、对话规则、记忆参考等内容，不得包含输出格式相关的技术指令
- **FR-003**: 系统必须在创建 chat_agent 时，将独立的输出格式指令追加到 system prompt 末尾
- **FR-004**: 输出格式指令必须要求 LLM 以 `{"message": "..."}` JSON 格式输出，不允许输出额外文字
- **FR-005**: 系统必须保留现有的 JSON 解析 + fallback 逻辑（解析失败时以原始文本作为 message 内容）
- **FR-006**: 系统必须在消息段遍历循环中显式处理 `type: "forward"` 的消息段，追加 `[合并转发消息 id=xxx]` 到 plain_message 中
- **FR-007**: 系统必须在 forward 处理全链路（检测→API 调用→JSON 构建）添加控制台 debug 日志
- **FR-008**: 成功路径的日志必须包含 API 返回的子消息数量和前 3 条消息的预览
- **FR-009**: 现有普通消息和回复消息的处理行为不得因本次修改而改变

### Key Entities

- **输出格式指令**: 独立的指令文本（在 agent 创建模块中定义），包含 LLM 必须输出 `{"message": "..."}` JSON 的要求。与角色提示词分离，在 agent 创建时追加到 system prompt 末尾。
- **Debug Log（调试日志）**: 控制台输出的全链路追踪信息，覆盖 forward segment 检测返回值、API 解析返回的消息数量、前 3 条子消息预览。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: LLM JSON 输出解析成功率达到 98% 以上（以 100 条实际回复为样本）
- **SC-002**: 角色提示词（role_sys_prompt 字符串）中不含 "输出格式"、"JSON"、"message" 等技术格式指令
- **SC-003**: 合并转发消息处理后，控制台至少输出 3 条 distinct 的 debug 日志（检测、API、构建各一条）
- **SC-004**: 普通消息和回复消息的现有单元测试全部保持通过
- **SC-005**: 即使 forward API 调用失败，LLM 上下文中仍能看到转发消息标识（而非空白内容）

## Assumptions

- 假设在 system prompt 末尾追加格式指令（近因效应）比在角色提示词中部嵌入指令更能提高 LLM 遵循率
- 假设 LLM（Mimo、DeepSeek、Volcengine）在 agent 工具调用完成后，能够遵循 system prompt 末尾的 JSON 输出格式指令
- 假设 debug 日志的输出量在合理范围内，不会对生产环境日志系统造成负担
- 本次修改不改变现有的消息队列流、状态管理和 graph 执行流程
