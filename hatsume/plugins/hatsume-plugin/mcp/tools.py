"""LangChain-facing MCP management and dynamic tool factories."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import StructuredTool, tool
from pydantic import Field, create_model

from .manager import get_mcp_manager
from .models import MCPServerConfig


def _log_tool(name: str, server: str = "") -> None:
    from ..group_runtime import get_current_group_id

    group = get_current_group_id(required=False)
    target = f" server={server!r}" if server else ""
    print(f"🔧 [mcp-tool] group={group or '?'} tool={name}{target}", flush=True)


def _connection_failure(server: str, exc: Exception) -> str:
    print(
        f"⚠️ [mcp] Skipping unavailable server {server!r}: "
        f"{type(exc).__name__}: {exc}",
        flush=True,
    )
    return f"错误：MCP Server '{server}' 连接失败，本轮已跳过。"


@tool
def mcp_add_server(
    name: str,
    description: str,
    transport: str = "stdio",
    command: str = "",
    server_args: list[str] | None = None,
    url: str = "",
    env: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """Add one MCP server JSON config under the current QQ group's MCP directory.

    This is a mutating operation available to users in the current group.
    Choose exactly one transport: ``stdio`` requires ``command`` (and optionally ``server_args``),
    while ``sse`` and ``streamable-http`` require ``url``. The server is saved
    in the current group's isolated directory, so it is not shared with other
    groups. Credentials should be supplied as environment/secret references
    rather than literal values. The server is enabled by default, but its
    tools are still loaded dynamically only when needed.

    Parameters:
        name: MCP service name. Use a short filename-safe value without ``/``,
            ``\\`` or control characters; it becomes the JSON filename.
        description: Brief human- and AI-readable explanation of what the
            service does. Do not put credentials or secrets here.
        transport: Connection type. Must be ``"stdio"``, ``"sse"`` or
            ``"streamable-http"``. Use ``"stdio"`` for a local process.
        command: Executable used to start a stdio server, such as ``npx``,
            ``python`` or an absolute path. Required for ``stdio``; leave
            empty for HTTP transports.
        server_args: Individual arguments for ``command``, for example
            ``["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]``.
            Pass one argument per list item, not one combined shell string.
        url: Endpoint URL for ``sse`` or ``streamable-http``, for example
            ``"https://example.com/mcp"``. Leave empty for ``stdio``.
        env: Environment variables for a stdio process as a string-to-string
            mapping. Prefer secret/environment references and never expose
            plaintext tokens, passwords or private keys in this config.
        headers: HTTP request headers for ``sse`` or ``streamable-http`` as a
            string-to-string mapping. Avoid putting plaintext credentials here.
    """
    _log_tool("mcp_add_server", name)
    try:
        config = MCPServerConfig.from_dict(
            {
                "name": name,
                "description": description,
                "transport": transport,
                "command": command or None,
                "args": server_args or [],
                "url": url or None,
                "env": env or {},
                "headers": headers or {},
            },
            filename=f"{name}.json",
        )
        get_mcp_manager().add_server(config)
    except Exception as exc:
        return f"错误：添加 MCP Server 失败：{exc}"
    return f"✅ MCP Server '{config.name}' 已添加到当前群配置。"


@tool
def mcp_list_servers() -> str:
    """列出当前群配置的 MCP Server 及其描述和启用状态。"""
    _log_tool("mcp_list_servers")
    servers = get_mcp_manager().list_servers()
    if not servers:
        return "当前群没有 MCP Server。"
    return "\n".join(f"- {item.name}：{item.description}（{'启用' if item.enabled else '停用'}）" for item in servers)


@tool
async def mcp_search_tools(query: str, server: str = "") -> str:
    """搜索当前群 MCP Server 的工具名称和描述，不会执行工具。"""
    _log_tool("mcp_search_tools", server)
    manager = get_mcp_manager()
    try:
        servers = [manager.server(server)] if server.strip() else manager.list_servers()
    except Exception as exc:
        return _connection_failure(server, exc)
    needle = query.casefold().strip()
    rows: list[str] = []
    failures: list[str] = []
    async def discover(item: Any) -> tuple[Any, list[Any] | None, Exception | None]:
        try:
            return item, await manager.discover_tools(item.name), None
        except Exception as exc:
            return item, None, exc

    results = await asyncio.gather(*(
        discover(item) for item in servers if item.enabled
    ))
    for item, infos, error in results:
        if error is not None:
            failures.append(_connection_failure(item.name, error))
            continue
        assert infos is not None
        for info in infos:
            haystack = f"{info.name} {info.description}".casefold()
            if not needle or needle in haystack:
                rows.append(f"- {item.name}/{info.name}：{info.description or '无描述'}")
    if rows:
        return "\n".join(rows[:30])
    return "\n".join(failures) or "没有找到匹配的 MCP 工具。"


@tool
async def mcp_load_tools(server: str, tools: list[str]) -> str:
    """把当前群指定 MCP 工具加载到本轮 Agent，不永久修改配置。

    成功后必须立即结束当前轮工具编排，不能再搜索或重复加载 MCP 工具；
    ai_node 会在下一次 Agent 调用时注入已加载工具。
    """
    _log_tool("mcp_load_tools", server)
    try:
        infos = await get_mcp_manager().discover_tools(server)
    except Exception as exc:
        return _connection_failure(server, exc)
    available = {item.name for item in infos}
    selected = [name for name in tools if name in available]
    if not selected:
        return "错误：没有可加载的 MCP 工具。"
    from ..group_runtime import get_current_group_runtime
    runtime = get_current_group_runtime()
    requested = list(runtime.mcp_requested_tools)
    for name in selected:
        pair = (server, name)
        if pair not in requested:
            requested.append(pair)
    runtime.mcp_requested_tools = requested
    return "MCP 工具已加入本轮待加载队列：" + json.dumps(selected, ensure_ascii=False)


@tool
def mcp_unload_tools(server: str = "", tools: list[str] | None = None) -> str:
    """从当前回合的动态工具请求队列中移除工具，不修改 JSON 配置。"""
    _log_tool("mcp_unload_tools", server)
    from ..group_runtime import get_current_group_runtime
    runtime = get_current_group_runtime()
    names = set(tools or [])
    before = len(runtime.mcp_requested_tools)
    runtime.mcp_requested_tools = [
        pair for pair in runtime.mcp_requested_tools
        if (server and pair[0] != server) or (names and pair[1] not in names)
    ]
    return f"已移除 {before - len(runtime.mcp_requested_tools)} 个本轮 MCP 工具请求。"


def consume_requested_tools() -> list[tuple[str, str]]:
    from ..group_runtime import get_current_group_runtime
    runtime = get_current_group_runtime()
    requested = list(runtime.mcp_requested_tools)
    runtime.mcp_requested_tools.clear()
    return requested


@tool
def mcp_status() -> str:
    """显示当前群 MCP Server 的配置状态。"""
    _log_tool("mcp_status")
    return mcp_list_servers.invoke({})


def get_mcp_management_tools() -> list[Any]:
    return [mcp_add_server, mcp_list_servers, mcp_search_tools, mcp_load_tools, mcp_unload_tools, mcp_status]


def _schema_model(name: str, schema: dict[str, Any]) -> type:
    fields: dict[str, tuple[Any, Any]] = {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
    for key in properties:
        fields[str(key)] = (Any, ... if key in required else None)
    return create_model(name, **fields) if fields else create_model(name, arguments=(dict[str, Any], Field(default_factory=dict)))


def make_dynamic_tools(server: str, infos: list[Any]) -> list[StructuredTool]:
    result: list[StructuredTool] = []
    manager = get_mcp_manager()
    for info in infos:
        model = _schema_model(f"MCP_{server}_{info.name}_Args", info.input_schema)

        async def invoke(_server=server, _name=info.name, **kwargs: Any) -> str:
            _log_tool(f"mcp__{_server}__{_name}", _server)
            try:
                return await manager.call(_server, _name, kwargs)
            except Exception as exc:
                return _connection_failure(_server, exc)

        result.append(StructuredTool.from_function(
            coroutine=invoke,
            name=f"mcp__{server}__{info.name}",
            description=info.description or f"调用 MCP Server {server} 的 {info.name}",
            args_schema=model,
        ))
    return result
