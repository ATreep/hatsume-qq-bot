# Research: 修复 JSON 输出格式与合并转发消息可见性

**Date**: 2026-05-31
**Plan**: [plan.md](./plan.md)

## Design Decisions

All decisions finalized during brainstorming phase. No open research questions.

### Decision 1: 输出格式指令分离策略

- **Decision**: 将 JSON 输出格式指令从 `prompts.py` 的 `role_sys_prompt` 中移除，在 `ai.py` 创建 `chat_agent` 时作为独立常量追加到 system prompt 末尾
- **Rationale**: 角色提示词应纯粹定义人设和对话规则（"是什么"），输出格式是技术指令（"怎么做"）。放在 agent 创建处更易维护和调试。system prompt 末尾的位置利用近因效应提高 LLM 遵循率
- **Alternatives considered**:
  - 保持现状（格式指令嵌入 role prompt）：LLM 忽略率较高，且修改格式时需要改动角色提示词
  - 使用 model `response_format` 参数：LangChain `create_agent()` 不直接暴露此参数，且不同 provider 支持度不一致

### Decision 2: Forward segment 显式处理

- **Decision**: 在 `get_human_message()` 的 segment 遍历 match-case 中增加 `case "forward"` 分支，追加 `[合并转发消息 id=xxx]` 标记到 `plain_message`
- **Rationale**: 防御性措施。即使 `get_forward_msg` API 失败，LLM 也能感知到转发消息的存在（而非完全空白）。与现有的 `has_forward_segment()` + `resolve_forward_content()` 路径互补
- **Alternatives considered**:
  - 仅依赖独立 forward 处理路径：API 调用失败时 forward 内容完全丢失，LLM 看不到任何转发痕迹
  - 在检测阶段抛异常：不符合 graceful degradation 原则

### Decision 3: Debug 日志粒度

- **Decision**: 全链路日志：检测（has_forward_segment 返回值）→ API（resolve_forward_content 消息数量）→ 构建（前 3 条子消息预览）
- **Rationale**: 足够定位问题而不过度刷屏。前 3 条预览提供足够上下文判断解析是否正确
- **Alternatives considered**:
  - 仅异常日志：无法排查 API 成功但内容丢失的问题
  - 全量消息日志：合并转发可能包含几十条消息，日志会过于冗长
