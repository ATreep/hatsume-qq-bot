# Implementation Plan: 修复 JSON 输出格式与合并转发消息可见性

**Branch**: `002-fix-json-output-forward-visibility` | **Date**: 2026-05-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-fix-json-output-forward-visibility/spec.md`

**Parent Plan**: [001-forward-message-support/plan.md](../001-forward-message-support/plan.md)

## Summary

两项精准修复：(1) 将 LLM 输出 JSON 格式指令从角色系统提示词中分离，改为在 `ai.py` 创建 chat_agent 时追加到 system prompt 末尾；(2) 在 pipeline.py 消息段遍历循环中增加 `case "forward"` 分支，并在 forward 处理全链路添加 debug 日志。

## Technical Context

**Language/Version**: Python 3.12+

**Primary Dependencies**: NoneBot2 (OneBot V11 adapter), LangChain/LangGraph, langchain-openai

**Storage**: N/A (no new storage)

**Testing**: pytest（现有框架）

**Target Platform**: Linux/macOS 服务器（Python 运行时）

**Project Type**: QQ 群机器人插件（NoneBot2 插件）

**Performance Goals**: 不增加延迟（json.dumps 和 print 日志开销可忽略）

**Constraints**: 不改变现有消息队列流、状态管理和 graph 执行流程；现有 31 个单元测试保持通过

**Scale/Scope**: 修改 4 个文件：prompts.py, ai.py, pipeline.py, forward.py

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

No project-specific constitution rules defined. All gates pass by default.

- Follow existing patterns: async handlers, dataclass state, pipeline message flow
- Maintain existing test framework (pytest)
- No new external dependencies required

## Project Structure

### Documentation (this feature)

```text
specs/002-fix-json-output-forward-visibility/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── prompts.py               # [MODIFY] 移除 "## 你的输出格式" section
├── graph/nodes/
│   └── ai.py                # [MODIFY] 新增 _OUTPUT_FORMAT_INSTRUCTION 常量，追加到 sys_prompt
├── handlers/
│   ├── pipeline.py          # [MODIFY] 增加 case "forward" + debug 日志
│   └── forward.py           # [MODIFY] 增加成功路径 debug 日志

tests/
├── test_forward.py          # [MODIFY] 新增 forward segment 遍历测试
└── test_ai_json_output.py   # [MODIFY] 新增 prompt 分离验证测试
```

**Structure Decision**: 沿用现有项目布局，仅修改已有文件。不新增模块。

## Complexity Tracking

> No constitution violations to justify. All design choices follow existing project patterns.

## Phase 0: Research

No unresolved unknowns. Design decisions already made during brainstorming:

| Decision | Rationale |
|----------|-----------|
| 格式指令从 role prompt 移至 agent 创建处 | 角色提示词保持纯粹（人设+规则），输出格式是指令层关注点 |
| 指令追加在 system prompt 末尾 | 近因效应（recency effect），提高 LLM 遵循率 |
| `case "forward"` 追加 `[合并转发消息]` 标记 | 防御性修复：即使 API 失败，LLM 也能感知转发存在 |
| debug 日志覆盖全链路 | 定位生产问题的前置条件 |
| 保留现有 JSON fallback | 向后兼容，安全网 |

### _OUTPUT_FORMAT_INSTRUCTION 指令设计

```text
## 输出格式（必须严格遵守）

你的一切回复必须以 JSON 格式输出：
{"message": "你的回复内容"}

- 只输出这一行 JSON，不要输出任何其他文字
- message 字段中的内容遵循角色设定中的格式规则
- 不允许在 JSON 之外输出解释、前缀、后缀
```

### Debug 日志点位

```text
pipeline.py:
  - has_forward_segment(msg) 返回值
  - resolve_forward_content() 返回的消息数量
  - 前 3 条子消息预览

forward.py:
  - parse_forward_messages() API 调用成功时的消息数量
  - 前 3 条已解析消息的 type/user/content 预览
```

## Phase 1: Design

### Data Model

See [data-model.md](./data-model.md).

No new entities. Changes only to instruction text (string constant) and debug log output.

### Quickstart

See [quickstart.md](./quickstart.md).

Testing: 运行 `python -m pytest tests/ -v` 验证所有测试通过，确认 prompts.py 中移除格式指令后测试仍然正确。

### Contracts

No external interface changes. Internal changes only:
- `get_role_sys_prompt()` 返回值移除格式指令段落
- `ai_node()` 内部逻辑变更：`sys_prompt` 组装方式改变
- `get_human_message()` 的 `plain_message` 构建增加 `"forward"` case
