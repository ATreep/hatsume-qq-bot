# Feature Specification: Skill Create Tool

**Feature Branch**: `013-skill-create-tool`

**Created**: 2026-06-16

**Status**: Draft

**Input**: User description: "Add a skill_create tool for the chat agent. The input argument is the skill content (must include YAML frontmatter), and this tool parses the skill name and description (must have both attributes) from the frontmatter and saves the skill file into data/hatsume-plugin/skills/."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create New Skill from Content (Priority: P1)

A user wants to create a new custom skill by providing the complete markdown content directly to the bot. The content includes YAML frontmatter with the skill's name and description. The bot parses the frontmatter, validates the required fields, saves the file, and confirms creation.

**Why this priority**: This is the core functionality — the primary reason the tool exists. Without this, nothing else matters.

**Independent Test**: Can be fully tested by providing valid markdown content with frontmatter containing both `name` and `description` fields. Confirms the skill file is written to disk and the bot confirms the creation.

**Acceptance Scenarios**:

1. **Given** the chat agent is running, **When** the LLM calls `skill_create` with content containing valid frontmatter (`name: "my-skill"`, `description: "Does something useful"`), **Then** a file `my-skill.md` is saved to the skills directory and the bot returns a success message: `"✅ 技能 'my-skill' 已创建。"`
2. **Given** the skills directory contains `my-skill.md`, **When** the skill list is queried after creation, **Then** `my-skill` appears in the list with its description.

---

### User Story 2 - Overwrite Existing Skill (Priority: P1)

A user wants to update an existing skill by providing new content with the same `name`. The tool detects the existing file, overwrites it with the new content, and warns that the file was overwritten.

**Why this priority**: Skills evolve over time. Users must be able to update them without manually deleting first. Same priority as creation because the update path is equally important.

**Independent Test**: Can be fully tested by calling `skill_create` twice with the same `name` but different body content. Verifies the second call returns an overwrite warning and the file contains the new content.

**Acceptance Scenarios**:

1. **Given** a skill file `my-skill.md` already exists, **When** the LLM calls `skill_create` with new content using the same `name` frontmatter field, **Then** the existing file is overwritten and the bot returns: `"✅ 技能 'my-skill' 已创建（覆盖了已有文件）。"`
2. **Given** a skill is overwritten, **When** the skill is loaded via `skill_loader`, **Then** the new content is returned, not the old.

---

### User Story 3 - Validation of Required Fields (Priority: P2)

The tool rejects content that is missing required frontmatter fields, providing clear error messages so the user (or the LLM acting on their behalf) can fix the input.

**Why this priority**: Input validation prevents broken or invisible skill files. Without it, users could create skill files that don't appear in the skill list or can't be loaded properly.

**Independent Test**: Can be fully tested by providing content missing `name`, missing `description`, or missing frontmatter entirely. Verifies appropriate error messages for each case.

**Acceptance Scenarios**:

1. **Given** content has no YAML frontmatter (no `---` delimiter), **When** `skill_create` is called, **Then** the tool returns: `"错误：内容不是有效的技能文件（缺少 --- frontmatter 或 'name' 字段）。"`
2. **Given** content has frontmatter but no `name` field, **When** `skill_create` is called, **Then** the tool returns an error message mentioning the missing `name` field.
3. **Given** content has frontmatter with `name` but no `description` field, **When** `skill_create` is called, **Then** the tool returns: `"错误：frontmatter 中缺少 'description' 字段。"`

---

### Edge Cases

- What happens when the skills directory doesn't exist yet? The system creates it automatically before saving.
- What happens when a file write fails (disk full, permission denied)? The tool returns a user-friendly error message instead of crashing.
- What happens when the content contains a `name` with special characters (spaces, slashes)? The name is used as-is for the filename (`{name}.md`); the filesystem may reject invalid characters, which will surface as a write error.
- What happens when two concurrent `skill_create` calls target the same skill name? Last write wins — no locking needed for this use case.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The chat agent MUST expose a `skill_create` tool that accepts a single `content` string parameter containing the full skill markdown with YAML frontmatter.
- **FR-002**: The tool MUST parse the YAML frontmatter to extract `name` and `description` fields.
- **FR-003**: The tool MUST reject content that lacks a valid YAML frontmatter (starting with `---`) or lacks a `name` field, returning a descriptive error message.
- **FR-004**: The tool MUST reject content that has a `name` but lacks a non-empty `description` field, returning an error message that includes the skill name.
- **FR-005**: The tool MUST save the skill file to the configured skills directory (`data/hatsume-plugin/skills/`) with the filename `{name}.md`.
- **FR-006**: The tool MUST overwrite an existing file with the same name and return a message indicating the overwrite occurred.
- **FR-007**: The tool MUST clear any cached content for the skill after saving, so subsequent loads return the fresh content.
- **FR-008**: The tool MUST create the skills directory if it does not already exist.
- **FR-009**: The tool MUST handle write failures gracefully with a user-readable error message.
- **FR-010**: The new `skill_create` tool MUST be registered in the chat agent's available tools list so the LLM can invoke it.

### Key Entities

- **Skill File**: A markdown file (`.md`) stored in the skills directory. Contains YAML frontmatter with at minimum `name` (unique identifier, used as filename) and `description` (one-line summary shown in skill listings), followed by markdown body content with the skill's instructions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The LLM can successfully create a new skill and verify it appears in the skill list within the same conversation turn.
- **SC-002**: 100% of invalid inputs (missing frontmatter, missing name, missing description) return a descriptive error message rather than silently creating broken skill files.
- **SC-003**: Existing skill updates via `skill_create` take effect immediately — loading the skill by name after an overwrite returns the new content.
- **SC-004**: All existing skill management tools (`skill_loader`, `skill_remove`, `skill_download`, `list_skills`) continue to function normally after the new tool is added.

## Assumptions

- The YAML frontmatter format follows the same convention as existing skill files (`cat-girl.md`, `leijun-perspective.md`): `---`, YAML fields, `---`, then markdown body.
- The `name` field in frontmatter is used as the filename (`{name}.md`). Characters valid in markdown frontmatter keys are assumed to be valid in filenames.
- The `SkillManager` singleton and `parse_frontmatter_text()` method are reused — no new parsing logic needed.
- Concurrent `skill_create` calls for the same skill name are not a concern in a single-bot-single-conversation context; last-write-wins is acceptable.
- The new `save_skill()` method on `SkillManager` is internal infrastructure; the chat agent tool is the public interface.
