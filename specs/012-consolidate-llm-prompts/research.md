# Research: Consolidate LLM Prompts

**Date**: 2026-06-14
**Feature**: [spec.md](./spec.md)

## Decision 1: Organization Structure

**Decision**: Group prompts into 5 sections by functional domain.

**Rationale**: The prompts naturally fall into 4 functional groups (Graph Nodes, Tools, Features, Timer) plus the existing Role section. This mirrors the project's existing module structure and makes it easy for developers to locate the prompt they need.

**Alternatives considered**:
- Single flat list: simpler but harder to navigate with 15+ entries
- Per-consumer-file grouping: ties organization to current code structure, fragile if consumers change
- Alphabetical: no semantic grouping, harder to understand

## Decision 2: Naming Convention

**Decision**: `UPPER_CASE` for pure string constants, `build_xxx_prompt()` for parameterized builders.

**Rationale**: Follows the existing pattern already established in `prompts.py` (`build_skill_prompt()`). UPPER_CASE makes constants visually distinct from functions. The `build_` prefix clearly signals a factory function.

**Alternatives considered**:
- All constants (with .format() at call site): pushes formatting responsibility to consumers, defeats centralization
- All functions (even for constants): unnecessarily verbose for simple strings
- `get_` prefix: less descriptive than `build_` for string construction

## Decision 3: Face Emotion Classifier Prompt Handling

**Decision**: Split into `FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX` + `FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX` constants with `build_face_emotion_classifier_prompt(emotions)` builder.

**Rationale**: This prompt dynamically inserts emotion names between its prefix and suffix. Splitting into two constants allows the builder to join them with the emotion list while keeping the static parts centralized.

**Alternatives considered**:
- Single f-string with placeholder: requires .format() at every call site, scatters the emotion list join logic
- Keep as inline: defeats the purpose of consolidation

## Decision 4: Skill Files Exclusion

**Decision**: Skill files (`data/hatsume-plugin/skills/*.md`) remain in their current location.

**Rationale**: These are runtime-loaded external configuration resources, not source code. They're loaded dynamically by `skill_loader` tool and have a fundamentally different lifecycle from code-level prompts. Moving them into `prompts.py` would conflate static code with dynamic configuration.

**Alternatives considered**:
- Embed as string constants: would make skill updates require code changes, defeating the skill system's purpose
- Move to a separate `skill_prompts.py`: unnecessary — skills already have a dedicated directory

## Decision 5: Timer System Prompt Self-Reference

**Decision**: `build_timer_system_prompt()` imports `role_sys_prompt` from same module.

**Rationale**: The timer executor currently concatenates `role_sys_prompt` with timer-specific instructions. The builder function lives in `prompts.py` and references `role_sys_prompt` directly — no circular dependency since both are in the same file.

**Alternatives considered**:
- Pass `role_sys_prompt` as parameter: adds unnecessary parameter at every call site
- Keep timer prompt construction in executor: defeats centralization for the timer prompt
