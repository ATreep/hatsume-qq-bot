# Feature Specification: Consolidate LLM Prompts

**Feature Branch**: `012-consolidate-llm-prompts`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Consolidate all LLM prompts from across the project into prompts.py. Move 15 LLM prompts scattered across 7 files into prompts.py as constants and builder functions. Each consumer file removes inline prompts and imports from prompts.py instead. No behavioral changes — pure relocation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Developer Finds All Prompts in One Place (Priority: P1)

As a developer working on the hatsume bot, I want to find all LLM prompt strings in a single file (`prompts.py`) so that I can quickly review, update, and maintain the bot's AI instructions without hunting across multiple files.

**Why this priority**: This is the core value proposition — the entire purpose of this refactoring. Without this, developers continue to scatter prompts across 7+ files.

**Independent Test**: Open `prompts.py` and verify it contains all prompt constants and builder functions. Every prompt that previously existed inline in other files should be present in `prompts.py`.

**Acceptance Scenarios**:

1. **Given** the project codebase, **When** a developer searches for an LLM prompt (e.g., the conversation end detection prompt), **Then** they find it defined in `prompts.py` rather than embedded in a node/tool file.
2. **Given** `prompts.py`, **When** a developer reads through it, **Then** all prompts are organized in clearly labeled sections (Graph Node, Tool, Feature, Timer) for easy navigation.

---

### User Story 2 - Prompt Changes Don't Require Hunting Through Business Logic (Priority: P1)

As a developer, I want to modify a prompt's wording without navigating through LangGraph node functions, tool definitions, or handler logic, so that prompt tuning is fast and safe.

**Why this priority**: Prompt tuning is a frequent task for AI bots. Making it easy and safe is critical for iteration speed.

**Independent Test**: Pick any prompt, change its text in `prompts.py`, restart the bot — the new wording takes effect without touching any other file.

**Acceptance Scenarios**:

1. **Given** a prompt constant defined in `prompts.py`, **When** a developer changes the prompt text, **Then** all consumers automatically use the updated text with no other file changes needed.
2. **Given** parameterized builder functions in `prompts.py`, **When** a developer changes the prompt template, **Then** the change applies consistently wherever that builder is called.

---

### User Story 3 - No Behavior Changes From Relocation (Priority: P1)

As a user of the hatsume bot, I want the bot to behave exactly the same as before after the prompt consolidation, so that my chat experience is not disrupted.

**Why this priority**: This is a pure refactoring. Any behavioral change is a regression.

**Independent Test**: Run the full test suite — all existing tests must pass. The bot's responses, tool usage, detection behavior, and all features must work identically.

**Acceptance Scenarios**:

1. **Given** the refactored codebase, **When** the test suite runs, **Then** all tests pass without modification.
2. **Given** the refactored codebase, **When** the bot processes any message (auto-reply, @mention, command, timer), **Then** the response is identical to what the pre-refactoring code would produce.

---

### Edge Cases

- What happens when a prompt contains special characters (backticks, f-string braces, newlines)? All prompts must be preserved exactly, including special characters, using proper Python string escaping.
- What about the face emotion classifier prompt that dynamically inserts emotion names? It must become a builder function that accepts the emotion list as a parameter and produces the same combined string.
- What about prompts that reference `role_sys_prompt` (e.g., timer executor)? The builder function must import `role_sys_prompt` from within the same file — no circular imports.
- What about skill files (`cat-girl.md`, `leijun-perspective.md`)? These are runtime-loaded external resources, not code-level prompts, and are excluded from this consolidation.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All LLM prompt strings currently defined inline across the codebase MUST be relocated to `prompts.py` as named constants or parameterized builder functions.
- **FR-002**: Pure string prompts (no dynamic components) MUST be defined as `UPPER_CASE` module-level constants.
- **FR-003**: Prompts containing dynamic content (variable interpolation) MUST be defined as `build_xxx_prompt()` functions that accept parameters and return a formatted string.
- **FR-004**: Each consumer file MUST import its required prompts from `prompts.py` and MUST NOT define prompts inline.
- **FR-005**: The relocated prompts MUST produce character-for-character identical output to the original inline prompts under all execution paths.
- **FR-006**: Prompts in `prompts.py` MUST be organized into clearly labeled sections: Graph Node Prompts, Tool Prompts, Feature Prompts, Timer Prompts.
- **FR-007**: Skill files (`data/hatsume-plugin/skills/*.md`) MUST remain in their current location — they are external resources, not code-level prompts.
- **FR-008**: The `role_sys_prompt` constant (already in `prompts.py`) and `build_skill_prompt()` function MUST remain unchanged.
- **FR-009**: Internal control signals (`"__end__"`, `"[CONVERSATION END]"`, `"## 历史聊天记录："`) MUST remain in their current locations — they are not LLM prompts.

### Key Entities

- **Prompt Constant**: A `UPPER_CASE` string constant in `prompts.py` containing an LLM instruction (e.g., `CHAT_END_DETECT_PROMPT`).
- **Prompt Builder Function**: A `build_xxx_prompt()` function in `prompts.py` that takes parameters and returns a formatted prompt string (e.g., `build_memory_context_prompt(summary)`).
- **Consumer File**: A file that previously defined prompts inline and now imports them from `prompts.py`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 15 prompts are defined in `prompts.py` and locatable by grep/search in that single file.
- **SC-002**: Zero prompt strings remain defined inline in consumer files (verified by code review of each affected file).
- **SC-003**: All existing automated tests pass without modification after the refactoring.
- **SC-004**: The ruff linter reports no new issues.
- **SC-005**: The bot starts and operates normally — manual smoke test passes for at least one conversation flow.

## Assumptions

- This is a pure code relocation task — no prompt rewording, no logic changes.
- The existing `prompts.py` file structure (sections, naming conventions) serves as the pattern for new additions.
- All consumer files use standard Python imports compatible with the project's existing import patterns.
- Skill files in `data/hatsume-plugin/skills/` are external configuration, not source code, and are out of scope.
- Tests do not mock individual prompt strings, so they will continue to pass without modification.
