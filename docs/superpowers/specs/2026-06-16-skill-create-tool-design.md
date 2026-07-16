# Design: `skill_create` Tool for Chat Agent

**Date**: 2026-06-16
**Status**: approved

## Goal

Add a `skill_create` tool to the chat agent so the LLM can create or update skill files from raw markdown content containing YAML frontmatter. This complements `skill_download` (URL-based) with a direct-content pathway.

## Behavior

| Scenario | Result |
|----------|--------|
| Valid content, new skill name | Save file, return `"✅ 技能 'xxx' 已创建。"` |
| Valid content, existing skill name | Overwrite file, return `"✅ 技能 'xxx' 已创建（覆盖了已有文件）。"` |
| No YAML frontmatter (`---`) | Return error: `"错误：内容不是有效的技能文件（缺少 --- frontmatter）。"` |
| Missing `name` field | Return error: `"错误：frontmatter 中缺少 'name' 字段。"` |
| Missing `description` field | Return error: `"错误：frontmatter 中缺少 'description' 字段。"` |

Both `name` and `description` are required because `SkillManager.list_skills()` filters to entries with both fields.

Overwrite behavior matches the existing `skill_download` tool.

The tool uses default LangChain tool behavior (no `return_direct`) — the LLM can process the result and add commentary before replying to the user.

## Architecture

```
skill_create(content: str) → str
  │
  ├─ SkillManager.parse_frontmatter_text(content)   # existing, validates name present
  ├─ Check description non-empty                     # NEW validation
  └─ SkillManager.save_skill(name, content)           # NEW method
       ├─ Write data/hatsume-plugin/skills/{name}.md
       └─ Clear _content_cache[name]
```

### Files touched

| File | Change |
|------|--------|
| `hatsume/plugins/hatsume-plugin/skills/manager.py` | Add `save_skill(name, content)` method |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Add `@tool skill_create(content: str) -> str` |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Import `skill_create`, add to chat agent tools list |

### New `SkillManager.save_skill(name, content)`

```python
def save_skill(self, name: str, content: str) -> str:
    """Save a skill file and clear its cache entry.

    Returns success message with overwrite flag.
    """
    self._ensure_dir()
    file_path = self._skills_dir / f"{name}.md"
    existed = file_path.exists()
    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"❌ [skills] Failed to write skill '{name}': {e}")
        return f"错误：保存技能文件失败：{e}"
    self._content_cache.pop(name, None)
    if existed:
        print(f"✅ [skills] Overwrote skill '{name}'")
        return f"✅ 技能 '{name}' 已创建（覆盖了已有文件）。"
    else:
        print(f"✅ [skills] Created skill '{name}'")
        return f"✅ 技能 '{name}' 已创建。"
```

### New `skill_create` tool

```python
@tool
def skill_create(content: str) -> str:
    """
    根据提供的内容创建一个新技能。内容必须包含 YAML frontmatter。

    ## 参数：
    - content: 完整的技能 markdown 内容，必须以 --- 开头的 YAML frontmatter 开始。
      frontmatter 中必须包含 name（技能名称）和 description（技能描述）字段。

    ## 行为：
    - 从 frontmatter 中自动解析 name 和 description
    - 保存为 data/hatsume-plugin/skills/{name}.md
    - 如果同名技能已存在，覆盖并提示
    - 创建后技能立即可用

    ## 使用时机：
    - 用户明确要求创建或编写一个新技能
    - 用户提供了完整的技能内容（含 frontmatter）
    """
```

## Testing

Unit tests covering:
1. Valid content with both `name` and `description` → success
2. Missing `description` in frontmatter → error
3. Missing `name` in frontmatter → error
4. Missing YAML frontmatter entirely → error
5. Overwrite existing skill → returns overwrite message

## Relation to existing tools

| Tool | Input | Purpose |
|------|-------|---------|
| `skill_download` | URL | Download skill from remote URL |
| `skill_create` (NEW) | Raw content string | Create/update skill from provided content |
| `skill_loader` | Name | Load skill instructions into conversation |
| `skill_remove` | Name | Delete skill file |
