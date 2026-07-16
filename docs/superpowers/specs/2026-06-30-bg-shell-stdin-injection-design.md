# Background Shell Agent — Stdin Injection

**Date**: 2026-06-30
**Status**: Design Approved
**Feature**: Add stdin injection capability to the background_shell agent

## 1. Overview

### Goal

When a background shell process needs interactive input (sudo password, auth token, confirmation prompt), the agent currently treats this as an error and kills the process. This feature replaces that behavior with a cooperative stdin pipeline: the background shell agent detects stdin needs, notifies the chat agent, receives raw input from the user/chat agent, passes it through the code model for final formatting, and writes it to the process's stdin.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Stdin source | Hybrid (auto + manual) | Code model auto-answers simple prompts (y/N), escalates to chat for secrets/tokens |
| Chat→BG communication | `asyncio.Queue` + `respond_to_shell_prompt` tool | Clean async interface, matches existing agent→tool→graph architecture |
| Chat→stdin translation | Code model mediates | Safety boundary — chat agent provides raw info, code model formats for the actual process context |
| Stdin detection | Code model judgment + output timeout | Dual-signal: pattern matching in recent output AND no-new-output timeout |
| Timeout handling | Code model decides, default 5 min | Flexible; model adjusts per context (urgent confirmation vs. long token wait) |
| Sensitive data handling | No special treatment | Warn users against sending secrets in chat; no extra filtering/logging changes |

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LangGraph StateGraph                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  human   │───▶│  detect  │───▶│  ai_node │───▶│  finish  │  │
│  │          │    │          │    │  (tools) │    │          │  │
│  └──────────┘    └──────────┘    └────┬─────┘    └──────────┘  │
│                                       │                         │
│                          respond_to_shell_prompt  tool          │
│                                       │                         │
└───────────────────────────────────────┼─────────────────────────┘
                                        │
                              asyncio.Queue[request_id]
                                        │
┌───────────────────────────────────────┼─────────────────────────┐
│                        BG Shell Agent (asyncio task)            │
│                                       ▼                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Poll Loop                              │  │
│  │  1. read_output(tmp) → feed to code model                 │  │
│  │  2. code model decision:                                  │  │
│  │     DONE | KILL | CONTINUE:N | NOTIFY:N | INPUT_NEEDED    │  │
│  │  3. if INPUT_NEEDED:                                      │  │
│  │     → notify chat (NOTIFY_MARK)                           │  │
│  │     → await queue.get(timeout)                            │  │
│  │     → code model transforms raw_text → final_text          │  │
│  │     → proc.stdin.write(final_text)                        │  │
│  │     → continue polling                                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                    subprocess.Popen                             │
│                    stdin=PIPE                                   │
└──────────────────────────────────────────────────────────────────┘
```

## 3. Component Design

### 3.1 `infra.py` — Modified `start_background_cmd()`

Add `stdin=subprocess.PIPE` to the `Popen` call:

```python
proc = subprocess.Popen(
    ["bash", launch_script, "--cmd"],
    stdin=subprocess.PIPE,       # NEW
    stdout=open(tmp_path, "w"),
    stderr=subprocess.STDOUT,
)
```

`_background_procs` dict structure unchanged — `proc.stdin` is accessible via the stored `proc` reference.

### 3.2 `prompts.py` — Extended Decision Prompt

Add `INPUT_NEEDED` decision to `BACKGROUND_SHELL_DECISION_PROMPT`:

```
- INPUT_NEEDED:<timeout_seconds>:<description>
  进程正在等待交互式输入。timeout_seconds 为等待回复的最大秒数
  (默认 300 = 5 分钟，根据上下文可调整)。description 简要说明需要什么输入。
  
  使用时机：
  - 进程输出了密码提示 (如 "[sudo] password")
  - 进程输出了确认提示 (如 "Continue? [y/N]")
  - 进程等待认证 token / OTP code
  - 进程进入交互式 CLI 等待命令
  
  示例：
  - INPUT_NEEDED:300:sudo 密码
  - INPUT_NEEDED:60:确认继续安装 [y/N]
  - INPUT_NEEDED:600:GitHub personal access token
  
  注意：INPUT_NEEDED 是阻塞决策 — agent 会等待回复后才继续轮询。
  与 NOTIFY 不同，NOTIFY 不阻塞且立即继续轮询。
```

Remove "unexpected stdin wait" from the `KILL` description — stdin waits are now expected and handled.

Update `NOTIFY` description to clarify it is for non-blocking notifications only.

#### 3.2.1 Stdin Resolution Prompt (secondary code model call)

After receiving `raw_text` from the queue (or timeout), the code model is called again with a focused context to decide the actual stdin content to write. A new prompt constant `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` is added:

```
你正在管理一个后台 shell 进程。进程正在等待 stdin 输入。

## 原始请求
- 需要的输入: {description}
- 进程上下文: {prompt_context}

## 收到的回复
{raw_text_or_"超时: 已等待 {timeout_}秒无回复"}

## 你的任务
根据收到的回复和进程上下文，决定实际要写入 stdin 的内容。

规则:
1. 如果回复提供了所需信息 → 提取/格式化后输出 FINAL_INPUT:<text>
   - 对于密码/token: 保持原样，追加换行
   - 对于确认提示: 转换为进程期望的格式 (如 "yes" → "y\n")
2. 如果超时且可以安全使用默认值 → FINAL_INPUT:<default>
   - 确认提示默认回答 N/no (安全优先)
   - 不要猜测密码/token
3. 如果超时且不应继续等待 → KILL
4. 如果回复不充分，需要重新请求 → REISSUE:<new_timeout>:<clarified_description>
```

### 3.3 `agents.py` — Core Changes

#### 3.3.1 New Data Structure

```python
# Module-level: request_id → asyncio.Queue
# Queue resolves to: str (raw_text from chat agent) or None (timeout/cancel)
_stdin_queues: dict[str, asyncio.Queue[str | None]] = {}
```

#### 3.3.2 Poll Loop State Machine

```
read output → code model decision
                    │
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
 DONE/KILL     CONTINUE:N     INPUT_NEEDED:t:d
     │              │              │
     ▼              ▼              ▼
 cleanup       sleep(N)     ┌─────────────────┐
                            │ generate req_id  │
                            │ notify chat      │
                            │ await queue.get  │
                            │     (timeout=t)  │
                            └────────┬────────┘
                                     │
                          ┌──────────┼──────────┐
                          ▼                     ▼
                      got raw_text          timeout → None
                          │                     │
                          ▼                     ▼
                   ┌─────────────┐     code model decides:
                   │ code model  │     fallback input /
                   │ raw→final   │     re-issue / kill
                   └──────┬──────┘
                          │
                   stdin.write(final)
                   stdin.flush()
                          │
                   loop back to poll
```

#### 3.3.3 Stdin Write Helper

```python
async def _write_stdin(proc: subprocess.Popen, text: str) -> bool:
    """Safely write to process stdin. Returns True on success."""
    try:
        if proc.poll() is not None:
            return False  # process already exited
        if not text.endswith("\n"):
            text += "\n"
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.flush()
        return True
    except (BrokenPipeError, OSError, AttributeError):
        return False
```

#### 3.3.4 Cleanup

```python
def _cleanup_stdin_queues(proc_id: str):
    """Wake all pending queue waiters on agent shutdown."""
    prefix = f"stdin_{proc_id}_"
    for rid in list(_stdin_queues.keys()):
        if rid.startswith(prefix):
            q = _stdin_queues.pop(rid, None)
            if q:
                q.put_nowait(None)
```

Called in `finally` block of `_run_background_shell`.

### 3.4 `tools.py` — New Tool

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
```

Handler logic:
1. Look up `request_id` in `_stdin_queues`
2. If not found → return error: `"No pending stdin request with id {request_id}"`
3. If found → `queue.put(text)`, remove from `_stdin_queues`, return success

To prevent double-reply: immediately pop from `_stdin_queues` on first `put()`.

### 3.5 `nodes/ai.py` — Tool Registration

Import `respond_to_shell_prompt` from `graph/tools.py` and add to `chat_agent` tools list. Follows the pattern documented in [[new-tool-registration]].

### 3.6 NOTIFY Message Format

When `INPUT_NEEDED` is detected, the notification injected into the conversation graph uses:

```
NOTIFY_MARK:<user_id>:background_shell
[SHELL_STDIN_REQUEST]
request_id: stdin_<proc_id>_<seq>
description: <human-readable description of what input is needed>
context: <recent process output showing the prompt>
timeout: <timeout_seconds>s
[/SHELL_STDIN_REQUEST]
```

## 4. Data Flow & Sequences

### 4.1 Normal Flow (stdin successfully provided)

```
Chat Agent(LLM)              BG Shell Agent(Code)           Process
       │                            │                         │
       │ agent_allocate("bg_shell") │                         │
       │───────────────────────────▶│ Popen(cmd)              │
       │                            │────────────────────────▶│
       │                            │                         │
       │                            │ poll: read output       │
       │                            │ "password for root:"    │
       │                            │◀────────────────────────│
       │                            │                         │
       │                            │ INPUT_NEEDED:300:       │
       │                            │   sudo password         │
       │                            │                         │
       │◀── notify(SHELL_STDIN) ────│                         │
       │                            │ await queue.get(300)    │
       │                            │                         │
       │ respond_to_shell_prompt(   │                         │
       │   id, "mypassword123")     │                         │
       │───────────────────────────▶│ queue.put("mypass...")  │
       │                            │                         │
       │                            │ code model:             │
       │                            │ "mypassword123"         │
       │                            │   → "mypassword123\n"   │
       │                            │                         │
       │                            │ stdin.write(final)      │
       │                            │────────────────────────▶│ continues
       │                            │                         │
       │                            │ poll: DONE              │
       │◀── notify(DONE) ──────────│                         │
```

### 4.2 Timeout Flow

```
BG Shell Agent                        Process
       │                                 │
       │ INPUT_NEEDED:60:confirm [y/N]  │
       │ queue.get(timeout=60)          │ blocked on read()
       │ ... 60s ...                    │
       │ → None (timeout)               │
       │                                 │
       │ code model secondary decision: │
       │ "timeout after 60s,            │
       │  safe default: answer N"       │
       │                                 │
       │ stdin.write("N\n")             │
       │────────────────────────────────▶│
       │                                 │
       │ OR: "process is hung, kill"    │
       │ → KILL                          │
```

### 4.3 Multiple Stdin Requests

```
BG Shell Agent
       │
       │ INPUT_NEEDED:300:password (seq=0)
       │ → request_id: stdin_abc_0
       │ → await queue, got "mypassword"
       │ → code model → "mypassword\n"
       │ → stdin.write(...)
       │
       │ poll: read next output
       │
       │ INPUT_NEEDED:60:confirm [Y/n] (seq=1)
       │ → request_id: stdin_abc_1
       │ → await queue, got "Y"
       │ → code model → "Y\n"
       │ → stdin.write(...)
       │
       │ poll: process completes → DONE
```

Each request has independent `request_id` and `asyncio.Queue`. Sequential by nature — the next `INPUT_NEEDED` is only issued after the current one is resolved.

## 5. Error Handling

| Scenario | Handling |
|----------|----------|
| stdin pipe write fails (process exited) | Catch `BrokenPipeError`/`OSError`, code model decides DONE or KILL |
| `respond_to_shell_prompt` with invalid request_id | Return error message; chat LLM can retry |
| Same request replied twice | First `put()` pops from `_stdin_queues`; second call returns "already handled" |
| Tool called outside INPUT_NEEDED state | No matching queue → return error message |
| Code model returns unparseable decision | Existing JSON parse fallback applies; default to CONTINUE |
| Process exits while waiting for stdin | `proc.poll() is not None` detected in loop; skip queue wait, read remaining output → DONE |
| Docker container crash | `read_background_output` catches; KILL path cleanup |
| Memory leak from abandoned queues | `_cleanup_stdin_queues` in `finally` block wakes all waiters |

## 6. Files Changed

| File | Change |
|------|--------|
| `hatsume/plugins/hatsume-plugin/infra.py` | `start_background_cmd()`: add `stdin=subprocess.PIPE` |
| `hatsume/plugins/hatsume-plugin/prompts.py` | Extend `BACKGROUND_SHELL_DECISION_PROMPT` with `INPUT_NEEDED`; add `BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT` |
| `hatsume/plugins/hatsume-plugin/graph/agents.py` | `_run_background_shell()`: stdin detection, queue wait, code model mediation, stdin write; `_stdin_queues` dict; `_write_stdin()`; `_cleanup_stdin_queues()` |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | New `respond_to_shell_prompt` tool |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Register `respond_to_shell_prompt` in `chat_agent` tools |

## 7. Testing Strategy

### Unit Tests
- `_write_stdin()`: success, process exited, broken pipe, missing newline
- `_cleanup_stdin_queues()`: wakes waiters, removes keys
- `respond_to_shell_prompt` tool: valid id, invalid id, double-reply
- Decision prompt parsing: all new `INPUT_NEEDED` format variants

### Integration Tests
- Full flow: spawn process that reads stdin → INPUT_NEEDED → tool call → stdin write → process completes
- Timeout: spawn process, never reply → timeout → code model fallback
- Multi-request: process with 2 interactive prompts → 2 stdin cycles
- Error recovery: process exits mid-wait → graceful cleanup

### Manual Verification
- Real command: `sudo apt install ...` requiring password
- Real command: `gh auth login` requiring browser fallback token
