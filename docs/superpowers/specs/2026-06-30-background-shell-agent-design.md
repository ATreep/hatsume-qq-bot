# Background Shell Agent — Design Spec

**Date**: 2026-06-30
**Status**: Draft
**Context**: hatsume QQ bot — NoneBot2 + LangGraph conversation agent

## 1. Problem

The chat agent's `shell_executor` tool calls `subprocess.run(capture_output=True)`, which blocks the LangGraph conversation graph until the command completes. This makes interactive commands (e.g., `gh auth login`, `gcloud auth login`) unusable — they output a URL, wait for user browser interaction, and the graph stalls indefinitely.

The existing `agent_allocate` + background agent pattern (`coding_agent`, `generate_video`) shows the correct architecture but has two gaps:
- Agents only notify once, at completion — cannot inject mid-progress output while staying alive
- No agent exists for general-purpose background shell commands with polling and LLM-driven decisions

## 2. Design

### 2.1 Overview — `background_shell` Agent

A new built-in agent registered in `graph/agents.py` that:

1. **Parses** the structured `task` argument into command code, termination description, and timeout
2. **Spawns** a background `subprocess.Popen` with stdout/stderr redirected to a tmp file
3. **Polls** in a loop: sleep → read incremental output → ask code model to decide
4. **Injects** mid-progress output to the main graph when the code model signals `NOTIFY`
5. **Keeps the process alive** across multiple poll cycles
6. **Terminates** on `DONE`, `KILL`, or total-timeout exceeded

### 2.2 Architecture Diagram

```
agent_allocate("background_shell", task="...", notified_user_id=123)
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│  BackgroundShell Agent (asyncio.create_task, does NOT block graph)│
│                                                                   │
│  1. code model parses task → {cmd, description, total_timeout}    │
│  2. proc, tmp = start_background_cmd(cmd)                         │
│  3. elapsed = 0, offset = 0                                       │
│                                                                   │
│  while proc alive AND elapsed < total_timeout:                    │
│    sleep(check_interval)                                          │
│    elapsed += check_interval                                      │
│    new_output, offset = read_background_output(tmp, offset)       │
│    decision = code_model.invoke(BG_SHELL_DECISION_PROMPT,         │
│                   task + new_output)                              │
│                                                                   │
│    if CONTINUE:N → check_interval = N, continue                   │
│    if NOTIFY:N   → inject_agent_notification(                     │
│                      mid-progress output to graph),               │
│                    check_interval = N, continue                   │
│    if DONE       → notify final result, break                     │
│    if KILL       → kill process, notify result, break             │
│                                                                   │
│  if elapsed >= total_timeout:                                     │
│    kill process, notify timeout                                   │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
inject_agent_notification(user_id, group_id, result)
  │
  ▼
Main graph LLM receives output, relays to user
```

### 2.3 `task` Argument Format

The chat agent passes this via `agent_allocate(task=...)`. The `background_shell` handler uses the code model to parse it. Three parts, natural language, no rigid schema:

```
1. command code
   The full shell script/command to execute, e.g.:
   ```
   gh auth login --hostname github.com --web
   ```

2. description + termination condition
   What the command does and when the agent should terminate, e.g.:
   "This authenticates with GitHub via web flow. Terminate when the output shows
   'Authentication complete' or 'Logged in as'."

3. total_timeout (seconds)
   Force-kill the process after this many seconds elapsed. Default 300 if not specified.
```

### 2.4 LLM Decision Prompt

The code model receives this system prompt for each poll cycle:

```
You are a background shell process monitor. A command is currently running.

## Input
- Task description and termination condition
- Command output (newly produced since the last check)

## Output (exactly one of):

DONE
    The command has completed successfully according to the termination condition.
    No further monitoring needed.

KILL
    The command should be terminated (it has failed, stalled, or is no longer meaningful).
    Include the reason.

CONTINUE:N
    The command is still running normally, no output needs user attention yet.
    N = seconds until the next check.
    Estimate N based on the task nature:
    - Short (compile, install): 15-30s
    - Medium (download, process): 30-60s
    - Long (auth wait, long compute): 60-120s
    - If unsure, default to 30s.

NOTIFY:N
    The output contains information that the user needs to see IMMEDIATELY
    (e.g., a URL to visit, a verification code, a critical status change).
    The output will be injected into the main conversation for the user.
    N = seconds until the next check after notifying.
    ⚠️ Only use NOTIFY for information requiring user action.
    For routine progress logs, use CONTINUE.
```

### 2.5 Mid-Progress Injection Format

When the code model decides `NOTIFY`, the agent calls `inject_agent_notification` with:

```python
notify_msg = (
    f"{NOTIFY_MARK}:{user_id}:background_shell\n"
    f"(SYSTEM) Agent 'background_shell' 执行中的中间输出。\n"
    f"任务：{task[:300]}\n"
    f"Agent 仍在后台运行中（已耗时 {elapsed}s / {total_timeout}s）。\n"
    f"以下是命令的当前输出，请告知用户：\n\n"
    f"{new_output}"
)
```

The main graph LLM sees this injected message on the next human-node cycle and relays the relevant info to the user.

### 2.6 Final Result Injection

On `DONE`, `KILL`, or timeout — same `inject_agent_notification` call with full accumulated output:

```python
final_msg = (
    f"{NOTIFY_MARK}:{user_id}:background_shell\n"
    f"(SYSTEM) Agent 'background_shell' 已执行完毕。\n"
    f"任务：{task[:300]}\n"
    f"总耗时：{elapsed}s\n"
    f"结果：{'成功完成' if decision == 'DONE' else '已终止' if decision == 'KILL' else '超时强制终止'}\n\n"
    f"完整输出：\n{full_output[:2000]}"
)
```

## 3. Implementation

### 3.1 File Changes

| File | Change | Purpose |
|------|--------|---------|
| `infra.py` | Add `start_background_cmd()`, `read_background_output()`, `kill_background_cmd()` | Background process + tmp file I/O |
| `graph/agents.py` | Register `background_shell` agent + `_run_background_shell()` handler | Agent logic and decision loop |
| `prompts.py` | Add `BACKGROUND_SHELL_DECISION_PROMPT` | Code model decision system prompt |

### 3.2 Files NOT Changed (Zero-Change Reuse)

| Component | Why |
|-----------|-----|
| `graph/tools.py` — `agent_allocate` | Already dispatches agents by name |
| `graph/tools.py` — `configure_agent_notification_callback` | Already wires notification callback |
| `graph/nodes/ai.py` — `inject_agent_notification` | Already injects system messages into human_queue |
| `graph/nodes/ai.py` — `detect_agent_notification` | Already parses NOTIFY_MARK |
| `graph/nodes/ai.py` — `NOTIFY_MARK` | Already defined as `"__agent_notify__"` |
| `graph/agents.py` — `_AGENT_STATES`, `set_agent_state`, `get_agent_state` | Already tracks agent status |
| `handlers/commands.py` — `handle_agents` | Already displays agent states via `/agents` |
| `handlers/chat.py` — `_start_conv_for_agent` | Already starts new conversation for agent notification |

### 3.3 `infra.py` — New Functions

```python
import subprocess
import tempfile
from pathlib import Path

_background_procs: dict[str, tuple[subprocess.Popen, Path]] = {}

def start_background_cmd(code: str, proc_id: str) -> Path:
    """Spawn a background bash process in Docker.
    
    stdout + stderr are merged and redirected to a tmp file.
    Returns the tmp file path for incremental output reading.
    
    Caller is responsible for cleanup via kill_background_cmd().
    """
    ensure_container_running()
    tmp = Path(tempfile.mkstemp(prefix="hatsume-bg-", suffix=".log")[1])

    SOURCE_BASHRC = "source ~/.bashrc"
    script_path = Path(DOCKER_ENV_PATH, "script.sh").absolute()
    script_path.write_text(SOURCE_BASHRC + "\n" + code)

    proc = subprocess.Popen(
        ["bash", Path(DOCKER_ENV_PATH, "launch_image.sh"), "--cmd"],
        cwd=DOCKER_ENV_PATH,
        stdout=open(str(tmp), "w"),
        stderr=subprocess.STDOUT,
    )
    _background_procs[proc_id] = (proc, tmp)
    return tmp


def read_background_output(tmp_path: Path, offset: int) -> tuple[str, int]:
    """Read new output from tmp file since last read position.
    
    Returns (new_content_since_offset, new_total_offset).
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


def kill_background_cmd(proc_id: str) -> str | None:
    """Terminate a background process and clean up tmp file.
    
    Returns any remaining unread output, or None if the process was
    already cleaned up.
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

### 3.4 `graph/agents.py` — Agent Registration

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
    import time as _time
    import uuid

    from langchain.messages import HumanMessage, SystemMessage
    from ..models import get_code_model
    from ..prompts import BACKGROUND_SHELL_DECISION_PROMPT
    from ..infra import start_background_cmd, read_background_output, kill_background_cmd
    from .ai import inject_agent_notification
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
    
    import json, re
    raw = str(parse_response.content)
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
            decision = str(decision_response.content).strip().upper()

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


# Register at module level
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

### 3.5 `prompts.py` — Decision Prompt

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

## 4. Behavior Summary

### 4.1 Happy Path — Auth Flow

```
User: gh auth login
  → Chat LLM calls agent_allocate("background_shell", task="...")
  → Agent starts: gh auth login --hostname github.com --web
  → Sleep 30s, read output, code model decides: NOTIFY:60
     (output contains "https://github.com/login/device")
  → inject_agent_notification → main LLM tells user the URL
  → Agent continues: sleep 60s
  → Read output, code model decides: DONE
     (output contains "Authentication complete")
  → inject_agent_notification → main LLM tells user auth succeeded
```

### 4.2 Timeout Path

```
User: some long-running command
  → Agent starts, polls every 30s, all CONTINUE
  → After 300s elapsed >= total_timeout
  → Force kill process, notify user with partial output
```

### 4.3 Error Path

```
User: command that fails
  → Agent starts, polls, output shows "Permission denied"
  → Code model decides: KILL
  → Kill process, notify user with error output
```

## 5. Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Process dies between polls | `poll()` returns non-None; code model sees this and returns DONE or KILL |
| Tmp file deleted externally | `read_background_output` returns empty on missing file; agent continues |
| Code model returns garbage | Falls back to CONTINUE with current interval |
| `agent_allocate` called while agent already running | `is_agent_running("background_shell")` check blocks duplicate |
| Bot restarts during agent execution | Process + tmp file lost; no persistence (acceptable for shell commands) |
| `asyncio.CancelledError` (e.g., /clear) | Cleanup tmp file, kill process, return gracefully |

## 6. Testing Strategy

| Test | What it verifies |
|------|-----------------|
| `test_background_shell_parse_task` | Code model correctly parses task → {cmd, description, total_timeout} |
| `test_background_shell_done_decision` | Code model returns DONE when output matches termination |
| `test_background_shell_notify_decision` | Code model returns NOTIFY when output contains URL |
| `test_background_shell_continue_decision` | Code model returns CONTINUE for normal progress output |
| `test_background_shell_timeout` | Agent kills process after total_timeout exceeded |
| `test_background_shell_mid_injection` | NOTIFY triggers inject_agent_notification while agent stays alive |
| `test_start_background_cmd` | Process spawns correctly, output goes to tmp file |
| `test_read_background_output_incremental` | Offset tracking works across multiple reads |
| `test_kill_background_cmd` | Process terminated, tmp file cleaned up |
