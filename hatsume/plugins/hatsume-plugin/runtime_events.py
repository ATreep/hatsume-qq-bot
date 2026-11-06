"""Runtime-authored notifications, never human input or executable tool requests."""

from __future__ import annotations

from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

INJECTED_EVENT_TOOL = "receive_event__injected"
EVENT_MARKER = "hatsume_runtime_event"
EventType = Literal["agent", "timer", "hook", "sandbox_channel", "group_increase"]
EVENT_TYPES = {"agent", "timer", "hook", "sandbox_channel", "group_increase"}


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: EventType
    group_id: int
    text: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    notified_user_ids: tuple[int, ...] = ()
    correlation_id: str | None = None
    original_tool_name: str | None = None
    original_tool_call_id: str | None = None
    original_args: dict[str, Any] | None = None
    occurrence_key: str | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported runtime event type: {self.event_type}")
        if (
            isinstance(self.group_id, bool)
            or not isinstance(self.group_id, int)
            or self.group_id <= 0
        ):
            raise ValueError("Runtime event group_id must be a positive integer")
        if not self.source or not self.event_id:
            raise ValueError("Runtime event source and event_id are required")

    @property
    def dedup_key(self) -> str:
        return f"{self.group_id}:{self.event_type}:{self.source}:{self.occurrence_key or self.event_id}"


def stable_event_key(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def enqueue_runtime_event(state: Any, event: RuntimeEvent) -> bool:
    if state.group_id != event.group_id:
        raise ValueError("Runtime event belongs to another group")
    if any(
        isinstance(item, RuntimeEvent) and item.dedup_key == event.dedup_key
        for item in state.human_queue
    ):
        print(
            f"[runtime-event] duplicate group={event.group_id} type={event.event_type}",
            flush=True,
        )
        return False
    state.human_queue.append(event)
    print(
        f"[runtime-event] queued group={event.group_id} type={event.event_type} source={event.source} id={event.event_id}",
        flush=True,
    )
    return True


def event_messages(event: RuntimeEvent) -> list[Any]:
    call_id = f"evt_{event.event_id}"
    metadata = {EVENT_MARKER: event.event_id, "event_type": event.event_type}
    args = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "source": event.source,
        "correlation_id": event.correlation_id,
        "original_tool_name": event.original_tool_name,
        "original_tool_call_id": event.original_tool_call_id,
        "original_args": event.original_args,
    }
    body = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "source": event.source,
        "group_id": event.group_id,
        "created_at": event.created_at,
        "text": event.text,
        "payload": event.payload,
        "notified_user_ids": list(event.notified_user_ids),
        "correlation_id": event.correlation_id,
        "occurrence_key": event.occurrence_key,
    }
    return [
        AIMessage(
            content="",
            id=f"{call_id}_call",
            additional_kwargs=metadata,
            tool_calls=[
                {
                    "name": INJECTED_EVENT_TOOL,
                    "args": args,
                    "id": call_id,
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(body, ensure_ascii=False),
            id=f"{call_id}_result",
            name=INJECTED_EVENT_TOOL,
            tool_call_id=call_id,
            additional_kwargs=metadata,
        ),
    ]


def is_event_message(message: Any) -> bool:
    return bool(getattr(message, "additional_kwargs", {}).get(EVENT_MARKER))


def consume_inputs(items: list[Any]) -> list[Any]:
    """Batch adjacent human content, preserving event positions and complete pairs."""
    messages: list[Any] = []
    human: list[Any] = []

    def flush() -> None:
        if human:
            messages.append(HumanMessage(content=list(human)))
            human.clear()

    for item in items:
        if isinstance(item, RuntimeEvent):
            flush()
            messages.extend(event_messages(item))
        else:
            human.append(item)
    flush()
    return messages


def safe_cutoff(messages: list[Any], cutoff: int) -> int:
    """Move a cut left until no tool result loses its initiating AI call."""
    cutoff = max(0, min(cutoff, len(messages)))
    while cutoff:
        left_calls = {
            call["id"]: i
            for i, message in enumerate(messages[:cutoff])
            for call in getattr(message, "tool_calls", [])
        }
        crossing = [
            left_calls[message.tool_call_id]
            for message in messages[cutoff:]
            if isinstance(message, ToolMessage) and message.tool_call_id in left_calls
        ]
        if not crossing:
            break
        cutoff = min(crossing)
    return cutoff


def assemble_input(
    history: list[Any], current: list[Any], memory: list[Any], auxiliary: list[dict]
) -> list[Any]:
    """Never rewrap an event result as human text or split a call/result pair."""
    current = list(current)
    if auxiliary:
        background = [{"type": "text", "text": "## 背景聊天记录："}, *auxiliary]
        index = next(
            (
                i
                for i, message in enumerate(current)
                if isinstance(message, HumanMessage)
            ),
            None,
        )
        if index is None:
            memory = [*memory, HumanMessage(content=background)]
        else:
            message = current[index]
            content = (
                message.content
                if isinstance(message.content, list)
                else [{"type": "text", "text": message.content}]
            )
            current[index] = message.model_copy(
                update={
                    "content": [
                        *background,
                        {"type": "text", "text": "## 当前聊天记录："},
                        *content,
                    ]
                }
            )
    return [*history, *memory, *current]


_current_tool_origin: ContextVar[dict[str, Any] | None] = ContextVar(
    "hatsume_tool_origin", default=None
)
_tool_origins: OrderedDict[tuple[int, str, str], dict[str, Any]] = OrderedDict()
MAX_TOOL_ORIGINS = 1024


def bind_tool_origin(call: dict[str, Any]):
    """Bind only genuine model execution metadata, never synthetic calls."""
    return _current_tool_origin.set(
        {
            "original_tool_name": call.get("name"),
            "original_tool_call_id": call.get("id"),
            "original_args": call.get("args"),
        }
    )


def reset_tool_origin(token: Any) -> None:
    _current_tool_origin.reset(token)


def remember_tool_origin(group_id: int, kind: str, correlation_id: Any) -> None:
    origin = _current_tool_origin.get()
    if origin is None or not origin.get("original_tool_call_id"):
        return
    key = (group_id, kind, str(correlation_id))
    _tool_origins[key] = dict(origin)
    _tool_origins.move_to_end(key)
    while len(_tool_origins) > MAX_TOOL_ORIGINS:
        _tool_origins.popitem(last=False)


def tool_origin(group_id: int, kind: str, correlation_id: Any) -> dict[str, Any]:
    # Old DB records, CLI-created tasks and evicted entries have no known origin.
    return dict(_tool_origins.get((group_id, kind, str(correlation_id)), {}))


def eviction_cutoff(messages: list[Any], requested: int = 2) -> int:
    """Evict at least the oldest complete exchange, including multi-tool results."""
    cutoff = min(requested, len(messages))
    while cutoff < len(messages) and safe_cutoff(messages, cutoff) != cutoff:
        cutoff += 1
    return cutoff
