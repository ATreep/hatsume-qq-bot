# Research: Random ACG Photo Tool

**Feature**: 030-random-acg-photo-tool
**Date**: 2026-07-11

## Research Questions

### R1: AppleScript API for Photos.app — random photo from specific album

**Decision**: Use `osascript` with inline AppleScript that queries album by name, counts media items, picks random index, exports single item.

**Rationale**:
- Photos.app Scripting Dictionary supports `album "<name>"` → `every media item` → `export {item N} to <POSIX file>` natively.
- `random number from 1 to count` built into AppleScript — no need for Python-side random.
- Single-item export (not all-then-pick) keeps the operation fast even for large albums.
- Using `try/on error` in AppleScript catches album-not-found, empty-album, and app-not-running cases.

**Alternatives considered**:
- PyObjC + PhotoKit: more powerful but requires `pyobjc-framework-Photos` dependency, violates zero-new-deps constraint.
- Direct SQLite on `photoslibrary`: fragile, unsupported, breaks on Photos.app updates.
- JXA (JavaScript for Automation): equivalent capability to AppleScript, but AppleScript is simpler for this use case.

### R2: File transfer from macOS host to Docker sandbox

**Decision**: Use `docker cp <host_path> <container>:<sandbox_path>` via `subprocess.run`.

**Rationale**:
- `docker cp` is the official Docker CLI mechanism for host↔container file transfer.
- Project already depends on Docker CLI (container launch/stop scripts, `run_cmd`).
- `subprocess.run` already used extensively in `tools.py` (see `shell_executor`, `capture_html_shot`).
- No need to use `run_cmd` (which executes inside container) — we need host→container direction.

**Alternatives considered**:
- Mount a shared volume: requires container restart, overengineered for a single-file copy.
- `docker exec` with stdin redirect: fragile, binary data issues.
- Base64 encoding + `docker exec` echo: double the transfer size, encoding overhead.

### R3: Timestamped filename convention

**Decision**: `apple_photo_export_YYMMDD_HHmmss.<original_ext>` in sandbox `/tmp/`.

**Rationale**:
- Timestamp prevents collisions between sequential calls (each invocation gets unique filename).
- Original extension preserved so image format is correct (JPEG, PNG, HEIC, etc.).
- Sandbox `/tmp/` is ephemeral — files naturally cleaned on container restart.
- `datetime.now().strftime("%y%m%d_%H%M%S")` provides second-level uniqueness.

**Alternatives considered**:
- UUID filenames: unique but less human-readable when debugging.
- Fixed filename: collision risk between calls; stale file from previous export could be served.

### R4: Error handling strategy

**Decision**: Return Chinese `❌ 错误：<description>` strings matching existing tool conventions.

**Rationale**:
- All existing tools (`generate_image`, `generate_video`, etc.) return Chinese error strings with `❌` prefix.
- LLM interprets error strings and relays appropriate message to user.
- Four error categories: Photos not running, album not found, album empty, sandbox unavailable.

**Alternatives considered**:
- Python exceptions: would crash the tool call and produce unhelpful stack traces in chat.
- English errors: inconsistent with existing tool conventions.
