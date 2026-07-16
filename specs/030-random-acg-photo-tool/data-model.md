# Data Model: Random ACG Photo Tool

**Feature**: 030-random-acg-photo-tool
**Date**: 2026-07-11

## Overview

This feature is a stateless tool — it has no persistent data model. It operates on transient file paths and returns a string. No database tables, no stored state.

## Transient Entities

### Exported Photo (filesystem)

| Attribute | Type | Description |
|-----------|------|-------------|
| `host_path` | `str` | macOS absolute path, e.g. `/tmp/hatsume_acg_export/IMG_1234.jpg` |
| `sandbox_path` | `str` | Container absolute path, e.g. `/tmp/apple_photo_export_260711_143025.jpg` |
| `extension` | `str` | Original file extension, preserved from export (`.jpg`, `.png`, `.heic`, etc.) |
| `timestamp` | `str` | `YYMMDD_HHmmss` format, embedded in sandbox filename |

### Lifecycle

```
[Photos.app ACG album]
    │
    │ AppleScript export
    ▼
[macOS /tmp/hatsume_acg_export/]
    │
    │ docker cp
    ▼
[sandbox /tmp/apple_photo_export_<ts>.<ext>]
    │
    │ send_image (file:// prefix)
    ▼
[QQ group chat message]
    │
    ▼
  (discarded on next export / container restart)
```

### State Transitions

| State | Trigger | Next State |
|-------|---------|------------|
| In Photos album | User manually adds photos | N/A (out of scope) |
| Exported to macOS tmp | `random_acg_photo()` called | Exported |
| Copied to sandbox | `docker cp` succeeds | Ready for send |
| Sent to chat | `send_image(file://...)` called | Delivered |
| Cleaned up | Next `random_acg_photo()` call (rmtree) or container restart | Deleted |

## Validation Rules

- macOS temp directory must exist (`os.makedirs` with `exist_ok=True`)
- Export directory must contain exactly 1 file after export
- File must exist before `docker cp` (`os.path.isfile` check)
- Sandbox container must be running (`ensure_container_running()`)
