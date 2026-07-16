# Background Shell Stdin Injection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stdin injection capability to the background_shell agent so interactive commands (sudo, auth, confirmations) can receive input from the chat agent without being killed.

**Architecture:** A `respond_to_shell_prompt` tool bridges the chat agent (LangGraph) to the bg shell agent's poll loop via `asyncio.Queue`. When the process needs stdin, the bg shell agent notifies the chat, waits on the queue (with code-model-determined timeout), then the code model mediates raw chat input into the actual stdin bytes written to the process.

**Tech Stack:** Python 3.12+, asyncio, subprocess.PIPE, LangChain @tool, LangGraph MessagesState

**Spec:** [bg-shell-stdin-injection-design](../specs/2026-06-30-bg-shell-stdin-injection-design.md)

## Global Constraints

- Python 3.12+ with `from __future__ import annotations`
- ruff lint rules from `pyproject.toml`
- snake_case functions, UPPER_CASE constants, PascalCase classes
- Module docstrings on new modules
- TDD: write test first, verify it fails, implement, verify pass
- Frequent commits after each task

---

### Task 1: `infra.py` — Add `stdin=subprocess.PIPE` to `start_background_cmd()`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py:137-142`

**Interfaces:**
- Consumes: nothing new
- Produces: `subprocess.Popen` now has `.stdin` attribute (subprocess.PIPE) — consumers (agents.py) can call `proc.stdin.write()` / `proc.stdin.flush()`

- [ ] **Step 1: Make the code change**

In `hatsume/plugins/hatsume-plugin/infra.py`, in function `start_background_cmd()`, change the `subprocess.Popen` call:

```python
# Before (lines 137-142):
    proc = subprocess.Popen(
        ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh"), "--cmd"],
        cwd=DOCKER_ENV_PATH,
        stdout=open(str(tmp), "w"),
        stderr=subprocess.STDOUT,
    )

# After:
    proc = subprocess.Popen(
        ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh"), "--cmd"],
        cwd=DOCKER_ENV_PATH,
        stdin=subprocess.PIPE,
        stdout=open(str(tmp), "w"),
        stderr=subprocess.STDOUT,
    )
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
python -m pytest tests/test_background_shell_infra.py -xvs
```
Expected: all existing tests PASS (tests use `sleep` which ignores stdin — no behavioral change).

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/infra.py
git commit -m "feat(infra): add stdin=PIPE to start_background_cmd for stdin injection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `prompts.py` — Extend decision prompt and add resolution prompt

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py:931-975`
- Create: `tests/test_background_shell_prompts.py` (new)

**Interfaces:**
- Produces:
  - `BACKGROUND_SHELL_DECISION_PROMPT` — updated with `INPUT_NEEDED` decision, `KILL` no longer mentions stdin waits, `NOTIFY` clarified as non-blocking
  - `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` — new constant, used by agents.py when transforming raw chat input → final stdin text

- [ ] **Step 1: Write the failing test**

Create `tests/test_background_shell_prompts.py`:

```python
"""Tests for background shell prompt constants."""
from __future__ import annotations

import types
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _load_prompts_module():
    """Load prompts.py with minimal stubs."""
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

    import importlib.util
    prompts_path = PLUGIN_DIR / "prompts.py"
    prompts_name = "hatsume.plugins.hatsume_plugin.prompts"
    if prompts_name in sys.modules:
        del sys.modules[prompts_name]
    spec = importlib.util.spec_from_file_location(prompts_name, prompts_path)
    prompts_mod = importlib.util.module_from_spec(spec)
    sys.modules[prompts_name] = prompts_mod
    spec.loader.exec_module(prompts_mod)
    return prompts_mod


def test_decision_prompt_has_input_needed():
    """BACKGROUND_SHELL_DECISION_PROMPT includes INPUT_NEEDED decision."""
    prompts = _load_prompts_module()
    prompt = prompts.BACKGROUND_SHELL_DECISION_PROMPT
    assert "INPUT_NEEDED" in prompt


def test_decision_prompt_kill_no_longer_mentions_stdin_wait():
    """KILL decision no longer treats stdin wait as kill reason."""
    prompts = _load_prompts_module()
    prompt = prompts.BACKGROUND_SHELL_DECISION_PROMPT
    assert "非预期的 stdin 等待" not in prompt


def test_stdin_resolution_prompt_exists():
    """BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT constant exists with expected
    decision types."""
    prompts = _load_prompts_module()
    prompt = prompts.BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT
    assert "FINAL_INPUT:" in prompt
    assert "REISSUE:" in prompt
    assert "KILL" in prompt
```

- [ ] **Step 2: Run test to verify it FAILS**

```bash
python -m pytest tests/test_background_shell_prompts.py -xvs
```
Expected: FAIL — `test_decision_prompt_has_input_needed` fails (`INPUT_NEEDED` not in original prompt), `test_stdin_resolution_prompt_exists` fails (constant doesn't exist).

- [ ] **Step 3: Replace `BACKGROUND_SHELL_DECISION_PROMPT`**

In `hatsume/plugins/hatsume-plugin/prompts.py`, replace lines 931-975 (the existing `BACKGROUND_SHELL_DECISION_PROMPT` assignment) with the updated version:

```python
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
    注意：NOTIFY 是非阻塞的 — 发送通知后 agent 继续监控。
    示例：NOTIFY:60

INPUT_NEEDED:<timeout_seconds>:<description>
    进程正在等待交互式输入（密码、确认、token 等），需要向 stdin 发送数据。
    timeout_seconds 为等待回复的最大秒数（默认 300 = 5 分钟，根据上下文可调整）。
    description 简要说明需要什么输入。

    使用时机：
    - 进程输出了密码提示（如 "[sudo] password"）
    - 进程输出了确认提示（如 "Continue? [y/N]"）
    - 进程等待认证 token / OTP code
    - 进程进入交互式 CLI 等待命令

    注意：INPUT_NEEDED 是阻塞决策 — agent 会等待回复后才继续轮询。
    与 NOTIFY 不同，NOTIFY 不阻塞且立即继续轮询。

    示例：
    - INPUT_NEEDED:300:sudo 密码
    - INPUT_NEEDED:60:确认继续安装 [y/N]
    - INPUT_NEEDED:600:GitHub personal access token

## 注意事项
- 如果输出为空或无新变化且进程仍在运行：
  - 如果输出末尾包含典型的交互式提示符（如 "password"、"[y/N]"、"> "） → 使用 INPUT_NEEDED
  - 否则 → 使用 CONTINUE 而非 KILL
- 如果进程已经退出（poll() 返回非 None），根据输出判断 DONE 或 KILL。
- 不要因为等待时间长就主动 KILL，除非有明确的失败信号。"""
```

- [ ] **Step 4: Add `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` constant**

Immediately after `BACKGROUND_SHELL_DECISION_PROMPT`, appending to `prompts.py`:

```python
BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT = """\
你正在管理一个后台 shell 进程。进程正在等待 stdin 输入。

## 原始请求
- 需要的输入: {description}
- 最近的进程输出: {process_output}

## 收到的回复
{raw_response}

## 你的任务
根据收到的回复和进程上下文，决定实际要写入 stdin 的内容。

规则:
1. 如果回复提供了所需信息 → 提取/格式化后输出 FINAL_INPUT:<text>
   - 对于密码/token: 保持原样，追加换行
   - 对于确认提示: 转换为进程期望的格式（如回复 "yes" → 输出 "y\\n"）
   - text 就是直接写入 stdin 的文本（不含引号）
2. 如果超时且可以安全使用默认值 → FINAL_INPUT:<default>
   - 确认提示默认回答 N/no（安全优先）
   - 不要猜测密码/token — 超时且无默认值时使用 KILL
3. 如果超时且不应继续等待 → KILL
4. 如果回复不充分，需要重新请求 → REISSUE:<new_timeout>:<clarified_description>

## 输出格式
必须且仅返回以下之一（不要多余文字）：
- FINAL_INPUT:<text>
- KILL
- REISSUE:<timeout_seconds>:<description>

## 提示
- 你应该先检查进程输出中提示的是什么（如 "[sudo] password" vs "[Y/n]"），
  确保 FINAL_INPUT 的格式匹配提示的期望。
- 如果用户回复了明显无关的内容，使用 REISSUE 重新说明需要什么。
- 默认超时时间为 300 秒（5 分钟），可根据上下文调整。"""
```

- [ ] **Step 5: Run tests to verify PASS**

```bash
python -m pytest tests/test_background_shell_prompts.py -xvs
```
Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py tests/test_background_shell_prompts.py
git commit -m "feat(prompts): add INPUT_NEEDED decision and stdin resolution prompt

- BACKGROUND_SHELL_DECISION_PROMPT: add INPUT_NEEDED decision type
- Remove 'unexpected stdin wait' from KILL (now handled by INPUT_NEEDED)
- Clarify NOTIFY as non-blocking
- Add BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT for raw→final stdin mediation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: `agents.py` — Core stdin infrastructure and poll loop changes

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/agents.py`
- Create: `tests/test_background_shell_stdin.py` (new)

**Interfaces:**
- Consumes:
  - `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` from `..prompts` (Task 2)
  - `start_background_cmd()` now returns process with `.stdin` (Task 1)
  - `NOTIFY_MARK`, `inject_agent_notification` from `.nodes.ai` (existing import)
- Produces:
  - `_stdin_queues: dict[str, asyncio.Queue[str | None]]` — module-level dict, consumed by tools.py (Task 4)
  - `_write_stdin(proc, text) -> bool` — internal helper
  - `_cleanup_stdin_queues(proc_id)` — internal helper, called in finally block

- [ ] **Step 1: Write failing tests for stdin helpers and queues**

Create `tests/test_background_shell_stdin.py`:

```python
"""Tests for background shell stdin injection helpers."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from pathlib import Path

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


_setup_package_hierarchy()


class TestWriteStdin:
    """Tests for _write_stdin() helper."""

    def test_writes_text_to_stdin(self):
        """_write_stdin writes text to process stdin and returns True."""
        # Create a test process that reads from stdin
        proc = subprocess.Popen(
            ["cat", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        result = _write_stdin(proc, "hello")

        stdout, _ = proc.communicate(timeout=2)
        assert result is True
        assert stdout == b"hello\n"

    def test_returns_false_when_process_exited(self):
        """_write_stdin returns False if process already exited."""
        proc = subprocess.Popen(
            ["true"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        proc.wait(timeout=2)

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        result = _write_stdin(proc, "hello")
        assert result is False

    def test_adds_newline_if_missing(self):
        """_write_stdin appends newline if text doesn't end with one."""
        proc = subprocess.Popen(
            ["cat", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        _write_stdin(proc, "no_newline")
        stdout, _ = proc.communicate(timeout=2)
        assert stdout == b"no_newline\n"

    def test_preserves_existing_newline(self):
        """_write_stdin does not double-append newline."""
        proc = subprocess.Popen(
            ["cat", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin
        _write_stdin(proc, "has_newline\n")
        stdout, _ = proc.communicate(timeout=2)
        assert stdout == b"has_newline\n"


class TestCleanupStdinQueues:
    """Tests for _cleanup_stdin_queues() helper."""

    def test_wakes_pending_waiters(self):
        """_cleanup_stdin_queues puts None into all matching queues."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _stdin_queues,
            _cleanup_stdin_queues,
        )

        # Create queues for a proc
        q = asyncio.Queue()
        _stdin_queues["stdin_test_abc_0"] = q
        _stdin_queues["stdin_test_abc_1"] = asyncio.Queue()
        _stdin_queues["stdin_other_xyz_0"] = asyncio.Queue()

        _cleanup_stdin_queues("test_abc")

        # Our queue should get None
        assert q.get_nowait() is None
        # Matching keys should be removed
        assert "stdin_test_abc_0" not in _stdin_queues
        assert "stdin_test_abc_1" not in _stdin_queues
        # Non-matching key should still exist
        assert "stdin_other_xyz_0" in _stdin_queues

        # Clean up remaining
        _stdin_queues.pop("stdin_other_xyz_0", None)


class TestStdinQueuesDict:
    """Tests for _stdin_queues module-level dict."""

    def test_dict_exists_as_module_attr(self):
        """_stdin_queues is a module-level dict."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _stdin_queues
        assert isinstance(_stdin_queues, dict)
```

- [ ] **Step 2: Run tests to verify they FAIL**

```bash
python -m pytest tests/test_background_shell_stdin.py -xvs
```
Expected: FAIL — `ImportError`, `_write_stdin` / `_cleanup_stdin_queues` / `_stdin_queues` not defined.

- [ ] **Step 3a: Add module-level `import asyncio` to `agents.py`**

At the top of `hatsume/plugins/hatsume-plugin/graph/agents.py`, change line 5 from:

```python
from typing import Any, Callable, Coroutine
```

to:

```python
import asyncio
from typing import Any, Callable, Coroutine
```

- [ ] **Step 3b: Add stdin infrastructure code after `_AGENT_STATES` section**

After line 31 (the `is_agent_running` function), add:

```python

# ---------------------------------------------------------------------------
# Stdin injection infrastructure (for background_shell agent)
# ---------------------------------------------------------------------------
_stdin_queues: dict[str, asyncio.Queue[str | None]] = {}


def _write_stdin(proc: subprocess.Popen, text: str) -> bool:
    """Safely write text to process stdin. Returns True on success.

    Automatically appends a trailing newline if missing.
    Returns False if the process has already exited or stdin is unavailable.
    """
    try:
        if proc.poll() is not None:
            return False
        if not text.endswith("\n"):
            text += "\n"
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.flush()
        return True
    except (BrokenPipeError, OSError, AttributeError):
        return False


def _cleanup_stdin_queues(proc_id: str) -> None:
    """Wake all pending stdin queue waiters for the given proc_id.

    Called during agent shutdown to prevent dangling awaiters.
    """
    prefix = f"stdin_{proc_id}_"
    for rid in list(_stdin_queues.keys()):
        if rid.startswith(prefix):
            q = _stdin_queues.pop(rid, None)
            if q is not None:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass
```

- [ ] **Step 3c: Modify `_run_background_shell` poll loop to handle `INPUT_NEEDED`**

In function `_run_background_shell`, update the import block (around lines 139-155) to also import:

```python
from ..prompts import (
    BACKGROUND_SHELL_DECISION_PROMPT,
    BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT,
)
```

Change the existing single-line import of `BACKGROUND_SHELL_DECISION_PROMPT` to the multi-line form above.

Then, after the `NOTIFY:` handling branch (after line 310), add the `INPUT_NEEDED:` branch. Insert after the closing of `elif decision.startswith("NOTIFY:"):` block (after the `inject_agent_notification(...)` call and its closing), before the `else:` block:

```python
            elif decision.startswith("INPUT_NEEDED:"):
                # Parse: INPUT_NEEDED:<timeout>:<description>
                try:
                    parts = decision.split(":", 2)
                    stdin_timeout = int(parts[1])
                    stdin_description = parts[2] if len(parts) > 2 else "需要输入"
                except (IndexError, ValueError):
                    stdin_timeout = 300
                    stdin_description = "需要输入"

                seq = get_agent_state("background_shell").get("stdin_seq", 0)
                request_id = f"stdin_{proc_id}_{seq}"
                get_agent_state("background_shell")["stdin_seq"] = seq + 1

                # Create queue and notify chat agent
                queue: asyncio.Queue[str | None] = asyncio.Queue()
                _stdin_queues[request_id] = queue

                notify_msg = (
                    f"{NOTIFY_MARK}:{user_id}:background_shell\n"
                    f"[SHELL_STDIN_REQUEST]\n"
                    f"request_id: {request_id}\n"
                    f"description: {stdin_description}\n"
                    f"context: {new_output[:500]}\n"
                    f"timeout: {stdin_timeout}s\n"
                    f"[/SHELL_STDIN_REQUEST]\n"
                    f"(SYSTEM) Agent 'background_shell' 进程正在等待输入。\n"
                    f"任务：{task[:300]}\n"
                    f"请使用 respond_to_shell_prompt 工具回复所需信息。"
                )
                print(f"BG Shell stdin request: {request_id=} {stdin_description=} {stdin_timeout=}")
                inject_agent_notification(
                    user_id=user_id,
                    group_id=_current_group_id or 0,
                    agent_name="background_shell",
                    result=notify_msg,
                    start_conversation_cb=_agent_notification_callback,
                )

                # Wait for response with timeout
                raw_text: str | None = None
                try:
                    raw_text = await asyncio.wait_for(
                        queue.get(), timeout=stdin_timeout
                    )
                except asyncio.TimeoutError:
                    raw_text = None
                finally:
                    _stdin_queues.pop(request_id, None)

                # Ask code model to decide final stdin content
                resolution_prompt = (
                    BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT
                    .replace("{description}", stdin_description)
                    .replace("{process_output}", (full_output + new_output)[-1000:])
                    .replace(
                        "{raw_response}",
                        raw_text if raw_text is not None
                        else f"超时: 已等待 {stdin_timeout}s 无回复"
                    )
                )
                resolution_response = await code_model.ainvoke([
                    SystemMessage(resolution_prompt),
                    HumanMessage("请决定下一步操作。"),
                ])
                resolution = str(resolution_response.content).strip()

                print(f"BG Shell stdin resolution: {resolution}")

                if resolution.startswith("FINAL_INPUT:"):
                    final_text = resolution.split(":", 1)[1].strip()
                    success = _write_stdin(proc, final_text)
                    if success:
                        last_decision = f"INPUT_SENT:{stdin_description}"
                        # Reset check_interval to short for quick follow-up
                        check_interval = 15
                    else:
                        # Process exited, will be caught next loop iteration
                        last_decision = "INPUT_FAILED"
                        check_interval = 5
                elif resolution.startswith("REISSUE:"):
                    # Re-issue: update timeout and description, put back
                    try:
                        reissue_parts = resolution.split(":", 2)
                        reissue_timeout = int(reissue_parts[1])
                        reissue_desc = reissue_parts[2]
                    except (IndexError, ValueError):
                        reissue_timeout = stdin_timeout
                        reissue_desc = stdin_description

                    # Re-create queue with same request_id
                    queue = asyncio.Queue()
                    _stdin_queues[request_id] = queue

                    reissue_msg = (
                        f"{NOTIFY_MARK}:{user_id}:background_shell\n"
                        f"[SHELL_STDIN_REQUEST]\n"
                        f"request_id: {request_id}\n"
                        f"description: {reissue_desc}\n"
                        f"context: {new_output[:500]}\n"
                        f"timeout: {reissue_timeout}s\n"
                        f"[/SHELL_STDIN_REQUEST]\n"
                        f"(SYSTEM) Agent 'background_shell' 重新请求输入。\n"
                        f"之前的回复不充分，请重新提供。"
                    )
                    inject_agent_notification(
                        user_id=user_id,
                        group_id=_current_group_id or 0,
                        agent_name="background_shell",
                        result=reissue_msg,
                        start_conversation_cb=_agent_notification_callback,
                    )

                    try:
                        raw_text = await asyncio.wait_for(
                            queue.get(), timeout=reissue_timeout
                        )
                    except asyncio.TimeoutError:
                        raw_text = None
                    finally:
                        _stdin_queues.pop(request_id, None)

                    if raw_text is not None:
                        resolution_prompt = (
                            BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT
                            .replace("{description}", reissue_desc)
                            .replace("{process_output}", (full_output + new_output)[-1000:])
                            .replace("{raw_response}", raw_text)
                        )
                        resolution_response = await code_model.ainvoke([
                            SystemMessage(resolution_prompt),
                            HumanMessage("请决定下一步操作。"),
                        ])
                        resolution = str(resolution_response.content).strip()

                        if resolution.startswith("FINAL_INPUT:"):
                            final_text = resolution.split(":", 1)[1].strip()
                            _write_stdin(proc, final_text)
                            last_decision = f"INPUT_SENT:{stdin_description}"
                            check_interval = 15
                        elif resolution.startswith("KILL"):
                            last_decision = "KILL"
                            break
                        else:
                            # Fail-safe: give up and kill
                            last_decision = "KILL"
                            break
                    else:
                        # Timeout on re-issue → kill
                        last_decision = "KILL"
                        break
                elif resolution.startswith("KILL"):
                    last_decision = "KILL"
                    break
                else:
                    # Unrecognized resolution, continue polling
                    last_decision = "INPUT_UNKNOWN"
                    check_interval = 30
```

This replaces the `else:` block at line 311-313. Keep the existing `else` as a fallback for completely unrecognized decisions (non-INPUT_NEEDED ones):

```python
            else:
                # Unrecognized, default to continue
                last_decision = f"CONTINUE:{check_interval}"
```

- [ ] **Step 3d: Add cleanup call in the `finally` block**

In the `_run_background_shell` function, the `try` block spans lines 218-321. Add a `finally` block (if not already present) that calls `_cleanup_stdin_queues`. After the `except Exception:` block (around line 321), add:

```python
        finally:
            _cleanup_stdin_queues(proc_id)
```

Actually, looking at the code structure: there's already an `except asyncio.CancelledError:` (line 314) and `except Exception:` (line 317). We need to add `finally:` after the last `except`:

```python
    except asyncio.CancelledError:
        kill_background_cmd(proc_id)
        return "background_shell: cancelled."
    except Exception:
        import traceback
        traceback.print_exc()
        kill_background_cmd(proc_id)
        return "background_shell: internal error."
    finally:
        _cleanup_stdin_queues(proc_id)

    # ── Step 4: Final cleanup and notification ──
```

Wait — but the `return` statements inside `except` blocks would bypass `finally` in the normal case? No, in Python `finally` always runs even after `return`. But the issue is that we also have the normal code path after the try-except (Step 4). The `finally` block would run before Step 4, which is fine — we just want to make sure cleanup happens regardless.

Let me re-check: the `try` block at line 218 contains the while loop. When the loop breaks normally (DONE, KILL, TIMEOUT, process exit), execution falls to after the `except` blocks — but actually the code at line 323+ (Step 4) is AFTER the `try/except`. In the current code, there's NO `finally`. The `return` in `except asyncio.CancelledError` (line 316) and `except Exception` (line 321) are the only early returns from inside the try.

So the current structure is:
```python
    try:
        while True: ... (loop with breaks)
    except CancelledError:
        ...
        return "..."
    except Exception:
        ...
        return "..."
    
    # Step 4 (normal completion)
    ...
    return final_msg
```

We need:
```python
    try:
        while True: ... (loop with breaks)
    except CancelledError:
        ...
        return "..."
    except Exception:
        ...
        return "..."
    finally:
        _cleanup_stdin_queues(proc_id)
    
    # Step 4 (normal completion)
    ...
    return final_msg
```

This is correct — `finally` runs after the try body (when loop breaks normally) AND after except blocks (before their return executes).

- [ ] **Step 4: Run tests to verify PASS**

```bash
python -m pytest tests/test_background_shell_stdin.py -xvs
```
Expected: all tests in `test_background_shell_stdin.py` PASS.

- [ ] **Step 5: Verify existing tests still pass**

```bash
python -m pytest tests/test_background_shell_infra.py tests/test_background_shell_prompts.py -xvs
```
Expected: all existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/agents.py tests/test_background_shell_stdin.py
git commit -m "feat(agents): add stdin injection to background_shell poll loop

- Add _stdin_queues dict, _write_stdin(), _cleanup_stdin_queues() helpers
- Handle INPUT_NEEDED decision in poll loop with queue-based wait
- Code model mediates raw chat text → final stdin content
- Support REISSUE for insufficient responses
- Add finally block for stdin queue cleanup

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: `tools.py` — Add `respond_to_shell_prompt` tool

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Consumes: `_stdin_queues` from `.agents` (Task 3)
- Produces: `respond_to_shell_prompt(request_id, text) -> str` — callable LangChain tool

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools.py`:

```python
class TestRespondToShellPrompt:
    """Tests for respond_to_shell_prompt tool."""

    def test_successfully_puts_text_into_queue(self):
        """The tool puts text into the stdin queue and returns success."""
        import asyncio
        from hatsume.plugins.hatsume_plugin.graph.agents import _stdin_queues

        # Create a test queue
        test_q: asyncio.Queue[str | None] = asyncio.Queue()
        _stdin_queues["stdin_test_001_0"] = test_q

        try:
            from hatsume.plugins.hatsume_plugin.graph.tools import (
                respond_to_shell_prompt,
            )

            # Call the underlying function directly (not through tool wrapper)
            import inspect
            result = respond_to_shell_prompt.func(
                request_id="stdin_test_001_0",
                text="test_password",
            )

            assert "成功" in result
            # Queue should have the text
            assert test_q.get_nowait() == "test_password"
            # Queue entry should be removed
            assert "stdin_test_001_0" not in _stdin_queues
        finally:
            _stdin_queues.pop("stdin_test_001_0", None)

    def test_returns_error_for_invalid_request_id(self):
        """Returns error when request_id is not found."""
        from hatsume.plugins.hatsume_plugin.graph.tools import (
            respond_to_shell_prompt,
        )
        import inspect

        result = respond_to_shell_prompt.func(
            request_id="nonexistent_id_xyz",
            text="anything",
        )

        assert "找不到" in result or "No pending" in result or "错误" in result

    def test_second_call_for_same_id_fails(self):
        """Second call for same request_id returns error (already handled)."""
        import asyncio
        from hatsume.plugins.hatsume_plugin.graph.agents import _stdin_queues

        test_q: asyncio.Queue[str | None] = asyncio.Queue()
        _stdin_queues["stdin_test_002_0"] = test_q

        try:
            from hatsume.plugins.hatsume_plugin.graph.tools import (
                respond_to_shell_prompt,
            )
            import inspect

            result1 = respond_to_shell_prompt.func(
                request_id="stdin_test_002_0",
                text="first",
            )
            assert "成功" in result1

            result2 = respond_to_shell_prompt.func(
                request_id="stdin_test_002_0",
                text="second",
            )
            assert "找不到" in result2 or "No pending" in result2 or "错误" in result2
        finally:
            _stdin_queues.pop("stdin_test_002_0", None)
```

- [ ] **Step 2: Run test to verify FAIL**

```bash
python -m pytest tests/test_tools.py::TestRespondToShellPrompt -xvs
```
Expected: FAIL — `ImportError: cannot import name 'respond_to_shell_prompt'`

- [ ] **Step 3: Implement `respond_to_shell_prompt` tool**

In `hatsume/plugins/hatsume-plugin/graph/tools.py`, after the existing `@tool` definitions (after `check_agent`, around line 898), add:

```python

@tool
async def respond_to_shell_prompt(
    request_id: str,
    text: str,
) -> str:
    """向后台 shell 进程的 stdin 请求发送回复。

    当后台 shell agent 发出 SHELL_STDIN_REQUEST 通知时，
    使用此 tool 将所需信息传递给进程。

    Args:
        request_id: 通知中的 request_id，格式为 stdin_<proc_id>_<seq>
        text: 要传递的原始信息（如密码、确认、token 等）。
              后台 shell agent 的代码模型会将其转换为进程实际需要的格式。

    Returns:
        成功或失败的描述信息。
    """
    from .agents import _stdin_queues

    q = _stdin_queues.pop(request_id, None)
    if q is None:
        return (
            f"错误：找不到 pending stdin 请求 (request_id={request_id})。"
            f"可能该请求已超时、已被处理、或 request_id 不正确。"
        )

    await q.put(text)
    return f"✅ 已成功向后台进程发送 stdin 输入 (request_id={request_id})。"
```

- [ ] **Step 4: Run tests to verify PASS**

```bash
python -m pytest tests/test_tools.py::TestRespondToShellPrompt -xvs
```
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py tests/test_tools.py
git commit -m "feat(tools): add respond_to_shell_prompt tool for stdin injection

- New @tool reads from _stdin_queues dict
- Returns error for invalid/expired request_id
- Prevents double-reply by popping queue on first access

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `nodes/ai.py` — Register `respond_to_shell_prompt` in chat_agent

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:28-35,354-361`

**Interfaces:**
- Consumes: `respond_to_shell_prompt` from `graph/tools.py` (Task 4)
- Produces: tool available to `chat_agent` LLM calls

- [ ] **Step 1: Add import**

In `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`, at lines 28-35 (the existing tools import block), add `respond_to_shell_prompt`:

```python
# Before (lines 28-35):
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    capture_html_shot, generate_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate, check_agent,
)

# After:
from ..tools import (
    search_web, shell_executor, find_memory, query_memory,
    capture_html_shot, generate_image,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch,
    agent_allocate, check_agent, respond_to_shell_prompt,
)
```

- [ ] **Step 2: Add to chat_agent tools list**

In the same file, at lines 354-361 (the `create_agent` call), add `respond_to_shell_prompt`:

```python
# Before (lines 354-361):
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory, capture_html_shot,
         generate_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate, check_agent],
        system_prompt=sys_prompt,
    )

# After:
    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory, capture_html_shot,
         generate_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate, check_agent, respond_to_shell_prompt],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 3: Run existing tests to verify no regression**

```bash
python -m pytest tests/test_graph_nodes.py tests/test_tools.py -xvs
```
Expected: all existing tests PASS (new tool is just another entry in lists).

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat(ai): register respond_to_shell_prompt in chat_agent tools

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Integration test — End-to-end stdin injection flow

**Files:**
- Create: `tests/test_background_shell_stdin_integration.py` (new)

**Interfaces:**
- Consumes: All previous tasks (complete stdin pipeline)
- Produces: Integration test validating the full flow

- [ ] **Step 1: Write the integration test**

Create `tests/test_background_shell_stdin_integration.py`:

```python
"""Integration test: full stdin injection flow for background_shell agent."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import types
from pathlib import Path

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


_setup_package_hierarchy()


class TestStdinInjectionIntegration:
    """End-to-end tests for stdin injection via _write_stdin and queues."""

    def test_write_stdin_to_interactive_process(self):
        """Spawn a process that reads stdin, write to it, verify output."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin

        # Use a script that prompts for input, reads it, and echoes it
        proc = subprocess.Popen(
            ["bash", "-c", 'read -p "Enter: " v; echo "Got: $v"'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,  # binary mode for manual encoding
        )

        # Write stdin — _write_stdin will encode to utf-8
        result = _write_stdin(proc, "hello_world\n")
        assert result is True

        # Read output
        stdout, _ = proc.communicate(timeout=5)
        assert b"Got: hello_world" in stdout

    def test_write_stdin_multiple_times(self):
        """Multiple stdin writes to the same process work correctly."""
        from hatsume.plugins.hatsume_plugin.graph.agents import _write_stdin

        # Script that reads two inputs
        proc = subprocess.Popen(
            ["bash", "-c", 'read v1; read v2; echo "$v1|$v2"'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
        )

        result1 = _write_stdin(proc, "first_value\n")
        assert result1 is True
        result2 = _write_stdin(proc, "second_value\n")
        assert result2 is True

        stdout, _ = proc.communicate(timeout=5)
        assert b"first_value|second_value" in stdout

    def test_queue_flow_for_stdin_request(self):
        """Simulate the full queue-based stdin request/response flow."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _stdin_queues,
            _cleanup_stdin_queues,
        )

        proc_id = "test_integration"
        request_id = f"stdin_{proc_id}_0"

        # Simulate bg shell agent creating a queue
        q: asyncio.Queue[str | None] = asyncio.Queue()
        _stdin_queues[request_id] = q

        # Simulate chat agent responding via the tool
        async def simulate_tool_response():
            popped_q = _stdin_queues.pop(request_id, None)
            assert popped_q is not None
            await popped_q.put("my_secret_token")
            return "success"

        # Simulate bg shell agent waiting
        async def simulate_agent_wait():
            raw = await asyncio.wait_for(q.get(), timeout=2)
            return raw

        async def run():
            tool_task = asyncio.create_task(simulate_tool_response())
            agent_task = asyncio.create_task(simulate_agent_wait())
            raw = await agent_task
            await tool_task
            return raw

        raw = asyncio.run(run())
        assert raw == "my_secret_token"
        assert request_id not in _stdin_queues

    def test_cleanup_wakes_waiters(self):
        """_cleanup_stdin_queues wakes pending queue waiters with None."""
        from hatsume.plugins.hatsume_plugin.graph.agents import (
            _stdin_queues,
            _cleanup_stdin_queues,
        )

        proc_id = "test_cleanup"
        request_id = f"stdin_{proc_id}_0"
        q: asyncio.Queue[str | None] = asyncio.Queue()
        _stdin_queues[request_id] = q

        async def wait_then_cleanup():
            await asyncio.sleep(0.05)
            _cleanup_stdin_queues(proc_id)

        async def agent_wait():
            raw = await q.get()
            return raw

        async def run():
            cleanup_task = asyncio.create_task(wait_then_cleanup())
            agent_task = asyncio.create_task(agent_wait())
            raw = await agent_task
            await cleanup_task
            return raw

        raw = asyncio.run(run())
        assert raw is None
        assert request_id not in _stdin_queues
```

- [ ] **Step 2: Run integration test to verify PASS**

```bash
python -m pytest tests/test_background_shell_stdin_integration.py -xvs
```
Expected: all 4 tests PASS.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -xvs --ignore=tests/test_omni_model.py --ignore=tests/test_agents_command.py
```
Expected: all tests PASS (excluding tests that require external services).

- [ ] **Step 4: Commit**

```bash
git add tests/test_background_shell_stdin_integration.py
git commit -m "test: add integration tests for stdin injection flow

- Test stdin write to interactive process
- Test multiple stdin writes
- Test queue-based request/response flow
- Test cleanup wakes pending waiters

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task Dependency Graph

```
Task 1 (infra.py) ──┐
                    ├──▶ Task 3 (agents.py) ──▶ Task 4 (tools.py) ──▶ Task 5 (ai.py)
Task 2 (prompts.py)─┘                                                    │
                                                                         ▼
                                                                  Task 6 (integration)
```

- Task 1 and Task 2 can run in parallel (no shared state)
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 3 (needs `_stdin_queues`)
- Task 5 depends on Task 4 (needs `respond_to_shell_prompt` tool)
- Task 6 depends on all prior tasks

## Summary of All Changes

| Task | File | Lines Changed |
|------|------|---------------|
| 1 | `infra.py` | 1 line (+`stdin=subprocess.PIPE`) |
| 2 | `prompts.py` | ~50 lines (replace prompt + add constant) |
| 3 | `agents.py` | ~100 lines (helpers, INPUT_NEEDED branch, finally) |
| 4 | `tools.py` | ~30 lines (new tool + imports) |
| 5 | `ai.py` | 2 lines (import + tools list) |
| 6 | `tests/` | ~200 lines (integration tests) |

**Total estimated changes:** ~380 lines across 5 source files + 2 test files.
