"""Built-in agent registry for agent_dispatch tool."""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Callable, Coroutine, Iterator, Literal, overload

# Handler: async (task: str, user_id: int) -> str
AgentHandler = Callable[[str, int], Coroutine[Any, Any, str]]


def _validate_agent_group_id(group_id: int) -> int:
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
        raise ValueError("group_id must be a positive integer")
    return group_id

# ---------------------------------------------------------------------------
# Agent state tracking (in-memory)
# ---------------------------------------------------------------------------
_AGENT_STATES: dict[str, list[dict]] = {}
_current_agent_instance_id: ContextVar[str | None] = ContextVar(
    "hatsume_current_agent_instance_id",
    default=None,
)


@contextmanager
def bind_agent_instance(instance_id: str) -> Iterator[str]:
    """Bind the owning Agent instance for the current task."""
    token: Token[str | None] = _current_agent_instance_id.set(instance_id)
    try:
        yield instance_id
    finally:
        _current_agent_instance_id.reset(token)


@overload
def get_current_agent_instance_id(*, required: Literal[True] = True) -> str: ...


@overload
def get_current_agent_instance_id(*, required: Literal[False]) -> str | None: ...


def get_current_agent_instance_id(*, required: bool = True) -> str | None:
    instance_id = _current_agent_instance_id.get()
    if instance_id is None and required:
        raise RuntimeError("Agent instance is not bound")
    return instance_id


def add_agent_instance(name: str, *, group_id: int, **kwargs: Any) -> str:
    """Create a new agent instance and return its instance_id."""
    resolved_group_id = _validate_agent_group_id(group_id)
    instance_id = f"{name}_{uuid.uuid4().hex[:8]}"
    state: dict[str, Any] = {
        "instance_id": instance_id,
        "name": name,
        "group_id": resolved_group_id,
    }
    state.update(kwargs)
    _AGENT_STATES.setdefault(name, []).append(state)
    return instance_id


def set_agent_state(
    name: str,
    *,
    group_id: int,
    instance_id: str | None = None,
    **kwargs: Any,
) -> str:
    """Create or update agent instance state. Returns instance_id.

    If instance_id is provided, updates that specific instance.
    If no instance_id and a running instance exists, updates the latest one
    (upsert semantics, used by handlers that call set_agent_state after
    _run_and_notify already created the instance).
    Otherwise creates a new instance.
    """
    resolved_group_id = _validate_agent_group_id(group_id)
    instances = _AGENT_STATES.setdefault(name, [])

    if instance_id is not None:
        for inst in instances:
            if (
                inst.get("instance_id") == instance_id
                and inst.get("group_id") == resolved_group_id
            ):
                inst.update(kwargs)
                return instance_id
        # instance_id not found — create a new one with this id
        state = {
            "instance_id": instance_id,
            "name": name,
            "group_id": resolved_group_id,
        }
        state.update(kwargs)
        instances.append(state)
        return instance_id

    # If a running instance exists, update the latest one (upsert)
    for inst in reversed(instances):
        if (
            inst.get("status") == "running"
            and inst.get("group_id") == resolved_group_id
        ):
            inst.update(kwargs)
            return str(inst["instance_id"])

    # Otherwise create a new instance
    return add_agent_instance(name, group_id=resolved_group_id, **kwargs)


def get_agent_state(name: str, group_id: int) -> dict | None:
    """Return the most recently added state for an agent name, or None."""
    resolved_group_id = _validate_agent_group_id(group_id)
    instances = [
        instance
        for instance in _AGENT_STATES.get(name, [])
        if instance.get("group_id") == resolved_group_id
    ]
    return instances[-1] if instances else None


def get_agent_instance(name: str, group_id: int, instance_id: str) -> dict | None:
    """Return one exact Agent instance without crossing group ownership."""
    resolved_group_id = _validate_agent_group_id(group_id)
    return next(
        (
            instance
            for instance in _AGENT_STATES.get(name, [])
            if instance.get("group_id") == resolved_group_id
            and instance.get("instance_id") == instance_id
        ),
        None,
    )


def has_running_agent_task(name: str, group_id: int, task: str) -> bool:
    """Return whether this group already runs the same normalized task."""
    normalized_task = str(task).strip()
    resolved_group_id = _validate_agent_group_id(group_id)
    return any(
        instance.get("status") == "running"
        and instance.get("group_id") == resolved_group_id
        and str(instance.get("task", "")).strip() == normalized_task
        for instance in _AGENT_STATES.get(name, [])
    )


def get_running_instances(group_id: int) -> list[dict]:
    """Return currently running Agent instances owned by one group."""
    resolved_group_id = _validate_agent_group_id(group_id)
    result: list[dict] = []
    for instances in _AGENT_STATES.values():
        for inst in instances:
            if (
                inst.get("status") == "running"
                and inst.get("group_id") == resolved_group_id
            ):
                result.append(inst)
    return result


def is_agent_running(name: str, group_id: int) -> bool:
    """Return True if at least one instance of this agent is running."""
    resolved_group_id = _validate_agent_group_id(group_id)
    return any(
        inst.get("status") == "running"
        and inst.get("group_id") == resolved_group_id
        for inst in _AGENT_STATES.get(name, [])
    )


def get_running_agent_instance(name: str) -> dict | None:
    """Return the active instance for an agent across all groups."""
    return next(
        (
            instance
            for instance in reversed(_AGENT_STATES.get(name, []))
            if instance.get("status") == "running"
        ),
        None,
    )


def get_unfinished_agent_instances() -> list[dict]:
    """Return every still-running Agent instance across all groups.

    Used by runtime shutdown and the self-evolution Skill to decide whether
    work must wait: an Agent counts as unfinished when its tracked
    instance state says ``running``, or when its asyncio task is still being
    tracked and has not finished. A running instance whose task is also
    tracked is counted once.
    """
    result: list[dict] = []
    seen_instance_ids: set[str] = set()
    for instances in _AGENT_STATES.values():
        for inst in instances:
            if inst.get("status") == "running":
                instance_id = str(inst.get("instance_id", ""))
                if instance_id:
                    seen_instance_ids.add(instance_id)
                result.append(inst)
    for instance_id, (group_id, task) in _agent_tasks.items():
        if not task.done() and instance_id not in seen_instance_ids:
            result.append(
                {
                    "instance_id": instance_id,
                    "name": "background_task",
                    "group_id": group_id,
                    "status": "running",
                }
            )
    return result


def get_agent_context(name: str, group_id: int) -> str:
    """Return the context string from the latest agent instance, or empty str."""
    state = get_agent_state(name, group_id)
    if state is None:
        return ""
    return str(state.get("context", ""))


# ---------------------------------------------------------------------------
# Stdin injection infrastructure (for background_shell agent)
# ---------------------------------------------------------------------------
_stdin_queues: dict[str, asyncio.Queue[str | None]] = {}
_stdin_request_groups: dict[str, int] = {}
_agent_tasks: dict[str, tuple[int, asyncio.Task[Any]]] = {}


def register_stdin_request(
    request_id: str,
    group_id: int,
    queue: asyncio.Queue[str | None],
) -> None:
    _stdin_queues[request_id] = queue
    _stdin_request_groups[request_id] = _validate_agent_group_id(group_id)


def pop_stdin_request(
    request_id: str,
    group_id: int,
) -> asyncio.Queue[str | None] | None:
    if _stdin_request_groups.get(request_id) != _validate_agent_group_id(group_id):
        return None
    _stdin_request_groups.pop(request_id, None)
    return _stdin_queues.pop(request_id, None)


def _discard_stdin_request(request_id: str) -> None:
    _stdin_request_groups.pop(request_id, None)
    _stdin_queues.pop(request_id, None)


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


def _cleanup_stdin_queues(proc_id: str, group_id: int) -> None:
    """Wake all pending stdin queue waiters for the given proc_id.

    Called during agent shutdown to prevent dangling awaiters.
    """
    prefix = f"stdin_{proc_id}_"
    for rid in list(_stdin_queues.keys()):
        if (
            rid.startswith(prefix)
            and _stdin_request_groups.get(rid) == _validate_agent_group_id(group_id)
        ):
            q = _stdin_queues.pop(rid, None)
            _stdin_request_groups.pop(rid, None)
            if q is not None:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass


def track_agent_task(
    instance_id: str,
    group_id: int,
    task: asyncio.Task[Any],
) -> None:
    resolved_group_id = _validate_agent_group_id(group_id)
    _agent_tasks[instance_id] = (resolved_group_id, task)

    def _forget(done_task: asyncio.Task[Any]) -> None:
        current = _agent_tasks.get(instance_id)
        if current is not None and current[1] is done_task:
            _agent_tasks.pop(instance_id, None)

    task.add_done_callback(_forget)


def untrack_agent_task(instance_id: str) -> None:
    """Remove a task from the unfinished snapshot after its handler completes."""
    _agent_tasks.pop(instance_id, None)


async def shutdown_group_agents(group_id: int) -> None:
    resolved_group_id = _validate_agent_group_id(group_id)
    tasks = [
        task
        for owner_group_id, task in _agent_tasks.values()
        if owner_group_id == resolved_group_id and not task.done()
    ]
    for task in tasks:
        task.cancel()
    for request_id, owner_group_id in list(_stdin_request_groups.items()):
        if owner_group_id != resolved_group_id:
            continue
        queue = _stdin_queues.get(request_id)
        _discard_stdin_request(request_id)
        if queue is not None:
            queue.put_nowait(None)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def shutdown_all_agents() -> None:
    group_ids = {
        group_id for group_id, _task in _agent_tasks.values()
    } | set(_stdin_request_groups.values())
    for group_id in group_ids:
        await shutdown_group_agents(group_id)


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

def _extract_visible_agent_text(content: Any) -> str:
    """Extract visible text from an agent message without reasoning metadata."""
    from ..utils import strip_thinking_tags

    if isinstance(content, str):
        return strip_thinking_tags(content).strip()

    if not isinstance(content, list):
        return strip_thinking_tags(str(content or "")).strip()

    text_parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            text = part
        elif isinstance(part, Mapping):
            part_type = str(part.get("type", "")).lower()
            if part_type in {"reasoning", "thinking", "thought"}:
                continue
            text_value = part.get("text")
            if isinstance(text_value, str):
                text = text_value
            elif isinstance(part.get("content"), (str, list)):
                text = _extract_visible_agent_text(part["content"])
            else:
                text = ""
        else:
            text = ""

        text = strip_thinking_tags(text).strip()
        if text:
            text_parts.append(text)

    return "\n".join(text_parts)


async def _invoke_agent_until_tool(
    agent: Any,
    agent_input: dict[str, Any],
    *,
    recursion_limit: int = 20,
) -> str | None:
    """Run an agent until its tool node returns, without a follow-up model call."""
    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.errors import GraphInterrupt

    streamed_messages: list[Any] = []
    stream = agent.astream(
        agent_input,
        {"recursion_limit": recursion_limit},
        stream_mode="updates",
    )
    try:
        async for event in stream:
            if not isinstance(event, dict):
                continue
            for node_name, update in event.items():
                if not isinstance(update, dict):
                    continue
                messages = update.get("messages")
                if isinstance(messages, list):
                    streamed_messages.extend(messages)
                if node_name != "tools" or not isinstance(messages, list):
                    continue
                for message in reversed(messages):
                    if isinstance(message, ToolMessage):
                        return str(message.content)
    finally:
        try:
            await stream.aclose()
        except GraphInterrupt:
            # LangGraph can surface its internal interrupt when a stream is
            # closed immediately after the tool node emits its result.
            pass

    for message in reversed(streamed_messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = _extract_visible_agent_text(message.content)
            if text:
                return text
    return None


def _get_coding_agent_tools() -> list[Any]:
    """Build the coding-agent tool list without creating an import cycle."""
    from .tools import (
        generate_image,
        search_image,
        shell_executor,
        skill_create,
        skill_download,
        skill_loader,
        skill_remove,
        web_search
    )

    return [
        shell_executor,
        skill_loader,
        web_search,
        search_image,
        skill_remove,
        skill_download,
        skill_create,
        generate_image,
    ]


def _get_sandbox_computer_use_tools() -> list[Any]:
    """Build the isolated desktop and browser toolset."""
    from .tools import (
        chrome_click,
        chrome_focus,
        chrome_inspect,
        chrome_open,
        chrome_set_text,
        gui_click,
        gui_click_coordinates,
        gui_drag,
        gui_focus,
        gui_inspect,
        gui_key,
        gui_launch,
        gui_screenshot,
        gui_set_text,
        gui_type,
        load_skill,
        shell_executor,
        view_image,
        web_search,
    )

    return [
        web_search,
        gui_inspect,
        gui_click,
        gui_click_coordinates,
        gui_drag,
        gui_focus,
        gui_set_text,
        gui_key,
        gui_type,
        gui_launch,
        gui_screenshot,
        chrome_open,
        chrome_inspect,
        chrome_click,
        chrome_focus,
        chrome_set_text,
        view_image,
        shell_executor,
        load_skill,
    ]


async def _run_web_researcher(task: str, user_id: int) -> str:
    """Search the web with one tool and return results via agent_dispatch."""
    from langchain.agents import create_agent
    from langchain.messages import AIMessage, HumanMessage
    from tenacity import stop_after_attempt

    from ..models import get_lite_model
    from ..prompts import WEB_RESEARCHER_PROMPT
    from .tools import shell_executor, skill_loader, web_search
    from .tools import set_shell_executor_limit

    set_shell_executor_limit(3)
    researcher = create_agent(
        get_lite_model(),
        tools=[web_search, shell_executor, skill_loader],
        system_prompt=WEB_RESEARCHER_PROMPT,
    )
    response = await researcher.with_retry(stop_after_attempt=3).ainvoke(
        {"messages": [HumanMessage(task)]},
        {"recursion_limit": 30},
    )
    for message in reversed(response.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = _extract_visible_agent_text(message.content)
            if text:
                return text
    return "网络研究未返回报告。"


async def _run_sandbox_computer_use(task: str, user_id: int) -> str:
    """Operate the shared GUI sandbox with Jev-controlled routing."""
    from langchain.agents import create_agent
    from langchain.messages import AIMessage, HumanMessage, ToolMessage
    from tenacity import stop_after_attempt

    from ..config import SANDBOX_COMPUTER_USE_MAX_ITERATIONS
    from ..models import get_code_model, get_jev_model, get_lite_model
    from ..prompts import SANDBOX_COMPUTER_USE_PROMPT
    from ..skills import get_skill_manager
    from .sandbox_computer_use import CoordinatorDeps, SandboxComputerUseCoordinator
    from .systemone import post_systemone
    from .tools import set_shell_executor_limit
    from .tools import (
        chrome_click, chrome_focus, chrome_inspect, chrome_open, chrome_set_text,
        gui_click, gui_click_coordinates, gui_drag, gui_inspect, gui_key, gui_launch,
        gui_screenshot, gui_set_text, gui_type, view_image,
    )

    async def jev(state: dict[str, Any], questions: dict[str, Any]) -> Any:
        return await post_systemone(get_jev_model(), state, questions)

    async def inspect_gui(application: str = "") -> Any:
        return await gui_inspect.ainvoke({"application": application})

    async def inspect_chrome(target_id: str = "") -> Any:
        return await chrome_inspect.ainvoke({"target_id": target_id})

    async def bounded(
        kind: str,
        state: dict[str, Any],
        tools: list[Any],
        *,
        model: Any | None = None,
        context_mode: str = "none",
        limit_tool_calls: bool = True,
        stop_after_tool: bool = False,
        chrome_inspect_context: Any | None = None,
    ) -> str:
        from langchain_core.tools import StructuredTool

        call_state = {"used": False}
        limited_tools = []
        for original_tool in tools:
            async def limited_call(_tool=original_tool, **kwargs: Any) -> Any:
                if limit_tool_calls and call_state["used"]:
                    return "该受限 Agent 已经执行过一次工具调用。"
                if limit_tool_calls:
                    call_state["used"] = True
                return await _tool.ainvoke(kwargs)

            limited_tools.append(
                StructuredTool.from_function(
                    coroutine=limited_call,
                    name=original_tool.name,
                    description=original_tool.description,
                    args_schema=original_tool.args_schema,
                )
            )
        llm_state = {**state, "task": task}
        branch_instruction = {
            "chrome_set_text": (
                "必须调用 chrome_set_text 恰好一次并实际完成输入。"
                "element_id 必须使用 state 中 element_id 的当前 ID；"
                "text 必须是从 task 提取出的最终输入文字，不要只返回说明或把工具调用留给下一轮。"
            ),
            "set_text": (
                "必须调用 set_text 工具恰好一次。text 要从 task 提取为最终输入文字，"
                "不要只返回说明。"
            ),
            "focus_key": "必须调用 focus_key 工具恰好一次，并从 task 提取要发送的按键。",
            "focus_type": "必须调用 focus_type 工具恰好一次，并从 task 提取要输入的最终文字。",
        }.get(kind)
        if branch_instruction:
            llm_state["branch_instruction"] = branch_instruction
        if context_mode in {"open", "chrome_set_text", "finish_report"}:
            llm_state["screenshot"] = await gui_screenshot.ainvoke({})
        if context_mode in {"open", "finish_report"}:
            llm_state["gui_inspect"] = await gui_inspect.ainvoke({})
        has_chrome_window = (
            context_mode == "open"
            or any(
                isinstance(window, dict) and window.get("kind") == "chrome"
                for window in (state.get("windows", []) or [])
            )
        )
        if context_mode in {"chrome_set_text"} or has_chrome_window:
            if chrome_inspect_context is not None:
                llm_state["chrome_inspect"] = chrome_inspect_context
            else:
                try:
                    llm_state["chrome_inspect"] = await chrome_inspect.ainvoke({})
                except Exception as exc:
                    llm_state["chrome_inspect"] = f"Chrome inspect unavailable: {exc}"
        selected_model = model or get_code_model()
        model_name = getattr(selected_model, "model_name", None) or getattr(
            selected_model, "model", None
        ) or ("lite_model" if model is not None else "code_model")
        print(
            f"[sandbox_computer_use] entering bounded_llm kind={kind!r} "
            f"model={model_name!r} context_mode={context_mode!r} "
            f"tools={[tool.name for tool in limited_tools]!r}"
        )
        branch = create_agent(
            selected_model,
            limited_tools,
            system_prompt=(
                f"{SANDBOX_COMPUTER_USE_PROMPT}\n\n"
                f"Complete only branch: {kind}.\n"
                "If branch_instruction is present in the task state, follow it exactly."
            ),
        )
        agent_input = {"messages": [HumanMessage(json.dumps(llm_state, ensure_ascii=False))]}
        if stop_after_tool:
            tool_result = await _invoke_agent_until_tool(branch, agent_input)
            if tool_result is not None:
                print(
                    f"[sandbox_computer_use] bounded_llm stopped after tool kind={kind!r}"
                )
                return tool_result
            response = await branch.with_retry(stop_after_attempt=3).ainvoke(
                agent_input,
                {"recursion_limit": 20},
            )
        else:
            response = await branch.with_retry(stop_after_attempt=3).ainvoke(
                agent_input,
                {"recursion_limit": 20},
            )
        print(f"[sandbox_computer_use] bounded_llm completed kind={kind!r} model={model_name!r}")
        for message in reversed(response.get("messages", [])):
            if isinstance(message, AIMessage) and not message.tool_calls:
                text = _extract_visible_agent_text(message.content)
                if text:
                    return text
            if isinstance(message, ToolMessage):
                return str(message.content)
            return f"{kind} branch completed without a textual result."

    def screenshot_path(value: Any) -> str:
        """Extract the sandbox screenshot path returned by gui_screenshot."""
        decoded = value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                decoded = value
        path = decoded.get("path") if isinstance(decoded, dict) else decoded
        if not isinstance(path, str) or not path.strip():
            raise RuntimeError(f"截图工具未返回有效路径：{value!r}")
        path = path.strip()
        return path if path.startswith(("file://", "http://", "https://")) else f"file://{path}"

    async def screenshot_coordinate_click(state: dict[str, Any]) -> str:
        """Run the coordinate branch as exactly screenshot -> vision -> click."""
        screenshot = await gui_screenshot.ainvoke({})
        image_url = screenshot_path(screenshot)
        vision = await view_image.ainvoke({
            "image_url": image_url,
            "prompt": (
                "分析这张原始桌面截图，定位 task 指定的目标控件。"
                "只返回可供 gui_click_coordinates 使用的 JSON："
                "{\"x\":整数,\"y\":整数,\"button\":\"left|right|middle\",\"clicks\":1或2}。"
                "原点是截图左上角，单位是原始截图像素；找不到或不能确定时返回简短错误。"
                f"\n任务：{task}"
            ),
        })
        return await bounded(
            "screenshot_coordinate_click",
            {
                **state,
                "screenshot": screenshot,
                "image_url": image_url,
                "vision_result": vision,
                "branch_instruction": (
                    "必须调用 gui_click_coordinates 恰好一次。"
                    "只根据 vision_result 提取 x、y、button、clicks，不要调用其他工具或返回说明。"
                ),
            },
            [gui_click_coordinates],
            model=get_lite_model(),
            stop_after_tool=True,
        )

    async def screenshot_coordinate_drag(state: dict[str, Any]) -> str:
        """Run the drag branch as exactly screenshot -> vision -> drag."""
        screenshot = await gui_screenshot.ainvoke({})
        image_url = screenshot_path(screenshot)
        selected_window = state.get("selected_window") or {}
        app_id = str(selected_window.get("app_id") or "")
        vision = await view_image.ainvoke({
            "image_url": image_url,
            "prompt": (
                "分析这张原始桌面截图，定位 task 指定的拖拽目标。"
                "只返回可供 gui_drag 使用的 JSON："
                "{\"start_x\":整数,\"start_y\":整数,\"end_x\":整数,"
                "\"end_y\":整数,\"speed\":正数}。"
                "必须提供拖拽起点和终点；原点是截图左上角，单位是原始截图像素；"
                "找不到或不能确定时返回简短错误。"
                f"\n任务：{task}\napp_id：{app_id}"
            ),
        })
        return await bounded(
            "screenshot_coordinate_drag",
            {
                **state,
                "screenshot": screenshot,
                "image_url": image_url,
                "vision_result": vision,
                "branch_instruction": (
                    "必须调用 gui_drag 恰好一次。使用 state.selected_window.app_id 作为 app_id，"
                    "只根据 vision_result 提取起点、终点和 speed，不要调用其他工具或返回说明。"
                ),
            },
            [gui_drag],
            model=get_lite_model(),
            stop_after_tool=True,
        )

    async def branch(kind: str, state: dict[str, Any]) -> str:
        if kind == "screenshot_coordinate_click":
            return await screenshot_coordinate_click(state)
        if kind == "screenshot_coordinate_drag":
            return await screenshot_coordinate_drag(state)
        tools = {
            "open_application": [gui_launch],
            "open_webpage": [chrome_open],
            "finish_report": [gui_screenshot, view_image],
            "jev_fallback": [gui_screenshot, view_image],
        }.get(kind, [gui_screenshot, view_image])
        context_mode = {"open_application": "open", "open_webpage": "open", "finish_report": "finish_report"}.get(kind, "none")
        model = get_lite_model() if kind in {"open_application", "open_webpage"} else None
        return await bounded(
            kind,
            state,
            tools,
            model=model,
            context_mode=context_mode,
            stop_after_tool=kind in {"open_application", "open_webpage"},
        )

    async def native_action(operation: str, element: dict[str, Any], task_text: str) -> str:
        element_id = str(element["id"])
        if operation == "click":
            return await gui_click.ainvoke({"element_id": element_id})
        tools = {"set_text": [gui_set_text], "focus_key": [gui_key], "focus_type": [gui_type]}[operation]
        return await bounded(
            operation,
            {"task": task_text, "element": element, "element_id": element_id},
            tools,
            stop_after_tool=True,
        )

    async def chrome_action(operation: str, element: dict[str, Any], task_text: str) -> str:
        element_id = str(element["id"])
        if operation == "chrome_click":
            return await chrome_click.ainvoke({"element_id": element_id})
        if operation == "chrome_focus":
            return await chrome_focus.ainvoke({"element_id": element_id})
        latest_inspection = await chrome_inspect.ainvoke({})
        latest_data = latest_inspection
        if isinstance(latest_inspection, str):
            try:
                latest_data = json.loads(latest_inspection)
            except json.JSONDecodeError:
                latest_data = None
        latest_elements = (
            latest_data.get("elements", [])
            if isinstance(latest_data, dict)
            else []
        )
        refreshed_element = next(
            (
                candidate for candidate in latest_elements
                if isinstance(candidate, dict)
                and candidate.get("backendNodeId") == element.get("backendNodeId")
            ),
            None,
        )
        if isinstance(refreshed_element, dict) and refreshed_element.get("id"):
            element = {**element, **refreshed_element}
            element_id = str(element["id"])
            print(
                f"[sandbox_computer_use] refreshed Chrome element id "
                f"{str(element_id)!r} by backendNodeId={element.get('backendNodeId')!r}"
            )
        return await bounded(
            operation,
            {"task": task_text, "element": element, "element_id": element_id},
            [chrome_set_text],
            model=get_lite_model(),
            context_mode="chrome_set_text",
            stop_after_tool=True,
            chrome_inspect_context=latest_inspection,
        )

    return await SandboxComputerUseCoordinator(
        task,
        CoordinatorDeps(
            jev,
            inspect_gui,
            inspect_chrome,
            native_action,
            chrome_action,
            branch,
            policy_prompt=SANDBOX_COMPUTER_USE_PROMPT,
        ),
        max_iterations=SANDBOX_COMPUTER_USE_MAX_ITERATIONS,
    ).run()

async def _run_coding_agent(task: str, user_id: int) -> str:
    """Execute coding agent task using shell_executor + claude-code-agent skill.

    Reads the claude-code-agent skill file as the system prompt, which
    instructs the LLM to call `claude -p` via shell_executor for all
    coding work rather than writing code directly.

    Returns the final result text (after advance-model rephrasing).
    """
    from langchain.agents import create_agent
    from langchain.messages import HumanMessage
    from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter

    from ..models import get_code_model
    from ..prompts import CODING_AGENT_PROMPT, build_skill_prompt
    from .tools import set_shell_executor_limit
    from ..skills import get_skill_manager

    coding_agent = create_agent(
        get_code_model(),
        _get_coding_agent_tools(),
        system_prompt=CODING_AGENT_PROMPT + "\n\n" + build_skill_prompt(get_skill_manager().list_skills()),
    )

    set_shell_executor_limit(None)  # coding_agent: no call count or timeout cap

    from langchain_core.messages import AIMessage, ToolMessage

    result = ""
    streamed_messages: list[Any] = []
    try:
        # Runnable.with_retry() does not retry streaming calls.
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential_jitter(),
            reraise=True,
        ):
            with attempt:
                streamed_messages.clear()
                async for event in coding_agent.astream(
                    {"messages": [HumanMessage(task)]},
                    {"recursion_limit": 400},
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
                    result = _extract_visible_agent_text(msg.content)
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
        ensure_container_running,
        get_background_process,
        start_background_cmd,
        read_background_output,
        kill_background_cmd,
    )
    from .nodes import inject_agent_notification
    from .tools import _agent_notification_callback
    from ..group_runtime import get_current_group_id

    group_id = get_current_group_id()
    instance_id = get_current_agent_instance_id()

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

    raw = _extract_visible_agent_text(parse_response.content)
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

    notified_user_name = None
    if user_id != 0:
        try:
            from ..group_runtime import group_runtime_registry
            from ..utils import get_group_member_name

            notified_user_name = await get_group_member_name(
                group_runtime_registry.get_bot(group_id),
                group_id,
                user_id,
            )
        except Exception as e:
            print(f"❌ background_shell user lookup failed: user={user_id} err={e}")
    
    if not cmd.strip():
        return "background_shell: no command found in task."

    # ── Step 2: Spawn background process ──
    proc_id = f"bgshell_{uuid.uuid4().hex[:8]}"
    await ensure_container_running(group_id)
    tmp = start_background_cmd(cmd, proc_id, group_id=group_id)

    # ── Step 3: Poll loop ──
    check_interval = 30  # initial default, seconds
    elapsed = 0
    offset = 0
    full_output = ""
    last_decision = ""

    set_agent_state(
        "background_shell",
        group_id=group_id,
        instance_id=instance_id,
        status="running",
        task=task,
        user_id=user_id,
        started_at=_time.time(),
        proc_id=proc_id,
        stdin_seq=0,
    )

    try:
        while True:
            await asyncio.sleep(check_interval)
            elapsed += check_interval

            new_output, offset = read_background_output(tmp, offset)
            full_output += new_output

            # Check if process is still alive
            proc_entry = get_background_process(proc_id, group_id=group_id)
            if proc_entry is None:
                # Process was killed externally
                last_decision = "KILL"
                break

            proc, _ = proc_entry
            proc_alive = proc.poll() is None

            # ── Timeout check ──
            if elapsed >= total_timeout:
                remaining = kill_background_cmd(proc_id, group_id=group_id)
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
            decision = _extract_visible_agent_text(decision_response.content).upper()

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
                    f"(SYSTEM) Agent 'background_shell' 执行中的中间输出。\n"
                    f"任务：{task[:300]}\n"
                    f"Agent 仍在后台运行中（已耗时 {elapsed}s / {total_timeout}s）。\n"
                    f"以下是命令的输出：\n\n"
                    f"{full_output}"
                )
                print("Injecting command intermediate output to graph")
                inject_agent_notification(
                    user_id=user_id,
                    group_id=group_id,
                    agent_name="background_shell",
                    result=notify_msg,
                    task=task,
                    notified_user_name=notified_user_name,
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

                agent_state = get_agent_instance(
                    "background_shell",
                    group_id,
                    instance_id,
                )
                seq = agent_state.get("stdin_seq", 0) if agent_state else 0
                request_id = f"stdin_{proc_id}_{seq}"
                if agent_state:
                    agent_state["stdin_seq"] = seq + 1
                    agent_state["stdin_request_id"] = request_id

                # Create queue and notify chat agent
                queue: asyncio.Queue[str | None] = asyncio.Queue()
                register_stdin_request(request_id, group_id, queue)

                notify_msg = (
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
                    group_id=group_id,
                    agent_name="background_shell",
                    result=notify_msg,
                    task=task,
                    notified_user_name=notified_user_name,
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
                    _discard_stdin_request(request_id)
                    if agent_state is not None:
                        agent_state["stdin_request_id"] = None

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
                resolution = _extract_visible_agent_text(resolution_response.content)

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
                    register_stdin_request(request_id, group_id, queue)
                    if agent_state is not None:
                        agent_state["stdin_request_id"] = request_id

                    reissue_msg = (
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
                        group_id=group_id,
                        agent_name="background_shell",
                        result=reissue_msg,
                        task=task,
                        notified_user_name=notified_user_name,
                        start_conversation_cb=_agent_notification_callback,
                    )

                    try:
                        raw_text = await asyncio.wait_for(
                            queue.get(), timeout=reissue_timeout
                        )
                    except asyncio.TimeoutError:
                        raw_text = None
                    finally:
                        _discard_stdin_request(request_id)
                        if agent_state is not None:
                            agent_state["stdin_request_id"] = None

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
                        resolution = _extract_visible_agent_text(
                            resolution_response.content
                        )

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
        kill_background_cmd(proc_id, group_id=group_id)
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        kill_background_cmd(proc_id, group_id=group_id)
        return "background_shell: internal error."
    finally:
        _cleanup_stdin_queues(proc_id, group_id)

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

    remaining = kill_background_cmd(proc_id, group_id=group_id)
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
    name="web_researcher",
    description=(
        "用于网络热点与名词搜索的 Agent。"
        "chat_agent 需要搜索网络时必须通过 agent_dispatch 派发给此 Agent，"
        "仅当用户只提供了关键词或问题时，才调用此 Agent 进行网络搜索。若用户提供了URL或网站域名，则应首选 coding_agent。"
        "task 应包含完整问题、关键词、时间范围及所需来源；完成后返回带来源链接的报告。"
    ),
    handler=_run_web_researcher,
)
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
    name="sandbox_computer_use",
    description=(
        "沙盒桌面与网站自动化专用 Agent。仅当用户要求注册账号、自动化操作网站或控制沙盒 GUI 时，"
        "才通过此 Agent 执行。如果用户的需求可以使用脚本解决，必须优先使用 coding_agent。"
        "该 Agent 全局只能同时运行一个实例，派发前先检查当前 Agent 状态。"
        "你需要将所有必要的信息告诉此 Agent，如要填写的信息、网站URL、账号名、密码、秘钥等。"
    ),
    handler=_run_sandbox_computer_use,
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
