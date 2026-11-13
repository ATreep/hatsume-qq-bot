"""Count chat tool rounds and enforce the initial user-facing tool call."""

import asyncio
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import HumanMessage, SystemMessage, ToolMessage
from ..runtime_events import (
    INJECTED_EVENT_TOOL,
    RuntimeEvent,
    event_messages,
    is_event_message,
    bind_tool_origin,
    reset_tool_origin,
)

CHAT_LOOP_DELEGATION_ROUNDS = 7
CHAT_LOOP_DELEGATION_MESSAGE = (
    "[SYSTEM] 你不应该调用太多次工具，请你立即将当前任务分发给 Agent，"
    "然后使用 send_text 工具向用户说明情况。"
)
MAX_SEND_TEXT_INVOCATIONS = 3
SEND_TEXT_FIRST_WARNING = (
    "You must call send_text first before calling any other tools."
)
SEND_TEXT_LAST_CHANCE_MESSAGE = (
    "[SYSTEM] 你已经调用 send_text 两次，现在只剩最后一次调用机会。"
    "请在所有任务完成后再调用 send_text。"
)
SEND_TEXT_LIMIT_WARNING = (
    "send_text invocation limit reached: at most three calls are allowed per chat invocation."
)


class SendTextFirstMiddleware(AgentMiddleware):
    """Require send_text first and limit it to three calls per chat invocation."""

    def __init__(self) -> None:
        self._send_text_started = False
        self._send_text_invocations = 0
        self._send_text_last_chance_reminded = False
        self._lock = asyncio.Lock()
        self._last_tool_name: str | None = None
        self._completion_checked = False

    def completion_reminder(self, group_id: int) -> list[Any]:
        """Check only the first completed invocation, independent of compaction."""
        if self._completion_checked:
            return []
        self._completion_checked = True
        print(
            f"[初芽] first invocation completed last_tool={self._last_tool_name!r} "
            f"send_tool_check={not (self._last_tool_name and self._last_tool_name.startswith('send_'))}",
            flush=True,
        )
        if self._last_tool_name and self._last_tool_name.startswith("send_"):
            return []
        return event_messages(RuntimeEvent(
            event_type="chat_loop",
            group_id=group_id,
            source="send_text_completion_check",
            text="初芽，请再次检查是否需要调用 send_text 工具；如果无需发送内容，可以直接结束。",
            payload={"last_tool_name": self._last_tool_name},
        ))

    @property
    def send_text_started(self) -> bool:
        """Whether this invocation attempted send_text, even if it failed."""
        return self._send_text_started

    @property
    def send_text_invocations(self) -> int:
        """Number of send_text attempts, including calls whose handler failed."""
        return self._send_text_invocations

    def _before_send_text(self) -> ToolMessage | None:
        if self._send_text_invocations >= MAX_SEND_TEXT_INVOCATIONS:
            print(
                "⚠️ [初芽] blocked send_text: invocation limit reached "
                f"({MAX_SEND_TEXT_INVOCATIONS})",
                flush=True,
            )
            return ToolMessage(
                content=SEND_TEXT_LIMIT_WARNING,
                tool_call_id="",
                name="send_text",
                status="error",
            )
        self._send_text_started = True
        self._send_text_invocations += 1
        print(
            f"[初芽] send_text invocation="
            f"{self._send_text_invocations}/{MAX_SEND_TEXT_INVOCATIONS}",
            flush=True,
        )
        return None

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Remind the model once after its second send_text attempt."""
        if (
            self._send_text_invocations < 2
            or self._send_text_last_chance_reminded
        ):
            return None
        self._send_text_last_chance_reminded = True
        print("[初芽] inserted send_text last-chance reminder", flush=True)
        return {"messages": [SystemMessage(content=SEND_TEXT_LAST_CHANCE_MESSAGE)]}

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    def retry_prompt(self, messages: list[Any]) -> SystemMessage | None:
        """Request one continuation when the agent ended without send_text."""
        if self._send_text_started:
            return None
        output = getattr(messages[-1], "content", "") if messages else ""
        print("⚠️ [初芽] ended without send_text; requesting one retry", flush=True)
        return SystemMessage(content=(
            "[SYSTEM] 你刚才直接结束了，但没有调用 send_text。"
            "你必须调用 send_text，并提供非空白的 text；空文本会报错，不支持静默模式。"
            f"\n你刚才的输出：\n{output}"
        ))

    @staticmethod
    def _tool_name(request: Any) -> str:
        tool_call = getattr(request, "tool_call", {})
        return str(tool_call.get("name", "")) if isinstance(tool_call, dict) else ""

    @staticmethod
    def _blocked_result(request: Any) -> ToolMessage:
        tool_call = getattr(request, "tool_call", {})
        tool_call_id = tool_call.get("id", "") if isinstance(tool_call, dict) else ""
        return ToolMessage(
            content=SEND_TEXT_FIRST_WARNING,
            tool_call_id=str(tool_call_id),
            name=str(tool_call.get("name", ""))
            if isinstance(tool_call, dict)
            else None,
            status="error",
        )

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name = self._tool_name(request)
        if tool_name == INJECTED_EVENT_TOOL:
            return ToolMessage(
                content="Runtime-only event receiver; model invocation is forbidden.",
                tool_call_id=str(request.tool_call.get("id", "")),
                name=tool_name,
                status="error",
            )
        async with self._lock:
            self._last_tool_name = tool_name
            if not self._send_text_started and tool_name != "send_text":
                print(
                    f"⚠️ [初芽] blocked first tool call: {tool_name!r}; "
                    "send_text is required first",
                    flush=True,
                )
                return self._blocked_result(request)
            if tool_name == "send_text":
                limit_result = self._before_send_text()
                if limit_result is not None:
                    limit_result.tool_call_id = str(request.tool_call.get("id", ""))
                    return limit_result
        token = bind_tool_origin(request.tool_call)
        try:
            return await handler(request)
        finally:
            reset_tool_origin(token)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name = self._tool_name(request)
        if tool_name == INJECTED_EVENT_TOOL:
            return ToolMessage(
                content="Runtime-only event receiver; model invocation is forbidden.",
                tool_call_id=str(request.tool_call.get("id", "")),
                name=tool_name,
                status="error",
            )
        self._last_tool_name = tool_name
        if not self._send_text_started and tool_name != "send_text":
            print(
                f"⚠️ [初芽] blocked first tool call: {tool_name!r}; "
                "send_text is required first",
                flush=True,
            )
            return self._blocked_result(request)
        if tool_name == "send_text":
            limit_result = self._before_send_text()
            if limit_result is not None:
                limit_result.tool_call_id = str(request.tool_call.get("id", ""))
                return limit_result
        token = bind_tool_origin(request.tool_call)
        try:
            return handler(request)
        finally:
            reset_tool_origin(token)


class ChatLoopDelegationMiddleware(AgentMiddleware):
    """Share one instance across MCP passes of a single chat invocation."""

    def __init__(self, initial_message_count: int) -> None:
        self.initial_message_count = initial_message_count
        self.reminder_id = f"chat-loop-delegation-{uuid4().hex}"
        self._seen_messages: set[str | int] = set()
        self._started = False
        self._rounds = 0
        self._reminded = False

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        if not self._started:
            self._seen_messages.update(
                message.id or id(message)
                for message in messages[: self.initial_message_count]
            )
            self._started = True
        # One AI message can request multiple tools: count rounds, not tools.
        # Keep the count outside history: compaction can remove earlier rounds.
        for message in messages:
            key = message.id or id(message)
            if key in self._seen_messages:
                continue
            self._seen_messages.add(key)
            if (
                message.type == "ai"
                and getattr(message, "tool_calls", None)
                and not is_event_message(message)
            ):
                self._rounds += 1
        print(f"[初芽] completed_tool_rounds={self._rounds}", flush=True)
        if self._rounds < CHAT_LOOP_DELEGATION_ROUNDS or self._reminded:
            return None
        self._reminded = True
        return {
            "messages": [
                HumanMessage(
                    content=CHAT_LOOP_DELEGATION_MESSAGE,
                    id=self.reminder_id,
                )
            ]
        }

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)
