# Tasks: Group Member Fuzzy Search

**Input**: Design documents from `specs/011-group-member-search/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Included — TDD mandated by workflow. Tests written first, verified to fail, then implementation.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

- Source: `hatsume/plugins/hatsume-plugin/`
- Tests: `tests/`

---

## Phase 1: Setup

**Purpose**: Test scaffolding shared by all phases

- [ ] T001 Create test file `tests/test_membersearch.py` with import scaffolding — stubs for nonebot, langchain, hatsume modules, FakeBot, _make_member/_make_member_info helpers, _FakeMatcher, _MatcherFinished, _FakeEvent, _FakeBotForCommand, MessageStub, module loader functions

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core `search_group_members()` — BOTH US1 and US2 depend on it

**⚠️ CRITICAL**: No user story work until this phase is complete

- [ ] T002 Write failing tests for `search_group_members()` in `tests/test_membersearch.py` — TestSearchGroupMembers class with 11 tests: test_substring_match, test_card_priority_over_nickname, test_nickname_fallback_when_card_empty, test_substring_before_character_overlap, test_character_overlap_fallback, test_max_results_truncated_to_5, test_no_match_returns_empty, test_level_defaults_to_unknown_on_api_failure, test_case_insensitive_match, test_empty_query_returns_empty, test_member_list_cache
- [ ] T003 Run `python -m pytest tests/test_membersearch.py -v` — verify FAIL (AttributeError: search_group_members not defined)
- [ ] T004 Implement `search_group_members(bot, group_id, query, max_results=5)` in `hatsume/plugins/hatsume-plugin/utils.py` — two-pass matching (substring → character-overlap), 300s TTL cache, card priority over nickname, level fetching with "未知" fallback
- [ ] T005 Run `python -m pytest tests/test_membersearch.py::TestSearchGroupMembers -v` — verify ALL PASS (11 tests)
- [ ] T006 Commit: `git commit -m "feat: add search_group_members() core fuzzy search function"`

**Checkpoint**: Foundation ready — both user stories can now build on search_group_members()

---

## Phase 3: User Story 1 - LLM Agent Identifies User by Fuzzy Nickname (Priority: P1) 🎯 MVP

**Goal**: Chat agent can call `membersearch` tool to fuzzy-search group members, getting JSON results

**Independent Test**: Invoke `membersearch("菠萝")` with stubbed member list, verify correct JSON array

### Tests for User Story 1

- [ ] T007 [P] [US1] Write failing test `test_membersearch_returns_json_array` in `tests/test_membersearch.py`
- [ ] T008 [P] [US1] Write failing test `test_membersearch_empty_results` in `tests/test_membersearch.py`
- [ ] T009 [P] [US1] Write failing test `test_membersearch_no_group_id` in `tests/test_membersearch.py`
- [ ] T010 [P] [US1] Write failing test `test_membersearch_respects_check_tool_call` in `tests/test_membersearch.py`
- [ ] T011 Run tests — verify FAIL (AttributeError: membersearch not defined)
- [ ] T012 [US1] Implement `membersearch` @tool in `hatsume/plugins/hatsume-plugin/graph/tools.py` — reads _current_group_id, calls search_group_members, returns JSON string, includes check_tool_call guard
- [ ] T013 Run `python -m pytest tests/test_membersearch.py::TestMembersearchTool -v` — verify ALL PASS (4 tests)
- [ ] T014 Run full test suite to confirm no regressions
- [ ] T015 Commit: `git commit -m "feat: add membersearch @tool for LLM fuzzy group member search"`

**Checkpoint**: LLM agent can search for group members by fuzzy nickname 🎯 MVP

---

## Phase 4: User Story 2 - /membersearch Slash Command (Priority: P2)

**Goal**: Group members can use `/membersearch <query>` to search and get formatted text results

**Independent Test**: Simulate `/membersearch 菠萝` and verify formatted response with username, QQ ID, level

### Tests for User Story 2

- [ ] T016 [P] [US2] Write failing test `test_command_returns_formatted_results` in `tests/test_membersearch.py`
- [ ] T017 [P] [US2] Write failing test `test_command_empty_query_shows_help` in `tests/test_membersearch.py`
- [ ] T018 [P] [US2] Write failing test `test_command_no_results` in `tests/test_membersearch.py`
- [ ] T019 Run tests — verify FAIL (AttributeError: handle_membersearch not defined)
- [ ] T020 [US2] Implement `handle_membersearch(bot, event, matcher, args)` in `hatsume/plugins/hatsume-plugin/handlers/commands.py` — calls search_group_members, formats results, handles empty query
- [ ] T021 [US2] Register `on_command("membersearch")` in `hatsume/plugins/hatsume-plugin/__init__.py` — add matcher, import handle_membersearch, wire handler
- [ ] T022 Run `python -m pytest tests/test_membersearch.py::TestHandleMembersearchCommand -v` — verify ALL PASS (3 tests)
- [ ] T023 Run full test suite `python -m pytest tests/ -v` — all existing tests still pass
- [ ] T024 Commit: `git commit -m "feat: add /membersearch slash command with shared search logic"`

**Checkpoint**: Users can type /membersearch in group chat and get formatted results

---

## Phase 5: User Story 3 - Character-Overlap Fallback Verification (Priority: P3)

**Goal**: Confirm imprecise queries with no substring match return results via character-overlap

**Independent Test**: Search "菠蜜" against "菠萝包" and "水蜜桃" — both appear ranked by overlap

**Note**: Character-overlap logic already implemented in Phase 2 (T004). This phase verifies correctness.

- [ ] T025 [US3] Verify `test_character_overlap_fallback` and `test_substring_before_character_overlap` (from T002) pass — confirms two-pass matching works end-to-end
- [ ] T026 Run quickstart.md validation — execute example commands, verify outputs match

**Checkpoint**: All three user stories independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final verification and cleanup

- [ ] T027 [P] Run full test suite: `python -m pytest tests/ -v` — all tests pass
- [ ] T028 [P] Update CLAUDE.md command list to include `/membersearch`
- [ ] T029 Verify no duplicated logic between tool and command — both call search_group_members
- [ ] T030 Final commit with all changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational; independent of US1
- **US3 (Phase 5)**: Depends on Foundational; verification only
- **Polish (Phase 6)**: Depends on all stories complete

### Parallel Opportunities

- T007-T010 (US1 tests): parallel
- T016-T018 (US2 tests): parallel
- US1 and US2 can be implemented in parallel after Foundational
- T027-T028 (Polish): parallel

### Single Developer Execution

T001 → T002-T006 → T007-T015 → T016-T024 → T025-T026 → T027-T030

## Implementation Strategy

### MVP (User Story 1 Only)

Phase 1 + Phase 2 + Phase 3 → LLM tool works → Deploy 🎯

### Full Feature

Add Phase 4 → /membersearch command → Add Phase 5 → Verify → Phase 6 → Ship
