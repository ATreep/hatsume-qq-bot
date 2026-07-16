# Quickstart: 修复 JSON 输出格式与合并转发消息可见性

**Date**: 2026-05-31
**Plan**: [plan.md](./plan.md)

## Testing

```bash
# Run all related tests
python -m pytest tests/test_forward.py tests/test_ai_json_output.py tests/test_pipeline_json.py -v

# Verify no regression on existing test suite
python -m pytest tests/ -v
```

## Verification Checklist

1. prompts.py: role_sys_prompt 不含格式指令
2. ai.py: _OUTPUT_FORMAT_INSTRUCTION 存在，追加到 sys_prompt
3. pipeline.py: case "forward" 分支 + debug 日志
4. forward.py: 成功路径 debug 日志
5. All tests pass
