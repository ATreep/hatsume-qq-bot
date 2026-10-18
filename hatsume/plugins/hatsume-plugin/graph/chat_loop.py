"""Count chat tool rounds and remind the model to delegate long tasks."""

from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import HumanMessage

CHAT_LOOP_DELEGATION_ROUNDS = 7
CHAT_LOOP_DELEGATION_MESSAGE = (
    "[SYSTEM] 你不应该调用太多次工具，请你立即将当前任务分发给 Agent，"
    "然后使用 send_text 工具向用户说明情况。"
)


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
