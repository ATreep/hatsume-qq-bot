"""Sandbox Channel handler that injects messages into chat_agent's queue."""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

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

        with bind_group_runtime(runtime):
            if conv_state.is_graph_running:
                # Keep Sandbox Channel input marked as a system trigger so the
                # human node can preserve trigger semantics while normalizing
                # the queued message into a HumanMessage.
                from ..graph.nodes import make_system_trigger_message

                conv_state.human_queue.append(
                    make_system_trigger_message(
                        channel_message.content,
                        "sandbox_channel",
                    )
                )
                conv_state.human_source_queue.append(source_entry)
                print(
                    "💬 [sandbox_channel] Injected message into queue "
                    f"(group={channel_message.group_id}, "
                    f"agent={channel_message.agent_name}, "
                    f"len={len(channel_message.content)})"
                )
            else:
                print(
                    "💬 [sandbox_channel] Starting conversation with injected message "
                    f"(group={channel_message.group_id}, "
                    f"agent={channel_message.agent_name})"
                )
                _start_conv_for_trigger(
                    channel_message.user_id or 0,
                    channel_message.group_id,
                    channel_message.content,
                    trigger_type="sandbox_channel",
                )
    except Exception as exc:
        print(f"❌ Error handling Sandbox Channel message: {exc}")
        traceback.print_exc()


def setup_sandbox_channel_handler(server: SandboxChannelSocketServer) -> None:
    """Register the Sandbox Channel handler with the socket server."""
    server.register_handler(handle_sandbox_channel_message)
    print("✅ Sandbox Channel handler registered with socket server")
