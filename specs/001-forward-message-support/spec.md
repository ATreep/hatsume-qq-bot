# Feature Specification: 合并转发消息解析与 JSON 化消息格式

**Feature Branch**: `001-forward-message-support`

**Created**: 2026-05-31

**Status**: Draft

**Input**: User description: "我希望机器人可以读取用户发送的合并转发消息（OneBot 11 get_forward_msg API）。机器人不仅要能读到合并消息的内容，而且还应该知道LLM上下文中哪些消息是属于合并转发消息里面的，而且该合并转发消息是谁发的。另外，合并转发消息可能存在嵌套，需要正确处理（最大嵌套深度为3）"

## Clarifications

### Session 2026-05-31

- Q: No critical ambiguities detected — all design decisions were resolved during the brainstorming phase. → A: Spec is fully clarified and ready for planning.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 机器人读取单层合并转发消息 (Priority: P1)

群成员在 QQ 群中发送一条合并转发消息（包含多条他人聊天记录），机器人能够识别该消息为合并转发类型，通过 OneBot 11 API 获取完整内容，并将其中每条消息以 JSON 格式呈现给 LLM，同时标记该合并转发消息的发送者身份。

**Why this priority**: 这是核心功能——没有它，机器人完全无法理解合并转发消息。单层转发是最常见的使用场景，覆盖 90% 以上的情况。

**Independent Test**: 在测试群中发送一条包含 3 条消息的合并转发，验证机器人回复是否引用了合并转发中的内容，且能正确指出"这是你转发的那条消息里的"。

**Acceptance Scenarios**:

1. **Given** 群成员 A 发送了一条合并转发（包含成员 B、C 的聊天记录），**When** 机器人收到该消息，**Then** 机器人能看到转发中每条消息的内容及其原始发送者，并在 LLM 上下文中以 JSON 格式（`type: "forward"`）呈现
2. **Given** 合并转发消息中的某条内容引用了机器人关注的话题，**When** 机器人回复时，**Then** 机器人能自然提及转发内容中的具体信息
3. **Given** 群成员发送了一条不包含合并转发的普通消息，**When** 机器人收到该消息，**Then** 消息以 JSON 格式（`type: "message"`）正常呈现，不受影响

---

### User Story 2 - 机器人正确处理嵌套合并转发 (Priority: P2)

群成员发送的合并转发中，某条消息本身也是一个合并转发（嵌套深度 ≤ 3）。机器人能递归解析嵌套结构，保持树形结构，并用 `depth` 字段标记每条消息所在层级。

**Why this priority**: 嵌套转发虽不常见，但一旦出现而机器人无法处理，会导致信息丢失或上下文混乱。深度限制为 3 覆盖了实际使用中的所有合理场景。

**Independent Test**: 构造一条深度为 2 的嵌套合并转发，验证机器人回复时能正确理解各层消息的归属关系。

**Acceptance Scenarios**:

1. **Given** 合并转发中第 3 条消息又是另一条合并转发（depth=1），**When** 机器人解析该消息，**Then** 嵌套转发的内容在 JSON 中内联展开，子消息带有 `depth: 1` 字段，并标记该嵌套转发的原始发送者
2. **Given** 合并转发嵌套深度达到 4（超过上限），**When** 机器人解析时，**Then** 第 4 层及更深的内容被截断，显示占位提示"嵌套层数过多，已省略"
3. **Given** 合并转发嵌套深度恰好为 3，**When** 机器人解析，**Then** 第 3 层的消息正常展开，不会触发截断

---

### User Story 3 - LLM 以 JSON 格式输出回复 (Priority: P3)

机器人内部的 LLM 输出统一为 JSON 格式（`{"message": "回复内容"}`），由 Python 代码解析后通过 QQ 发送给用户。这包括所有回复类型：文字回复、工具调用后的回复等。

**Why this priority**: 这是消息格式统一化的一部分——LLM 输入既是 JSON，输出也应是 JSON，形成闭环。但不影响核心的消息解析功能，优先级稍低。

**Independent Test**: 发送任意聊天消息，验证机器人能正常回复（从用户视角看行为不变），同时内部日志记录 LLM 输出了 JSON 格式。

**Acceptance Scenarios**:

1. **Given** 机器人需要回复消息，**When** LLM 生成回复，**Then** 输出为 `{"message": "..."}` 格式的 JSON 字符串
2. **Given** LLM 输出的 JSON 解析失败（如格式异常），**When** Python 代码尝试解析，**Then** 系统回退为将原始文本作为 message 字段内容发送，不崩溃

---

### Edge Cases

- 合并转发消息的 `get_forward_msg` API 调用超时或失败时，机器人应在 JSON 中生成占位消息（"合并转发消息获取失败"），而非静默丢失
- 合并转发内容为空（消息数为 0）时，JSON 中 `messages` 数组为空，LLM 能看到"这是一个空的合并转发"
- 合并转发中包含图片时，图片应被下载并转为 base64，与文本内容一同在 `content` 数组中呈现
- 转发者自身也在转发内容中出现时（自己转发包含自己发言的记录），`user` 和 `messages[].user` 各司其职——`user` 是转发操作执行者，`messages[].user` 是消息原始发送者
- 合并转发消息中的 @提及：如果转发内容中包含对机器人的 @，不应触发机器人的 mention 规则（因为这是转发内容而非直接消息）
- 合并转发消息长度极大（如包含数十条消息）时，每条消息仍独立解析为 JSON 节点，由 LLM 的上下文窗口自行截断
- 当有人在合并转发中再次转发了包含机器人的消息时，机器人能正确识别

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须能检测 QQ 消息中是否包含 `type: "forward"` 的消息段（message segment）
- **FR-002**: 系统必须通过 OneBot 11 `get_forward_msg` API 获取合并转发消息的完整内容
- **FR-003**: 系统必须递归解析合并转发中的嵌套结构，最大处理深度为 3 层
- **FR-004**: 系统必须将合并转发内容构建为 JSON 格式：`type: "forward"`，包含 `user`（转发者）、`messages`（子消息数组）字段
- **FR-005**: 嵌套合并转发中的每条消息必须带有 `depth` 字段标记其所在层级
- **FR-006**: 超过最大深度（3）的嵌套内容必须被截断，呈现占位提示而非继续展开
- **FR-007**: 所有群聊消息（普通消息、回复消息、合并转发消息）必须以统一的 JSON 格式输入 LLM，使用 `type` 字段区分消息类型
- **FR-008**: 普通消息的 JSON 格式必须包含：`type`、`time`、`user`（含 `id` 和 `name`）、`content`（字符串或数组）字段；回复消息额外包含 `reply_to` 字段
- **FR-009**: 合并转发中每条消息的原始发送者（`user`）必须准确记录，与转发操作执行者区分
- **FR-010**: 合并转发中的图片必须与普通消息中的图片以相同方式处理（下载转 base64，以 `content` 数组中的 `image_url` 类型呈现）
- **FR-011**: `get_forward_msg` API 调用失败时，系统必须在 JSON 中生成占位消息，表示合并转发内容无法获取，不得静默丢弃
- **FR-012**: LLM 输出必须为 JSON 格式，至少包含 `message` 字段；系统必须解析该 JSON 并提取 `message` 内容发送给用户
- **FR-013**: 系统必须更新角色提示词（system prompt），说明 JSON 输入格式中各字段的含义，以及 LLM 应输出的 JSON 格式
- **FR-014**: 合并转发消息中出现的所有发言人必须被收录到 `source_entry.people` 列表中

### Key Entities

- **MessageJSON（消息 JSON）**: 表示一条输入给 LLM 的消息。包含 `type`（message/forward）、`time`、`user`（含 id 和 name）、`content`（纯文本字符串或多模态数组）、可选的 `reply_to`、可选的 `messages`（仅 forward 类型）、可选的 `depth`（仅嵌套 forward 中的消息）
- **ForwardNode（转发节点）**: `get_forward_msg` API 返回的原始消息单元。包含 `user_id`、`nickname`、`content`（消息段数组，可能包含嵌套 forward segment）
- **ForwardSegment（转发段）**: 事件消息中的 `type: "forward"` 段。仅包含 `id` 字段，指向可通过 API 获取的合并转发内容
- **LLMOutputJSON（LLM 输出 JSON）**: LLM 返回的 JSON。至少包含 `message` 字段（字符串）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 机器人对包含合并转发消息的群聊回复，能正确引用转发内容中的具体信息（抽查 20 条包含合并转发的聊天，准确引用率 ≥ 80%）
- **SC-002**: 嵌套深度 ≤ 3 的合并转发消息中，所有层级的所有消息均被正确解析和呈现，无信息丢失
- **SC-003**: 深度超过 3 的合并转发不被错误展开，且用户可见到截断提示
- **SC-004**: `get_forward_msg` API 调用失败时，机器人仍能正常回复（不回退为空回复或报错）
- **SC-005**: 已有的普通消息和回复消息功能不受影响——在不含合并转发的对话中，机器人行为与改造前一致
- **SC-006**: LLM JSON 输出解析成功率达到 98% 以上（以 100 条实际回复为样本）

## Assumptions

- 假设 OneBot 11 协议实现（如 Lagrange、LLOneBot）正确实现了 `get_forward_msg` API
- 假设 `get_forward_msg` API 返回的 node 中包含的 `user_id` 和 `nickname` 准确可靠
- 假设合并转发消息中的图片 URL 可被机器人访问和下载（与普通消息中的图片具有相同的访问条件）
- 假设 LLM（Mimo、DeepSeek 等）能够理解和遵循 JSON 格式的输入和输出指令
- 嵌套深度上限 3 基于实际使用场景的合理估计——绝大多数合并转发嵌套不超过 2 层
