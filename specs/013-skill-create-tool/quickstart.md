# Quickstart: Skill Create Tool

**Feature**: 013-skill-create-tool
**Date**: 2026-06-16

## Overview

The `skill_create` tool lets the LLM create or update skill files from raw markdown content.

## How It Works

1. User asks the bot to create a skill: *"帮我创建一个新技能"*
2. The LLM constructs the full skill markdown content with YAML frontmatter.
3. The LLM calls `skill_create(content)` with the constructed content.
4. The tool parses the frontmatter, validates `name` and `description`, and saves to `data/hatsume-plugin/skills/{name}.md`.
5. The bot confirms the creation to the user.

## Files Affected

| File | Change |
|------|--------|
| `hatsume/plugins/hatsume-plugin/skills/manager.py` | Add `save_skill()` method |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Add `@tool skill_create(content)` |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Import + register in chat agent |

## Testing

```bash
# Run skill_create tests
python -m pytest tests/test_skill_create.py -xvs

# Run existing skill management tests
python -m pytest tests/test_skill_manager.py -xvs
```
