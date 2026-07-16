# Quickstart: Extract Links from Markdown-to-Image Messages

## What Changed

`auto_convert_text` now returns `list[MessageSegment]` instead of `MessageSegment`. When a message is rendered as an image and contains URLs, a second text segment with the links is appended.

## Caller Migration

Before:
```python
msg = await auto_convert_text(text)
await send(msg)
```

After:
```python
segments = await auto_convert_text(text)
for seg in segments:
    await send(seg)
```

## Testing

```bash
python -m pytest tests/test_md_to_image.py -xvs
```
