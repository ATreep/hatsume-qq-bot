# Feature Specification: Random ACG Photo Tool

**Feature Branch**: `030-random-acg-photo-tool`

**Created**: 2026-07-11

**Status**: Draft

**Input**: User description: "Add a tool that can access photos in my gallery of Apple Photos App. The tool is called `random_acg_photo`. It randomly selects a photo from the 'ACG' album in Apple Photos, exports it via AppleScript to a macOS temp directory, copies it to the Docker sandbox container, and returns the sandbox absolute path. The LLM then uses the existing `send_image` tool with 'file://' prefix to send it to the user."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Request a Random ACG Photo (Priority: P1)

A group chat member asks the bot for a random ACG (anime/comic/game) image. The bot retrieves a random photo from the "ACG" album in Apple Photos and sends it to the group chat.

**Why this priority**: This is the sole function of the feature — without it, nothing else exists. It directly delivers the user-visible value.

**Independent Test**: Can be fully tested by sending a message like "来张二次元图" in the group chat and verifying the bot responds with an image from the ACG album.

**Acceptance Scenarios**:

1. **Given** Photos.app is running and the "ACG" album contains photos, **When** the bot invokes the `random_acg_photo` tool, **Then** a photo is exported to the sandbox, a valid sandbox path is returned, and the bot sends the image to the group chat.
2. **Given** the "ACG" album contains exactly 1 photo, **When** the bot invokes the tool, **Then** that single photo is returned every time.
3. **Given** the "ACG" album contains many photos, **When** the bot invokes the tool multiple times, **Then** different photos are returned (random selection).

---

### User Story 2 — Graceful Error Handling (Priority: P2)

When the tool cannot retrieve a photo due to environmental issues, it informs the user with a clear, Chinese-language error message instead of failing silently.

**Why this priority**: Error handling is essential for reliability, but the core photo retrieval (P1) must exist first. Users need meaningful feedback when things go wrong.

**Independent Test**: Can be tested by triggering each error condition (e.g., closing Photos.app, renaming the album) and verifying the bot returns an appropriate Chinese error message.

**Acceptance Scenarios**:

1. **Given** Photos.app is not running, **When** the bot invokes the tool, **Then** a Chinese error message is returned indicating that Photos cannot be accessed and that the user should open Photos.app.
2. **Given** the "ACG" album does not exist, **When** the bot invokes the tool, **Then** a Chinese error message is returned indicating the album was not found.
3. **Given** the "ACG" album exists but contains no photos, **When** the bot invokes the tool, **Then** a Chinese error message is returned indicating the album is empty.
4. **Given** the sandbox container is not running, **When** the bot invokes the tool, **Then** a Chinese error message is returned indicating the sandbox is unavailable.

---

### Edge Cases

- What happens when the exported photo filename contains spaces or special characters?
- What happens when macOS `/tmp/hatsume_acg_export/` already exists from a previous failed export?
- What happens when the exported photo has an unusual file extension (e.g., `.heic`, `.png`, `.gif`)?
- What happens when two users request a photo simultaneously (concurrent access to the same macOS temp directory)?
- What happens when the `docker cp` command times out?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an LLM-callable tool named `random_acg_photo` that requires no parameters.
- **FR-002**: System MUST query the Apple Photos "ACG" album and randomly select one media item.
- **FR-003**: System MUST export the selected photo to a macOS temporary directory via AppleScript.
- **FR-004**: System MUST copy the exported file to the Docker sandbox container with a timestamped filename in the format `apple_photo_export_YYMMDD_HHmmss.<ext>`.
- **FR-005**: System MUST return the sandbox absolute path (e.g., `/tmp/apple_photo_export_260711_143025.jpg`) without a `file://` prefix.
- **FR-006**: System MUST clean the macOS temporary export directory before each export to avoid stale files.
- **FR-007**: System MUST return Chinese-language error messages when Photos.app is not running, the "ACG" album is not found, the album is empty, or the sandbox container is unavailable.
- **FR-008**: The LLM MUST prepend `file://` to the returned path when calling the existing `send_image` tool.
- **FR-009**: System MUST ensure the sandbox container is running before attempting `docker cp`.

### Key Entities

- **Photo (media item)**: A single image file stored in the Apple Photos "ACG" album, identified by filename and extension.
- **Export result**: A file in the sandbox at `/tmp/apple_photo_export_<timestamp>.<ext>`, represented by its absolute path string.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The bot successfully retrieves and sends a photo from the ACG album in response to a user request, with the full round-trip (tool call → export → copy → send) completing within 15 seconds under normal conditions.
- **SC-002**: When an error condition occurs (Photos not running, album missing, album empty), the bot returns a descriptive Chinese error message within 5 seconds.
- **SC-003**: The tool returns a valid sandbox path that works with the existing `send_image` tool without modification beyond adding the `file://` prefix.

## Assumptions

- The bot runs on macOS where Apple Photos.app is installed and the user has granted automation permissions (System Events / Photos) to the terminal or process running the bot.
- The "ACG" album already exists in the user's Photos library and is manually maintained by the user.
- The Docker sandbox container (`hatsume-space`) is managed by the existing infrastructure code and the `ensure_container_running()` function is available.
- The exported photo's file extension is preserved as-is; no format conversion is performed.
- Concurrent access to the tool is rare enough that sharing a single macOS temp directory (`/tmp/hatsume_acg_export/`) is acceptable.
- The existing `send_image` tool already supports `file://` paths and reads from the sandbox container.
- No new Python dependencies or external services are required.
