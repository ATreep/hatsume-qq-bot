"""Count chat tool rounds and enforce the initial user-facing tool call."""

import asyncio
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import HumanMessage, ToolMessage

CHAT_LOOP_DELEGATION_ROUNDS = 7
CHAT_LOOP_DELEGATION_MESSAGE = (
    "[SYSTEM] 你不应该调用太多次工具，请你立即将当前任务分发给 Agent，"
    "然后使用 send_text 工具向用户说明情况。"
)
SEND_TEXT_FIRST_WARNING = "You must call send_text first before calling any other tools."


class SendTextFirstMiddleware(AgentMiddleware):
    """Require the first executable tool call in one chat invocation to be send_text."""

    def __init__(self) -> None:
        self._send_text_started = False
        self._lock = asyncio.Lock()

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
            name=str(tool_call.get("name", "")) if isinstance(tool_call, dict) else None,
            status="error",
        )

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name = self._tool_name(request)
        async with self._lock:
            if not self._send_text_started:
                if tool_name != "send_text":
                    print(
                        f"⚠️ [chat_agent] blocked first tool call: {tool_name!r}; "
                        "send_text is required first",
                        flush=True,
                    )
                    return self._blocked_result(request)
                # Mark before execution: this records the first attempted call,
                # even if send_text later returns a validation or send error.
                self._send_text_started = True
                print("[chat_agent] first tool call accepted: send_text", flush=True)
        return await handler(request)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name = self._tool_name(request)
        if not self._send_text_started:
            if tool_name != "send_text":
                print(
                    f"⚠️ [chat_agent] blocked first tool call: {tool_name!r}; "
                    "send_text is required first",
                    flush=True,
                )
                return self._blocked_result(request)
            self._send_text_started = True
            print("[chat_agent] first tool call accepted: send_text", flush=True)
        return handler(request)


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
                for message in messages[:self.initial_message_count]
            )
            self._started = True
        # One AI message can request multiple tools: count rounds, not tools.
        # Keep the count outside history: compaction can remove earlier rounds.
        for message in messages:
            key = message.id or id(message)
            if key in self._seen_messages:
                continue
            self._seen_messages.add(key)
            if message.type == "ai" and getattr(message, "tool_calls", None):
                self._rounds += 1
        print(f"[chat_agent] completed_tool_rounds={self._rounds}", flush=True)
        if self._rounds < CHAT_LOOP_DELEGATION_ROUNDS or self._reminded:
            return None
        self._reminded = True
        return {"messages": [HumanMessage(
            content=CHAT_LOOP_DELEGATION_MESSAGE,
            id=self.reminder_id,
        )]}

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)
