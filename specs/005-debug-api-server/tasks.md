# Tasks: 调试 API 数据采集层与服务器

**Input**: Design documents from `/specs/005-debug-api-server/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included — plan.md specifies `tests/test_debug_api.py` and pytest + pytest-asyncio.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable (different files or independent functions)
- **[Story]**: Maps to user story (US1, US2, US3, US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add configuration items required by all subsequent phases

- [x] T001 [P] Add `DEBUG_ENABLED`, `DEBUG_HOST`, `DEBUG_PORT` config items in `hatsume/plugins/hatsume-plugin/config.py`. Follow existing UPPER_SNAKE_CASE conventions with defaults: `DEBUG_ENABLED=True`, `DEBUG_HOST="127.0.0.1"`, `DEBUG_PORT=8899`. Read from environment variables (`os.environ.get`) with fallback to defaults.

---

## Phase 2: Foundational — Lifecycle & Data Collectors (US3 🎯 MVP)

**Purpose**: Core debug.py skeleton with FastAPI app, lifecycle hooks, and data collector functions. Fulfills User Story 3 (自动启停) and provides the foundation all endpoints depend on.

**⚠️ CRITICAL**: No endpoint work can begin until this phase is complete.

**Independent Test**: Start NoneBot, verify `curl http://127.0.0.1:8899/debug/api/summary` connects (server running). Stop NoneBot, verify port released.

- [x] T002 Create `hatsume/plugins/hatsume-plugin/debug.py` with FastAPI app instance (`debug_app = FastAPI()`), uvicorn server creation (`_create_server()`), and lifecycle functions (`start_debug_server()` / `stop_debug_server()`) using `nonebot.get_driver().on_startup` / `on_shutdown` decorators. Use `asyncio.create_task(server.serve())` pattern per research.md R1. Wrap startup in try/except OSError for graceful port-conflict handling per FR-011.
- [x] T003 Register debug server lifecycle import in `hatsume/plugins/hatsume-plugin/__init__.py` — add `from .debug import start_debug_server, stop_debug_server  # noqa: F401` to trigger decorator registration on plugin load.
- [x] T004 [P] Implement synchronous data collector functions in `hatsume/plugins/hatsume-plugin/debug.py`: `collect_state()`, `collect_queues(limit=20)`, `collect_memory()`, `collect_tools()`, `collect_config()`, `collect_health()`. Each returns a dict following data-model.md schemas. Import state from `..state`, `..config`, `..memory.store`, `..memory.retrieval`, `..graph.tools`, `..graph.nodes.ai`. Use snapshot reads (`.copy()` for lists, no async) per research.md R3. Health collector maintains module-level counters (`_start_time`, `_conversation_count`, `_error_count`, etc.) initialized at import time.

**Checkpoint**: Debug server starts/stops with NoneBot. All collector functions callable. Foundation ready.

---

## Phase 3: User Story 1 — Summary API 查看实时状态 (Priority: P1) 🎯 MVP

**Goal**: `GET /debug/api/summary` returns JSON overview — bot_status, queue lengths, memory count, uptime.

**Independent Test**: `curl http://127.0.0.1:8899/debug/api/summary` returns JSON with `bot_status`, `is_chatting`, `is_graph_running`, 8 queue lengths, `total_memories`, `bm25_dirty`, `uptime_seconds`.

### Implementation

- [x] T005 [US1] Implement `GET /debug/api/summary` route in `hatsume/plugins/hatsume-plugin/debug.py`. Call all collectors, derive `bot_status` from `is_graph_running`/`is_chatting` (idle/chatting/conversing), aggregate queue lengths, return `SummaryResponse` schema per `contracts/debug-api.yaml`.
- [x] T006 [US1] Add error handler for `/debug/api/summary` — catch exceptions, return 500 with `{"error": "message"}`, log traceback.

### Tests

- [x] T007 [P] [US1] Test summary endpoint returns 200 and valid structure when robot idle in `tests/test_debug_api.py`: mock `ConversationState(is_chatting=False, is_graph_running=False)`, empty queues; verify `bot_status == "idle"`, all 8 queue keys present with value 0.
- [x] T008 [P] [US1] Test summary returns `bot_status: "conversing"` when `is_graph_running=True` in `tests/test_debug_api.py`.
- [x] T009 [P] [US1] Test summary returns `bot_status: "chatting"` when `is_chatting=True, is_graph_running=False` in `tests/test_debug_api.py`.

**Checkpoint**: Summary endpoint functional and tested. MVP ready.

---

## Phase 4: User Story 2 — 模块化详细状态端点 (Priority: P2)

**Goal**: 6 modular endpoints for inspecting specific subsystems.

**Independent Test**: Each endpoint returns 200 with module-specific JSON per contracts/debug-api.yaml.

### Implementation

- [x] T010 [P] [US2] Implement `GET /debug/api/state` route in `hatsume/plugins/hatsume-plugin/debug.py` — return `ServerStatus` schema from `collect_state()`.
- [x] T011 [P] [US2] Implement `GET /debug/api/queues` route in `hatsume/plugins/hatsume-plugin/debug.py` — return 8 queue snapshots from `collect_queues(limit)`, respect `?limit=N` (default 20). Each message: `user_name`, `content_preview` (≤30 chars + "…"), `time`, `source_id`. JSON-escape content_preview per FR-014.
- [x] T012 [P] [US2] Implement `GET /debug/api/memory` route in `hatsume/plugins/hatsume-plugin/debug.py` — return `MemoryStatus` schema from `collect_memory()`.
- [x] T013 [P] [US2] Implement `GET /debug/api/tools` route in `hatsume/plugins/hatsume-plugin/debug.py` — return `ToolStatus` schema from `collect_tools()`, compute `image_rate_remaining`/`video_rate_remaining`.
- [x] T014 [P] [US2] Implement `GET /debug/api/config` route in `hatsume/plugins/hatsume-plugin/debug.py` — return `ConfigSnapshot` from `collect_config()`. API keys MUST be boolean presence flags only (FR-008).
- [x] T015 [P] [US2] Implement `GET /debug/api/health` route in `hatsume/plugins/hatsume-plugin/debug.py` — return `HealthMetrics` schema from `collect_health()`.
- [x] T016 [US2] Add 404/405 handlers in `hatsume/plugins/hatsume-plugin/debug.py` — 404 returns `{"error": "not found", "available_endpoints": [...]}`, 405 returns Method Not Allowed.

### Tests

- [x] T017 [P] [US2] Test `/debug/api/queues` structure with populated messages in `tests/test_debug_api.py`: verify `user_name`, `content_preview` truncation, `source_id`.
- [x] T018 [P] [US2] Test `/debug/api/queues?limit=5` respects limit in `tests/test_debug_api.py`.
- [x] T019 [P] [US2] Test `/debug/api/memory` returns `bm25_dirty: true` when flag set in `tests/test_debug_api.py`.
- [x] T020 [P] [US2] Test `/debug/api/config` does NOT expose API key values — all `keys.*` are boolean in `tests/test_debug_api.py`.
- [x] T021 [P] [US2] Test all 6 module endpoints return 200 with valid JSON in `tests/test_debug_api.py`.
- [x] T022 [P] [US2] Test 404 handler returns available endpoints list in `tests/test_debug_api.py`.
- [x] T023 [P] [US2] Test 405 handler returns Method Not Allowed in `tests/test_debug_api.py`.

**Checkpoint**: All 7 endpoints (summary + 6 module) functional and tested.

---

## Phase 5: User Story 4 — 配置化端口与访问控制 (Priority: P3)

**Goal**: Deployer can customize host/port or disable debug server. Default localhost-only.

**Independent Test**: Change `DEBUG_PORT`, restart, verify API on new port. Set `DEBUG_ENABLED=false`, restart, verify no server.

### Implementation

- [x] T024 [US4] Add config-driven startup in `hatsume/plugins/hatsume-plugin/debug.py` — `start_debug_server()` reads `DEBUG_ENABLED` (skip if False), `DEBUG_HOST`, `DEBUG_PORT` from config module, passes to uvicorn Config.
- [x] T025 [US4] Add port-conflict graceful degradation — `start_debug_server()` catches `OSError` on bind, logs WARNING, continues without raising per FR-011.

### Tests

- [x] T026 [P] [US4] Test `DEBUG_ENABLED=False` skips server startup in `tests/test_debug_api.py`.
- [x] T027 [P] [US4] Test `DEBUG_HOST`/`DEBUG_PORT` from config used by uvicorn in `tests/test_debug_api.py`.

**Checkpoint**: Debug server fully configurable with production-safe defaults.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Edge case hardening and documentation validation.

- [x] T028 [P] Harden JSON special character escaping for queue content_preview using `json.dumps()` in `hatsume/plugins/hatsume-plugin/debug.py` (FR-014).
- [x] T029 [P] Add health counter increment hooks — `increment_conversation_count()` and `record_error(msg)` in `hatsume/plugins/hatsume-plugin/debug.py`. Wire `increment_conversation_count()` into `hatsume/plugins/hatsume-plugin/handlers/chat.py` `start_chat()`.
- [x] T030 Run quickstart.md curl examples to validate all endpoints with live NoneBot.
- [x] T031 Review all error handling paths — ensure no unhandled exceptions escape API handlers.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all endpoints
- **US1 (Phase 3)**: Depends on Phase 2 — Summary endpoint (MVP)
- **US2 (Phase 4)**: Depends on Phase 2 — Modular endpoints
- **US4 (Phase 5)**: Depends on Phase 2 — Config validation
- **Polish (Phase 6)**: Depends on all desired stories complete

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — independent
- **US2 (P2)**: After Phase 2 — independent of US1 (separate endpoints)
- **US3 (P1)**: Fulfilled by Phase 2 Foundational
- **US4 (P3)**: After Phase 2 — independent of US1/US2

### Parallel Opportunities

- **Phase 2**: T004 parallel with T002 (collectors vs server lifecycle)
- **Phase 3**: T007, T008, T009 all parallel (3 test functions)
- **Phase 4**: T010-T015 all parallel (6 endpoints), T017-T023 all parallel (7 tests)
- **Phase 5**: T026, T027 parallel
- **Cross-phase**: US1, US2, US4 can start in parallel after Phase 2

---

## Implementation Strategy

### MVP First (US1 + US3)

1. Phase 1 → Phase 2 → Phase 3
2. **VALIDATE**: `curl http://127.0.0.1:8899/debug/api/summary` returns valid JSON
3. **Deployable MVP** — developer can diagnose robot status

### Incremental Delivery

1. Setup + Foundational → server auto-starts
2. US1 summary → **MVP Deployable**
3. US2 modules → Full API surface
4. US4 config → Production-safe
5. Polish → Hardened

### Single Developer

Execute sequentially: 1 → 2 → 3 → 4 → 5 → 6. Each phase adds incremental value.
