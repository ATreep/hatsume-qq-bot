# random_acg_photo Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-callable `random_acg_photo` tool that randomly selects and exports a photo from the Apple Photos "ACG" album into the Docker sandbox, returning the sandbox path so the existing `send_image` tool can send it to the user.

**Architecture:** The tool runs `osascript` on the macOS host to export a random photo from the "ACG" album to a temp directory, then uses `docker cp` to copy the file into the sandbox container with a timestamped filename. The sandbox absolute path is returned (no `file://` prefix). The existing `send_image` tool already handles `file://` paths — the LLM appends the prefix when calling it.

**Tech Stack:** Python 3.12+, `subprocess` (built-in), `osascript` (macOS built-in), `docker cp` (CLI), no new dependencies.

---

## File Structure

| Action | File |
|--------|------|
| Modify | `hatsume/plugins/hatsume-plugin/graph/tools.py` |
| Modify | `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` |
| Create | `tests/test_random_acg_photo.py` |

---

### Task 1: Add `random_acg_photo` tool function in `tools.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py` (insert new @tool function, ~80 lines)

**Interfaces:**
- Consumes: `ensure_container_running` (from `..infra`), `CONTAINER_NAME` (from `..config`)
- Produces: `async def random_acg_photo() -> str` — returns sandbox path like `/tmp/apple_photo_export_260711_143025.jpg` or Chinese error string

- [ ] **Step 1: Write the failing test**

Create `tests/test_random_acg_photo.py`:

```python
"""Tests for random_acg_photo tool."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"


def _load_tools_module():
    """Load graph/tools.py with all external dependencies stubbed."""
    for name in list(sys.modules):
        if name.startswith("hatsume") or name in (
            "nonebot", "nonebot.adapters", "nonebot.adapters.onebot",
            "nonebot.adapters.onebot.v11",
            "langchain", "langchain.messages", "langchain.agents",
            "langchain_core", "langchain_core.messages", "langchain_core.tools",
            "langchain_community", "langchain_community.tools",
            "langgraph", "langgraph.graph",
        ):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
        ("hatsume.plugins.hatsume-plugin.graph", base / "graph"),
        ("hatsume.plugins.hatsume-plugin.memory", base / "memory"),
        ("hatsume.plugins.hatsume-plugin.infra", base / "infra"),
    ]:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

    for dash_name, underscore_name in [
        ("hatsume.plugins.hatsume-plugin", "hatsume.plugins.hatsume_plugin"),
        ("hatsume.plugins.hatsume-plugin.graph", "hatsume.plugins.hatsume_plugin.graph"),
        ("hatsume.plugins.hatsume-plugin.memory", "hatsume.plugins.hatsume_plugin.memory"),
        ("hatsume.plugins.hatsume-plugin.infra", "hatsume.plugins.hatsume_plugin.infra"),
    ]:
        if underscore_name not in sys.modules and dash_name in sys.modules:
            alias = types.ModuleType(underscore_name)
            alias.__path__ = sys.modules[dash_name].__path__
            sys.modules[underscore_name] = alias

    for cfg_name in (
        "hatsume.plugins.hatsume_plugin.config",
        "hatsume.plugins.hatsume-plugin.config",
    ):
        if cfg_name not in sys.modules:
            cfg_mod = types.ModuleType(cfg_name)
            sys.modules[cfg_name] = cfg_mod
        else:
            cfg_mod = sys.modules[cfg_name]
        cfg_mod.AGENT_QQ_EMAIL = "test@qq.com"
        cfg_mod.BOT_QQ_ID = "12345"
        cfg_mod.DOCKER_ENV_PATH = Path("/tmp/test_docker")
        cfg_mod.SHELL_MAX_OUTPUT = 1000
        cfg_mod.SHELL_TIMEOUT = 10
        cfg_mod.CONTEXT_QUEUE_LEN = 20
        cfg_mod.CONTAINER_NAME = "hatsume-space"

    sys.modules["nonebot"] = types.ModuleType("nonebot")
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    sys.modules["nonebot.adapters"] = adapters_mod
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod

    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = type("Message", (), {})
    v11_mod.MessageSegment = types.SimpleNamespace(
        text=lambda s: s, image=lambda *a, **kw: None,
    )
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    nonebot_params = types.ModuleType("nonebot.params")
    nonebot_params.CommandArg = lambda: None
    sys.modules["nonebot.params"] = nonebot_params

    langchain_mod = types.ModuleType("langchain")
    langchain_mod.__path__ = []
    sys.modules["langchain"] = langchain_mod

    class _SystemMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "system"
    class _HumanMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "human"

    langchain_messages = types.ModuleType("langchain.messages")
    langchain_messages.SystemMessage = _SystemMessage
    langchain_messages.HumanMessage = _HumanMessage
    sys.modules["langchain.messages"] = langchain_messages

    langchain_agents = types.ModuleType("langchain.agents")
    langchain_agents.create_agent = lambda *a, **kw: None
    sys.modules["langchain.agents"] = langchain_agents

    langchain_core_mod = types.ModuleType("langchain_core")
    langchain_core_mod.__path__ = []
    sys.modules["langchain_core"] = langchain_core_mod
    langchain_core_messages = types.ModuleType("langchain_core.messages")
    sys.modules["langchain_core.messages"] = langchain_core_messages

    langchain_core_tools = types.ModuleType("langchain_core.tools")
    def _mock_tool(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f
    langchain_core_tools.tool = _mock_tool
    sys.modules["langchain_core.tools"] = langchain_core_tools

    langchain_community = types.ModuleType("langchain_community")
    langchain_community.__path__ = []
    sys.modules["langchain_community"] = langchain_community
    langchain_community_tools = types.ModuleType("langchain_community.tools")
    langchain_community_tools.DuckDuckGoSearchRun = type("DuckDuckGoSearchRun", (), {})
    sys.modules["langchain_community.tools"] = langchain_community_tools

    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    config_mod.DOCKER_ENV_PATH = "/tmp/test"
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    config_mod.BOT_QQ_ID = 1234567890
    config_mod.AGENT_QQ_EMAIL = "test@qq.com"
    config_mod.GIITHUB_ACCOUNT = "test-account"
    config_mod.GITHUB_REPO = "test/repo"
    config_mod.CONTEXT_QUEUE_LEN = 20
    config_mod.CONTAINER_NAME = "hatsume-space"
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.get_lite_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"))
    async def _mock_ainvoke(*a, **kw):
        return types.SimpleNamespace(content="ok")
    models_mod.get_code_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"),
        ainvoke=_mock_ainvoke,
    )
    models_mod.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
    models_mod.choose_image_model = lambda: "4"
    models_mod.generate_video_for = lambda *a, **kw: None
    models_mod.choose_video_model = lambda: "1.5"
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    utils_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
    utils_mod.get_qq_avatar_url = lambda qq_id: f"https://q.qlogo.cn/g?b=qq&nk={qq_id}&s=640"
    utils_mod.message_to_json = MagicMock(return_value='{"type":"text","text":"test"}')
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod

    infra_mod = sys.modules["hatsume.plugins.hatsume-plugin.infra"]
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.ensure_container_running = lambda *a, **kw: None
    infra_mod.delete_container = lambda *a, **kw: None
    async def _mock_render_html(*a, **kw):
        return b"fake_png_bytes"
    infra_mod.render_html_to_image = _mock_render_html

    memory_store_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.store")
    memory_store_mod.get_mem_list = lambda: []
    memory_store_mod.add_mem = lambda *a, **kw: None
    sys.modules["hatsume.plugins.hatsume-plugin.memory.store"] = memory_store_mod

    memory_retrieval_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.retrieval")
    memory_retrieval_mod.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.retrieval"] = memory_retrieval_mod

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.graph.tools", TOOLS_PATH)
    tools_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"] = tools_mod
    spec.loader.exec_module(tools_mod)
    return tools_mod


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------

class TestRandomAcgPhoto:
    """Tests for random_acg_photo tool."""

    def test_tool_exists(self):
        """random_acg_photo is defined as a callable on the tools module."""
        tools = _load_tools_module()
        assert hasattr(tools, "random_acg_photo")
        assert callable(tools.random_acg_photo)

    def test_success_returns_sandbox_path(self):
        """On success, returns a sandbox path matching the expected timestamp pattern."""
        tools = _load_tools_module()

        app_import_path = "hatsume.plugins.hatsume_plugin.graph.tools"

        with (
            patch("subprocess.run") as mock_run,
            patch("os.listdir") as mock_listdir,
            patch("os.path.isfile", return_value=True),
            patch("shutil.rmtree"),
            patch("os.makedirs"),
            patch(f"{app_import_path}.ensure_container_running") as mock_ensure,
        ):
            # First call (osascript): success
            # Second call (docker cp): success
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=b""),
                MagicMock(returncode=0, stdout=b""),
            ]
            mock_listdir.return_value = ["IMG_1234.jpg"]

            result = asyncio.run(tools.random_acg_photo())

            assert result.startswith("/tmp/apple_photo_export_")
            assert result.endswith(".jpg")
            assert mock_ensure.called

    def test_photos_app_not_running_returns_error(self):
        """When osascript fails with a Photos-related error, return Chinese error."""
        tools = _load_tools_module()

        app_import_path = "hatsume.plugins.hatsume_plugin.graph.tools"

        with (
            patch("subprocess.run") as mock_run,
            patch("shutil.rmtree"),
            patch(f"{app_import_path}.ensure_container_running"),
        ):
            # Simulate Photos not running — osascript returns non-zero with error
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = b"Application isn't running (-600)"
            mock_run.return_value = mock_result

            result = asyncio.run(tools.random_acg_photo())

            assert "错误" in result or "❌" in result

    def test_empty_album_returns_error(self):
        """When ACG album has no photos, return Chinese error."""
        tools = _load_tools_module()

        app_import_path = "hatsume.plugins.hatsume_plugin.graph.tools"

        with (
            patch("subprocess.run") as mock_run,
            patch("shutil.rmtree"),
            patch(f"{app_import_path}.ensure_container_running"),
        ):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = b"ALBUM_EMPTY"
            mock_run.return_value = mock_result

            result = asyncio.run(tools.random_acg_photo())

            assert "空" in result or "没有" in result or "无" in result

    def test_docker_cp_failure_returns_error(self):
        """When docker cp fails, return Chinese error."""
        tools = _load_tools_module()

        app_import_path = "hatsume.plugins.hatsume_plugin.graph.tools"

        with (
            patch("subprocess.run") as mock_run,
            patch("os.listdir") as mock_listdir,
            patch("os.path.isfile", return_value=True),
            patch("shutil.rmtree"),
            patch(f"{app_import_path}.ensure_container_running"),
        ):
            # First call (osascript): success
            # Second call (docker cp): failure
            call_results = [
                MagicMock(returncode=0, stdout=b""),
                MagicMock(returncode=1, stderr=b"Error: No such container"),
            ]
            mock_run.side_effect = call_results
            mock_listdir.return_value = ["photo.png"]

            result = asyncio.run(tools.random_acg_photo())

            assert "❌" in result
```

Run: `python -m pytest tests/test_random_acg_photo.py -xvs`
Expected: FAIL — `module 'hatsume.plugins.hatsume-plugin.graph.tools' has no attribute 'random_acg_photo'`

- [ ] **Step 2: Verify the test fails**

```bash
python -m pytest tests/test_random_acg_photo.py -xvs
```

Expected output includes: `AttributeError: ... has no attribute 'random_acg_photo'`

- [ ] **Step 3: Add `random_acg_photo` to `tools.py`**

Insert the following code **after** the `get_avatar` tool (after line ~234) and **before** the `send_image` tool (before line ~238):

```python
@tool
async def random_acg_photo() -> str:
    """
    从 Apple Photos 的 "ACG" 相簿中随机获取一张照片。

    照片会被导出并复制到沙盒容器中。返回沙盒内的绝对路径（不带 file:// 前缀）。
    获取到路径后，你必须调用 send_image 工具，并在路径前加上 "file://" 前缀来发送图片。

    ## 返回值示例：
    - 成功：/tmp/apple_photo_export_260711_143025.jpg
    - 失败：❌ 错误描述

    ## 使用场景：
    - 用户想要一张随机的 ACG 图片时
    - 用户提到想看"二次元"、"动漫"、"ACG" 图时
    """
    import os as _os
    import shutil as _shutil
    from datetime import datetime
    from ..config import CONTAINER_NAME

    _MACOS_TMP = "/tmp/hatsume_acg_export"

    # 1. Clean and recreate macOS temp export directory
    if _os.path.exists(_MACOS_TMP):
        _shutil.rmtree(_MACOS_TMP)
    _os.makedirs(_MACOS_TMP, exist_ok=True)

    # 2. AppleScript: query "ACG" album, pick random photo, export
    applescript = f'''
    try
        tell application "Photos"
            if not (exists album "ACG") then
                error "ALBUM_NOT_FOUND"
            end if
            set targetAlbum to album "ACG"
            set allPhotos to every media item of targetAlbum
            set photoCount to count of allPhotos
            if photoCount is 0 then
                error "ALBUM_EMPTY"
            end if
            set randomIndex to random number from 1 to photoCount
            set thePhoto to item randomIndex of allPhotos
            set exportDir to POSIX file "{_MACOS_TMP}"
            export {{thePhoto}} to exportDir with using originals
        end tell
    on error errMsg
        return "ERROR:" & errMsg
    end try
    '''

    result = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True,
        timeout=30,
    )

    stdout_text = result.stdout.decode("utf-8", errors="replace").strip()

    # Check for AppleScript-level errors
    if stdout_text.startswith("ERROR:"):
        err_msg = stdout_text[len("ERROR:"):].strip()
        if "ALBUM_NOT_FOUND" in err_msg:
            return "❌ 错误：未找到名为 'ACG' 的相簿。"
        if "ALBUM_EMPTY" in err_msg:
            return "❌ 错误：'ACG' 相簿中没有照片。"
        return f"❌ 错误：Photos 操作失败：{err_msg}"

    # Check for osascript process failure (Photos not running, permissions, etc.)
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        combined = (stdout_text + " " + stderr_text).strip()
        if "not running" in combined.lower() or "application isn't running" in combined.lower():
            return "❌ 错误：无法访问 Photos 应用，请确认 Photos.app 已打开并授权。"
        return f"❌ 错误：Photos 操作失败：{combined}"

    # 3. Find exported file
    exported = [
        f for f in _os.listdir(_MACOS_TMP)
        if _os.path.isfile(_os.path.join(_MACOS_TMP, f))
    ]
    if not exported:
        return "❌ 错误：照片导出失败，未找到导出文件。"

    host_file = _os.path.join(_MACOS_TMP, exported[0])
    _, ext = _os.path.splitext(exported[0])
    if not ext:
        ext = ".jpg"

    # 4. Ensure sandbox container is running
    ensure_container_running()

    # 5. Generate timestamped sandbox path and docker cp
    timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
    sandbox_name = f"apple_photo_export_{timestamp}{ext}"
    sandbox_path = f"/tmp/{sandbox_name}"

    cp_result = subprocess.run(
        ["docker", "cp", host_file, f"{CONTAINER_NAME}:{sandbox_path}"],
        capture_output=True,
        timeout=30,
    )
    if cp_result.returncode != 0:
        stderr = cp_result.stderr.decode("utf-8", errors="replace").strip()
        return f"❌ 错误：无法复制文件到沙盒：{stderr}"

    print(f"📷 [random_acg_photo] Exported {host_file} → sandbox {sandbox_path}")
    return sandbox_path
```

Note: `subprocess` and `ensure_container_running` are already imported at the top of `tools.py` (line 10 and line 24 respectively).

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_random_acg_photo.py -xvs
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_random_acg_photo.py hatsume/plugins/hatsume-plugin/graph/tools.py
git commit -m "feat: add random_acg_photo tool for Apple Photos ACG album access"
```

---

### Task 2: Register `random_acg_photo` in `ai.py` chat_agent tools list

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` (2 locations: import line + tools list)

**Interfaces:**
- Consumes: `random_acg_photo` from `..tools`
- Produces: `chat_agent` now includes `random_acg_photo` in its bound tools

- [ ] **Step 1: Add import**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, at line 31-38, add `random_acg_photo` to the import block:

Change:
```python
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    generate_image, generate_video, send_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_dispatch, respond_to_shell_prompt,
)
```

To:
```python
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    generate_image, generate_video, send_image,
    reset_capture_flag, get_avatar, random_acg_photo,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_dispatch, respond_to_shell_prompt,
)
```

- [ ] **Step 2: Add to tools list**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, at lines 511-518, add `random_acg_photo` to the `chat_agent` tools list:

Change:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory,
         generate_image, generate_video, send_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_dispatch, respond_to_shell_prompt],
        system_prompt=sys_prompt,
    )
```

To:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory,
         generate_image, generate_video, send_image, get_avatar, random_acg_photo,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_dispatch, respond_to_shell_prompt],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 3: Run existing tests to verify no regressions**

```bash
python -m pytest tests/ -x --timeout=60
```

Expected: All existing tests still pass

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: register random_acg_photo in chat_agent tools list"
```
