# Quickstart: Group Member Fuzzy Search

**Feature**: 011-group-member-search

## For Users

### /membersearch Command

```
/membersearch <nickname-keyword>
```

**Examples:**
- `/membersearch 菠萝` — find members whose name contains "菠萝"
- `/membersearch 张` — find all members with "张" in name (max 5)

**Output:**
```
搜索 '菠萝' 的结果：
1. 菠萝面包 (QQ: 123456) - 活跃LV6
2. 测试菠萝二号 (QQ: 000002) - 未知
```

### LLM Tool

The chat agent can call the `membersearch` tool when identifying users by vague nickname. Returns JSON array sorted by relevance.

## For Developers

### Core Function

```python
from hatsume.plugins.hatsume-plugin.utils import search_group_members

results = await search_group_members(bot, group_id, "菠萝")
# => [{"username": "菠萝面包", "id": "123456", "level": "活跃LV6"}, ...]
```

### Tests

```bash
python -m pytest tests/test_membersearch.py -v
```

### Key Files

| File | What |
|------|------|
| utils.py | search_group_members() |
| graph/tools.py | membersearch @tool |
| handlers/commands.py | handle_membersearch() |
| __init__.py | Command registration |
| tests/test_membersearch.py | All tests |
