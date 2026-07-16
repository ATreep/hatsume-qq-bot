# Research: 合并转发消息解析

**Date**: 2026-05-31

## Decisions

### 1. OneBot 11 Forward Message Detection

**Decision**: 在 `pipeline.get_human_message()` 迭代 `event.original_message` 的 segment 时检测 `type == "forward"`

**Rationale**: 这是 OneBot 11 标准协议——当用户发送合并转发时，消息段中以 `type: "forward"` 段出现，`data.id` 即为转发 ID。NoneBot 的 `MessageSegment` 原生支持检测：`msg_seg.type == "forward"`。

**Alternatives considered**:
- 从原始 JSON 事件中检测 → 过于底层，NoneBot 已封装
- 使用独立 matcher → 复杂度高，无需单独事件监听

### 2. API Call Method

**Decision**: 使用 `await bot.call_api("get_forward_msg", id=forward_id)` 获取合并转发内容

**Rationale**: NoneBot 的 Bot 基类提供 `call_api` 方法用于调用任意 OneBot API 端点。`get_forward_msg` 不是高频 API（NoneBot 没有为其提供封装的适配器方法），使用通用 `call_api` 即可。

**Alternatives considered**:
- 直接 HTTP 请求 OneBot 实现 → 绕过 NoneBot 的事件循环管理
- 使用 aiohttp 自行封装 → 重复造轮子

### 3. Recursive Parsing Strategy

**Decision**: 递归解析，每层 depth+1，depth > MAX_FORWARD_DEPTH(3) 时截断

**Rationale**: 合并转发天然嵌套，递归是最直接的解析方式。深度限制防止恶意或异常的深层嵌套导致栈溢出或无限 API 调用。3 层覆盖所有实际使用场景。

**Alternatives considered**:
- 迭代 BFS → 代码复杂度更高，无明显优势
- 无深度限制 → 安全风险

### 4. Picture Handling in Forward Messages

**Decision**: 合并转发中的图片与普通消息中的图片采用相同处理逻辑（下载 → base64 编码）

**Rationale**: 图片在合并转发中的 URL 与普通消息中的 URL 具有相同的可访问性。视觉模型（omni 模式）需要 base64，非视觉模型需要 URL 占位符。

**Alternatives considered**:
- 仅处理文本 → 丢失图片信息
- 对嵌套图片降低分辨率 → 过度设计，LLM 上下文窗口管理应由调用方负责

### 5. JSON Output Format for LLM

**Decision**: LLM 输出 `{"message": "回复内容"}`，Python 侧 `json.loads()` 解析提取 `message` 字段

**Rationale**: JSON 输出结构化，易于解析，可扩展（未来可加 `at`、`reply_to` 等字段）。与 JSON 输入格式形成闭环。

**Alternatives considered**:
- XML/自定义格式 → JSON 是 LLM 训练数据中最常见的结构化格式
- 纯文本输出 → 无法结构化，失去闭环优势
