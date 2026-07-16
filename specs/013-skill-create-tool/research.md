# Research: Skill Create Tool

**Feature**: 013-skill-create-tool
**Date**: 2026-06-16

## Decisions

### Decision 1: Reuse SkillManager.parse_frontmatter_text()

**Rationale**: The `SkillManager` already has a `parse_frontmatter_text(text)` method that parses YAML frontmatter from raw text and returns `{name, description}`. Creating a separate parser would duplicate logic. The method only requires `name` to be present (description is optional for the download use case), so the `skill_create` tool layer adds the additional `description` validation.

**Alternatives considered**:
- Duplicate parsing logic in the tool — rejected: DRY violation, maintenance burden
- Modify `parse_frontmatter_text` to always require description — rejected: would break `skill_download` behavior

### Decision 2: Add save_skill() to SkillManager (not a standalone function)

**Rationale**: The `SkillManager` class already handles skill file lifecycle: `load_skill`, `remove_skill`, and `list_skills`. Adding `save_skill` keeps all file I/O in one place with access to `_content_cache` and `_skills_dir`.

**Alternatives considered**:
- Inline the file write in the tool — rejected: violates single responsibility, no cache clearing
- Standalone function in tools.py — rejected: no access to SkillManager cache state

### Decision 3: Overwrite existing files (matching skill_download)

**Rationale**: The existing `skill_download` tool overwrites files with the same name. Consistency between the two creation tools is important for predictable user experience.

**Alternatives considered**:
- Reject overwrites with error — rejected: forces users to manually delete before updating
- Versioned filenames — rejected: over-engineering for a skill management system

### Decision 4: No return_direct on the tool

**Rationale**: The LLM should be able to process the tool result and add commentary (e.g., "I've created the skill for you!"). `return_direct=True` would send the raw tool output directly to the user without LLM processing.

**Alternatives considered**:
- `return_direct=True` — rejected: less natural conversation flow
