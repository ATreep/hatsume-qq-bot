"""Sandbox Channel handler that injects messages into chat_agent's queue."""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from ..runtime_events import RuntimeEvent, enqueue_runtime_event
from ..group_runtime import bind_group_runtime, group_runtime_registry
from ..handlers.dialogue import _start_conv_for_trigger
from .sandbox_channel import SandboxChannelMessage

if TYPE_CHECKING:
    from .sandbox_channel import SandboxChannelSocketServer

__all__ = [
    "handle_sandbox_channel_message",
    "setup_sandbox_channel_handler",
]


async def handle_sandbox_channel_message(channel_message: SandboxChannelMessage) -> None:
    """Inject a Sandbox Channel message into the chat_agent queue."""
    if channel_message.group_id <= 0:
        print(
            "⚠️ Invalid group_id in Sandbox Channel message: "
            f"{channel_message.group_id}"
        )
        return

    try:
        runtime = group_runtime_registry.get_or_create(channel_message.group_id)
        conv_state = runtime.conversation

        source_entry = {
            "source_id": f"sandbox_channel_{channel_message.timestamp}",
            "text": channel_message.content,
            "people": [
                {
                    "user_id": channel_message.user_id,
                    "user_name": channel_message.agent_name or "Sandbox Channel",
                }
            ] if channel_message.user_id > 0 else [],
        }

        event = RuntimeEvent(
            event_type="sandbox_channel", source="sandbox_channel", group_id=channel_message.group_id,
            text=channel_message.content,
            payload={"timestamp": channel_message.timestamp, "user_id": channel_message.user_id,
                     "agent_name": channel_message.agent_name, "priority": channel_message.priority,
                     "source_record": source_entry},
        )
        with bind_group_runtime(runtime):
            if conv_state.is_graph_running:
                enqueue_runtime_event(conv_state, event)
                conv_state.human_source_queue.append(source_entry)
            else:
                _start_conv_for_trigger(channel_message.user_id or 0, channel_message.group_id, event)
    except Exception as exc:
        print(f"❌ Error handling Sandbox Channel message: {exc}")
        traceback.print_exc()


def setup_sandbox_channel_handler(server: SandboxChannelSocketServer) -> None:
    """Register the Sandbox Channel handler with the socket server."""
    server.register_handler(handle_sandbox_channel_message)
    print("✅ Sandbox Channel handler registered with socket server")
