# 设计：将 aux_queue + human_queue 的拼接逻辑从 human_node 迁移到 ai_node

- 日期：2026-07-03
- 状态：已实现

## 背景

当前（迁移前）`human_node`（`hatsume/plugins/hatsume-plugin/graph/nodes/human.py`）在等到
`human_queue` 非空后，会把模块级全局 `auxiliary_messages_queue`（`ai.py` 中定义，代表"自动
回复触发前的辅助上下文"）与 `human_queue` 拼接成一条内容列表：

```
["## 历史聊天记录："] + aux_queue + ["## 当前聊天记录："] + human_queue
```

并把这条合并后的内容作为唯一一条 `HumanMessage` 返回。由于图使用 `MessagesState`
（`add_messages` reducer），这条消息会被**永久追加**进 `state["messages"]` 历史 —— 也就是说，
一旦某一轮混入了 aux 历史文本和 markers，这些文本会被后续所有轮次的 `chat_agent.ainvoke()`
反复重放，历史越滚越冗余。

`ai_node`（`graph/nodes/ai.py`）目前完全不碰这两个队列，只读取已经合并好的
`state["messages"][-1]`。

`auxiliary_messages_queue` / `auxiliary_source_queue` 是 `ai.py` 里的**模块级全局变量**，与
`ConversationState`（`state.py`）中同名的 `auxiliary_queue` / `auxiliary_source_queue`
dataclass 字段是两个不同的存储 —— 后者目前只在 `/clear` 命令中被清空，属于基本死代码，本次
设计将赋予它新用途（归档）。

`builder.py` 的路由条件 `_chat_end_detect_condition` 依赖模块级标志
`_last_was_auxiliary_only`（在 `human_node` 内计算），用于判断"本轮是否只有 aux 内容、没有
真实 human 输入"。这个判断发生在 `human → chat_end_detect → chat_llm` 之间，早于 `ai_node`
执行。

## 目标

1. `human_node` 只返回**当前轮次的原始 human 内容**，不再混入 aux 历史文本，不再永久污染
   `state["messages"]`。
2. aux 历史与 human 内容的拼接，改为在 `ai_node` 中**临时构造**，仅用于本次
   `chat_agent.ainvoke()` 调用，不写回 `state["messages"][-1]`。
3. 用于 memory 检索的 query 只使用原始 human 内容，不包含 aux 历史文本（因为
   `human_node` 不再合并，`state["messages"][-1]` 天然就是纯 human 内容，无需额外改动）。
4. 本轮被消费的 aux 历史内容不应被静默丢弃，需归档到 `ConversationState`，供审计/后续排查。

## 非目标

- 不改变 `auxiliary_messages_queue` 的写入方（`handlers/chat.py`、`finish.py` 中
  `append_auxiliary_message()` 调用点）。
- 不改变 `append_auxiliary_message()` 内部的摘要压缩逻辑（`CONTEXT_QUEUE_LEN` 超限时的 LLM
  摘要）。
- 不改变 memory 检索本身的算法（BM25 + 向量混合），只改变喂给它的 query 内容来源。

## 详细设计

### 改动 1 — `graph/nodes/human.py::human_node`

- 保留现有 5 分钟轮询超时逻辑不变（超时路径本来就不清空 aux，行为不变）。
- `human_queue` 非空后：
  - 仍然 snapshot + `.clear()` `human_queue` / `human_source_queue`。
  - **不再**读取、拼接、清空 `auxiliary_messages_queue` / `auxiliary_source_queue`。
  - `_last_was_auxiliary_only` 的计算方式不变：
    `not human_queue and bool(auxiliary_messages_queue)`，但改为**只读探测**（不清空 aux），
    因为 aux 的实际消费和清空推迟到了 `ai_node`。
  - `append_memory_record_sources(human_sources)` 保留在 `human_node`（只涉及 human 来源，
    与本次迁移无关）；`append_memory_record_sources(aux_sources)` 迁移到 `ai_node`（见下）。
- 返回值简化为：

```python
return {"messages": [HumanMessage(human_queue)]}
```

### 改动 2 — `graph/nodes/ai.py::ai_node`

在构造 `chat_agent.ainvoke()` 调用之前（现有代码中，`state["messages"][:-1] + mem_msg +
[state["messages"][-1]]` 的位置），新增一步：

1. 读取模块级 `auxiliary_messages_queue` / `auxiliary_source_queue`（`ai_node` 所在文件本身
   持有这两个全局变量，无需 import）。
2. 若非空，临时构造合并内容（不修改 `state["messages"][-1]` 本身）：

```python
merged_content = (
    [{"type": "text", "text": "## 历史聊天记录："}]
    + aux_queue
    + [{"type": "text", "text": "## 当前聊天记录："}]
    + state["messages"][-1].content
)
```

   并用一个临时消息对象（复制自 `state["messages"][-1]`，仅替换 `content`）替代传给
   `ainvoke()` 的最后一条消息。若 aux_queue 为空，直接使用 `state["messages"][-1]` 原样。

3. `append_memory_record_sources(aux_sources)`（从 `human.py` 迁移过来）。
4. 归档：将本轮消费的 `aux_queue` / `aux_sources`（合并前的原始数据）追加写入
   `ConversationState.auxiliary_queue` / `.auxiliary_source_queue`。
5. 清空模块级 `auxiliary_messages_queue` / `auxiliary_source_queue`（从 `human.py` 迁移过来）。

**memory 检索 query**：现有第 315 行 `last_content = state["messages"][-1].content` **保持不
变**——因为 `human_node` 不再合并 aux，`state["messages"][-1]` 现在天然就是纯 human 内容。

### 改动 3 — `graph/nodes/finish.py::finish_conversation_node`

对话结束时，除了现有逻辑（把完整 transcript 重新写回模块级 `auxiliary_messages_queue`，供
下一轮对话使用）之外，额外清空归档字段
`ConversationState.auxiliary_queue` / `.auxiliary_source_queue`，避免跨多轮对话的无限累积。

这与"写回模块级 `auxiliary_messages_queue`"是两件不同的事：
- 模块级 `auxiliary_messages_queue`：面向未来，给下一轮对话提供历史上下文。
- `ConversationState.auxiliary_queue`（归档字段）：面向过去，记录本次对话过程中每一轮实际
  消费过的 aux 历史快照，仅用于审计，随对话结束而清空。

## 数据流对比

**迁移前：**

```
human_node: 读 human_queue + aux_queue → 拼接 → 清空两者 → 写入 state["messages"]（永久）
ai_node:    读 state["messages"][-1]（已合并）→ 喂给 chat_agent
```

**迁移后：**

```
human_node: 读 human_queue → 清空 human_queue → 写入 state["messages"]（纯 human，永久）
            （只读探测 aux_queue 是否非空，计算 _last_was_auxiliary_only，不清空）
ai_node:    读 state["messages"][-1]（纯 human）→ 临时拼接 aux_queue → 喂给 chat_agent（不落盘）
            → 归档 aux_queue 到 ConversationState.auxiliary_queue → 清空模块级 aux_queue
finish_node: 对话结束时清空 ConversationState.auxiliary_queue（归档字段）
```

## 测试影响

- `test_human_node_returns_nonempty_content_when_queue_populated`、
  `test_human_node_queue_is_cleared_after_processing`：不涉及 aux，预期仍通过。
- `test_human_node_sets_auxiliary_only_flag_when_no_human_queue`、
  `test_human_node_clears_auxiliary_only_flag_when_human_queue_present`：需要检查断言是否依赖
  `human_node` 清空 aux 队列的副作用；若依赖，需更新为"只读探测、不清空"语义。
- 现有测试中**没有**覆盖"aux 非空 + human 非空"的合并分支（迁移前的 gap），迁移后需要在
  `ai_node` 侧补充等价的合并/归档/清空测试。
- 新增测试点：
  - `ai_node` 在 aux 非空时，构造的临时合并内容格式与迁移前 `human_node` 的格式一致。
  - `ai_node` 调用后，`state["messages"][-1]`（原始 human 消息）内容不受影响（未被污染）。
  - `ai_node` 调用后，模块级 `auxiliary_messages_queue` 被清空。
  - `ai_node` 调用后，`ConversationState.auxiliary_queue` 追加了本轮消费的 aux 内容。
  - `finish_conversation_node` 执行后，`ConversationState.auxiliary_queue` 被清空。
  - memory 检索 query 在 aux 非空时，仍只使用纯 human 内容（不含 aux 文本）。

## 待确认 / 已用默认值的决策

以下两点因用户当时不在线，按推荐项定稿，用户回来后仍可调整：

1. **归档字段选择**：复用现有的 `ConversationState.auxiliary_queue` /
   `auxiliary_source_queue`（目前基本死代码），赋予其"已消费 aux 历史归档"的新用途，而非新增
   专门字段。
2. **归档清理时机**：在 `finish_conversation_node`（对话结束）时清空，而非仅在 `/clear` 命令
   时清空，避免跨多轮对话累积增长。
