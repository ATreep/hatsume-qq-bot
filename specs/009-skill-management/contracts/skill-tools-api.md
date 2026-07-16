# Skill Tools & Command API Contract

**Feature**: 009-skill-management
**Date**: 2026-06-08
**Updated**: 2026-06-09 — Added `skill_download` tool and `/skills` command

## Overview

Three LangChain tools exposed to the chat agent's LLM, plus one NoneBot command for users. All tools are defined with the `@tool` decorator and registered in the `create_agent()` tools list. The command is registered via `on_command()` in `__init__.py`.

## Tools

### skill_loader

Loads a skill's full content by name.

```
Tool Name: skill_loader
Parameters:
  - name: str  (required) — the skill name to load
Returns: str — full skill content, or error message
```

**Behavior**:
- If skill is already loaded this conversation → returns "技能 '{name}' 已在本次对话中加载。"
- If skill exists in cache or on disk → reads full content, caches, marks loaded, returns content
- If skill does not exist → returns "错误：技能 '{name}' 不存在。"

**Side effects**:
- Adds `name` to per-conversation dedup set
- Caches content in memory on first load

### skill_remove

Removes a skill file from disk.

```
Tool Name: skill_remove
Parameters:
  - name: str  (required) — the skill name to remove
Returns: str — success confirmation or error message
```

**Behavior**:
- If skill exists → deletes file from disk, clears cache entry, returns "✅ 技能 '{name}' 已删除。"
- If skill does not exist → returns "错误：技能 '{name}' 不存在。"

**Safety**: Tool description instructs LLM to ONLY call this when user explicitly requests skill removal. No code-level permission check.

**Side effects**:
- Deletes `.md` file from `data/hatsume-plugin/skills/`
- Removes entry from content cache
- Does NOT clear from dedup set (already loaded skills remain in conversation context)

### skill_download

Downloads a skill markdown file from a raw URL and saves it to the skills directory.

```
Tool Name: skill_download
Parameters:
  - url: str  (required) — raw URL to a skill markdown file
Returns: str — success/overwrite confirmation or error message
```

**Behavior**:
- Downloads content from URL via HTTP GET (10s timeout)
- Parses YAML frontmatter to extract `name`
- If frontmatter missing or `name` empty → returns error, no file written
- If skill with same `name` already exists → overwrites, response notes "overwritten"
- If new skill → saves as `{name}.md`, response notes "downloaded"
- Clears SkillManager content cache for that name
- Saves file with UTF-8 encoding

**Error cases**:
- Network error (timeout, DNS failure, 404) → returns error describing the failure
- Invalid frontmatter → returns "错误：无法从下载内容中解析技能名称"
- Empty response body → returns error

**Side effects**:
- Creates or overwrites `.md` file in `data/hatsume-plugin/skills/`
- Clears entry from SkillManager content cache
- Does NOT add to dedup set (available fresh for next load_skill call)

**Note in tool description**: "你可以通过 `web_browser` 工具浏览网页，找到 skill 文件的 raw URL。"

## Command

### /skills

A NoneBot command (`on_command`) that lists all available skills.

```
Command: /skills
Access: Any user, any group
Output: Formatted text list of skills (name + description), or "no skills" message
```

**Behavior**:
- Calls `get_skill_manager().list_skills()`
- If skills exist → returns formatted list:
  ```
  当前可用技能：
  - **{name}**: {description}
  - **{name}**: {description}
  ```
- If no skills → returns: "当前没有可用技能。"
- No caching — each invocation reflects current filesystem state

**Integration**: Registered in `__init__.py` as `on_command("skills", priority=10, block=True)`. Handler in `handlers/commands.py`.

## Prompt Injection Contract

### build_skill_prompt

Generates the skill list section for the system prompt.

```
Function: build_skill_prompt(skills: list[dict]) -> str
Input: [{"name": str, "description": str}, ...]
Output: str — formatted prompt section, or "" if skills list is empty
```

**Output format** (when skills exist):
```

# 可用技能

以下是你可以使用的技能。当用户的需求匹配某个技能的描述时，调用 `skill_loader` 工具加载该技能以获取详细指令。

- **{name}**: {description}
- **{name}**: {description}
...
```

**Output** (when no skills): Empty string `""`.

## Integration Points

| Point | File | Method |
|-------|------|--------|
| Skill list injection | `graph/nodes/ai.py` `ai_node()` | Call `get_skill_manager().list_skills()` → `build_skill_prompt()` → append to `sys_prompt` |
| Tool registration | `graph/nodes/ai.py` `ai_node()` | Add `skill_loader`, `skill_remove`, `skill_download` to `create_agent()` tools list |
| Conversation end | `graph/nodes/finish.py` | Call `get_skill_manager().reset_conversation()` |
| Config | `config.py` | `SKILLS_DIR` path constant |
| `/skills` command | `__init__.py` | Register `skills_cmd = on_command("skills", ...)` |
| `/skills` handler | `handlers/commands.py` | `handle_list_skills(matcher, args)` |
| Unlimited tool whitelist | `graph/tools.py` | `_UNLIMITED_TOOLS` frozenset + guard in `check_tool_call()` |
