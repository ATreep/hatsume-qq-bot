# Tasks: Skill Management System

**Input**: Design documents from `/specs/009-skill-management/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: TDD approach — write tests first, ensure they fail, then implement.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Project root: `hatsume/plugins/hatsume-plugin/`
Test root: `tests/`
Skills directory: `hatsume/plugins/hatsume-plugin/skills/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration and directory scaffolding

- [ ] T001 Create skills sub-package directory at `hatsume/plugins/hatsume-plugin/skills/`
- [ ] T002 Add `SKILLS_DIR` path constant to `hatsume/plugins/hatsume-plugin/config.py` — default to `data/hatsume-plugin/skills/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core SkillManager class and prompt integration — MUST complete before ANY user story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T003 [P] Create SkillManager class in `hatsume/plugins/hatsume-plugin/skills/manager.py` with: `__init__`, `list_skills()` (frontmatter scan), `load_skill()` (lazy read + cache + dedup), `remove_skill()` (file delete + cache clear), `reset_conversation()` (dedup clear), `_parse_frontmatter()` (PyYAML helper), `_ensure_dir()` (auto-create)
- [ ] T004 [P] Create `hatsume/plugins/hatsume-plugin/skills/__init__.py` with singleton `get_skill_manager()` accessor (matching timer's `get_store()` pattern)
- [ ] T005 [P] Add `build_skill_prompt(skills: list[dict]) -> str` function to `hatsume/plugins/hatsume-plugin/prompts.py` — formats skill list for system prompt injection, returns empty string when no skills
- [ ] T006 [P] Write unit tests for SkillManager in `tests/test_skill_manager.py`: test list_skills (empty dir, with files, malformed frontmatter), test load_skill (success, missing, dedup), test remove_skill (success, nonexistent), test reset_conversation, test auto-create directory
- [ ] T007 [P] Write unit tests for build_skill_prompt in `tests/test_skill_manager.py`: test with skills list, with empty list
- [ ] T008 Verify all foundational tests fail/pass correctly — SkillManager tests should pass once implemented

**Checkpoint**: Foundation ready — skill manager is functional, prompt builder works, tests pass

---

## Phase 3: User Story 1 - Operator Adds a Skill (Priority: P1) 🎯 MVP

**Goal**: Skills are discoverable in system prompts and loadable via skill_loader tool

**Independent Test**: Drop a `.md` skill file into the data directory, trigger conversation, verify system prompt includes skill name/description, verify LLM can load it via skill_loader

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T009 [P] [US1] Write integration test for skill_loader tool behavior in `tests/test_skill_manager.py`: test tool returns full content for valid skill, returns already-loaded message for duplicate, returns error for missing skill

### Implementation for User Story 1

- [ ] T010 [US1] Register `skill_loader` tool in `hatsume/plugins/hatsume-plugin/graph/tools.py` — `@tool` decorated async function calling `get_skill_manager().load_skill()`, with docstring describing usage and dedup behavior
- [ ] T011 [US1] Inject skill list into system prompt in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` `ai_node()`: import `get_skill_manager` and `build_skill_prompt`, call before `create_agent()`, append to `sys_prompt`
- [ ] T012 [US1] Add `skill_loader` to `create_agent()` tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` `ai_node()`
- [ ] T013 [US1] Verify User Story 1 end-to-end: start bot, add skill file, trigger conversation, confirm skill appears in prompt and LLM can load it

**Checkpoint**: Skills are discoverable and loadable via chat agent — MVP achieved

---

## Phase 4: User Story 2 - Operator Removes a Skill (Priority: P2)

**Goal**: Skills can be removed via skill_remove tool when user explicitly requests it

**Independent Test**: With a skill file present, explicitly ask bot to remove it, verify file deleted and skill gone from next prompt

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T014 [P] [US2] Write test for skill_remove tool in `tests/test_skill_manager.py`: test successful removal (file deleted, cache cleared), test removal of nonexistent skill returns error

### Implementation for User Story 2

- [ ] T015 [US2] Register `skill_remove` tool in `hatsume/plugins/hatsume-plugin/graph/tools.py` — `@tool` decorated async function calling `get_skill_manager().remove_skill()`, with docstring explicitly stating ONLY call when user explicitly requests removal
- [ ] T016 [US2] Add `skill_remove` to `create_agent()` tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` `ai_node()`
- [ ] T017 [US2] Call `get_skill_manager().reset_conversation()` in `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py` finish node to clear per-conversation dedup set

**Checkpoint**: Skills can be explicitly removed and dedup resets per conversation

---

## Phase 5: User Story 3 - Skill Content Updates Take Effect (Priority: P3)

**Goal**: Modified skill files are picked up on next conversation due to lazy loading

**Independent Test**: Load skill in conversation, end conversation, modify file, start new conversation, verify updated content

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T018 [US3] Write test for content update behavior in `tests/test_skill_manager.py`: verify content cache returns stale content within same conversation (dedup), verify reset_conversation clears dedup allowing reload, verify file modification is reflected on next load_skill after cache clear

### Implementation for User Story 3

- [ ] T019 [US3] Validate lazy-load behavior works correctly end-to-end — no code changes needed; this story is a natural consequence of the design

**Checkpoint**: Skill content updates propagate correctly across conversation boundaries

---

## Phase 6: User Story 4 - User Lists Available Skills via Command (Priority: P2)

**Goal**: Any user can send `/skills` to see all available skills

**Independent Test**: Send `/skills` with skills present, verify formatted list. Send `/skills` with empty directory, verify friendly "no skills" message.

### Tests for User Story 4

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T025 [P] [US4] Write test for `/skills` command handler in `tests/test_skill_manager.py`: test with skills present (verify formatted output contains name + description), test with empty skills directory (verify friendly "no skills" message)

### Implementation for User Story 4

- [x] T026 [US4] Add `handle_list_skills(matcher, args)` function to `hatsume/plugins/hatsume-plugin/handlers/commands.py` — calls `get_skill_manager().list_skills()`, formats results as text list, calls `matcher.finish()` with output
- [x] T027 [US4] Register `skills_cmd = on_command("skills", priority=10, block=True)` in `hatsume/plugins/hatsume-plugin/__init__.py` and wire `handle_list_skills` as the handler function via `@skills_cmd.handle()` decorator

**Checkpoint**: `/skills` command works — any user can list available skills

---

## Phase 7: User Story 5 - Operator Downloads a Skill from URL (Priority: P2)

**Goal**: LLM can invoke `skill_download` to download a skill from a raw URL

**Independent Test**: Provide a raw URL to a valid skill markdown, ask bot to download it, verify file appears in skills directory with correct filename matching frontmatter `name`.

### Tests for User Story 5

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T028 [P] [US5] Write test for skill_download tool in `tests/test_skill_manager.py`: test successful download (mock HTTP response with valid frontmatter), test overwrite existing skill, test invalid URL (network error), test missing frontmatter returns error

### Implementation for User Story 5

- [x] T029 [US5] Register `skill_download` tool in `hatsume/plugins/hatsume-plugin/graph/tools.py` — `@tool` decorated function accepting `url: str`, using `urllib.request.urlopen` with 10s timeout, parsing frontmatter via `SkillManager._parse_frontmatter`, saving to `{SKILLS_DIR}/{name}.md`, clearing SkillManager cache. Docstring includes note: "你可以通过 `web_browser` 工具浏览网页，找到 skill 文件的 raw URL。"
- [x] T030 [US5] Add `skill_download` to `create_agent()` tools list in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` `ai_node()`
- [x] T031 [US5] Add `skill_download` to `_UNLIMITED_TOOLS` whitelist in `hatsume/plugins/hatsume-plugin/graph/tools.py`

**Checkpoint**: Skills can be downloaded from URLs via chat agent

---

## Phase 8: User Story 6 - Utility Tools Have Unlimited Invocations (Priority: P3)

**Goal**: Whitelisted tools (`web_browser`, `search_web`, `skill_loader`, `skill_download`, `skill_remove`, `create_timer`, `list_timers`, `delete_timer`) can be called unlimited times per conversation

**Independent Test**: Invoke `search_web` twice in one conversation — both succeed. Invoke `write_memory` twice — second call rejected.

### Tests for User Story 6

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T032 [P] [US6] Write test for unlimited tool invocation in `tests/test_skill_manager.py` (or reuse existing tools test): verify whitelisted tools (use `search_web` or `list_timers` as representative) can be called multiple times without error, verify non-whitelisted tools (use `write_memory` as representative) still get rejected on second call

### Implementation for User Story 6

- [x] T033 [US6] Add `_UNLIMITED_TOOLS` frozenset to `hatsume/plugins/hatsume-plugin/graph/tools.py` containing: `web_browser`, `search_web`, `skill_loader`, `skill_download`, `skill_remove`, `create_timer`, `list_timers`, `delete_timer`
- [x] T034 [US6] Add early-return guard at top of `check_tool_call()` in `hatsume/plugins/hatsume-plugin/graph/tools.py`: `if tool_name in _UNLIMITED_TOOLS: return None`

**Checkpoint**: Whitelisted tools have unlimited invocations, restricted tools remain single-invocation

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Validation, documentation, and cleanup

- [x] T035 Run full test suite: `python -m pytest tests/test_skill_manager.py -xvs`
- [x] T036 Verify quickstart.md instructions are accurate by following them step-by-step (including new `/skills` command and download flow)
- [x] T037 Run ruff lint on all modified files: `ruff check hatsume/plugins/hatsume-plugin/skills/ hatsume/plugins/hatsume-plugin/handlers/commands.py hatsume/plugins/hatsume-plugin/__init__.py hatsume/plugins/hatsume-plugin/graph/tools.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`
- [x] T038 Verify existing tests still pass: `python -m pytest tests/ -xvs` (regression check)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational phase — core skill loading MVP
- **User Story 2 (Phase 4)**: Depends on Foundational phase — can run parallel with US1
- **User Story 3 (Phase 5)**: Depends on Foundational phase — largely validation, no new code
- **User Story 4 (Phase 6)**: Depends on Foundational phase — independent of US1/US2/US3
- **User Story 5 (Phase 7)**: Depends on Foundational phase — independent of other user stories; T031 also depends on T033 (US6's frozenset must exist first)
- **User Story 6 (Phase 8)**: Depends on Foundational phase — independent of other user stories
- **Polish (Phase 9)**: Depends on ALL user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent — only needs Foundational (Phase 2)
- **User Story 2 (P2)**: Independent of US1 — only needs Foundational (Phase 2)
- **User Story 3 (P3)**: No new code — validation only, depends on US1 + US2
- **User Story 4 (P2)**: Independent — only needs Foundational (Phase 2)
- **User Story 5 (P2)**: Independent — only needs Foundational (Phase 2)
- **User Story 6 (P3)**: Independent — only needs Foundational (Phase 2)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Core implementation → integration verification
- Story complete before moving to next priority

### Parallel Opportunities

- US4, US5, US6 can all run in parallel (different files, no shared dependencies beyond Foundational)
- T025, T028, T032 can run in parallel (test writing in same file but distinct)
- T026, T029, T033 can run in parallel (implementation in different files)
- Within US6: T033 and T034 are sequential (T034 depends on T033's frozenset definition)

---

## Parallel Example: New User Stories (US4-US6)

```bash
# Launch all test writing in parallel:
Task: "Write tests for /skills command in tests/test_skill_manager.py"
Task: "Write tests for skill_download tool in tests/test_skill_manager.py"
Task: "Write tests for unlimited invocation in tests/test_skill_manager.py"

# Launch implementation in parallel (different files):
Task: "Add handle_list_skills to handlers/commands.py + register in __init__.py"
Task: "Add skill_download tool to graph/tools.py + register in ai.py"
Task: "Add _UNLIMITED_TOOLS + guard in graph/tools.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Manually test skill loading end-to-end
5. Deploy/demo if ready — skills are usable

### Incremental Delivery

1. Setup + Foundational → SkillManager ready
2. Add User Story 1 → Skills discoverable and loadable (MVP!)
3. Add User Story 2 → Skills can be removed via chat
4. Add User Story 3 → Validate update propagation
5. Add User Story 4 → `/skills` command for skill discovery
6. Add User Story 5 → Download skills from URLs via chat
7. Add User Story 6 → Unlimited invocation for utility tools
8. Polish → Lint, tests, quickstart validation

### This Update (US4-US6)

Since US1-US3 are already implemented (SkillManager, skill_loader, skill_remove, prompt injection all exist in codebase), the focus is on Phases 6-8:

1. Phase 6: `/skills` command (T025-T027) — 3 tasks, ~2 files changed
2. Phase 7: `skill_download` tool (T028-T031) — 4 tasks, ~2 files changed
3. Phase 8: Unlimited invocation (T032-T034) — 3 tasks, 1 file changed
4. Phase 9: Polish (T035-T038) — validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD workflow)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Follow existing code patterns: @tool decorator, singleton accessor, sub-package structure matching timer/
- US1-US3 (T001-T024) are already implemented in the codebase; this tasks.md update adds US4-US6 (T025-T038)
- `skill_download` uses `urllib.request.urlopen` with 10s timeout per research.md decision
- `_UNLIMITED_TOOLS` is a `frozenset` — immutable, module-level constant
