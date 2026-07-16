# Implementation Plan: Debug API Queue Message Full Detail

**Branch**: `007-debug-api-queues-full-message` | **Date**: 2026-06-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-debug-api-queues-full-message/spec.md`

## Summary

Enhance `GET /debug/api/queues` to return full message details by parsing the `text` field of each source entry (which is already `message_to_json()` JSON output) and expanding it into the response. This replaces the previous minimal `content_preview`/`user_name`/empty `time` fields with the complete `message_to_json` structure: `type`, `time`, `user: {id, name}`, `content`, `reply_to`, `depth`, plus `source_id`.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI (debug_app), json (stdlib)
**Storage**: N/A (in-memory queue snapshots)
**Testing**: pytest, FastAPI TestClient
**Target Platform**: Linux/macOS server (NoneBot plugin)
**Project Type**: web-service (embedded FastAPI debug server)
**Performance Goals**: < 50ms response time (localhost, existing latency + negligible JSON parsing)
**Constraints**: Must not break existing 8-queue structure; must degrade gracefully on malformed JSON
**Scale/Scope**: 3 files changed; internal developer tool

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|-------|
| Minimal scope | ✅ PASS | Only 3 files; no architecture changes |
| Test coverage | ✅ PASS | Existing tests updated; no gap created |
| Backward compat | ✅ PASS | Internal tool; no external consumers |

## Project Structure

### Documentation (this feature)

```text
specs/007-debug-api-queues-full-message/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── debug-api-queues-response.json
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── debug.py             # MODIFY: collect_queues() message extraction
├── handlers/
│   └── pipeline.py      # (reference only — no change)
└── utils.py             # (reference only — no change)

docs/
└── debug-api-contract.md # MODIFY: Section 5 QueueMessage schema

tests/
└── test_debug_api.py    # MODIFY: queue message field assertions
```

**Structure Decision**: Single-project Python plugin. Changes are localized: `collect_queues()` in `debug.py` (core logic), contract doc, and test assertions.

## Complexity Tracking

No violations. No complexity to justify.
