"""Thin async adapter over the official MCP Python SDK."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from .models import MCPServerConfig, MCPToolInfo


def _expand(value: str) -> str:
    return os.path.expandvars(value)


def connection_key(config: MCPServerConfig) -> tuple[Any, ...]:
    """Identify configs that address the same MCP server."""
    if config.url:
        parsed = urlsplit(_expand(config.url))
        endpoint = urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/") or "/",
                parsed.query,
                "",
            )
        )
        headers = tuple(
            sorted((key.lower(), _expand(value)) for key, value in config.headers.items())
        )
        return ("http", endpoint, headers)
    return (
        "stdio",
        _expand(config.command or ""),
        tuple(_expand(item) for item in config.args),
        tuple(sorted((key, _expand(value)) for key, value in config.env.items())),
    )


@asynccontextmanager
async def _session(config: MCPServerConfig) -> AsyncIterator[ClientSession]:
    if config.transport == "stdio":
        if not config.command:
            raise ValueError("stdio MCP server 缺少 command")
        params = StdioServerParameters(
            command=_expand(config.command),
            args=[_expand(item) for item in config.args],
            env={**os.environ, **{key: _expand(value) for key, value in config.env.items()}},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    if not config.url:
        raise ValueError("HTTP MCP server 缺少 url")
    if config.transport == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(_expand(config.url), headers={k: _expand(v) for k, v in config.headers.items()}) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(_expand(config.url)) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


class MCPConnection:
    """One transport-owning worker retained for a single conversation."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._queue: asyncio.Queue[tuple[str, tuple[Any, ...], asyncio.Future[Any]]] = (
            asyncio.Queue()
        )
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] | None = None
        self._failure: BaseException | None = None

    async def start(self) -> None:
        if self._task is None:
            loop = asyncio.get_running_loop()
            self._ready = loop.create_future()
            self._task = asyncio.create_task(
                self._run(), name=f"mcp-connection:{self.config.name}"
            )
        assert self._ready is not None
        try:
            await asyncio.shield(self._ready)
        except BaseException:
            # A manager-level timeout cancels the waiter, not the worker that
            # owns the transport. Stop that worker so a failed connection is
            # not left running outside the conversation lifecycle.
            if self._task is not None and not self._task.done():
                self._task.cancel()
            raise

    async def _run(self) -> None:
        current: asyncio.Future[Any] | None = None
        try:
            async with _session(self.config) as session:
                assert self._ready is not None
                if not self._ready.done():
                    self._ready.set_result(None)
                while True:
                    operation, args, current = await self._queue.get()
                    if operation == "close":
                        if not current.done():
                            current.set_result(None)
                        current = None
                        return
                    try:
                        if operation == "list":
                            result = await session.list_tools()
                        else:
                            result = await session.call_tool(args[0], arguments=args[1])
                    except Exception as exc:
                        if not current.done():
                            current.set_exception(exc)
                    else:
                        if not current.done():
                            current.set_result(result)
                    current = None
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._failure = exc
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(exc)
            if current is not None and not current.done():
                current.set_exception(exc)
            while not self._queue.empty():
                _, _, pending = self._queue.get_nowait()
                if not pending.done():
                    pending.set_exception(exc)

    async def _submit(self, operation: str, *args: Any) -> Any:
        await self.start()
        if self._task is None or self._task.done():
            raise RuntimeError("MCP connection is closed") from self._failure
        future = asyncio.get_running_loop().create_future()
        await self._queue.put((operation, args, future))
        try:
            done, _ = await asyncio.wait(
                (future, self._task), return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            future.cancel()
            raise
        if future in done:
            return future.result()
        raise RuntimeError("MCP connection closed unexpectedly") from self._failure

    async def list_tools(self, server_name: str) -> list[MCPToolInfo]:
        result = await self._submit("list")
        return [
            MCPToolInfo(
                server=server_name,
                name=item.name,
                description=str(item.description or ""),
                input_schema=dict(item.inputSchema),
            )
            for item in result.tools
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = await self._submit("call", tool_name, arguments)
        text = _result_text(result)
        return f"MCP 工具返回错误：{text}" if result.isError else text

    async def close(self) -> None:
        if self._task is None:
            return
        if not self._task.done():
            future = asyncio.get_running_loop().create_future()
            await self._queue.put(("close", (), future))
            done, _ = await asyncio.wait(
                (future, self._task), return_when=asyncio.FIRST_COMPLETED
            )
            if future not in done:
                raise RuntimeError("MCP connection closed unexpectedly") from self._failure
        await self._task

    async def abort(self) -> None:
        """Cancel a connection whose transport or request has timed out."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass


def _result_text(result: CallToolResult) -> str:
    chunks: list[str] = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            chunks.append(str(text))
        elif getattr(item, "type", "") == "resource":
            chunks.append(str(item))
    if result.structuredContent:
        chunks.append(str(result.structuredContent))
    return "\n".join(chunks) or "MCP 工具调用完成，但没有返回文本。"
