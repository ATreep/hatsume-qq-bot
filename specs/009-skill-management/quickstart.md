# Quickstart: Skill Management System

**Feature**: 009-skill-management
**Date**: 2026-06-08
**Updated**: 2026-06-09 — Added `/skills` command, skill download via chat, unlimited invocation

## Overview

Skills let you extend the bot's capabilities by writing markdown files. Each skill file contains instructions that the LLM can load on-demand when relevant to the conversation. You can manage skills in three ways:

1. **Manually** — place `.md` files in the skills directory (requires filesystem access)
2. **Via `/skills` command** — list all available skills from chat
3. **Via chat** — ask the bot to download skills from URLs or remove them

## Listing Available Skills

Send `/skills` in any group chat:

```
/skills
```

The bot replies with a list of all available skills:

```
当前可用技能：
- **zhangxuefeng-perspective**: 张雪峰的思维框架与表达方式...
- **trump-perspective**: Trump's communication patterns...
```

If no skills are installed: `当前没有可用技能。`

## Downloading a Skill from URL

1. Find a skill markdown file online (e.g., in a GitHub repository)
2. Copy the **raw URL** of the file (use the `web_browser` tool to help find it)
3. Ask the bot to download it, e.g., "下载技能 https://raw.githubusercontent.com/.../skill-name.md"

The bot will:
- Download the file
- Extract the skill name from its frontmatter
- Save it to the skills directory as `{name}.md`
- Confirm success (or report an error)

If a skill with the same name already exists, it will be overwritten (with a note in the confirmation).

## Adding a Skill Manually

1. Create a `.md` file in `data/hatsume-plugin/skills/`:

```markdown
---
name: math-tutor
description: 当用户需要数学辅导、解题或数学概念解释时使用此技能。
---

# Math Tutor Skill

当用户提出数学问题时，请按以下步骤解答：

1. 先确认用户的问题类型（代数、几何、微积分等）
2. 用通俗易懂的语言解释核心概念
3. 给出解题步骤，每步附上解释
4. 最后总结关键知识点

注意：
- 使用中文回答
- 避免使用过于专业的术语
- 如果题目有多种解法，简要提及其他思路
```

2. That's it. The next time someone triggers a conversation, the bot will see `math-tutor` in its available skills and load it when relevant.

## Removing a Skill

**In chat**: Explicitly tell the bot to remove a skill, e.g., "删除技能 math-tutor".

**Manually**: Delete the `.md` file from `data/hatsume-plugin/skills/`.

## Skill File Format

```markdown
---
name: <unique-skill-name>
description: <when-to-use-this-skill>
---

<skill content in markdown>
```

- `name`: A unique identifier for the skill. Use lowercase, hyphens for spaces.
- `description`: Tells the LLM when this skill is relevant. Be specific about triggers.
- Content: Everything after the second `---` is the skill body, loaded when the LLM calls `skill_loader`.

## Tips

- **Be specific in descriptions**: "当用户询问天气相关信息时使用" is better than "天气技能"
- **Keep content focused**: Each skill should do one thing well
- **Test with explicit requests**: Ask the bot something clearly in the skill's domain to trigger loading
- **Update on the fly**: Edit the `.md` file anytime — changes take effect on the next conversation
