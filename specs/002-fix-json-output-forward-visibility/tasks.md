# Tasks: 修复 JSON 输出格式与合并转发消息可见性

**Input**: Design documents from `/specs/002-fix-json-output-forward-visibility/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Minimal test updates to validate new behavior and prevent regressions.

**Organization**: Tasks grouped by user story for independent implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md project structure:
- Source: `hatsume/plugins/hatsume-plugin/`
- Tests: `tests/`

---

## Phase 1: Setup (Verify Baseline)

**Purpose**: Confirm all existing tests pass before making changes

- [ ] T001 Run existing test suite and confirm all tests pass via `python -m pytest tests/ -v`

---

## Phase 2: User Story 1 - LLM 稳定输出 JSON 格式回复 (Priority: P1) 🎯 MVP

**Goal**: 将输出格式指令从角色提示词分离，在 chat_agent 创建时追加到 system prompt 末尾

**Independent Test**: `python -m pytest tests/test_ai_json_output.py -v` — 所有 JSON 解析测试通过；手动检查 prompts.py 不含格式指令

### Implementation for User Story 1

- [ ] T002 [US1] Remove "## 你的输出格式" section from role_sys_prompt in hatsume/plugins/hatsume-plugin/prompts.py
- [ ] T003 [US1] Define _OUTPUT_FORMAT_INSTRUCTION constant and append it to sys_prompt before create_agent() call in hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
- [ ] T004 [US1] Run test suite to verify no regressions: `python -m pytest tests/ -v`

**Checkpoint**: role_sys_prompt 不含格式指令；_OUTPUT_FORMAT_INSTRUCTION 在 agent 创建时注入

---

## Phase 3: User Story 2 - 合并转发消息段显式处理 (Priority: P2)

**Goal**: segment 遍历循环显式处理 "forward" 类型，追加标记到 plain_message

**Independent Test**: 构造包含 forward segment 的 Message，验证 plain_message 含标记

### Tests for User Story 2

- [ ] T005 [P] [US2] Add test for forward segment handling in segment loop in tests/test_forward.py

### Implementation for User Story 2

- [ ] T006 [US2] Add case "forward" branch in get_human_message() segment loop in hatsume/plugins/hatsume-plugin/handlers/pipeline.py
- [ ] T007 [US2] Run forward tests: `python -m pytest tests/test_forward.py -v`

**Checkpoint**: forward segment 被显式标记

---

## Phase 4: User Story 3 - 转发处理全链路调试可见性 (Priority: P3)

**Goal**: 在 pipeline.py 和 forward.py 全链路增加 debug 日志

**Independent Test**: 处理合并转发消息，检查控制台输出含三阶段日志

### Implementation for User Story 3

- [ ] T008 [P] [US3] Add debug logs in get_human_message() forward path in hatsume/plugins/hatsume-plugin/handlers/pipeline.py
- [ ] T009 [P] [US3] Add success-path debug logs in parse_forward_messages() in hatsume/plugins/hatsume-plugin/handlers/forward.py
- [ ] T010 [US3] Run full test suite: `python -m pytest tests/ -v`

**Checkpoint**: 全链路日志覆盖检测→API→构建三阶段

---

## Phase 5: Polish & Final Verification

**Purpose**: Final regression check and spec compliance

- [ ] T011 Run complete test suite and confirm all tests pass: `python -m pytest tests/ -v`
- [ ] T012 Verify SC-002: Confirm role_sys_prompt string contains no output format instructions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies
- **Phase 2 (US1)**: After Phase 1 — prompts.py + ai.py
- **Phase 3 (US2)**: After Phase 1 — independent of US1
- **Phase 4 (US3)**: After Phase 3 — same file as US2
- **Phase 5 (Polish)**: After all stories

### Parallel Opportunities

- T002 + T005: prompts.py and test_forward.py (different files)
- T003 + T006: ai.py and pipeline.py (different files)
- T008 + T009: pipeline.py and forward.py (different files)

### Implementation Strategy

**MVP**: Phase 1 → Phase 2 (US1 only) → Validate → Deploy
**Full**: Phase 1 → US1 + US2 (parallel) → US3 → Polish
