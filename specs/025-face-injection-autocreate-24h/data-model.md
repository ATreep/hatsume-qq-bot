# Data Model: Face Emoji Injection + Auto-Create 24h

**Date**: 2026-07-02

No new entities or schema changes. All changes modify existing in-memory state and file formats.

## Existing entities (unchanged)

### Face Image File

- **Location**: `data/hatsume-plugin/faces/`
- **Naming**: `{emotion}_{index}.{ext}` (e.g., `开心_0.png`)
- **Emotion extracted as**: text before first `_`
- **No changes** to format, storage, or reading logic

### Face Tag (new in-memory concept)

- **Format**: `<hatsumeface>{emotion}</hatsumeface>`
- **Location in message**: Anywhere in LLM text output (typically at end)
- **Extraction**: `re.compile(r"<hatsumeface>(.*?)</hatsumeface>")` — first match
- **Lifecycle**: Extracted from `ai_text` → stripped for user output → preserved in `AIMessage` for graph state

### Auto-Create Timer Task

- **Table**: `timer_tasks` (SQLite), `task_type = 'auto_create'`
- **Trigger time**: Random Unix timestamp in `[now+4h, now+6h]` (was: clamped to 07:00–22:00 UTC+8)
- **No schema changes** — only the trigger time calculation changes

## Removed

- `AUTO_CREATE_TIME_START: int` config constant
- `AUTO_CREATE_TIME_END: int` config constant
- `_face_cooling_count`: module-level global remains, behavior unchanged
