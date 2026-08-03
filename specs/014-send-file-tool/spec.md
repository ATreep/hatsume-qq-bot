# Feature Specification: Send File from Ubuntu Container

**Feature Branch**: `014-send-file-tool`

**Created**: 2026-06-25

**Status**: Draft

**Input**: User description: "Add a new tool that allows bot send a file from its ubuntu docker container"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Send Script Output File on Explicit Request (Priority: P1)

A user asks the bot to write a Python script inside the Ubuntu container and explicitly says "send me the script file." The bot executes the shell commands to create the script in `/work/`, then uses the send_file tool to extract the file from the container and deliver it to the QQ group as a group file attachment.

**Why this priority**: This is the core capability — delivering container-generated files to users on demand. Without this, users cannot receive any files generated inside the container.

**Independent Test**: Can be tested by asking the bot to "create a hello.py file in /work/ and send it to me." The bot should produce a file that appears as a group file attachment with the correct name and contents.

**Acceptance Scenarios**:

1. **Given** a file `report.txt` exists at `/work/report.txt` inside the container, **When** the user says "send me report.txt", **Then** the bot extracts the file, sends it to the group, and the user receives it as a group file with name "report.txt".
2. **Given** a file exists at `/work/results/data.csv`, **When** the user says "把 data.csv 发到群里", **Then** the bot sends the file successfully.

---

### User Story 2 - Send File with Custom Display Name (Priority: P2)

A user generates a file with a cryptic or auto-generated name inside the container (e.g., `tmp_a73k2x_output.pdf`), and wants it sent with a human-readable name. The bot uses the optional display_name parameter to rename the file when sending.

**Why this priority**: Enhances usability for files with non-descriptive generated names, but the core sending capability (P1) works without it.

**Independent Test**: Ask the bot to create a file named `/work/tmp_data.txt` and send it as `summary.txt`. Verify the received file is named `summary.txt`.

**Acceptance Scenarios**:

1. **Given** a file `/work/tmp_a73k2x_output.pdf` exists, **When** the user says "把那个 PDF 作为 report.pdf 发给我", **Then** the bot sends the file displayed as "report.pdf".

---

### User Story 3 - Malicious Path Request Refused (Priority: P1 - Security)

A user (or the LLM acting on its own) attempts to send a file from outside the `/work/` directory, such as `/etc/passwd` or `../../root/.ssh/id_rsa`. The system detects the invalid path and returns an error message instead of sending the file.

**Why this priority**: Security is non-negotiable. Path traversal protection prevents exposure of sensitive container files.

**Independent Test**: Attempt to trigger the bot to send `/etc/shadow`. Verify the bot returns an error about the path being outside `/work/`.

**Acceptance Scenarios**:

1. **Given** the container has files at `/etc/passwd`, **When** the LLM attempts to send `/etc/passwd`, **Then** the system returns an error: "只允许访问 /work/ 目录下的文件".
2. **Given** a file at `/root/.ssh/id_rsa`, **When** the LLM attempts to send `../../root/.ssh/id_rsa`, **Then** the system returns an error about path traversal being rejected.

---

### User Story 4 - Oversize File Rejected (Priority: P2)

A user requests a file that exceeds the 10 MB size limit. The system detects the oversize file before copying it and returns a clear error message, without attempting the transfer.

**Why this priority**: Prevents bandwidth waste and hangs on large file transfers, but 10 MB covers most generated artifacts.

**Independent Test**: Create a 15 MB file in `/work/` and ask the bot to send it. Verify the bot returns an error about the file exceeding 10 MB without attempting to send it.

**Acceptance Scenarios**:

1. **Given** a 15 MB file at `/work/large.bin`, **When** the user says "send me large.bin", **Then** the bot returns "文件大小为 15.00 MB，超过最大限制 10 MB".

---

### User Story 5 - LLM Asks Before Sending (Priority: P2)

The user asks the bot to write a script but does NOT explicitly request the file be sent. The LLM, following its prompt rules, asks "需要我把脚本文件发到群里吗？" before calling send_file. If the user confirms, the LLM then sends the file.

**Why this priority**: Prevents the bot from sending files unprompted, but the core sending capability (P1) covers the sending itself.

**Independent Test**: Ask the bot "帮我写个 Python 爬虫脚本" without mentioning sending. Verify the bot responds asking whether to send the file.

**Acceptance Scenarios**:

1. **Given** a conversation where the user says "帮我生成一个配置文件", **When** the LLM considers whether to send the file, **Then** the LLM first asks "需要我把配置文件发到群里吗？" rather than immediately calling send_file.
2. **Given** the user says "把刚才那个脚本发给我", **When** the LLM detects the explicit request, **Then** the LLM calls send_file directly without asking first.

---

### Edge Cases

- What happens when the Docker container is not running? The system checks container status and returns "Ubuntu 容器未运行".
- What happens when the file path points to a directory? The system checks if it's a regular file and returns "是一个目录".
- What happens when docker cp times out? After 30 seconds, the system returns "文件提取超时" and cleans up temp files.
- What happens with symlinks? Symlink targets are validated to also be within `/work/`.
- What happens when the user provides an empty display_name? The original filename is used.
- What happens when multiple files are needed? The user must request each file individually.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow extraction of files from the Ubuntu Docker container `/work/` directory to the QQ group chat.
- **FR-002**: System MUST resolve relative file paths against `/work/` and accept absolute paths starting with `/work/`.
- **FR-003**: System MUST reject file paths that resolve outside `/work/` (including `../` traversal and absolute paths outside `/work/`).
- **FR-004**: System MUST enforce a maximum file size of 10 MB before attempting extraction.
- **FR-005**: System MUST check that the target path is a regular file (not directory, device, or socket) before sending.
- **FR-006**: System MUST verify the Docker container is running before attempting file operations.
- **FR-007**: System MUST auto-delete temporary files created on the host during the transfer process.
- **FR-008**: System MUST return Chinese-language error messages for all failure scenarios.
- **FR-009**: System MUST support an optional display_name parameter to customize the filename shown to recipients.
- **FR-010**: LLM MUST only invoke the send_file tool when the user explicitly requests a file be sent.
- **FR-011**: LLM MUST ask for confirmation before sending when the user has not explicitly requested file delivery.
- **FR-012**: System MUST validate symlink targets to ensure the resolved target also resides within `/work/`.

### Key Entities

- **Container File**: A file located inside the Ubuntu Docker container at a path under `/work/`. Has attributes: path, size (bytes), type (file/directory/symlink).
- **Transferred File**: The file after extraction from the container to the host temporary directory, before being sent to QQ.
- **Group File Message**: The file as received by QQ group members. Displays with a filename and appears in the group file list.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can receive container-generated files in the QQ group within 30 seconds of requesting them (for files under 10 MB).
- **SC-002**: 100% of path traversal attempts (paths escaping `/work/`) are blocked and return an error message.
- **SC-003**: 100% of files exceeding 10 MB are rejected before any data transfer begins.
- **SC-004**: Zero temporary files are left on the host after any file send operation (success or failure).
- **SC-005**: The LLM correctly asks for confirmation before sending in 100% of cases where the user has not explicitly requested file delivery.

## Assumptions

- The Ubuntu Docker container is named `hatsume-space` and accessible via `docker cp`.
- The OneBot V11 protocol implementation supports `MessageSegment.file()` for group file sending.
- Users are interacting via QQ group chat (not private chat initially).
- Files sent are small to medium-sized artifacts (scripts, reports, configs, scan results).
- Docker is installed and accessible on the host running the bot.
- The bot has permission to upload group files in the target QQ groups.
