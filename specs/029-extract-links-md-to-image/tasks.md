# Tasks: Extract Links from Markdown-to-Image Messages

**Input**: Design documents from `/specs/029-extract-links-md-to-image/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: Included — TDD approach per project workflow.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Project root: `hatsume/plugins/hatsume-plugin/`
Test root: `tests/`

---

## Phase 1: Setup

**Purpose**: Prepare test infrastructure for the new feature

- [x] T001 [P] Create empty test file at `tests/test_md_to_image.py` with imports (pytest, anyio, MessageSegment)

---

## Phase 2: Foundational — Core Link Extraction

**Purpose**: New helpers in `md_to_image.py` — the building blocks that all user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 [P] Implement `_extract_links(text: str) -> list[str]` in `hatsume/plugins/hatsume-plugin/utils/md_to_image.py` — regex for raw URLs (`https?://\S+`) and Markdown links (`[label](url)`), deduplicated with dict.fromkeys
- [x] T003 [P] Implement `_format_links(links: list[str]) -> str` in `hatsume/plugins/hatsume-plugin/utils/md_to_image.py` — produces "LINKS\n\n1. url1\n2. url2..."
- [x] T004 Write unit tests for `_extract_links` in `tests/test_md_to_image.py` — test: raw URLs, Markdown links, mixed, duplicates, no links, invalid URLs (no protocol)
- [x] T005 [P] Write unit tests for `_format_links` in `tests/test_md_to_image.py` — test: single link, multiple links, empty list
- [x] T006 Run foundational tests: `python -m pytest tests/test_md_to_image.py -xvs`

**Checkpoint**: `_extract_links` and `_format_links` working, all unit tests passing

---

## Phase 3: User Story 1 — Links Preserved in Image-Rendered Messages (Priority: P1) 🎯 MVP

**Goal**: When a long message is rendered as image, links are extracted and sent as a separate text follow-up

**Independent Test**: Send a message exceeding `LONG_MSG_THRESHOLD` containing `[GitHub](https://github.com)` and `https://example.com`. Verify bot sends image + LINKS text message with both URLs.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T007 [P] [US1] Write integration test for `auto_convert_text` with long text + links in `tests/test_md_to_image.py` — verify returns `[image, text_with_links]` with correct link formatting
- [x] T008 [P] [US1] Write integration test for `auto_convert_text` with long text + no links in `tests/test_md_to_image.py` — verify returns `[image]` only (no links segment)
- [x] T009 Run US1 tests to verify they FAIL: `python -m pytest tests/test_md_to_image.py -k "US1 or test_extract" -xvs`

### Implementation for User Story 1

- [x] T010 [US1] Modify `auto_convert_text` return type in `hatsume/plugins/hatsume-plugin/utils/md_to_image.py` — change from `MessageSegment` to `list[MessageSegment]`. Text path: `[MessageSegment.text(text)]`. Image path with links: `[MessageSegment.image(img_bytes), MessageSegment.text(formatted_links)]`. Image path no links: `[MessageSegment.image(img_bytes)]`.
- [x] T011 [P] [US1] Update caller in `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:585-599` — iterate returned list, send each segment via existing `at_callback`/`_ai_answer`
- [x] T012 [P] [US1] Update caller in `hatsume/plugins/hatsume-plugin/handlers/chat.py:213-215,220-225` — iterate returned list, send each segment via `matcher.send`
- [x] T013 Run US1 tests to verify they PASS: `python -m pytest tests/test_md_to_image.py -k "US1 or test_extract" -xvs`

**Checkpoint**: Long messages with links render as image + LINKS follow-up. Long messages without links render as image only. Both callers working.

---

## Phase 4: User Story 2 — Short Messages With Markdown Features (Priority: P2)

**Goal**: Short messages with rich Markdown (code blocks, headers, LaTeX) that trigger image rendering also get link extraction

**Independent Test**: Send a short message (under threshold) containing ``` ```python``` and `https://docs.python.org`. Verify it renders as image + LINKS.

### Tests for User Story 2

- [x] T014 [P] [US2] Write integration test for `auto_convert_text` with short text + Markdown features + links in `tests/test_md_to_image.py` — verify image rendering triggered and links extracted
- [x] T015 [P] [US2] Write integration test for `auto_convert_text` with LaTeX math + link in `tests/test_md_to_image.py` — verify image rendering triggered and link extracted
- [x] T016 Run US2 tests to verify they FAIL (or pass if already covered): `python -m pytest tests/test_md_to_image.py -k "US2" -xvs`

**Checkpoint**: Short Markdown-rich messages with links get same image + LINKS treatment as long messages

---

## Phase 5: User Story 3 — Plain Text Messages Unchanged (Priority: P3)

**Goal**: Short plain-text messages without Markdown features are unaffected — delivered as plain text, no image, no LINKS

**Independent Test**: Send "Hello, how are you?" — verify it arrives as plain text MessageSegment only.

### Tests for User Story 3

- [x] T017 [P] [US3] Write test for `auto_convert_text` with short plain text in `tests/test_md_to_image.py` — verify returns `[MessageSegment.text(text)]` only
- [x] T018 [P] [US3] Write test for `auto_convert_text` with short text + URL (no MD features) in `tests/test_md_to_image.py` — verify returns `[MessageSegment.text(text)]` (no image, no separate links)
- [x] T019 Run US3 tests: `python -m pytest tests/test_md_to_image.py -k "US3" -xvs`

**Checkpoint**: Plain text path completely unchanged. No regression in existing behavior.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T020 Run all tests: `python -m pytest tests/test_md_to_image.py -xvs`
- [x] T021 Run ruff lint check on changed files: `ruff check hatsume/plugins/hatsume-plugin/utils/md_to_image.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py hatsume/plugins/hatsume-plugin/handlers/chat.py`
- [x] T022 Quickstart validation: verify all steps in `specs/029-extract-links-md-to-image/quickstart.md` work correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - US1 → US2 → US3 (sequential due to shared implementation; US1 contains actual code changes)
- **Polish (Phase 6)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — contains actual `auto_convert_text` return type change and caller updates
- **US2 (P2)**: After US1 — tests for Markdown feature trigger path (impl shared with US1)
- **US3 (P3)**: After US2 — regression tests for plain text path

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation tasks follow test failures
- Tests re-run to verify PASS after implementation

### Parallel Opportunities

- T002 and T003 can run in parallel (different functions, same file but independent)
- T004 and T005 can run in parallel (different test functions)
- T007 and T008 can run in parallel (different test scenarios)
- T011 and T012 can run in parallel (different caller files)
- T014 and T015 can run in parallel (different test scenarios)
- T017 and T018 can run in parallel (different test scenarios)

---

## Parallel Example: Foundational Phase

```bash
# Launch helpers in parallel:
Task: "Implement _extract_links in hatsume/plugins/hatsume-plugin/utils/md_to_image.py"
Task: "Implement _format_links in hatsume/plugins/hatsume-plugin/utils/md_to_image.py"

# Launch tests in parallel:
Task: "Write unit tests for _extract_links in tests/test_md_to_image.py"
Task: "Write unit tests for _format_links in tests/test_md_to_image.py"
```

## Parallel Example: Caller Updates (US1)

```bash
# Launch caller updates in parallel:
Task: "Update caller in hatsume/plugins/hatsume-plugin/graph/nodes/ai.py"
Task: "Update caller in hatsume/plugins/hatsume-plugin/handlers/chat.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002-T006)
3. Complete Phase 3: User Story 1 (T007-T013)
4. **STOP and VALIDATE**: Test US1 independently — long messages with links produce image + LINKS
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → helpers ready
2. Add US1 → long messages get link extraction (MVP!)
3. Add US2 → short Markdown messages get link extraction
4. Add US3 → confirm no regression in plain text path
5. Polish → lint, full test suite, quickstart validation

---

## Notes

- [P] tasks = different files or independent test functions, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Emoji stripping in `auto_convert_text` runs before link extraction (existing behavior preserved)
- The `ai.py` caller has three send paths: `at_callback(ai_msg, uid)` (notified/timer) and `_ai_answer(ai_msg)` — all must iterate
