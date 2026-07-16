# Data Model: Extract Links from Markdown-to-Image Messages

**Date**: 2026-07-08

No new entities, tables, or persistent data. This feature operates entirely on in-memory strings.

## Existing Types Affected

### `auto_convert_text` signature change

| Aspect | Before | After |
|--------|--------|-------|
| Return type | `MessageSegment` | `list[MessageSegment]` |
| Text path | `MessageSegment.text(text)` | `[MessageSegment.text(text)]` |
| Image path (no links) | `MessageSegment.image(img_bytes)` | `[MessageSegment.image(img_bytes)]` |
| Image path (with links) | `MessageSegment.image(img_bytes)` | `[MessageSegment.image(img_bytes), MessageSegment.text(formatted_links)]` |

### New internal helpers (in `md_to_image.py`)

- `_extract_links(text: str) -> list[str]` — extracts raw and Markdown URLs, deduplicated
- `_format_links(links: list[str]) -> str` — formats as "LINKS\n\n1. url1\n2. url2..."
