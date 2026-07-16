# Research: Debug API Queue Message Full Detail

**Date**: 2026-06-05

## Decision: Parse source entry `text` as JSON

**Decision**: Parse the `text` field of each source entry via `json.loads()` and merge with `source_id`.

**Rationale**:
- The `text` field is already `json.dumps(message_to_json(...))` / `json.dumps(build_forward_json(...))` output — no new data collection needed.
- `json` is stdlib — zero new dependencies.
- Parsing is O(n) on message count, with `limit` defaulting to 20 entries per queue — negligible overhead.

**Alternatives considered**:
1. Extract fields from source entry metadata directly — the source entry only stores `text`, `people`, and `source_id`. `time` and `reply_to` are only available inside the serialized JSON. Rejected: loses data.
2. Add new fields to source entry alongside `text` — requires changing pipeline handler. Rejected: unnecessary code churn when the data is already in `text`.

## Decision: Fallback on JSON parse failure

**Decision**: On `json.JSONDecodeError`, return raw `text` as `content` with `type: "message"`, `time: ""`, `user: {id: 0, name: "unknown"}`.

**Rationale**:
- The `text` field comes from a controlled code path (`json.dumps()` in pipeline.py), so parse failures should be extremely rare.
- Graceful degradation preserves observability — a single malformed entry should not break the whole endpoint.

## Decision: Preserve `source_id`

**Decision**: Add `source_id` as a top-level field alongside the parsed message object.

**Rationale**:
- `source_id` is not part of `message_to_json()` output but is critical for debugging (identifies which source entry a message belongs to).
- Adding it post-parse keeps the JSON structure clean.
