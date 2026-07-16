# Design: Send File from Kali Docker Container Tool

**Date**: 2026-06-25
**Status**: Approved

## Summary

Add a new `send_file` LangChain tool that allows the bot to extract files from the running Kali Docker container and send them to the QQ group chat as group file attachments. This enables the LLM to deliver script outputs, scan results, reports, generated artifacts, and other binary/text files to users.

## Motivation

Currently the bot can only send text, images, and video back to QQ chat. When a user asks the bot to write a script, generate a report, produce a compressed archive, or otherwise create a file artifact inside the Kali sandbox, there is no way to deliver that file to the user. The `shell_executor` tool can only return stdout/stderr text, making it impossible to send binary files or large text files that exceed the output truncation limit.

## Scope

**In scope:**
- Extract files from the Kali container (`kali-cmd-runner`) `/work/` directory
- Send files to QQ group chat using OneBot V11 `MessageSegment.file()`
- Path validation to prevent directory traversal
- File size limit enforcement (10 MB)
- Proper error messages returned to LLM
- Automatic temporary file cleanup

**Out of scope:**
- Sending files to private chats (only group chat supported initially, matches existing tool patterns)
- Sending files from outside the container (host filesystem)
- Uploading files *into* the container (direction is container → chat only)
- File compression or splitting (files over 10 MB are simply rejected)

## Design

### Architecture

A new independent module `file_transfer.py` encapsulates all container file extraction and QQ sending logic, keeping concerns separated from existing shell execution (`infra.py`) and tool definitions (`tools.py`).

```
┌─────────────────────────────────────────────────────────────┐
│                     LLM (chat_agent)                        │
└─────────────┬───────────────────────────────────────────────┘
              │ calls send_file(file_path, display_name)
              ▼
┌─────────────────────────────────────────────────────────────┐
│               tools.py - @tool send_file                    │
│  Thin wrapper that delegates to file_transfer module        │
└─────────────┬───────────────────────────────────────────────┘
              │ calls send_file_to_chat()
              ▼
┌─────────────────────────────────────────────────────────────┐
│            file_transfer.py - Core Logic                    │
│  ┌────────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │ Path Validation│  │ Size Check   │  │ Docker CP       │  │
│  │ (prevent ../)  │  │ (<= 10 MB)   │  │ Extract to temp │  │
│  └────────────────┘  └──────────────┘  └────────┬────────┘  │
│                                                  │          │
│  ┌────────────────┐  ┌──────────────┐             │          │
│  │ Rename (disp)  │  │  Cleanup     │◀────────────┘          │
│  │ Send via       │  │ (tempfile)   │                        │
│  │ _ai_answer()   │  │              │                        │
│  └────────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
              │ MessageSegment.file()
              ▼
┌─────────────────────────────────────────────────────────────┐
│                    QQ Group Chat                            │
└─────────────────────────────────────────────────────────────┘
```

### Files Changed

| File | Change Type | Purpose |
|------|-------------|---------|
| `hatsume/plugins/hatsume-plugin/file_transfer.py` | New | Core file transfer logic module |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Modify | Add `send_file` @tool definition |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Modify | Import and register `send_file` tool |
| `hatsume/plugins/hatsume-plugin/prompts.py` | Modify | Add tool usage rules to system prompt |
| `hatsume/plugins/hatsume-plugin/config.py` | Modify | Add new configuration constants |
| `tests/test_file_transfer.py` | New | Unit tests |

`infra.py` remains unchanged — all docker interaction for file transfer is contained within the new module.

### file_transfer.py Module Interface

```python
"""File transfer from Kali Docker container to QQ chat.

This module handles extracting files from the kali-cmd-runner container,
validating paths, enforcing size limits, and sending files via OneBot V11.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from collections.abc import Callable, Coroutine

# ---- Constants (from config.py, re-exported here) ----
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTAINER_PREFIX = Path("/work/")
CONTAINER_NAME = "kali-cmd-runner"
DOCKER_CP_TIMEOUT = 30  # seconds
TMP_PREFIX = "hatsume-send-"


def validate_container_path(file_path: str) -> Path:
    """Validate and normalize a container file path.

    - Relative paths are resolved against /work/
    - Absolute paths must start with /work/
    - Resolved path must not escape /work/ (blocks ../../ traversal)
    - Symlinks are not followed for security; if the target is a symlink,
      the link target is also validated to be within /work/.

    Returns normalized absolute Path.
    Raises ValueError on invalid paths.
    """
    ...


def get_container_file_size(container_path: Path) -> int:
    """Get file size in bytes via `docker exec stat -c%s <path>`.

    Raises FileNotFoundError if file doesn't exist.
    Raises RuntimeError on docker command failure.
    """
    ...


def is_container_path_a_file(container_path: Path) -> bool:
    """Check if path points to a regular file (not directory/device/socket).

    Uses `docker exec test -f <path>`.
    """
    ...


def resolve_symlink_target(container_path: Path) -> Path:
    """Resolve symlink target inside container using readlink -f.

    Returns the final resolved path.
    """
    ...


async def send_file_to_chat(
    file_path: str,
    display_name: str | None,
    ai_answer: Callable[..., Coroutine],
) -> str:
    """Full pipeline: validate → check → copy → send → cleanup.

    Args:
        file_path: Path inside container (relative to /work or absolute /work/... path)
        display_name: Optional filename override for the sent file
        ai_answer: Async callback to send MessageSegment to QQ chat (injected from tools.py globals)

    Returns:
        Status message string describing success or error for the LLM.
    """
    ...
```

### Data Flow

1. **LLM decides to send a file** — Only after the user explicitly requests a file output; otherwise the LLM asks for confirmation first (enforced via prompt).
2. **Tool invocation** — LLM calls `send_file(file_path="report.pdf")` or `send_file(file_path="results/scan.txt", display_name="port-scan-result.txt")`.
3. **Path validation** — `validate_container_path()` normalizes the path and verifies it stays within `/work/`.
4. **File existence and type check** — Verify the file exists and is a regular file (not directory/device). If it is a symlink, resolve the target and re-validate.
5. **Size check** — `get_container_file_size()` queries the size; rejects files > 10 MB.
6. **Extract from container** — Create a temporary directory via `tempfile.TemporaryDirectory()`, run `docker cp kali-cmd-runner:<path> <tmp_dir>/`.
7. **Optional rename** — If `display_name` is provided, rename the file in the temp directory.
8. **Send to QQ** — Construct `MessageSegment.file(file=host_path, name=display_name or original_name)` and call `await ai_answer(segment)`.
9. **Cleanup** — `TemporaryDirectory` context manager exits, automatically deleting the temporary directory and all contents.
10. **Return result** — Return a status message like `✅ 文件 report.pdf (2.3 MB) 已发送到群文件` to the LLM.

### tools.py Integration

```python
@tool
async def send_file(file_path: str, display_name: str = "") -> str:
    """从 Kali 容器中提取文件并发送到 QQ 群文件。

    使用规则：
    - 【重要】只有用户明确要求"发文件"、"把xxx给我"、"导出文件"、"发脚本"等明确要求
      产出文件的场景才能调用本工具。
    - 如果用户没有明确要求发送文件，必须先在文本回复中询问"需要我把xxx文件发到群里吗？"，
      等用户确认后再调用。
    - 文件必须位于容器的 /work/ 目录下（shell_executor 默认工作目录）。
    - 支持相对路径（相对于/work）和以/work开头的绝对路径。
    - 文件最大支持 10 MB，超过会直接拒绝发送。

    Args:
        file_path: 容器内文件路径，相对路径相对于/work目录
        display_name: （可选）发送时显示的文件名，不填则使用原文件名
    """
    from .file_transfer import send_file_to_chat
    return await send_file_to_chat(
        file_path=file_path,
        display_name=display_name or None,
        ai_answer=_ai_answer,
    )
```

The tool is async (matches `generate_image`, `capture_html_shot` pattern) and does not use `return_direct=True` — the LLM still generates a text reply after sending the file, which is consistent with how `generate_image` works.

### Configuration Constants (config.py)

```python
# ---- File send tool (send_file) ----
SEND_FILE_MAX_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
SEND_FILE_ALLOWED_PREFIX: str = "/work/"
SEND_FILE_CONTAINER_NAME: str = "kali-cmd-runner"
SEND_FILE_DOCKER_CP_TIMEOUT: int = 30  # seconds
SEND_FILE_TMP_PREFIX: str = "hatsume-send-"
```

### Security

Multiple layers of protection prevent abuse:

1. **Path normalization with prefix check**: After resolving `.` and `..` components, the path must start with `/work/`. This blocks `../../etc/passwd` style traversal.
2. **Symlink validation**: If the target is a symlink, `readlink -f` resolves the ultimate target, which must also be within `/work/`. Prevents symlink-based escapes.
3. **File type check**: `test -f` ensures we send regular files only, not directories, device files, sockets, or FIFOs.
4. **Size pre-check**: File size is queried via `stat -c%s` before attempting `docker cp`, so oversize files are rejected without consuming bandwidth.
5. **Docker cp timeout**: 30-second timeout on the subprocess prevents hanging on network or I/O issues.
6. **Automatic temp file cleanup**: `tempfile.TemporaryDirectory()` guarantees cleanup even on exceptions; no orphan files accumulate.
7. **Container name is hardcoded and validated**: The fixed container name `kali-cmd-runner` is not user-controlled.

### Error Handling

All errors are returned as user-facing (LLM-facing) strings rather than raising exceptions, consistent with existing tool patterns:

| Scenario | Message returned to LLM |
|----------|------------------------|
| Path traversal attempt | `❌ 错误：只允许访问 /work/ 目录下的文件，非法路径已被拒绝` |
| Absolute path outside /work | `❌ 错误：只允许发送容器内 /work/ 目录下的文件，当前路径: {path}` |
| File not found | `❌ 错误：容器内未找到文件 {name}，请检查路径是否正确` |
| Path is a directory | `❌ 错误：{name} 是一个目录，请指定具体文件路径` |
| File exceeds 10 MB | `❌ 错误：文件大小为 {size:.2f} MB，超过最大限制 10 MB，无法发送` |
| Container not running | `❌ 错误：Kali 容器未运行，请先执行一个命令启动容器` |
| Docker cp failure/timeout | `❌ 错误：文件提取失败，请检查文件是否存在或稍后重试` |

Success case:
```
✅ 文件 {display_name} ({size:.2f} MB) 已发送到群文件
```

### System Prompt Update (prompts.py)

Add to the tool rules section of the system prompt:

```
- **send_file**：从Kali容器发送文件到群文件。使用规则：
  (1) 只有用户明确要求"发文件"、"把xxx发出来"、"导出"、"给我脚本/文件"等明确要求产出文件的场景才能调用本工具。
  (2) 如果用户没有明确要求发送文件，**必须先在文本回复中询问**："需要我把xxx文件发到群里吗？"，得到用户确认后再调用。
  (3) 文件必须位于容器的 /work/ 目录下（shell_executor 默认工作目录）。
  (4) 支持相对路径（自动相对于/work）和 /work/ 开头的绝对路径。
  (5) 可以用 display_name 参数指定发送时显示的文件名。
  (6) 文件最大 10 MB，超过限制会直接拒绝发送。
```

### Testing

New test file: `tests/test_file_transfer.py`

Test cases:

1. **Path validation**
   - Relative path `"report.txt"` resolves to `/work/report.txt` ✓
   - Absolute path `/work/results/scan.pdf` passes ✓
   - Traversal `"../../etc/passwd"` raises ValueError ✓
   - Absolute outside root `/root/.ssh/id_rsa` raises ValueError ✓
   - Traversal with encoded/slashed variants all blocked ✓

2. **Size check**
   - File exactly 10 MB passes ✓
   - File 10 MB + 1 byte rejected with correct message ✓
   - `stat` command failure returns appropriate error ✓

3. **File type checks**
   - Directory path returns "is a directory" error ✓
   - Non-existent path returns "file not found" error ✓

4. **Tool registration**
   - `send_file` is importable from `graph.tools` ✓
   - `send_file` is present in the `chat_agent` tool list in `ai.py` ✓

5. **Integration (mocked)**
   - With docker subprocess and `_ai_answer` mocked, verify full happy path: validate → size check → docker cp called → MessageSegment.file constructed with correct path → ai_answer called → temp directory cleaned up after ✓
   - On docker cp failure, temp directory is still cleaned up ✓

All docker subprocess calls are mocked to avoid requiring a running Kali environment during testing.

## Out of Scope / Future Work

- Private chat file delivery (group chat only for initial implementation)
- Host filesystem file sending (container only)
- File upload into container
- Automatic compression for oversized files
- Progress indication for large file transfers
- Sending multiple files in one call
- File expiration or auto-delete from group files
