# Research: Extract Links from Markdown-to-Image Messages

**Date**: 2026-07-08

## Decision: URL Regex Pattern

**Decision**: Use `re.findall(r'https?://\S+', text)` for raw URL extraction, plus `re.findall(r'\[([^\]]*)\]\(((?:https?://)[^\)]+)\)', text)` for Markdown links.

**Rationale**: Covers both raw URLs and Markdown link syntax. `\S+` captures everything until whitespace (standard URL pattern in QQ messages). No need for a heavy URL-parsing library — the goal is extraction, not validation.

**Alternatives considered**:
- `urllib.parse.urlparse` — too restrictive; rejects valid URLs QQ users might send
- Full RFC 3986 regex — overkill; `https?://\S+` is sufficient for QQ chat contexts

## Decision: Deduplication Strategy

**Decision**: Use `dict.fromkeys(links).keys()` (order-preserving in Python 3.7+).

**Rationale**: Simple one-liner, preserves first-occurrence order. Links are short strings — memory is irrelevant.

**Alternatives considered**:
- `set()` — loses order
- `OrderedDict` — unnecessary boilerplate in Python 3.7+

## Decision: Return Type Change

**Decision**: `auto_convert_text` returns `list[MessageSegment]` instead of `MessageSegment`.

**Rationale**: Cleanest separation of concerns. Callers iterate and send. Already approved in design spec.

**Alternatives considered**: Tuple `(MessageSegment, str | None)` — rejected for being less extensible and more error-prone at call sites.
