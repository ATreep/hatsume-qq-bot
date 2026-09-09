"""MCP discovery and invocation facade, always scoped to one group."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..group_runtime import get_current_group_id, validate_group_id
from .client import MCPConnection, connection_key
from .config_store import MCPConfigStore
from .models import MCPServerConfig, MCPToolInfo

MCP_DISCOVERY_TIMEOUT_SECONDS = 30


class MCPManager:
    def __init__(self, store: MCPConfigStore | None = None) -> None:
        self.store = store or MCPConfigStore()
        self._catalog: dict[tuple[int, tuple[Any, ...]], list[MCPToolInfo]] = {}
        self._connections: dict[tuple[int, tuple[Any, ...]], MCPConnection] = {}
        self._connection_locks: dict[
            tuple[int, tuple[Any, ...]], asyncio.Lock
        ] = {}
        self._discovery_locks: dict[
            tuple[int, tuple[Any, ...]], asyncio.Lock
        ] = {}

    def _group(self, group_id: int | None) -> int:
        return validate_group_id(group_id if group_id is not None else get_current_group_id())

    def list_servers(self, group_id: int | None = None) -> list[MCPServerConfig]:
        return self.store.list_servers(self._group(group_id))

    def add_server(
        self,
        config: MCPServerConfig,
        group_id: int | None = None,
        *,
        overwrite: bool = False,
    ) -> None:
        """Persist one validated Server in the current group's JSON directory."""
        group = self._group(group_id)
        self.store.validate_name(config.name)
        if self.store.get_group_server(group, config.name) is not None and not overwrite:
            raise ValueError(f"MCP server '{config.name}' 已存在。")
        self.store.save_server(group, config)
        self.clear_cache(group)

    def server(self, name: str, group_id: int | None = None) -> MCPServerConfig:
        result = self.store.get_server(self._group(group_id), name)
        if result is None:
            raise ValueError(f"MCP server '{name}' 不存在。")
        return result

    def _require_conversation(self, group: int) -> None:
        from ..group_runtime import group_runtime_registry

        runtime = group_runtime_registry.get_existing(group)
        if runtime is None or not runtime.conversation.is_graph_running:
            raise RuntimeError("MCP Server 只能在进行中的对话内连接。")

    async def _connection(
        self, group: int, config: MCPServerConfig
    ) -> tuple[tuple[int, tuple[Any, ...]], MCPConnection]:
        self._require_conversation(group)
        key = (group, connection_key(config))
        existing = self._connections.get(key)
        if existing is not None:
            print(
                f"♻️ [mcp] group={group} reuse server={config.name!r} "
                f"connected_as={existing.config.name!r}",
                flush=True,
            )
            return key, existing

        lock = self._connection_locks.setdefault(key, asyncio.Lock())
        async with lock:
            existing = self._connections.get(key)
            if existing is not None:
                print(
                    f"♻️ [mcp] group={group} reuse server={config.name!r} "
                    f"connected_as={existing.config.name!r}",
                    flush=True,
                )
                return key, existing
            connection = MCPConnection(config)
            print(
                f"🔌 [mcp] group={group} connecting server={config.name!r} "
                f"transport={config.transport}",
                flush=True,
            )
            await connection.start()
            self._connections[key] = connection
            print(
                f"✅ [mcp] group={group} connected server={config.name!r}",
                flush=True,
            )
            return key, connection

    async def discover_tools(self, name: str, group_id: int | None = None, *, refresh: bool = False) -> list[MCPToolInfo]:
        group = self._group(group_id)
        self._require_conversation(group)
        config = self.server(name, group)
        key = (group, connection_key(config))
        if not config.enabled:
            raise ValueError(f"MCP server '{config.name}' 已停用。")
        discovery_lock = self._discovery_locks.setdefault(key, asyncio.Lock())
        started = time.monotonic()
        async with discovery_lock:
            if not refresh and key in self._catalog:
                print(
                    f"📚 [mcp] group={group} catalog reuse server={config.name!r} "
                    f"tools={len(self._catalog[key])}",
                    flush=True,
                )
                return [
                    MCPToolInfo(
                        server=config.name,
                        name=item.name,
                        description=item.description,
                        input_schema=item.input_schema,
                    )
                    for item in self._catalog[key]
                ]

            print(
                f"🔎 [mcp] group={group} discovering tools server={config.name!r}",
                flush=True,
            )
            connection: MCPConnection | None = None
            try:
                # The deadline covers transport creation, session initialize,
                # and list_tools. Previously only list_tools was bounded.
                key, connection, tools = await asyncio.wait_for(
                    self._connect_and_discover(group, config),
                    timeout=MCP_DISCOVERY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                print(
                    f"⏱️ [mcp] group={group} discovery timeout "
                    f"server={config.name!r} after={time.monotonic() - started:.3f}s",
                    flush=True,
                )
                await self._discard_connection(key, connection)
                raise

            self._catalog[key] = tools
            print(
                f"✅ [mcp] group={group} discovered server={config.name!r} "
                f"tools={len(tools)} elapsed={time.monotonic() - started:.3f}s",
                flush=True,
            )
            return tools

    async def _connect_and_discover(
        self, group: int, config: MCPServerConfig
    ) -> tuple[tuple[int, tuple[Any, ...]], MCPConnection, list[MCPToolInfo]]:
        key, connection = await self._connection(group, config)
        tools = await connection.list_tools(config.name)
        return key, connection, tools

    async def _discard_connection(
        self,
        key: tuple[int, tuple[Any, ...]],
        connection: MCPConnection | None,
    ) -> None:
        active = self._connections.pop(key, None) or connection
        self._catalog.pop(key, None)
        if active is not None:
            await active.abort()

    async def call(self, server_name: str, tool_name: str, arguments: dict[str, Any], group_id: int | None = None) -> str:
        group = self._group(group_id)
        started = time.monotonic()
        print(
            f"▶️ [mcp] group={group} calling server={server_name!r} "
            f"tool={tool_name!r}",
            flush=True,
        )
        config = self.server(server_name, group)
        if not config.enabled:
            raise ValueError(f"MCP server '{config.name}' 已停用。")
        tools = await self.discover_tools(config.name, group)
        selected = next((item for item in tools if item.name == tool_name), None)
        if selected is None:
            raise ValueError(f"MCP 工具 '{tool_name}' 不存在。")
        _, connection = await self._connection(group, config)
        result = await asyncio.wait_for(
            connection.call_tool(selected.name, arguments), timeout=60
        )
        print(
            f"✅ [mcp] group={group} completed server={server_name!r} "
            f"tool={tool_name!r} elapsed={time.monotonic() - started:.3f}s",
            flush=True,
        )
        return result

    async def close_conversation(self, group_id: int | None = None) -> None:
        group = self._group(group_id)
        connections = [
            self._connections.pop(key)
            for key in list(self._connections)
            if key[0] == group
        ]
        for key in list(self._catalog):
            if key[0] == group:
                self._catalog.pop(key, None)
        for key in list(self._connection_locks):
            if key[0] == group:
                self._connection_locks.pop(key, None)
        for key in list(self._discovery_locks):
            if key[0] == group:
                self._discovery_locks.pop(key, None)
        if connections:
            print(
                f"🔌 [mcp] group={group} closing connections={len(connections)}",
                flush=True,
            )
            results = await asyncio.gather(
                *(connection.close() for connection in connections),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    print(
                        f"⚠️ [mcp] Failed to close conversation connection: {result}",
                        flush=True,
                    )
            print(f"✅ [mcp] group={group} connections closed", flush=True)

    async def close_all(self) -> None:
        groups = {key[0] for key in self._connections}
        for group in groups:
            await self.close_conversation(group)

    def clear_cache(self, group_id: int | None = None) -> None:
        if group_id is None:
            self._catalog.clear()
            return
        group = self._group(group_id)
        for key in list(self._catalog):
            if key[0] == group:
                self._catalog.pop(key, None)

    def set_enabled(self, name: str, enabled: bool, group_id: int | None = None) -> None:
        group = self._group(group_id)
        config = self.server(name, group)
        config.enabled = enabled
        self.store.save_server(group, config)
        self.clear_cache(group)

    def remove(self, name: str, group_id: int | None = None) -> bool:
        group = self._group(group_id)
        removed = self.store.remove_server(group, name)
        self.clear_cache(group)
        return removed


_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
