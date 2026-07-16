# Feature Specification: Skill Management System

**Feature Branch**: `009-skill-management`

**Created**: 2026-06-08

**Updated**: 2026-06-09 — Added `/skills` command, `skill_download` tool, unlimited tool invocation whitelist

**Status**: Draft

**Input**: User description: "Design a skill management system module. Add a skill loader tool for chat_agent. When enter ai_node in langgraph, inject all skills' names and descriptions to system prompts, and prompt LLM to invoke relative skills by the skill loading tool. Also add a skill remove tool. Only remove a skill when user obviously requires to remove it!"

**Extension**: "/skills command, skill_download tool, unlimited invocation for utility tools"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator Adds a Skill (Priority: P1)

An operator (bot administrator) wants to extend the bot's capabilities by creating a new skill file. They write a markdown file with YAML frontmatter (`name` and `description`) and place it in the skills directory. The next time anyone triggers a conversation with the bot, the bot sees the new skill in its available skills list and can invoke it when relevant.

**Why this priority**: This is the foundation — without skills being discoverable and loadable, the system provides no value. It's the core mechanism that enables all other skill interactions.

**Independent Test**: Drop a `.md` skill file into the skills directory, trigger a conversation, and verify the LLM's system prompt includes the skill's name and description. Then ask something matching the skill's domain and verify the LLM calls `skill_loader` to load the full content.

**Acceptance Scenarios**:

1. **Given** a skill file exists in the skills directory, **When** a conversation starts and the AI node is entered, **Then** the system prompt includes the skill's name and description in the available skills list.
2. **Given** the LLM sees a relevant skill in the available list, **When** a user asks something matching that skill's domain, **Then** the LLM invokes the `skill_loader` tool with the skill's name and receives the full skill content.
3. **Given** the skills directory is empty, **When** a conversation starts, **Then** the system prompt contains no skill-related content and the LLM behaves normally.
4. **Given** a skill was already loaded in the current conversation, **When** the LLM tries to load the same skill again, **Then** the loader indicates the skill is already loaded (deduplication).

---

### User Story 2 - Operator Removes a Skill (Priority: P2)

An operator wants to remove a skill that is no longer needed or contains outdated instructions. They explicitly tell the bot to remove a specific skill. The bot invokes the `skill_remove` tool, which deletes the skill file from the skills directory.

**Why this priority**: Removal is important for skill lifecycle management, but skills can also be removed manually from the filesystem. The tool provides a convenient in-chat mechanism but is not strictly required for MVP.

**Independent Test**: With a skill file present, explicitly ask the bot to remove that skill by name. Verify the file is deleted from disk and the skill no longer appears in subsequent conversation prompts.

**Acceptance Scenarios**:

1. **Given** a skill file exists, **When** a user explicitly requests removal of that skill (e.g., "删除技能 math-tutor"), **Then** the LLM calls `skill_remove` with the skill name, the file is deleted, and a success confirmation is returned.
2. **Given** a skill file exists, **When** a user vaguely mentions the skill without explicitly requesting removal, **Then** the LLM does NOT call `skill_remove`.
3. **Given** a skill file does NOT exist, **When** `skill_remove` is called with that name, **Then** an appropriate error message is returned indicating the skill was not found.

---

### User Story 3 - Skill Content Updates Take Effect (Priority: P3)

An operator modifies an existing skill file's content (or description) on disk. Since skills are lazily loaded, the updated content is used the next time the LLM loads that skill in a new conversation.

**Why this priority**: This is a natural consequence of lazy loading and requires no additional mechanism, but it's important to validate that stale caches don't prevent updates from taking effect.

**Independent Test**: Load a skill in one conversation, end the conversation, modify the skill file on disk, start a new conversation, load the skill again, and verify the updated content is returned.

**Acceptance Scenarios**:

1. **Given** a skill was loaded in a previous conversation that has since ended, **When** the skill file is modified on disk and a new conversation starts, **Then** loading the skill returns the updated content.
2. **Given** a skill file's frontmatter description is updated, **When** a new conversation starts, **Then** the system prompt reflects the updated description.

---

### User Story 4 - User Lists Available Skills via Command (Priority: P2)

Any group member sends `/skills` in the chat to see a formatted list of all available skills (name and description). This provides transparency into what the bot can do beyond its built-in capabilities.

**Why this priority**: Users need to discover available skills to know what to ask for. Without a listing mechanism, skills are invisible unless users already know their names. This is a companion feature to US1 — skills must be both usable and discoverable.

**Independent Test**: Send `/skills` with skills present in the directory, verify a formatted list is returned. Send `/skills` with an empty skills directory, verify a friendly "no skills" message.

**Acceptance Scenarios**:

1. **Given** one or more skill files exist in the skills directory, **When** any user sends `/skills`, **Then** the bot replies with a list showing each skill's name and description.
2. **Given** no skill files exist in the skills directory, **When** any user sends `/skills`, **Then** the bot replies with a friendly message indicating no skills are currently available.
3. **Given** a skill file is added or removed, **When** `/skills` is sent again, **Then** the list reflects the current state immediately (no restart required).

---

### User Story 5 - Operator Downloads a Skill from URL (Priority: P2)

An operator finds a skill markdown file online (e.g., in a GitHub repository or skill registry). They use the `web_browser` tool to locate the raw URL of the skill file, then ask the bot to download it. The bot invokes `skill_download` with the URL, downloads the content, extracts the skill name from its frontmatter, and saves it to the skills directory. The skill is immediately available for use.

**Why this priority**: Manual file placement requires filesystem access. A download tool enables operators to install skills entirely through the chat interface, making the bot self-serviceable without SSH or file transfer.

**Independent Test**: Provide a raw URL to a valid skill markdown file, ask the bot to download it, verify the file appears in the skills directory with the correct filename (matching the skill's `name` in frontmatter), and verify `/skills` shows it.

**Acceptance Scenarios**:

1. **Given** a valid raw URL pointing to a skill markdown file with proper YAML frontmatter, **When** the LLM invokes `skill_download` with that URL, **Then** the file is saved to the skills directory as `{name}.md` (where `name` is extracted from the frontmatter), the SkillManager cache is cleared for that name, and a success confirmation is returned.
2. **Given** a skill with the same `name` already exists in the skills directory, **When** `skill_download` is invoked with a URL for a skill with the same name, **Then** the existing file is overwritten and the response notes that the skill was overwritten.
3. **Given** an invalid URL or a URL that does not point to a valid skill markdown file (no frontmatter, missing `name` field), **When** `skill_download` is invoked, **Then** an appropriate error message is returned and no file is created.
4. **Given** a successfully downloaded skill, **When** the next conversation starts, **Then** the new skill appears in the system prompt's available skills list.

---

### User Story 6 - Utility Tools Have Unlimited Invocations (Priority: P3)

Certain utility tools (`web_browser`, `search_web`, `skill_loader`, `skill_download`, `skill_remove`, `create_timer`, `list_timers`, `delete_timer`) can be called an unlimited number of times within a single conversation. Other tools remain restricted to one call per conversation to prevent abuse or redundant operations.

**Why this priority**: This removes an artificial friction that prevents the LLM from using these tools effectively. Web searches, skill operations, and timer management are inherently multi-call workflows — restricting them to a single invocation breaks legitimate use cases.

**Independent Test**: In a single conversation, invoke `search_web` twice. Verify both calls succeed. Then invoke `write_memory` twice — verify the second call is rejected.

**Acceptance Scenarios**:

1. **Given** any tool in the unlimited whitelist, **When** the LLM invokes it multiple times in one conversation, **Then** every invocation succeeds without a "duplicate call" error.
2. **Given** a tool NOT in the unlimited whitelist (e.g., `write_memory`, `generate_image`), **When** the LLM invokes it a second time, **Then** the call is rejected with the existing "already called" error.
3. **Given** a new conversation starts, **When** the LLM invokes a previously-called restricted tool, **Then** the call counter is reset and the first invocation succeeds.

---

### Edge Cases

- What happens when a skill file has malformed frontmatter (missing `name` or `description`)? → The file is silently skipped in the skill list.
- What happens when two skill files have the same `name`? → The last one scanned wins (filesystem order); a warning is logged.
- What happens when a skill `.md` file has no frontmatter at all? → The file is skipped.
- What happens when the skills directory does not exist? → It is created automatically on first access; `list_skills()` returns an empty list.
- What happens when a skill file is deleted externally (outside the remove tool)? → `load_skill()` returns an error if the file is gone; `list_skills()` naturally stops showing it.
- What happens when skill content is very large (e.g., 50KB)? → The full content is loaded and returned to the LLM as tool output; no size limit is enforced at the manager level.
- What happens when `skill_remove` is called mid-conversation for a skill already loaded in that conversation? → The file is deleted; if the LLM tries to load it again, an error is returned.
- What happens when `skill_download` is given a URL that returns non-markdown content? → The frontmatter parsing fails and an error is returned; no file is created.
- What happens when `skill_download` encounters a network error (timeout, DNS failure, 404)? → An error message is returned describing the failure; no partial file is written.
- What happens when `/skills` is sent while a conversation is active? → The command is handled independently (it does not interact with the conversation graph).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST scan the configured skills directory for `.md` files and parse YAML frontmatter to extract `name` and `description` fields.
- **FR-002**: System MUST inject all available skills' names and descriptions into the LLM's system prompt when entering the AI node of the conversation graph.
- **FR-003**: System MUST provide a `skill_loader` tool that accepts a skill name and returns the full content of the corresponding skill file.
- **FR-004**: System MUST provide a `skill_remove` tool that accepts a skill name, deletes the corresponding file from disk, and clears any cached content.
- **FR-005**: The `skill_remove` tool description MUST instruct the LLM to only invoke it when the user explicitly requests skill removal.
- **FR-006**: System MUST deduplicate skill loading within a single conversation — loading the same skill twice returns an indication that it's already loaded rather than re-reading the file.
- **FR-007**: System MUST clear the per-conversation deduplication set when a conversation ends.
- **FR-008**: System MUST lazily load skill content (read full file only when `skill_loader` is called), while frontmatter scanning for the skills list reads only the YAML header of each file.
- **FR-009**: System MUST cache loaded skill content in memory to avoid re-reading the same file within a session.
- **FR-010**: System MUST gracefully handle missing or malformed skill files (skip them in listings, return errors on load attempts).
- **FR-011**: System MUST auto-create the skills directory if it does not exist on first access.
- **FR-012**: System MUST ensure skills are globally shared across all groups — no per-group skill isolation.
- **FR-013**: System MUST provide a `/skills` command (via NoneBot `on_command`) that any user can invoke to see a formatted list of all available skills (name and description). When no skills are available, a friendly message is returned.
- **FR-014**: System MUST provide a `skill_download` tool that accepts a raw URL, downloads the skill markdown content, parses the YAML frontmatter to extract the skill `name`, saves the file as `{name}.md` in the skills directory, and clears the SkillManager cache for that name. If a skill with the same name already exists, it is overwritten with a note in the response. The tool description MUST include a note that raw URLs can be found via the `web_browser` tool.
- **FR-015**: System MUST maintain a whitelist of tools that bypass the single-invocation restriction (`web_browser`, `search_web`, `skill_loader`, `skill_download`, `skill_remove`, `create_timer`, `list_timers`, `delete_timer`). Tools in this whitelist can be called unlimited times per conversation. All other tools remain restricted to 1 call per conversation.
- **FR-016**: The `/skills` command MUST reflect the current skills directory state on each invocation — no caching or staleness.

### Key Entities

- **Skill File**: A markdown (`.md`) file stored in the skills directory. Contains YAML frontmatter with `name` (unique identifier) and `description` (when to use this skill), followed by the skill's instruction content in markdown format.
- **Skill Manager**: The in-memory component that scans, caches, loads, and removes skills. Maintains a content cache (name → full text) and a per-conversation deduplication set (names loaded in current conversation).
- **Unlimited Tool Whitelist**: A set of tool names that are exempt from the single-invocation-per-conversation restriction. Tools in this set may be called any number of times.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Adding a new skill file to the directory makes it available in the LLM's system prompt on the very next conversation turn, without requiring a restart.
- **SC-002**: Loading a skill via `skill_loader` returns the full content in under 100ms for files under 10KB.
- **SC-003**: Removing a skill via `skill_remove` takes effect immediately — the file is gone from disk and the skill disappears from subsequent prompt injections.
- **SC-004**: A skill removed externally (file deleted manually) is gracefully absent from `list_skills()` on the next scan, with no errors or crashes.
- **SC-005**: Malformed skill files (missing frontmatter, invalid YAML) do not cause errors — they are silently skipped with a log entry.
- **SC-006**: The LLM correctly invokes `skill_loader` for relevant skills and does NOT invoke `skill_remove` unless the user explicitly requests removal.
- **SC-007**: The `/skills` command returns a formatted skill list in under 500ms regardless of the number of skills (up to 50).
- **SC-008**: `skill_download` completes download, parsing, and file save in under 10 seconds for files under 50KB from a reachable URL.
- **SC-009**: Whitelisted tools can be invoked 5+ times in a single conversation without any "already called" errors, while restricted tools still reject the second invocation.

## Assumptions

- Skill files use UTF-8 encoding.
- The YAML frontmatter is delimited by `---` (standard Jekyll/Hugo/Anthropic convention).
- A reasonable maximum of ~50 skill files is expected; scanning performance is not a bottleneck at this scale.
- Skills are authored by the bot operator, not by end users through the chat interface.
- The `skill_remove` tool physically deletes the file from disk (no soft-delete or trash mechanism in v1).
- The existing conversation graph (human → detect → ai → human → finish) provides a `finish` node where `reset_conversation()` can be called.
- The system prompt injection for skills is appended to (not replacing) the existing role system prompt.
- The `/skills` command uses NoneBot's standard `on_command` matcher pattern (consistent with existing `/timer`, `/img`, etc.).
- Raw URLs for `skill_download` point to publicly accessible markdown files (e.g., GitHub raw content URLs).
- `skill_download` uses Python's standard `urllib` or `httpx` for HTTP fetching — no external download manager required.
- Downloaded skill files are saved with UTF-8 encoding, consistent with manually placed skill files.
