# Tasks: 实时调试监控面板

**Input**: Design documents from `/specs/003-debug-monitor-panel/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — TDD workflow per user's directive. Tests written first, fail, then implement.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in descriptions

## Path Conventions

- Plugin source: `hatsume/plugins/hatsume-plugin/`
- HTML templates: `hatsume/plugins/hatsume-plugin/templates/`
- Tests: `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project scaffolding — directory and empty files

- [x] T001 Create templates directory at hatsume/plugins/hatsume-plugin/templates/
- [x] T002 [P] Create empty debug.py at hatsume/plugins/hatsume-plugin/debug.py with module docstring
- [x] T003 [P] Create empty test_debug.py at tests/test_debug.py with imports (pytest, pytest_asyncio, fastapi TestClient)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: StateCollector + registry + HTML routing — backend infrastructure that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests for Foundational

> **Write these FIRST, ensure they FAIL before implementation**

- [x] T004 [P] Test collector registration in tests/test_debug.py — test_register_collector, test_duplicate_name_rejected
- [x] T005 [P] Test collector execution in tests/test_debug.py — test_collect_all_returns_merged_dict, test_collector_exception_isolated
- [x] T006 [P] Test diff computation in tests/test_debug.py — test_diff_changed_only, test_diff_unchanged_empty, test_diff_new_keys
- [x] T007 [P] Test HTML route in tests/test_debug.py — test_get_debug_html_returns_200, test_content_type_html

### Implementation for Foundational

- [x] T008 Implement StateCollector dataclass and registry (register, collect_all, compute_diff) in hatsume/plugins/hatsume-plugin/debug.py
- [x] T009 Implement setup_debug_panel(app, collectors) — register /hatsume-debug/ GET route serving debug_panel.html in hatsume/plugins/hatsume-plugin/debug.py
- [x] T010 Integrate setup_debug_panel call into hatsume/plugins/hatsume-plugin/__init__.py — get app via nonebot.get_app(), call setup_debug_panel(app, [])

**Checkpoint**: Backend infrastructure ready — tests pass, GET route returns HTML, collector registry works

---

## Phase 3: User Story 1 - 连接监控面板并查看实时状态 (Priority: P1) 🎯 MVP

**Goal**: Developer opens browser URL and sees all module variables updating in real-time via WebSocket

**Independent Test**: Start bot, open `http://localhost:6999/hatsume-debug/`, verify variables display and auto-update

### Tests for User Story 1

> **Write these FIRST, ensure they FAIL before implementation**

- [x] T011 [P] [US1] WebSocket handshake test in tests/test_debug.py — test_ws_connect_receives_snapshot
- [x] T012 [P] [US1] WebSocket diff test in tests/test_debug.py — test_ws_diff_pushes_changed_values, test_ws_diff_empty_when_unchanged
- [x] T013 [P] [US1] HTML size constraint test in tests/test_debug.py — test_html_under_15kb
- [x] T014 [P] [US1] HTML no external refs test in tests/test_debug.py — test_html_no_external_script_links, test_html_no_external_css_links

### Implementation for User Story 1

- [x] T015 [US1] Implement WebSocket endpoint /hatsume-debug/ws in hatsume/plugins/hatsume-plugin/debug.py — accept, send snapshot, start diff loop
- [x] T016 [US1] Implement async collect loop in hatsume/plugins/hatsume-plugin/debug.py — periodic collect + diff + broadcast to WS clients
- [x] T017 [US1] Create debug_panel.html skeleton in hatsume/plugins/hatsume-plugin/templates/debug_panel.html — HTML structure: left nav + right detail panels, WebSocket connect, snapshot render
- [x] T018 [US1] Implement CSS glassmorphism styling in debug_panel.html — dark bg (#0a0a0f), frosted glass (rgba + backdrop-filter blur(12px)), 1px borders, rounded corners (12-20px), no box-shadow
- [x] T019 [US1] Implement variable card rendering in debug_panel.html — type-aware formatting (bool→dot, int/float→monospace right-align, str→monospace, null→"—")
- [x] T020 [US1] Implement WebSocket reconnection in debug_panel.html — exponential backoff (1s,2s,4s,max 30s), status indicator (green/red dot)
- [x] T021 [US1] Register all 6 module StateCollectors in hatsume/plugins/hatsume-plugin/__init__.py — conv_state, ai_node, tools, memory, infra, night_comic

**Checkpoint**: MVP complete — open browser, see all variables, values update in real-time

---

## Phase 4: User Story 2 - 按模块浏览变量 (Priority: P2)

**Goal**: Developer clicks module names in left sidebar to filter variables in right panel

**Independent Test**: Click each module in left nav, verify right panel shows only that module's variables

### Tests for User Story 2

> **Write these FIRST, ensure they FAIL before implementation**

- [x] T022 [P] [US2] Frontend module navigation test in tests/test_debug.py — test_snapshot_contains_all_modules_as_keys

### Implementation for User Story 2

- [x] T023 [US2] Implement module sidebar in debug_panel.html — render module list from snapshot keys, show variable count per module
- [x] T024 [US2] Implement module selection in debug_panel.html — click to filter, highlight active module, default to first
- [x] T025 [US2] Implement dict/list expand in debug_panel.html — nested dict as sub-cards, list shows count with click-to-expand

**Checkpoint**: Module navigation works — click to filter, nested data expands

---

## Phase 5: User Story 3 - 变量值变化高亮 (Priority: P3)

**Goal**: Changed variable cards briefly flash to draw developer attention

**Independent Test**: Trigger a state change, observe the affected variable card flash

### Tests for User Story 3

> **Write these FIRST, ensure they FAIL before implementation**

- [x] T026 [P] [US3] Diff application test in tests/test_debug.py — test_diff_updates_correct_module_variable

### Implementation for User Story 3

- [x] T027 [US3] Implement change flash animation in debug_panel.html — 300ms background-color transition on value change
- [x] T028 [US3] Implement diff merge logic in debug_panel.html — apply incoming diff to local state tree, mark changed keys for flash

**Checkpoint**: All user stories complete — connect, browse, highlight all work

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final integration quality and validation

- [x] T029 [P] Add URL parameter interval support in hatsume/plugins/hatsume-plugin/debug.py — parse ?interval=N, pass to collect loop
- [x] T030 [P] Add header bar in debug_panel.html — connection dot, interval indicator, close button
- [x] T031 Run full test suite — pytest tests/test_debug.py -v, verify all tests pass
- [x] T032 Validate quickstart.md — follow all steps, verify each checkpoint

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational — can run in parallel with US1
- **US3 (Phase 5)**: Depends on Foundational — best after US1 (needs rendering working)
- **Polish (Phase 6)**: Depends on all desired user stories

### User Story Dependencies

- **US1 (P1)**: After Foundational — no other story deps
- **US2 (P2)**: After Foundational — independent of US1 (different HTML sections)
- **US3 (P3)**: After Foundational — benefits from US1 rendering being in place

### Within Each User Story

- Tests written FIRST, verified FAILING
- Implementation follows
- Tests verified PASSING before moving on

### Parallel Opportunities

- Phase 3 US1 tests (T011-T014) can all run in parallel
- US2 and US3 can be developed in parallel with US1 — they touch different HTML sections
- Phase 1 tasks T002, T003 can run in parallel

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1 (tests → fail → implement → pass)
4. **STOP and VALIDATE**: Open debug panel, verify real-time state display
5. Commit MVP

### TDD Flow

For each phase:
1. Write all test tasks [P] in parallel (they FAIL)
2. Implement code tasks sequentially
3. Run tests — all must PASS before next phase

### Multi-Agent Parallel Strategy

With parallel agents:
1. Agent A: Foundational tests (T004-T007) + implementation (T008-T010)
2. Once Foundational done:
   - Agent A: US1 (T011-T021)
   - Agent B: US2 (T022-T025)
   - Agent C: US3 (T026-T028)
3. Agent D: Polish (T029-T032)

---

## Notes

- [P] tasks touch different files or independent sections — safe to parallelize
- [Story] label maps task to specific user story for traceability
- Every test task must FAIL on first run (TDD red-green cycle)
- Commit after each phase checkpoint
- debug_panel.html is a single file — [P] tasks within it target independent sections (CSS vs JS vs HTML)
- Zero new pip dependencies — all imports from stdlib or already-installed packages
