"""Sandbox-to-chat_agent channel system using Unix Domain Socket.

The channel allows coding_agent and servers running in the hatsume sandbox to inject messages
directly into chat_agent's message queue.

Sandbox Channel Protocol
-------------
Clients connect to Unix domain socket and send one channel message per connection as JSON:

    {
      "timestamp": <unix_timestamp_float>,
      "group_id": <positive_integer>,
      "user_id": <positive_integer or 0>,
      "agent_name": <optional_string>,
      "priority": "critical|normal|low",
      "content": <string>
    }

Server responds with "OK" or "INVALID" on success/failure, then closes connection.
"""

from __future__ import annotations

import asyncio
import json
import os
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

__all__ = [
    "SandboxChannelMessage",
    "SandboxChannelSocketServer",
    "get_or_create_sandbox_channel_server",
]


@dataclass
class SandboxChannelMessage:
    """Represents one Sandbox Channel message to inject into chat_agent."""

    timestamp: float
    group_id: int
    content: str
    user_id: int = 0  # 0 means anonymous/system
    agent_name: str = ""
    priority: str = "normal"  # "critical", "normal", "low"

    def is_valid(self) -> bool:
        """Validate channel message structure."""
        if self.group_id <= 0:
            return False
        if self.priority not in {"critical", "normal", "low"}:
            return False
        return bool(self.content.strip())


# Type for Sandbox Channel handlers
SandboxChannelHandler = Callable[[SandboxChannelMessage], Coroutine[Any, Any, None]]


class SandboxChannelSocketServer:
    """Unix domain socket server for Sandbox Channel messages from the sandbox."""

    def __init__(self, socket_path: str = "/tmp/hatsume_channel.sock") -> None:
        """Initialize the socket server.

        Args:
            socket_path: Path to Unix domain socket (e.g., /tmp/hatsume_channel.sock)
        """
        self.socket_path = socket_path
        self._handler: SandboxChannelHandler | None = None
        self._server: asyncio.Server | None = None

    def register_handler(self, handler: SandboxChannelHandler) -> None:
        """Register the channel message handler.

        Args:
            handler: Async callable that processes channel messages
        """
        self._handler = handler

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle an incoming Sandbox Channel connection.

        Each client connection sends one JSON channel message and receives a response.
        """
        try:
            # Read one line (newline-terminated JSON)
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not line:
                return

            # Parse channel message
            try:
                message_data = json.loads(line.decode("utf-8").strip())
                message = SandboxChannelMessage(**message_data)
            except (json.JSONDecodeError, TypeError, ValueError):
                writer.write(b"INVALID\n")
                await writer.drain()
                return

            # Validate channel message
            if not message.is_valid():
                writer.write(b"INVALID\n")
                await writer.drain()
                return

            # Dispatch to handler
            if self._handler:
                try:
                    await self._handler(message)
                    writer.write(b"OK\n")
                except Exception as exc:
                    print(f"❌ Error handling channel message: {exc}")
                    traceback.print_exc()
                    writer.write(b"ERROR\n")
            else:
                print("⚠️ No handler registered for the Sandbox Channel")
                writer.write(b"OK\n")

            await writer.drain()
        except asyncio.TimeoutError:
            writer.write(b"TIMEOUT\n")
            await writer.drain()
        except Exception as exc:
            print(f"❌ Socket handler error: {exc}")
            traceback.print_exc()
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self) -> None:
        """Start the Unix domain socket server.

        Creates and listens on the socket. Socket file is cleaned up if it already exists.
        """
        # Clean up old socket
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        try:
            self._server = await asyncio.start_unix_server(
                self._handle_client,
                path=self.socket_path,
            )
            # Make socket world-writable so sandbox can connect
            os.chmod(self.socket_path, 0o666)
            print(f"🔌 Sandbox Channel socket server listening on {self.socket_path}")
        except Exception as exc:
            print(f"❌ Failed to start Sandbox Channel socket server: {exc}")
            raise

    async def stop(self) -> None:
        """Stop the socket server gracefully."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            print("🛑 Sandbox Channel socket server stopped")

            # Clean up socket file
            if os.path.exists(self.socket_path):
                try:
                    os.unlink(self.socket_path)
                except OSError:
                    pass


# Global server instance
_sandbox_channel_server: SandboxChannelSocketServer | None = None


def get_or_create_sandbox_channel_server(socket_path: str = "/tmp/hatsume_channel.sock") -> SandboxChannelSocketServer:
    """Get or create the global Sandbox Channel socket server.

    Args:
        socket_path: Path to Unix domain socket

    Returns:
        The singleton SandboxChannelSocketServer instance.
    """
    global _sandbox_channel_server

    if _sandbox_channel_server is not None:
        return _sandbox_channel_server

    _sandbox_channel_server = SandboxChannelSocketServer(socket_path)
    return _sandbox_channel_server
