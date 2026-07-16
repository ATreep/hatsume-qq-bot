"""Built-in agent registry for agent_dispatch tool."""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from typing import Any, Callable, Coroutine

# Handler: async (task: str, user_id: int) -> str
AgentHandler = Callable[[str, int], Coroutine[Any, Any, str]]

# ---------------------------------------------------------------------------
# Agent state tracking (in-memory)
# ---------------------------------------------------------------------------
_AGENT_STATES: dict[str, list[dict]] = {}


def add_agent_instance(name: str, **kwargs: Any) -> str:
    """Create a new agent instance and return its instance_id."""
    instance_id = f"{name}_{uuid.uuid4().hex[:8]}"
    state: dict[str, Any] = {"instance_id": instance_id, "name": name}
    state.update(kwargs)
    _AGENT_STATES.setdefault(name, []).append(state)
    return instance_id


def set_agent_state(name: str, instance_id: str | None = None, **kwargs: Any) -> str:
    """Create or update agent instance state. Returns instance_id.

    If instance_id is provided, updates that specific instance.
    If no instance_id and a running instance exists, updates the latest one
    (upsert semantics, used by handlers that call set_agent_state after
    _run_and_notify already created the instance).
    Otherwise creates a new instance.
    """
    instances = _AGENT_STATES.setdefault(name, [])

    if instance_id is not None:
        for inst in instances:
            if inst.get("instance_id") == instance_id:
                inst.update(kwargs)
                return instance_id
        # instance_id not found — create a new one with this id
        state = {"instance_id": instance_id, "name": name}
        state.update(kwargs)
        instances.append(state)
        return instance_id

    # If a running instance exists, update the latest one (upsert)
    for inst in reversed(instances):
        if inst.get("status") == "running":
            inst.update(kwargs)
            return str(inst["instance_id"])

    # Otherwise create a new instance
    return add_agent_instance(name, **kwargs)


def get_agent_state(name: str) -> dict | None:
    """Return the most recently added state for an agent name, or None."""
    instances = _AGENT_STATES.get(name, [])
    return instances[-1] if instances else None


def get_running_instances() -> list[dict]:
    """Return all currently running agent instances across all agent types."""
    result: list[dict] = []
    for instances in _AGENT_STATES.values():
        for inst in instances:
            if inst.get("status") == "running":
                result.append(inst)
    return result


def is_agent_running(name: str) -> bool:
    """Return True if at least one instance of this agent is running."""
    return any(
        inst.get("status") == "running"
        for inst in _AGENT_STATES.get(name, [])
    )


def get_agent_context(name: str) -> str:
    """Return the context string from the latest agent instance, or empty str."""
    state = get_agent_state(name)
    if state is None:
        return ""
    return str(state.get("context", ""))


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
        proc.stdin.write(text.encode("utf-8"))  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
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


AGENT_REGISTRY: dict[str, dict] = {}

def register_agent(name: str, description: str, handler: AgentHandler) -> None:
    """Register a built-in agent."""
    AGENT_REGISTRY[name] = {"description": description, "handler": handler}


def get_agent_list() -> list[dict[str, str]]:
    """Return list of registered agents with name and description."""
    return [
        {"name": name, "description": info["description"]}
        for name, info in AGENT_REGISTRY.items()
    ]


def get_agent_handler(name: str) -> AgentHandler | None:
    """Return the handler for a registered agent, or None if not found."""
    info = AGENT_REGISTRY.get(name)
    return info["handler"] if info else None


# ---------------------------------------------------------------------------
# Built-in agent handler implementations
# ---------------------------------------------------------------------------

async def _run_coding_agent(task: str, user_id: int) -> str:
    """Execute coding agent task using shell_executor + claude-code-agent skill.

    Reads the claude-code-agent skill file as the system prompt, which
    instructs the LLM to call `claude -p` via shell_executor for all
    coding work rather than writing code directly.

    Returns the final result text (after advance-model rephrasing).
    """
    from langchain.agents import create_agent
    from langchain.messages import HumanMessage

    from ..models import get_code_model
    from ..prompts import CODING_AGENT_PROMPT, build_skill_prompt
    from .tools import shell_executor, skill_loader, search_web, skill_remove, skill_download, skill_create, generate_image, set_shell_executor_limit
    from ..skills import get_skill_manager

    coding_agent = create_agent(
        get_code_model(),
        [shell_executor, skill_loader, search_web, skill_remove, skill_download, skill_create, generate_image],
        system_prompt=CODING_AGENT_PROMPT + "\n\n" + build_skill_prompt(get_skill_manager().list_skills()),
    )

    set_shell_executor_limit(None)  # coding_agent: no shell_executor call limit

    from langchain_core.messages import AIMessage, ToolMessage

    result = ""
    streamed_messages: list[Any] = []
    try:
        async for event in coding_agent.astream(
            {"messages": [HumanMessage(task)]},
            {"recursion_limit": 200},
            stream_mode="updates",
        ):
            # Each event is {node_name: {state_update}}
            for _node_name, update in event.items():
                if isinstance(update, dict) and "messages" in update:
                    streamed_messages.extend(update["messages"])

        # Extract final AI content from the last message
        if streamed_messages:
            for msg in reversed(streamed_messages):
                if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                    result = str(msg.content)
                    break
    except Exception as e:
        import traceback
        print("❌ _run_coding_agent failed")
        traceback.print_exc()

        # Collect last 3 tool call args & tool outputs from streamed messages
        tool_call_entries: list[str] = []
        for msg in streamed_messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call_entries.append(
                        f"[Tool Call] {tc['name']}: {str(tc['args'])[:500]}"
                    )
            elif isinstance(msg, ToolMessage):
                tool_call_entries.append(
                    f"[Tool Output] {msg.name}: {str(msg.content)[:500]}"
                )

        # Keep only the last 3 entries
        recent_context = "\n".join(tool_call_entries[-6:])
        error_msg = f"任务执行失败：{e}"
        if recent_context:
            error_msg += f"\n\n最后3次工具调用日志：\n{recent_context}"
        return error_msg

    if result.strip() == "":
        return "没有返回任何内容。"
    else:
        return result


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
    from ..prompts import (
        BACKGROUND_SHELL_DECISION_PROMPT,
        BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT,
    )
    from ..infra import (
        start_background_cmd,
        read_background_output,
        kill_background_cmd,
        _background_procs,
    )
    from .nodes import inject_agent_notification, NOTIFY_MARK
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

    print(f"BG Shell Agent: \n{cmd=}\n{description=}\n{total_timeout=}")
    
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
        task=task,
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

            # ── Process exited on its own ──
            if not proc_alive:
                # Read any remaining output before finishing
                remaining, offset = read_background_output(tmp, offset)
                if remaining:
                    full_output += remaining
                last_decision = "DONE"
                break

            # ── Ask code model for decision ──
            decision_prompt = (
                f"## 任务描述\n{task}\n\n"
                f"## 终止条件\n{description}\n\n"
                f"## 当前命令的完整输出（包括历史输出与新增输出）\n"
                + "```\n" + (full_output if full_output.strip() else "(无历史输出)") + "\n```\n"
                + "\n\n## 当前命令新增输出\n"
                + "```\n" + (new_output if new_output.strip() else "(无新输出)") + "\n```\n"
                + f"\n\n## 状态\n"
                f"- 已耗时: {elapsed}s / {total_timeout}s\n"
                f"- 进程状态: {'运行中' if proc_alive else '已结束'}\n"
            )

            print(f"BG Shell Check Point: \n{decision_prompt}")

            decision_response = await code_model.ainvoke([
                SystemMessage(BACKGROUND_SHELL_DECISION_PROMPT),
                HumanMessage(decision_prompt),
            ])
            decision = str(decision_response.content).strip().upper()

            print(f"BG Shell Agent Decision: {decision}")

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
                    f"以下是命令的输出：\n\n"
                    f"{full_output}"
                )
                print("Injecting command intermediate output to graph")
                inject_agent_notification(
                    user_id=user_id,
                    group_id=_current_group_id or 0,
                    agent_name="background_shell",
                    result=notify_msg,
                    task=task,
                    start_conversation_cb=_agent_notification_callback,
                )
            elif decision.startswith("INPUT_NEEDED:"):
                # Parse: INPUT_NEEDED:<timeout>:<description>
                try:
                    parts = decision.split(":", 2)
                    stdin_timeout = int(parts[1])
                    stdin_description = parts[2] if len(parts) > 2 else "需要输入"
                except (IndexError, ValueError):
                    stdin_timeout = 300
                    stdin_description = "需要输入"

                agent_state = get_agent_state("background_shell")
                seq = agent_state.get("stdin_seq", 0) if agent_state else 0
                request_id = f"stdin_{proc_id}_{seq}"
                if agent_state:
                    agent_state["stdin_seq"] = seq + 1

                # Create queue and notify chat agent
                queue: asyncio.Queue[str | None] = asyncio.Queue()
                _stdin_queues[request_id] = queue

                notify_msg = (
                    f"{NOTIFY_MARK}:{user_id}:background_shell\n"
                    f"[SHELL_STDIN_REQUEST]\n"
                    f"request_id: {request_id}\n"
                    f"description: {stdin_description}\n"
                    f"context: {new_output}\n"
                    f"timeout: {stdin_timeout}s\n"
                    f"[/SHELL_STDIN_REQUEST]\n"
                    f"(SYSTEM) Agent 'background_shell' 进程正在等待输入，请将输入提示告知用户并向用户请求相关的输入信息。\n"
                    f"关联任务：{task[:300]}\n"
                    f"请使用 respond_to_shell_prompt 工具回复所需信息。"
                )
                print(f"BG Shell stdin request: {request_id=} {stdin_description=} {stdin_timeout=}")
                inject_agent_notification(
                    user_id=user_id,
                    group_id=_current_group_id or 0,
                    agent_name="background_shell",
                    result=notify_msg,
                    task=task,
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
                        check_interval = 15
                    else:
                        last_decision = "INPUT_FAILED"
                        check_interval = 5
                elif resolution.startswith("REISSUE:"):
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
                        task=task,
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
                            last_decision = "KILL"
                            break
                    else:
                        last_decision = "KILL"
                        break
                elif resolution.startswith("KILL"):
                    last_decision = "KILL"
                    break
                else:
                    # Unrecognized resolution, continue polling
                    last_decision = "INPUT_UNKNOWN"
                    check_interval = 30
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
    finally:
        _cleanup_stdin_queues(proc_id)

    # ── Step 4: Final cleanup and notification ──
    print("Last decision of BG Shell Agent: ", last_decision)
    if last_decision == "DONE":
        result_text = "命令执行结束。"
    elif last_decision == "KILL":
        result_text = "命令已被强制终止。"
    elif last_decision == "TIMEOUT":
        result_text = f"命令已超时（timeout = {total_timeout}s），被强制终止。"
    else:
        # Process ended on its own
        result_text = "命令已结束。"

    remaining = kill_background_cmd(proc_id)
    if remaining:
        full_output += remaining

    final_msg = (
        f"任务：{task[:300]}\n"
        f"总耗时：{elapsed}s\n"
        f"结果：{result_text}\n\n"
        f"完整输出：\n{full_output}"
    )
    return final_msg


# Register built-in agents (module-level, before any imports from this module)
register_agent(
    name="coding_agent",
    description=(
        "涉及编码、重构、分支合并、程序或依赖的安装、代码阅读与分析、文档检索与查阅、项目配置修改、Git/GitHub 操作等复杂任务，"
        "必须调用 coding_agent 完成，禁止自行通过其他工具（如 shell_executor）直接执行这些操作。"
        "你需要将所有必要的信息告诉此 Agent。此 Agent 可以自行操作沙盒或者创建、删除与读取必要的 Skills。"
    ),
    handler=_run_coding_agent,
)
register_agent(
    name="background_shell",
    description=(
        "在后台执行交互式或耗时较长的单个 shell 命令。"
        "一次仅支持执行一个命令操作。"
        "支持中间状态通知（如输出 auth URL 给用户），自动轮询检查，超时强制终止。"
        "适用于：认证流程、长时间编译、分批处理等场景。"
        "Task 参数说明：该 Agent 的 Task 必须包含 “具体的某一个Shell命令” “该命令的解释” “检测到什么输出时可以停止该命令的运行”"
    ),
    handler=_run_background_shell,
)
