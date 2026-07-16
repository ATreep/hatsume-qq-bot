# Research: Skill Management System

**Feature**: 009-skill-management
**Date**: 2026-06-08

## 1. Frontmatter Parsing

**Decision**: Use PyYAML to parse `---` delimited YAML frontmatter from `.md` files.

**Rationale**: Standard approach used by Jekyll, Hugo, and Anthropic skills. PyYAML is a well-established library with no unusual dependencies. The frontmatter block is identified by splitting on `---` and parsing only the first YAML block.

**Alternatives considered**:
- Manual regex parsing — fragile for nested YAML, edge cases with quotes
- `python-frontmatter` library — adds dependency for minimal benefit over PyYAML
- `toml` frontmatter (`+++`) — not the Anthropic standard format

## 2. Singleton Pattern

**Decision**: Module-level `_skill_manager: SkillManager | None` with `get_skill_manager()` accessor, matching `timer/store.py`'s `get_store()` pattern.

**Rationale**: Consistent with the existing codebase. The timer module already uses this exact pattern. Skills are global (not per-group), so a single instance is correct.

**Alternatives considered**:
- Class-level singleton (`__new__`) — more opaque, harder to test
- Dependency injection — overkill for a single-instance module
- Global variable without accessor — no lazy init, import order issues

## 3. Tool Registration

**Decision**: Define `skill_loader` and `skill_remove` as `@tool` decorated async functions in `graph/tools.py`, added to the `create_agent()` tools list in `ai_node`.

**Rationale**: Matches every existing tool in the codebase (search_web, generate_image, create_timer, etc.). The `@tool` decorator auto-generates the JSON schema from the function signature and docstring. No new patterns needed.

**Alternatives considered**:
- StructuredTool / BaseTool subclass — more boilerplate, no benefit
- Separate tools module — unnecessary for just 2 tools

## 4. Prompt Injection

**Decision**: `build_skill_prompt()` in `prompts.py` returns a formatted string listing skill names and descriptions. This is appended to the existing `role_sys_prompt` in `ai_node` before creating the chat agent.

**Rationale**: Simplicity. The system prompt is constructed once per AI node entry. Skills may change between conversations (added/removed), so dynamic construction is correct. Separating the function keeps `prompts.py` as the single source of prompt text.

**Alternatives considered**:
- Prepend vs append — appended is less disruptive to the existing role prompt structure
- Inject via separate SystemMessage — would require modifying the agent creation pattern
- Template-based injection — over-engineering for a simple list

## 5. Caching Strategy

**Decision**: In-memory dict cache (`name → full_content`) that persists across conversations. Separate per-conversation dedup set cleared on `reset_conversation()`.

**Rationale**: Content cache avoids re-reading files within a bot session. Dedup set prevents the LLM from loading the same skill repeatedly in one conversation, saving tokens. Clearing dedup on conversation end allows the skill to be loaded again in the next conversation (useful if content was updated).

**Alternatives considered**:
- No cache (always read from disk) — slower, unnecessary I/O
- Cache with TTL — adds complexity without benefit; file changes between conversations are handled by the dedup reset
- LRU cache with size limit — over-engineering for ~50 small files

## 6. File Watching / Hot Reload

**Decision**: No file watching. Lazy loading (scan on each `list_skills()` call) provides pseudo-hot-reload: file changes are picked up on the next conversation.

**Rationale**: Adding a file watcher (watchdog, inotify) adds complexity and a background thread. The lazy scan approach is simple and sufficient — `list_skills()` runs on every AI node entry, and `load_skill()` reads from disk on first call in a new conversation.

**Alternatives considered**:
- watchdog library — adds dependency, background thread, complexity
- Manual polling — wasteful
- Restart-only — too restrictive for operators iterating on skills

## 7. `/skills` Command Pattern

**Decision**: Follow the exact `handle_timer` pattern: register via `on_command("skills", priority=10, block=True)` in `__init__.py`, handler function `handle_list_skills()` in `handlers/commands.py`, no `event` or `bot` parameter needed (no group-specific data access).

**Rationale**: Consistency with existing command handlers. The command is read-only and stateless — it calls `get_skill_manager().list_skills()` and formats the result. No need for async, no need for `bot`/`event` access.

**Alternatives considered**:
- `on_fullmatch("/skills")` — inconsistent with other commands that use `on_command`
- Per-group skill filtering — spec explicitly says global scope (FR-012)
- Rich Message formatting — YAGNI; simple text list is sufficient

## 8. `skill_download` HTTP Client

**Decision**: Use `urllib.request.urlopen` from the standard library, with a reasonable timeout (10 seconds). No external HTTP library dependency.

**Rationale**: The existing `shell_executor` tool already covers complex HTTP scenarios (via `curl`). `skill_download` only needs a simple GET request. Using stdlib avoids adding `httpx` or `requests` as a dependency just for this one call. The timeout prevents hanging on unreachable URLs.

**Alternatives considered**:
- `httpx` — modern but adds a dependency; overkill for a single GET
- `aiohttp` (async) — would require making the tool async for marginal benefit
- `requests` — legacy; unnecessarily adds a dependency
- Shell executor (`curl`) — reuses infra but adds container overhead; direct HTTP is simpler

## 9. Unlimited Tool Invocation Whitelist

**Decision**: A module-level `frozenset` named `_UNLIMITED_TOOLS` in `tools.py`. `check_tool_call()` checks membership and returns `None` (skip restriction) for whitelisted tools. All other logic unchanged.

**Rationale**: Minimal change — one `if` guard at the top of `check_tool_call()`. The whitelist is immutable (`frozenset`), making intent clear. No per-tool counting or complex quota system needed.

**Alternatives considered**:
- Per-tool `max_invocations` dict — more complex, not needed; all whitelisted tools are truly unlimited
- Decorator-based `@unlimited` — changes tool definition pattern, breaks `@tool` decorator chain
- Remove `check_tool_call` entirely — would remove protection for genuinely single-use tools (write_memory, generate_image)
