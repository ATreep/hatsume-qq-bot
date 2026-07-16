# Quickstart: 合并转发消息解析

**Date**: 2026-05-31

## Prerequisites

- Python 3.12+
- 项目依赖已安装
- OneBot 11 实现正在运行且正确实现 `get_forward_msg` API
- QQ 群中有成员可发送合并转发消息

## Development Setup

```bash
# 1. 确认在 feature 分支
git branch  # 应显示 * 001-forward-message-support

# 2. 运行现有测试确认基线
python -m pytest tests/ -v

# 3. 启动机器人
./run_nb.sh
```

## Manual Testing

### Test 1: 单层合并转发

1. 在 QQ 群中，由成员 A 选择几条成员 B、C 的聊天记录，合并转发到群里
2. @机器人 让机器人参与讨论
3. 验证：机器人回复中引用了合并转发中的具体内容，且能区分转发者 vs 原始发送者

### Test 2: 嵌套合并转发

1. 成员 D 合并转发一条消息，其中包含成员 E 之前发出的另一条合并转发
2. @机器人 讨论转发内容
3. 验证：机器人能理解各层消息的归属关系

### Test 3: 普通消息兼容性

1. 发送普通消息（不含合并转发），验证机器人行为无变化

### Test 4: 失败恢复

1. 模拟 API 不可用场景，验证机器人仍能正常回复不崩溃

## Key Files

| File | Change |
|------|--------|
| `handlers/forward.py` | **New** — 合并转发解析 |
| `handlers/pipeline.py` | JSON 格式 + forward 委托 |
| `utils.py` | 删除 `generate_msg_template()`，新增 `message_to_json()` |
| `prompts.py` | JSON 格式说明 + LLM 输出要求 |
| `graph/nodes/ai.py` | LLM JSON 输出解析 |

## Running Tests

```bash
python -m pytest tests/ -v
python -m pytest tests/test_forward.py -v
python -m pytest tests/test_pipeline_json.py -v
python -m pytest tests/test_ai_json_output.py -v
```
