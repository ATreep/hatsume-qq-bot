# Data Model: Skill Create Tool

**Feature**: 013-skill-create-tool
**Date**: 2026-06-16

## Entities

### Skill File

A markdown file stored on disk in the skills directory.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Unique skill identifier. Used as filename (`{name}.md`). Must be present in YAML frontmatter. |
| `description` | string | Yes | One-line summary shown in skill listings. Must be non-empty for `skill_create`. |
| `version` | string | No | Optional version string (informational only). |
| `author` | string | No | Optional author name (informational only). |
| `tags` | list | No | Optional tags for categorization (informational only). |
| `content` | string | Yes | Full markdown body containing the skill's instructions. Everything after the second `---` delimiter. |

### SkillManager Cache

In-memory cache (`_content_cache: dict[str, str]`) mapping skill name → full file content. Invalidated on `save_skill()`.

### Validation Rules

1. Content must start with `---` (YAML frontmatter delimiter).
2. Frontmatter must contain a non-empty `name` field.
3. Frontmatter must contain a non-empty `description` field.
4. No validation on filename characters — filesystem rejects invalid names naturally.

## State Transitions

```
                    ┌──────────────────┐
                    │  Skill does not  │
                    │      exist       │
                    └────────┬─────────┘
                             │ skill_create(content)
                             ▼
                    ┌──────────────────┐
                    │  Skill created   │
                    │  (on disk)        │
                    └────────┬─────────┘
                             │ skill_create(content) with same name
                             ▼
                    ┌──────────────────┐
                    │  Skill overwritten│
                    │  (cache cleared)  │
                    └──────────────────┘
```
