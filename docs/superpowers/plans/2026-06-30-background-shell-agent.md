# Background Shell Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `background_shell` built-in agent that executes interactive/time-consuming shell commands in the background with LLM-driven polling (sleep → check → decide) and mid-progress output injection.

**Architecture:** Three-file change. `prompts.py` gets a decision prompt constant. `infra.py` gets three functions for background process management (Popen + tmp file + incremental read + kill). `graph/agents.py` gets the `_run_background_shell` handler registered as `background_shell`, reusing existing `agent_allocate`, `inject_agent_notification`, `_AGENT_STATES`, and `NOTIFY_MARK` infrastructure zero-change.

**Tech Stack:** Python 3.12+, subprocess.Popen, asyncio, LangChain ChatOpenAI (code model), NoneBot2

## Global Constraints

- All existing agent infrastructure (`agent_allocate`, `inject_agent_notification`, `_AGENT_STATES`, `/agents` command) must remain unchanged
- Wait/poll intervals are in seconds, not minutes
- Mid-progress NOTIFY injection must include agent name and task description in the prompt
- `total_timeout` defaults to 300s when not specified by the chat agent
- Code model (`get_code_model`) is used for both task parsing and poll-cycle decisions
- Process stdout and stderr are merged into a single tmp file

---

### Task 1: `prompts.py` — Add `BACKGROUND_SHELL_DECISION_PROMPT`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py` (append at end)

**Interfaces:**
- Produces: `BACKGROUND_SHELL_DECISION_PROMPT: str` — system prompt for code model poll-cycle decisions

- [ ] **Step 1: Add the prompt constant at the end of prompts.py**

Add at the end of the file, before any trailing blank lines:

```python
# ---------------------------------------------------------------------------
# Background shell agent — decision prompt (used by graph/agents.py)
# ---------------------------------------------------------------------------
BACKGROUND_SHELL_DECISION_PROMPT = """\
你是一个后台 shell 进程监控器。你监控的命令当前正在运行中。

## 你的任务
根据命令的最新输出和用户提供的终止条件，判断下一步应该做什么。

## 决策选项（必须返回且仅返回以下之一，不要多余文字）

DONE
    命令已成功完成。输出满足终止条件。不需要继续监控。
    示例：输出中出现 "Authentication complete"、"Logged in as" 等成功标识。

KILL
    命令需要被立即终止。可能原因：
    - 输出明确显示失败/错误且无法自动恢复
    - 输出停滞（连续多次无变化）且不太可能自行恢复
    - 命令进入了不可自动退出的交互式提示（非预期的 stdin 等待）
    示例：输出显示 "Permission denied" 且反复重试。

CONTINUE:N
    命令仍在正常运行中，没有需要通知用户的信息。
    N 是你建议的下次检查等待秒数。
    根据任务性质估计：
    - 短期任务(编译、安装): 15-30s
    - 中期任务(下载、处理): 30-60s
    - 长期任务(认证等待、长计算): 60-120s
    - 不确定时: 30s
    示例：CONTINUE:30

NOTIFY:N
    命令输出包含用户需要【立即看到并可能行动】的信息。
    触发条件（满足任一即使用 NOTIFY）：
    - 输出包含 URL 链接，用户需要访问
    - 输出包含验证码、token、一次性密码
    - 输出包含关键状态变化（如 "waiting for authorization"、"press any key"）
    - 输出包含需要用户决策的问题
    N 是通知后的下次检查等待秒数。
    ⚠️ 重要：只有输出确实需要用户立即关注时才使用 NOTIFY。
    如果只是进度百分比、日志行、普通状态信息 → 请使用 CONTINUE。
    示例：NOTIFY:60

## 注意事项
- 如果输出为空或无新变化且进程仍在运行，使用 CONTINUE 而非 KILL。
- 如果进程已经退出（poll() 返回非 None），根据输出判断 DONE 或 KILL。
- 不要因为等待时间长就主动 KILL，除非有明确的失败信号。"""
```

- [ ] **Step 2: Verify the module still imports correctly**

Run: `python -c "from hatsume.plugins.hatsume_plugin import prompts; print(type(prompts.BACKGROUND_SHELL_DECISION_PROMPT))"`

Expected: `<class 'str'>` and non-empty content

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py
git commit -m "feat: add BACKGROUND_SHELL_DECISION_PROMPT for background_shell agent

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `infra.py` — Background process management functions

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py` (append three functions at end)
- Create: `tests/test_background_shell_infra.py`

**Interfaces:**
- Produces:
  - `start_background_cmd(code: str, proc_id: str) -> Path` — spawns Docker bash process, stdout+stderr → tmp file, returns tmp path
  - `read_background_output(tmp_path: Path, offset: int) -> tuple[str, int]` — reads new content from tmp file since offset, returns (new_content, new_offset)
  - `kill_background_cmd(proc_id: str) -> str | None` — terminates process, cleans up tmp file, returns remaining unread output
- Imports needed (added to existing infra.py imports): `tempfile`

- [ ] **Step 1: Write failing tests for `read_background_output` and `kill_background_cmd`**

Create `tests/test_background_shell_infra.py`:

```python
"""Tests for infra.py background process functions.
start_background_cmd is tested indirectly via the agent handler test
since it requires a running Docker container.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# -----------------------------------------------------------------------
# read_background_output
# -----------------------------------------------------------------------


class TestReadBackgroundOutput:
    """Tests for read_background_output() — incremental file reading."""

    def test_reads_new_content_from_offset_zero(self):
        """Reads all content when offset is 0."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        tmp.write_text("line 1\nline 2\nline 3\n")

        content, new_offset = read_background_output(tmp, 0)
        assert content == "line 1\nline 2\nline 3\n"
        assert new_offset == len("line 1\nline 2\nline 3\n")

        tmp.unlink()

    def test_reads_incremental_from_offset(self):
        """Reads only content after the given offset."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        full = "first chunk\nsecond chunk\n"
        tmp.write_text(full)

        # First read
        content1, offset1 = read_background_output(tmp, 0)
        assert content1 == full
        first_len = len("first chunk\n")

        # Append more content (simulate process writing more)
        tmp.write_text(full + "third chunk\n")

        # Second read from previous offset
        content2, offset2 = read_background_output(tmp, offset1)
        assert content2 == "third chunk\n"
        assert offset2 == len(full + "third chunk\n")

        tmp.unlink()

    def test_returns_empty_when_no_new_content(self):
        """Returns empty string and same offset when no new content exists."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        tmp.write_text("static content\n")

        content1, offset1 = read_background_output(tmp, 0)
        content2, offset2 = read_background_output(tmp, offset1)
        assert content2 == ""
        assert offset2 == offset1

        tmp.unlink()

    def test_returns_empty_for_missing_file(self):
        """Returns empty string when tmp file does not exist."""
        from hatsume.plugins.hatsume_plugin.infra import read_background_output

        content, offset = read_background_output(Path("/nonexistent/path.log"), 0)
        assert content == ""
        assert offset == 0  # offset unchanged


# -----------------------------------------------------------------------
# kill_background_cmd
# -----------------------------------------------------------------------


class TestKillBackgroundCmd:
    """Tests for kill_background_cmd() — process termination and cleanup."""

    def test_kills_running_process_and_cleans_up(self):
        """kill_background_cmd terminates the process, removes tmp file, returns output."""
        import time
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_procs,
            kill_background_cmd,
        )

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        tmp.write_text("process output\n")

        # Start a long-running process
        proc = subprocess.Popen(
            ["sleep", "60"],
            stdout=open(str(tmp), "w"),
            stderr=subprocess.STDOUT,
        )
        proc_id = "test_proc_1"
        _background_procs[proc_id] = (proc, tmp)

        remaining = kill_background_cmd(proc_id)

        # Process should be dead
        assert proc.poll() is not None
        # Tmp file should be cleaned up
        assert not tmp.exists()
        # Remaining output should be read
        assert "process output" in (remaining or "")

    def test_returns_none_for_unknown_proc_id(self):
        """Returns None when proc_id is not in _background_procs."""
        from hatsume.plugins.hatsume_plugin.infra import kill_background_cmd

        result = kill_background_cmd("nonexistent_proc")
        assert result is None

    def test_removes_entry_from_background_procs(self):
        """After kill_background_cmd, the proc_id is removed from the dict."""
        import time
        from hatsume.plugins.hatsume_plugin.infra import (
            _background_procs,
            kill_background_cmd,
        )

        tmp = Path(tempfile.mkstemp(suffix=".log")[1])
        proc = subprocess.Popen(
            ["sleep", "60"],
            stdout=open(str(tmp), "w"),
            stderr=subprocess.STDOUT,
        )
        proc_id = "test_proc_2"
        _background_procs[proc_id] = (proc, tmp)

        assert proc_id in _background_procs
        kill_background_cmd(proc_id)
        assert proc_id not in _background_procs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background_shell_infra.py -v`
Expected: FAIL — `read_background_output` and `kill_background_cmd` not defined

- [ ] **Step 3: Add `import tempfile` to infra.py imports**

In `hatsume/plugins/hatsume-plugin/infra.py`, add `import tempfile` after the existing `import subprocess` line:

```python
import subprocess
import tempfile
from pathlib import Path
```

- [ ] **Step 4: Implement `read_background_output` and `_background_procs` dict in `infra.py`**

Append after existing functions, before the last section divider:

```python

# ===========================================================================
# Background process management (used by background_shell agent)
# ===========================================================================
_background_procs: dict[str, tuple[subprocess.Popen, Path]] = {}


def read_background_output(tmp_path: Path, offset: int) -> tuple[str, int]:
    """Read new output from a background process tmp file since last read.

    Args:
        tmp_path: Path to the tmp log file.
        offset: Byte offset from which to start reading.

    Returns:
        (new_content_since_offset, new_total_offset).
        If the file doesn't exist, returns ("", offset).
    """
    if not tmp_path.exists():
        return ("", offset)
    try:
        with open(tmp_path, "r") as f:
            f.seek(offset)
            content = f.read()
        return (content, offset + len(content))
    except Exception:
        return ("", offset)
```

- [ ] **Step 5: Run `read_background_output` tests to verify they pass**

Run: `python -m pytest tests/test_background_shell_infra.py::TestReadBackgroundOutput -v`
Expected: 4 PASS

- [ ] **Step 6: Implement `kill_background_cmd` in `infra.py`**

Append after `read_background_output`:

```python

def kill_background_cmd(proc_id: str) -> str | None:
    """Terminate a background process and clean up its tmp file.

    Args:
        proc_id: The identifier used when the process was started.

    Returns:
        Any remaining unread output from the tmp file, or None if the
        proc_id was not found (already cleaned up).
    """
    entry = _background_procs.pop(proc_id, None)
    if entry is None:
        return None

    proc, tmp = entry
    remaining = ""

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass

    # Read any remaining output before cleanup
    try:
        if tmp.exists():
            remaining = tmp.read_text()
    except Exception:
        pass

    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass

    return remaining
```

- [ ] **Step 5b: Implement `start_background_cmd` in `infra.py`**

Append after `_background_procs` dict and before `read_background_output`:

```python

def start_background_cmd(code: str, proc_id: str) -> Path:
    """Spawn a background bash process in the Docker sandbox.

    stdout and stderr are merged and redirected to a tmp file.
    Docker container must already be running (ensure_container_running
    should be called before invoking shell_executor flows; for
    background_shell agent this is handled by the existing flow).

    Args:
        code: The shell script/command to execute.
        proc_id: Unique identifier for lifecycle management.

    Returns:
        Path to the tmp file where process output is written.
        Caller is responsible for cleanup via kill_background_cmd().
    """
    SOURCE_BASHRC = "source ~/.bashrc"
    script_path = Path(DOCKER_ENV_PATH, "script.sh").absolute()
    script_path.write_text(SOURCE_BASHRC + "\n" + code)

    tmp = Path(tempfile.mkstemp(prefix="hatsume-bg-", suffix=".log")[1])
    proc = subprocess.Popen(
        ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh"), "--cmd"],
        cwd=DOCKER_ENV_PATH,
        stdout=open(str(tmp), "w"),
        stderr=subprocess.STDOUT,
    )
    _background_procs[proc_id] = (proc, tmp)
    return tmp
```

> **Note:** `start_background_cmd` requires a running Docker container, so it is tested indirectly via the agent handler test in Task 3 (which mocks it). The Docker dependency is identical to the existing `run_cmd` function.

- [ ] **Step 7: Run `kill_background_cmd` tests to verify they pass**

Run: `python -m pytest tests/test_background_shell_infra.py::TestKillBackgroundCmd -v`
Expected: 3 PASS

- [ ] **Step 8: Run all infra tests**

Run: `python -m pytest tests/test_background_shell_infra.py -v`
Expected: 7 PASS

- [ ] **Step 9: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py tests/test_background_shell_infra.py
git commit -m "feat: add background process management functions to infra.py

- start_background_cmd: spawn Docker bash process with stdout→tmp file
- read_background_output: incremental read from tmp file with offset tracking
- kill_background_cmd: terminate process and clean up tmp file

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `graph/agents.py` — Register `background_shell` agent

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/agents.py` (add `_run_background_shell` handler + `register_agent` call)
- Create: `tests/test_background_shell_agent.py`

**Interfaces:**
- Consumes:
  - `BACKGROUND_SHELL_DECISION_PROMPT` from `..prompts` (Task 1)
  - `start_background_cmd`, `read_background_output`, `kill_background_cmd`, `_background_procs` from `..infra` (Task 2)
  - `inject_agent_notification`, `NOTIFY_MARK` from `.ai`
  - `_agent_notification_callback`, `_current_group_id` from `.tools`
  - `set_agent_state` from current module
  - `get_code_model` from `..models`
- Produces: `background_shell` agent registered in `AGENT_REGISTRY` with handler `_run_background_shell(task: str, user_id: int) -> str`

- [ ] **Step 1: Write failing tests for the agent handler**

Create `tests/test_background_shell_agent.py`:

```python
"""Tests for background_shell agent handler."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy():
    """Ensure hatsume.plugins.hatsume_plugin package hierarchy exists."""
    packages = [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]
    for name, path in packages:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias

    # Stub nonebot
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adap_name = "nonebot.adapters"
    if adap_name not in sys.modules:
        adap = types.ModuleType(adap_name)
        adap.__path__ = []
        sys.modules[adap_name] = adap
    if not hasattr(sys.modules[adap_name], "Bot"):
        sys.modules[adap_name].Bot = type("Bot", (), {})
    onebot_name = "nonebot.adapters.onebot"
    if onebot_name not in sys.modules:
        ob = types.ModuleType(onebot_name)
        ob.__path__ = []
        sys.modules[onebot_name] = ob
    v11_name = "nonebot.adapters.onebot.v11"
    if v11_name not in sys.modules:
        v11 = types.ModuleType(v11_name)
        v11.Message = type("Message", (), {})
        v11.MessageSegment = types.SimpleNamespace(
            text=lambda s: s, image=lambda *a, **kw: None
        )
        v11.GroupMessageEvent = type("GroupMessageEvent", (), {})
        sys.modules[v11_name] = v11


_setup_package_hierarchy()


# ---------------------------------------------------------------------------
# Helpers — mock the agent's dependencies
# ---------------------------------------------------------------------------

def _make_mock_code_model(responses: list[str]):
    """Return a mock code model that returns responses in sequence.
    Each response is a string like 'DONE', 'CONTINUE:30', etc.
    The first response is used for the parse (JSON), the rest for decisions.
    """
    call_count = [0]

    class MockResponse:
        def __init__(self, content):
            self.content = content

    async def mock_ainvoke(messages):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return {"messages": [MockResponse(responses[idx])]}
        return {"messages": [MockResponse("DONE")]}

    mock = types.SimpleNamespace(ainvoke=mock_ainvoke)
    return mock


def _make_mock_code_model_raw(content: str):
    """Return a mock that always returns the same content."""
    class MockResponse:
        def __init__(self, c):
            self.content = c

    async def mock_ainvoke(messages):
        return {"messages": [MockResponse(content)]}

    return types.SimpleNamespace(ainvoke=mock_ainvoke)


# ---------------------------------------------------------------------------
# Test: agent is registered
# ---------------------------------------------------------------------------

class TestBackgroundShellRegistration:
    """background_shell agent is correctly registered in AGENT_REGISTRY."""

    def test_agent_is_registered(self):
        """After importing agents module, background_shell is in the registry."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
            get_agent_list,
            get_agent_handler,
        )

        agent_names = [a["name"] for a in get_agent_list()]
        assert "background_shell" in agent_names, (
            f"background_shell not found in: {agent_names}"
        )

        handler = get_agent_handler("background_shell")
        assert handler is not None
        assert callable(handler)

    def test_agent_description_is_non_empty(self):
        """background_shell has a non-empty description string."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            AGENT_REGISTRY,
        )

        info = AGENT_REGISTRY.get("background_shell")
        assert info is not None, "background_shell not registered"
        assert isinstance(info.get("description"), str)
        assert len(info["description"]) > 10


# ---------------------------------------------------------------------------
# Test: parse task
# ---------------------------------------------------------------------------

class TestBackgroundShellParseTask:
    """The handler parses task description into {cmd, description, total_timeout}."""

    def test_parses_minimal_task_with_default_timeout(self):
        """When only cmd is given, description defaults to task, timeout to 300."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        # Inject mock code model that returns parse JSON
        parse_json = json.dumps({
            "cmd": "echo hello",
            "description": "prints hello",
            "total_timeout": 300,
        })

        # We need to patch get_code_model to return our mock
        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model_raw(parse_json),
        ):
            # Also prevent the actual Docker call and loop
            with patch(
                "hatsume.plugins.hatsume_plugin.graph.agents.start_background_cmd"
            ) as mock_start:
                mock_tmp = Path("/tmp/test_bg.log")
                mock_tmp.write_text("output")
                mock_start.return_value = mock_tmp

                with patch(
                    "hatsume.plugins.hatsume_plugin.graph.agents.read_background_output",
                    return_value=("DONE output", 100),
                ):
                    with patch(
                        "hatsume.plugins.hatsume_plugin.graph.agents.kill_background_cmd",
                        return_value=None,
                    ):
                        with patch(
                            "hatsume.plugins.hatsume_plugin.graph.agents._background_procs",
                            {"test": (MagicMock(), mock_tmp)},
                        ):
                            # Run with a short timeout to avoid actual sleep
                            result = asyncio.run(
                                asyncio.wait_for(
                                    _run_background_shell("echo hello", 123),
                                    timeout=2.0,
                                )
                            )

        assert "echo" in result or "hello" in result or "任务" in result
        # Clean up
        if mock_tmp.exists():
            mock_tmp.unlink()

    def test_parse_failure_returns_error(self):
        """When code model returns invalid JSON, handler returns error message."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model_raw("not valid json {{{"),
        ):
            result = asyncio.run(_run_background_shell("bad task", 123))

        assert "failed to parse" in result.lower()

    def test_empty_cmd_returns_error(self):
        """When parsed cmd is empty, handler returns an error."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        parse_json = json.dumps({
            "cmd": "",
            "description": "nothing to run",
            "total_timeout": 300,
        })

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model_raw(parse_json),
        ):
            result = asyncio.run(_run_background_shell("empty cmd", 123))

        assert "no command" in result.lower()


# ---------------------------------------------------------------------------
# Test: decision loop
# ---------------------------------------------------------------------------

class TestBackgroundShellDecisionLoop:
    """The poll loop makes correct decisions based on code model responses."""

    def test_done_decision_stops_loop(self):
        """When code model returns DONE, the loop breaks and returns final result."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        parse_json = json.dumps({
            "cmd": "echo done",
            "description": "prints done and exits",
            "total_timeout": 300,
        })

        response_seq = [
            parse_json,  # parse call
            "DONE",       # first poll decision
        ]

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model(response_seq),
        ):
            with patch(
                "hatsume.plugins.hatsume_plugin.graph.agents.start_background_cmd"
            ) as mock_start:
                mock_tmp = Path("/tmp/test_done.log")
                mock_tmp.write_text("finished successfully")
                mock_start.return_value = mock_tmp

                with patch(
                    "hatsume.plugins.hatsume_plugin.graph.agents.read_background_output",
                    return_value=("finished successfully", 100),
                ):
                    with patch(
                        "hatsume.plugins.hatsume_plugin.graph.agents.kill_background_cmd",
                    ) as mock_kill:
                        with patch(
                            "hatsume.plugins.hatsume_plugin.graph.agents._background_procs",
                            {"test": (MagicMock(), mock_tmp)},
                        ):
                            result = asyncio.run(
                                asyncio.wait_for(
                                    _run_background_shell("echo done", 123),
                                    timeout=2.0,
                                )
                            )

        assert "成功完成" in result or "已结束" in result
        # kill_background_cmd should NOT be called for DONE
        mock_kill.assert_not_called()
        if mock_tmp.exists():
            mock_tmp.unlink()

    def test_continue_decision_loops(self):
        """CONTINUE:N causes a re-poll after N seconds."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        parse_json = json.dumps({
            "cmd": "sleep 10",
            "description": "long running command",
            "total_timeout": 300,
        })

        # CONTINUE twice then DONE
        response_seq = [
            parse_json,
            "CONTINUE:1",   # first poll (use 1s for test speed)
            "CONTINUE:1",   # second poll
            "DONE",          # third poll
        ]

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model(response_seq),
        ):
            with patch(
                "hatsume.plugins.hatsume_plugin.graph.agents.start_background_cmd"
            ) as mock_start:
                mock_tmp = Path("/tmp/test_loop.log")
                mock_tmp.write_text("still running...")
                mock_start.return_value = mock_tmp

                read_calls = []

                def _read_side_effect(tmp_path, offset):
                    read_calls.append(1)
                    return ("still running...", 100)

                with patch(
                    "hatsume.plugins.hatsume_plugin.graph.agents.read_background_output",
                    side_effect=_read_side_effect,
                ):
                    with patch(
                        "hatsume.plugins.hatsume_plugin.graph.agents.kill_background_cmd",
                    ):
                        mock_proc = MagicMock()
                        mock_proc.poll.return_value = None  # process alive
                        with patch(
                            "hatsume.plugins.hatsume_plugin.graph.agents._background_procs",
                            {"test": (mock_proc, mock_tmp)},
                        ):
                            result = asyncio.run(
                                asyncio.wait_for(
                                    _run_background_shell("sleep 10", 123),
                                    timeout=5.0,
                                )
                            )

        # Should have at least 3 read calls (one per poll)
        assert len(read_calls) >= 3, f"Expected >=3 reads, got {len(read_calls)}"
        if mock_tmp.exists():
            mock_tmp.unlink()

    def test_notify_injects_mid_progress(self):
        """NOTIFY:N calls inject_agent_notification and continues the loop."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        parse_json = json.dumps({
            "cmd": "gh auth login --web",
            "description": "auth flow, terminate on success",
            "total_timeout": 300,
        })

        response_seq = [
            parse_json,
            "NOTIFY:1",   # poll: output has URL, notify user
            "DONE",        # next poll: auth complete
        ]

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model(response_seq),
        ):
            with patch(
                "hatsume.plugins.hatsume_plugin.graph.agents.start_background_cmd"
            ) as mock_start:
                mock_tmp = Path("/tmp/test_notify.log")
                mock_tmp.write_text("https://github.com/login/device\n")
                mock_start.return_value = mock_tmp

                with patch(
                    "hatsume.plugins.hatsume_plugin.graph.agents.read_background_output",
                    return_value=("https://github.com/login/device\n", 100),
                ):
                    with patch(
                        "hatsume.plugins.hatsume_plugin.graph.agents.kill_background_cmd",
                    ):
                        with patch(
                            "hatsume.plugins.hatsume_plugin.graph.agents.inject_agent_notification"
                        ) as mock_inject:
                            with patch(
                                "hatsume.plugins.hatsume_plugin.graph.agents._agent_notification_callback",
                                None,
                            ):
                                with patch(
                                    "hatsume.plugins.hatsume_plugin.graph.agents._current_group_id",
                                    0,
                                ):
                                    mock_proc = MagicMock()
                                    mock_proc.poll.return_value = None
                                    with patch(
                                        "hatsume.plugins.hatsume_plugin.graph.agents._background_procs",
                                        {"test": (mock_proc, mock_tmp)},
                                    ):
                                        result = asyncio.run(
                                            asyncio.wait_for(
                                                _run_background_shell(
                                                    "gh auth login", 123
                                                ),
                                                timeout=3.0,
                                            )
                                        )

        # inject_agent_notification should have been called (once for NOTIFY)
        assert mock_inject.call_count >= 1, (
            f"Expected inject_agent_notification to be called, got {mock_inject.call_count}"
        )
        if mock_tmp.exists():
            mock_tmp.unlink()

    def test_timeout_forces_termination(self):
        """When elapsed >= total_timeout, the process is killed and timeout reported."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        parse_json = json.dumps({
            "cmd": "sleep 999",
            "description": "very long command",
            "total_timeout": 1,  # 1 second timeout for fast test
        })

        response_seq = [
            parse_json,
            "CONTINUE:30",  # will be overridden by timeout
        ]

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model(response_seq),
        ):
            with patch(
                "hatsume.plugins.hatsume_plugin.graph.agents.start_background_cmd"
            ) as mock_start:
                mock_tmp = Path("/tmp/test_timeout.log")
                mock_tmp.write_text("running...")
                mock_start.return_value = mock_tmp

                with patch(
                    "hatsume.plugins.hatsume_plugin.graph.agents.read_background_output",
                    return_value=("running...", 100),
                ):
                    with patch(
                        "hatsume.plugins.hatsume_plugin.graph.agents.kill_background_cmd",
                    ) as mock_kill:
                        mock_kill.return_value = "killed output"
                        with patch(
                            "hatsume.plugins.hatsume_plugin.graph.agents._background_procs",
                            {"test": (MagicMock(), mock_tmp)},
                        ):
                            result = asyncio.run(
                                asyncio.wait_for(
                                    _run_background_shell("sleep 999", 123),
                                    timeout=5.0,
                                )
                            )

        assert "超时" in result, f"Expected timeout message, got: {result[:200]}"
        mock_kill.assert_called_once()
        if mock_tmp.exists():
            mock_tmp.unlink()

    def test_kill_decision_terminates_process(self):
        """KILL decision terminates the process immediately."""
        import json
        from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell

        parse_json = json.dumps({
            "cmd": "bad command",
            "description": "this will fail",
            "total_timeout": 300,
        })

        response_seq = [
            parse_json,
            "KILL",  # first poll: output shows failure
        ]

        with patch(
            "hatsume.plugins.hatsume_plugin.models.get_code_model",
            return_value=_make_mock_code_model(response_seq),
        ):
            with patch(
                "hatsume.plugins.hatsume_plugin.graph.agents.start_background_cmd"
            ) as mock_start:
                mock_tmp = Path("/tmp/test_kill.log")
                mock_tmp.write_text("Permission denied")
                mock_start.return_value = mock_tmp

                with patch(
                    "hatsume.plugins.hatsume_plugin.graph.agents.read_background_output",
                    return_value=("Permission denied", 100),
                ):
                    with patch(
                        "hatsume.plugins.hatsume_plugin.graph.agents.kill_background_cmd",
                    ) as mock_kill:
                        mock_kill.return_value = "remaining output"
                        with patch(
                            "hatsume.plugins.hatsume_plugin.graph.agents._background_procs",
                            {"test": (MagicMock(), mock_tmp)},
                        ):
                            result = asyncio.run(
                                asyncio.wait_for(
                                    _run_background_shell("bad command", 123),
                                    timeout=2.0,
                                )
                            )

        assert "终止" in result, f"Expected kill message, got: {result[:200]}"
        mock_kill.assert_called_once()
        if mock_tmp.exists():
            mock_tmp.unlink()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_background_shell_agent.py -v`
Expected: FAIL — `_run_background_shell` not defined or `background_shell` not in registry

- [ ] **Step 3: Implement `_run_background_shell` handler in `graph/agents.py`**

Add after the existing `_run_video_agent` handler (before the `register_agent` calls block):

```python

async def _run_background_shell(task: str, user_id: int) -> str:
    """background_shell agent: execute interactive/time-consuming commands.

    Uses the code model to:
    1. Parse the structured task into {cmd, description, total_timeout}
    2. Decide DONE/KILL/CONTINUE:N/NOTIFY:N at each poll cycle
    3. Inject mid-progress output to the main graph when needed

    The agent keeps the shell process alive across poll cycles and
    only terminates on DONE, KILL, or total_timeout exceeded.
    """
    import asyncio
    import json
    import re
    import time as _time
    import uuid

    from langchain.messages import HumanMessage, SystemMessage
    from ..models import get_code_model
    from ..prompts import BACKGROUND_SHELL_DECISION_PROMPT
    from ..infra import start_background_cmd, read_background_output, kill_background_cmd, _background_procs
    from .ai import inject_agent_notification, NOTIFY_MARK
    from .tools import _agent_notification_callback, _current_group_id

    # ── Step 1: Parse task with code model ──
    PARSE_PROMPT = """\
Extract the following from this task description. Return ONLY valid JSON, no extra text.

{
  "cmd": "<the full shell command to execute>",
  "description": "<what the command does and when to terminate>",
  "total_timeout": <timeout in seconds, integer>
}

Rules:
- cmd: the complete shell script/command code
- description: the termination condition description
- total_timeout: if a timeout is specified in the task, use it; otherwise default to 300
"""

    code_model = get_code_model()
    parse_response = await code_model.ainvoke([
        SystemMessage(PARSE_PROMPT),
        HumanMessage(task),
    ])

    raw = str(parse_response["messages"][-1].content)
    # Extract JSON block if wrapped in markdown
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        raw = match.group(0)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return f"background_shell: failed to parse task. Received: {raw[:500]}"

    cmd = parsed.get("cmd", "")
    description = parsed.get("description", task)
    total_timeout = int(parsed.get("total_timeout", 300))

    if not cmd.strip():
        return "background_shell: no command found in task."

    # ── Step 2: Spawn background process ──
    proc_id = f"bgshell_{uuid.uuid4().hex[:8]}"
    tmp = start_background_cmd(cmd, proc_id)

    # ── Step 3: Poll loop ──
    check_interval = 30  # initial default, seconds
    elapsed = 0
    offset = 0
    full_output = ""
    last_decision = ""

    set_agent_state(
        "background_shell",
        status="running",
        task=task[:200],
        user_id=user_id,
        started_at=_time.time(),
    )

    try:
        while True:
            await asyncio.sleep(check_interval)
            elapsed += check_interval

            new_output, offset = read_background_output(tmp, offset)
            full_output += new_output

            # Check if process is still alive
            proc_entry = _background_procs.get(proc_id)
            if proc_entry is None:
                # Process was killed externally
                last_decision = "KILL"
                break

            proc, _ = proc_entry
            proc_alive = proc.poll() is None

            # ── Timeout check ──
            if elapsed >= total_timeout:
                remaining = kill_background_cmd(proc_id)
                if remaining:
                    full_output += remaining
                last_decision = "TIMEOUT"
                break

            # ── Ask code model for decision ──
            decision_prompt = (
                f"## 任务描述\n{task[:500]}\n\n"
                f"## 终止条件\n{description}\n\n"
                f"## 命令最新输出 (自上次检查后新增)\n"
                + (new_output if new_output.strip() else "(无新输出)")
                + f"\n\n## 状态\n"
                f"- 已耗时: {elapsed}s / {total_timeout}s\n"
                f"- 进程状态: {'运行中' if proc_alive else '已结束'}\n"
            )

            decision_response = await code_model.ainvoke([
                SystemMessage(BACKGROUND_SHELL_DECISION_PROMPT),
                HumanMessage(decision_prompt),
            ])
            decision = str(decision_response["messages"][-1].content).strip().upper()

            # Parse decision: "DONE", "KILL", "CONTINUE:30", "NOTIFY:60"
            if decision.startswith("DONE"):
                last_decision = "DONE"
                break
            elif decision.startswith("KILL"):
                last_decision = "KILL"
                break
            elif decision.startswith("CONTINUE:"):
                try:
                    check_interval = int(decision.split(":")[1])
                except (IndexError, ValueError):
                    check_interval = 30
                last_decision = f"CONTINUE:{check_interval}"
            elif decision.startswith("NOTIFY:"):
                try:
                    check_interval = int(decision.split(":")[1])
                except (IndexError, ValueError):
                    check_interval = 30
                last_decision = f"NOTIFY:{check_interval}"

                # Inject mid-progress output to graph
                notify_msg = (
                    f"{NOTIFY_MARK}:{user_id}:background_shell\n"
                    f"(SYSTEM) Agent 'background_shell' 执行中的中间输出。\n"
                    f"任务：{task[:300]}\n"
                    f"Agent 仍在后台运行中（已耗时 {elapsed}s / {total_timeout}s）。\n"
                    f"以下是命令的当前输出，请告知用户：\n\n"
                    f"{new_output}"
                )
                inject_agent_notification(
                    user_id=user_id,
                    group_id=_current_group_id or 0,
                    agent_name="background_shell",
                    result=notify_msg,
                    start_conversation_cb=_agent_notification_callback,
                )
            else:
                # Unrecognized, default to continue
                last_decision = f"CONTINUE:{check_interval}"
    except asyncio.CancelledError:
        kill_background_cmd(proc_id)
        return "background_shell: cancelled."
    except Exception:
        import traceback
        traceback.print_exc()
        kill_background_cmd(proc_id)
        return "background_shell: internal error."

    # ── Step 4: Final cleanup and notification ──
    if last_decision == "DONE":
        result_text = "✅ 命令已成功完成。"
    elif last_decision == "KILL":
        remaining = kill_background_cmd(proc_id)
        if remaining:
            full_output += remaining
        result_text = "🛑 命令已被终止。"
    elif last_decision == "TIMEOUT":
        result_text = f"⏰ 命令已超时（{total_timeout}s）。"
    else:
        # Process ended on its own
        result_text = "命令已结束。"

    final_msg = (
        f"任务：{task[:300]}\n"
        f"总耗时：{elapsed}s\n"
        f"结果：{result_text}\n\n"
        f"完整输出：\n{full_output[:2000]}"
    )
    return final_msg
```

- [ ] **Step 4: Register the agent**

Add at the end of the existing `register_agent` calls block in `graph/agents.py`:

```python
register_agent(
    name="background_shell",
    description=(
        "Background Shell Agent，在后台执行交互式或耗时较长的 shell 命令。"
        "支持中间状态通知（如输出 auth URL 给用户），自动轮询检查，超时强制终止。"
        "适用于：认证流程、长时间编译、分批处理等场景。"
    ),
    handler=_run_background_shell,
)
```

- [ ] **Step 5: Run agent tests to verify they pass**

Run: `python -m pytest tests/test_background_shell_agent.py -v`
Expected: 8 PASS

- [ ] **Step 6: Run ALL tests to verify no regressions**

Run: `python -m pytest tests/ -xvs`
Expected: All existing tests still PASS, new tests PASS

- [ ] **Step 7: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/agents.py tests/test_background_shell_agent.py
git commit -m "feat: add background_shell agent for interactive/time-consuming commands

- Agent polls background process via tmp file with code-model decisions
- Supports DONE, KILL, CONTINUE:N, NOTIFY:N decision states
- Mid-progress NOTIFY injects output to main graph without stopping agent
- total_timeout with forced termination, default 300s
- Reuses existing agent_allocate, inject_agent_notification, _AGENT_STATES

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Integration verification

**Files:**
- None (verification only)

**Interfaces:**
- Consumes: All outputs from Tasks 1-3

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass, including existing and new tests

- [ ] **Step 2: Verify agent appears in agent list**

Run: `python -c "
from hatsume.plugins.hatsume_plugin.graph.agents import get_agent_list
names = [a['name'] for a in get_agent_list()]
assert 'background_shell' in names, f'Agent not found: {names}'
print('All agents:', names)
print('background_shell registered OK')
"`

Expected: `background_shell registered OK`

- [ ] **Step 3: Verify imports resolve without circular dependencies**

Run: `python -c "
from hatsume.plugins.hatsume_plugin.graph.agents import _run_background_shell, get_agent_handler
from hatsume.plugins.hatsume_plugin.infra import start_background_cmd, read_background_output, kill_background_cmd
from hatsume.plugins.hatsume_plugin.prompts import BACKGROUND_SHELL_DECISION_PROMPT
print('All imports OK')
"`

Expected: `All imports OK`

- [ ] **Step 4: Final commit (if any test fixes were needed)**

```bash
git add -A .
git commit -m "chore: integration verification for background_shell agent

Co-Authored-By: Claude <noreply@anthropic.com>"
```
