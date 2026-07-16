# Link Extraction from Markdown-to-Image Messages

**Date:** 2026-07-08
**Status:** approved

## Problem

When `auto_convert_text` in `md_to_image.py` renders a long or Markdown-rich message as an image, any URLs embedded in the text become unclickable — they're pixels in a PNG. Users must manually retype links, which is tedious and error-prone.

## Solution

After converting text to an image, extract all URLs from the original text and append them as a formatted plain-text follow-up message.

## Design

### 1. API Change: `auto_convert_text` return type

| Current | New |
|---------|-----|
| `MessageSegment` | `list[MessageSegment]` |

| Path | Return |
|------|--------|
| Text too short, no MD features | `[MessageSegment.text(text)]` |
| Text → image, links found | `[MessageSegment.image(img_bytes), MessageSegment.text(formatted_links)]` |
| Text → image, no links | `[MessageSegment.image(img_bytes)]` |

### 2. `_extract_links(text: str) -> list[str]`

- Regex to match `https?://\S+` for raw URLs
- Also extract URLs from Markdown link syntax `[label](url)`
- Returns deduplicated, order-preserving list
- Returns empty list if no links found

### 3. `_format_links(links: list[str]) -> str`

Produces:

```
LINKS

1. https://example.com/path
2. https://github.com/foo/bar
3. https://some.other/link
```

Returns `""` for empty input.

### 4. Caller Updates

Both call sites change from single send to iterating segments:

**`graph/nodes/ai.py:585`:**
```python
segments = await auto_convert_text(ai_text_clean)
for seg in segments:
    await send(seg)
```

**`handlers/chat.py:213-215`:**
```python
segments = await auto_convert_text(mask_secret_keys(raw))
for seg in segments:
    await send(seg)
```

### 5. File Changes

| File | Change |
|------|--------|
| `utils/md_to_image.py` | Add `_extract_links`, `_format_links`; change return type; strip emoji before link extraction |
| `graph/nodes/ai.py` | Iterate returned list |
| `handlers/chat.py` | Iterate returned list |

### 6. Edge Cases

- **No links in message:** No links segment appended
- **Duplicate URLs:** Deduplicated, first occurrence kept
- **Links in Markdown code blocks:** Still extracted (same pixel problem applies)
- **Invalid/partial URLs:** Only `https?://` prefixed URLs are matched
- **Emoji in text:** Already stripped before processing (existing behavior)

## Testing

- Unit test `_extract_links` with: raw URLs, Markdown links, mixed, duplicates, no links
- Unit test `_format_links` with: single link, multiple links
- Verify `auto_convert_text` returns correct segments for: short text, long text with links, long text without links
