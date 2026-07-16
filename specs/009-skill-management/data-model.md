# Data Model: Skill Management System

**Feature**: 009-skill-management
**Date**: 2026-06-08

## Entities

### Skill File (on disk)

A markdown file stored at `data/hatsume-plugin/skills/<name>.md`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique skill identifier, from YAML frontmatter |
| `description` | string | Yes | When to use this skill, from YAML frontmatter |
| `content` | string | Yes | Full markdown body after frontmatter |

**File format**:
```markdown
---
name: skill-name
description: When and why to use this skill.
---

# Skill Title

...skill instruction content in markdown...
```

**Identity**: `name` is the unique identifier. If two files have the same `name`, the last one scanned wins (filesystem order).

**Lifecycle**:
```
[Created on disk] → [Discovered by list_skills()] → [Loaded via load_skill()]
                                                          ↓
[Removed via skill_remove()] ← [Content updated on disk] ← [Conversation ends, dedup cleared]
```

### Skill Manager (in memory)

| Field | Type | Description |
|-------|------|-------------|
| `_skills_dir` | Path | Path to the skills directory |
| `_content_cache` | dict[str, str] | `name → full_file_content` cache |
| `_loaded_this_conversation` | set[str] | Names loaded in current conversation |

**Lifecycle**: Created on first `get_skill_manager()` call. Lives for the duration of the bot process.

### Skill List Entry (transient)

Returned by `list_skills()`, consumed by `build_skill_prompt()`.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Skill identifier |
| `description` | str | When to use this skill |

## State Transitions

### Skill File Lifecycle

```
                    list_skills()
                         │
                    ┌────▼────┐
                    │ Scanned │  (name + description extracted from frontmatter)
                    └────┬────┘
                         │ load_skill(name)
                    ┌────▼────┐
                    │ Loaded  │  (full content in cache, name in dedup set)
                    └────┬────┘
                         │ reset_conversation()
                    ┌────▼────┐
                    │ Cached  │  (content stays in cache, name removed from dedup)
                    └────┬────┘
                         │ remove_skill(name)  OR  skill_download(url) overwrite
                    ┌────▼────┐
                    │ Removed │  (file deleted, cache entry cleared)
                    └─────────┘

[Download URL] → skill_download(url) → [Parse frontmatter for name] → [Save as {name}.md] → [Available via list_skills()]
```

### Tool Invocation Flow

```
Tool invoked by LLM
    │
    ▼
check_tool_call(tool_name)
    │
    ├── tool_name in _UNLIMITED_TOOLS? → return None (always OK)
    │
    └── tool_name NOT in _UNLIMITED_TOOLS
        ├── first call → return None (OK)
        └── second+ call → return error message (rejected)
```

## Unlimited Tool Whitelist

A `frozenset` of tool names exempt from single-invocation restriction.

| Field | Type | Description |
|-------|------|-------------|
| `_UNLIMITED_TOOLS` | frozenset[str] | Tool names allowed unlimited calls |

**Members**: `web_browser`, `search_web`, `skill_loader`, `skill_download`, `skill_remove`, `create_timer`, `list_timers`, `delete_timer`

**Lifecycle**: Defined at module load time, immutable. No runtime modifications.

## Validation Rules

1. `name` must be non-empty after stripping whitespace
2. `description` must be non-empty after stripping whitespace
3. Files without valid `---` delimited frontmatter are skipped
4. Files without `.md` extension are ignored
5. Duplicate `name` values log a warning; last one wins
