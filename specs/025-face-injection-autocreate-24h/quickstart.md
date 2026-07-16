# Quickstart: Face Emoji Injection + Auto-Create 24h

**Date**: 2026-07-02

## Verify changes

1. **Face injection**: Start the bot (`nb run`), trigger a conversation in a group. After a few turns, observe logs for `[face] Injected face prompt with N emotions` and `[face] Detected face tag: xxx`.

2. **Face tag not visible to users**: Check the group chat — no `<hatsumeface>` tags should appear in messages.

3. **Auto-create 24h**: Check logs for `[auto_create] Rescheduled` — the next trigger time should be 4–6 hours from now regardless of current hour. Or use `/timer autocreate` to see the next scheduled time.

## Run tests

```bash
python -m pytest tests/ -xvs
```

Key tests:
- `test_generate_image_used_skips_face_injection`
- `test_face_injection_when_flags_false`
- `test_face_tag_stripped_from_user_text_preserved_in_aimessage`
