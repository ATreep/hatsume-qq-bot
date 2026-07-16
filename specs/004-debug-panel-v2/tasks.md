# Tasks: 调试面板 v2

**Input**: Design documents from `/specs/004-debug-panel-v2/`

**Tests**: TDD — tests written first, fail, then implement.

## Phase 1: Foundational (Backend Queue Summary)

**Purpose**: 采集器返回消息摘要数组，非仅计数

- [x] T001 [P] Test queue summary returns message list in tests/test_debug.py — test_queue_collector_returns_message_list
- [x] T002 [P] Test queue message has user/content/time fields in tests/test_debug.py — test_queue_message_fields
- [x] T003 [P] Test queue summary max 20 items in tests/test_debug.py — test_queue_summary_max_items
- [x] T004 Update _build_debug_collectors in hatsume/plugins/hatsume-plugin/__init__.py — 队列返回 [{user, content, time}]
- [x] T005 Add message_to_summary helper in hatsume/plugins/hatsume-plugin/debug.py — 截断 50 字

---

## Phase 2: User Story 1 - 消息队列内容查看 (Priority: P1) 🎯

- [x] T006 [P] [US1] Test HTML escaping in queue content in tests/test_debug.py
- [x] T007 [P] [US1] Test queue empty state rendering in tests/test_debug.py
- [x] T008 [US1] Implement message bubble component in templates/debug_panel.html
- [x] T009 [US1] Implement queue empty state in templates/debug_panel.html
- [x] T010 [US1] Update type detection for queue arrays in templates/debug_panel.html

---

## Phase 3: User Story 2 - Dashboard 概览 (Priority: P2)

- [x] T011 [P] [US2] Test Dashboard derives status from snapshot in tests/test_debug.py
- [x] T012 [P] [US2] Test Dashboard warning state (bm25_dirty) in tests/test_debug.py
- [x] T013 [US2] Implement Dashboard component in templates/debug_panel.html
- [x] T014 [US2] Implement Dashboard status colors in templates/debug_panel.html

---

## Phase 4: User Story 3 - 搜索/响应式/JSDoc (Priority: P3)

- [x] T015 [P] [US3] Test search filter matches variable keys in tests/test_debug.py
- [x] T016 [P] [US3] Test search no match shows empty in tests/test_debug.py
- [x] T017 [P] [US3] Test HTML under 20KB in tests/test_debug.py
- [x] T018 [US3] Implement search box + filter (200ms debounce) in templates/debug_panel.html
- [x] T019 [US3] Implement mobile responsive CSS (@media max-width:767px) in templates/debug_panel.html
- [x] T020 [US3] Add JSDoc @typedef and @type in templates/debug_panel.html

---

## Phase 5: Polish

- [x] T021 Run full test suite — pytest tests/test_debug.py -v, all pass
- [x] T022 Validate HTML <20KB — wc -c

## Dependencies

- Phase 1 → BLOCKS Phase 2,3,4
- Phase 2,3,4 可并行
- Phase 5 依赖所有

## MVP: Phase 1 + Phase 2 (T001-T010)
