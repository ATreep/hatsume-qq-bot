"""Focused offline tests for group-isolated MCP configuration and prompts."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "hatsume/plugins/hatsume-plugin"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _setup() -> None:
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN),
        ("hatsume.plugins.hatsume-plugin.mcp", PLUGIN / "mcp"),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod
    if "hatsume.plugins.hatsume-plugin.config" not in sys.modules:
        _load("hatsume.plugins.hatsume-plugin.config", PLUGIN / "config.py")
    if "hatsume.plugins.hatsume-plugin.group_runtime" not in sys.modules:
        _load("hatsume.plugins.hatsume-plugin.group_runtime", PLUGIN / "group_runtime.py")


def test_json_store_isolated_by_group(tmp_path):
    _setup()
    models = _load("hatsume.plugins.hatsume-plugin.mcp.models", PLUGIN / "mcp/models.py")
    store_mod = _load("hatsume.plugins.hatsume-plugin.mcp.config_store", PLUGIN / "mcp/config_store.py")
    store = store_mod.MCPConfigStore(tmp_path)
    store.save_server(
        123,
        models.MCPServerConfig(name="one", description="first", command="echo"),
    )
    store.save_server(
        456,
        models.MCPServerConfig(name="two", description="second", command="echo"),
    )
    assert [item.name for item in store.list_servers(123)] == ["one"]
    assert [item.name for item in store.list_servers(456)] == ["two"]
    assert store.get_server(123, "two") is None


def test_global_servers_are_visible_and_group_files_override(tmp_path):
    _setup()
    models = _load("hatsume.plugins.hatsume-plugin.mcp.models", PLUGIN / "mcp/models.py")
    store_mod = _load("hatsume.plugins.hatsume-plugin.mcp.config_store", PLUGIN / "mcp/config_store.py")
    store = store_mod.MCPConfigStore(tmp_path, global_root=tmp_path)
    store.save_server(
        999,
        models.MCPServerConfig(name="shared", description="group version", command="group"),
    )
    (tmp_path / "global.json").write_text(
        '{"name":"global","description":"all groups","command":"echo"}',
        encoding="utf-8",
    )
    (tmp_path / "shared.json").write_text(
        '{"name":"shared","description":"global version","command":"global"}',
        encoding="utf-8",
    )

    assert [item.name for item in store.list_servers(123)] == ["global", "shared"]
    assert store.get_server(123, "global").command == "echo"
    assert store.get_server(123, "shared").command == "global"
    assert store.get_server(999, "shared").command == "group"


def test_mcp_description_prompt_does_not_include_secrets():
    _setup()
    prompts = _load("hatsume.plugins.hatsume-plugin.prompts", PLUGIN / "prompts.py")
    result = prompts.build_mcp_server_prompt([
        {"name": "github", "description": "查询仓库"},
    ])
    assert "github" in result
    assert "查询仓库" in result
    assert "token" not in result.lower()


def test_store_ignores_incomplete_transport_config(tmp_path):
    _setup()
    models = _load("hatsume.plugins.hatsume-plugin.mcp.models", PLUGIN / "mcp/models.py")
    store_mod = _load("hatsume.plugins.hatsume-plugin.mcp.config_store", PLUGIN / "mcp/config_store.py")
    store = store_mod.MCPConfigStore(tmp_path)
    store.save_server(
        123,
        models.MCPServerConfig(name="broken", description="x", command="echo"),
    )
    # A config read must be rejected when stdio has no command.
    (tmp_path / "123" / "bad.json").write_text(
        '{"name":"bad","description":"x","transport":"stdio"}', encoding="utf-8"
    )
    assert [item.name for item in store.list_servers(123)] == ["broken"]


def test_add_server_tool_exposes_server_args_field():
    _setup()
    for suffix in ("models", "config_store", "client", "manager", "tools"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")
    tools = sys.modules["hatsume.plugins.hatsume-plugin.mcp.tools"]
    properties = tools.mcp_add_server.args_schema.model_json_schema()["properties"]
    assert "server_args" in properties
    assert "v__args" not in properties
    tool_description = tools.mcp_add_server.description
    for name in (
        "name",
        "description",
        "transport",
        "command",
        "server_args",
        "url",
        "env",
        "headers",
    ):
        assert f"{name}:" in tool_description
    assert "enabled:" not in tool_description
    assert "autoload:" not in tool_description
    assert "default_allowed:" not in tool_description
    assert not {"enabled", "autoload", "default_allowed"}.intersection(properties)


def test_add_server_tool_persists_for_current_group(tmp_path):
    _setup()
    for suffix in ("models", "config_store", "client", "manager", "tools"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    group_runtime = sys.modules["hatsume.plugins.hatsume-plugin.group_runtime"]
    manager_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.manager"]
    store_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.config_store"]
    tools = sys.modules["hatsume.plugins.hatsume-plugin.mcp.tools"]
    manager = manager_mod.MCPManager(store_mod.MCPConfigStore(tmp_path))

    original_manager = tools.get_mcp_manager
    try:
        tools.get_mcp_manager = lambda: manager
        runtime = group_runtime.GroupRuntime(987)
        group_runtime.set_current_group_runtime(runtime)

        result = tools.mcp_add_server.invoke(
            {
                "name": "local",
                "description": "local command",
                "command": "echo",
                "server_args": ["hello"],
            }
        )
        assert "已添加" in result
        saved = tmp_path / "987" / "local.json"
        assert saved.exists()
        assert '"enabled": true' in saved.read_text(encoding="utf-8")
        assert '"args": [' in saved.read_text(encoding="utf-8")
    finally:
        tools.get_mcp_manager = original_manager
        group_runtime.set_current_group_runtime(None)


def test_search_tools_skips_unavailable_server_and_keeps_healthy_results():
    _setup()
    for suffix in ("models", "config_store", "client", "manager", "tools"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    tools = sys.modules["hatsume.plugins.hatsume-plugin.mcp.tools"]

    class Manager:
        def list_servers(self):
            return [
                types.SimpleNamespace(name="broken", enabled=True),
                types.SimpleNamespace(name="healthy", enabled=True),
            ]

        async def discover_tools(self, name):
            if name == "broken":
                raise ConnectionError("connection refused")
            return [
                types.SimpleNamespace(
                    name="lookup", description="Look up local data"
                )
            ]

    original_manager = tools.get_mcp_manager
    try:
        tools.get_mcp_manager = Manager
        result = asyncio.run(tools.mcp_search_tools.ainvoke({"query": "lookup"}))
    finally:
        tools.get_mcp_manager = original_manager

    assert "healthy/lookup" in result
    assert "broken" not in result


def test_search_tools_discovers_enabled_servers_concurrently():
    _setup()
    for suffix in ("models", "config_store", "client", "manager", "tools"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    tools = sys.modules["hatsume.plugins.hatsume-plugin.mcp.tools"]
    active = 0
    peak = 0

    class Manager:
        def list_servers(self):
            return [
                types.SimpleNamespace(name="one", enabled=True),
                types.SimpleNamespace(name="two", enabled=True),
            ]

        async def discover_tools(self, name):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return [types.SimpleNamespace(name=name, description="tool")]

    original_manager = tools.get_mcp_manager
    try:
        tools.get_mcp_manager = Manager
        result = asyncio.run(tools.mcp_search_tools.ainvoke({"query": "tool"}))
    finally:
        tools.get_mcp_manager = original_manager

    assert peak == 2
    assert "one/one" in result
    assert "two/two" in result


def test_manager_discovery_timeout_includes_connection_startup(tmp_path):
    _setup()
    for suffix in ("models", "config_store", "client", "manager"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    group_runtime = sys.modules["hatsume.plugins.hatsume-plugin.group_runtime"]
    models = sys.modules["hatsume.plugins.hatsume-plugin.mcp.models"]
    manager_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.manager"]
    store_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.config_store"]
    group_id = 654322
    runtime = group_runtime.group_runtime_registry.get_or_create(group_id)
    runtime.conversation.is_graph_running = True
    store = store_mod.MCPConfigStore(tmp_path)
    store.save_server(
        group_id,
        models.MCPServerConfig(
            name="slow",
            description="slow startup",
            transport="streamable-http",
            url="http://example.test/mcp",
        ),
    )

    class SlowConnection:
        def __init__(self, config):
            self.config = config

        async def start(self):
            await asyncio.sleep(1)

    original_connection = manager_mod.MCPConnection
    original_timeout = manager_mod.MCP_DISCOVERY_TIMEOUT_SECONDS
    manager_mod.MCPConnection = SlowConnection
    manager_mod.MCP_DISCOVERY_TIMEOUT_SECONDS = 0.01
    try:
        manager = manager_mod.MCPManager(store)
        try:
            asyncio.run(manager.discover_tools("slow", group_id))
        except TimeoutError:
            pass
        else:
            raise AssertionError("slow connection should time out during startup")
    finally:
        manager_mod.MCPConnection = original_connection
        manager_mod.MCP_DISCOVERY_TIMEOUT_SECONDS = original_timeout
        group_runtime.group_runtime_registry.clear_for_tests()


def test_load_tools_returns_connection_failure_instead_of_raising():
    _setup()
    for suffix in ("models", "config_store", "client", "manager", "tools"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    tools = sys.modules["hatsume.plugins.hatsume-plugin.mcp.tools"]

    class Manager:
        async def discover_tools(self, name):
            raise TimeoutError("timed out")

    original_manager = tools.get_mcp_manager
    try:
        tools.get_mcp_manager = Manager
        result = asyncio.run(
            tools.mcp_load_tools.ainvoke({"server": "offline", "tools": ["x"]})
        )
    finally:
        tools.get_mcp_manager = original_manager

    assert "连接失败" in result
    assert "本轮已跳过" in result


def test_dynamic_tool_returns_connection_failure_instead_of_raising():
    _setup()
    for suffix in ("models", "config_store", "client", "manager", "tools"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    tools = sys.modules["hatsume.plugins.hatsume-plugin.mcp.tools"]

    class Manager:
        async def call(self, server, name, arguments):
            raise ConnectionError("server disconnected")

    info = types.SimpleNamespace(
        name="lookup",
        description="Look up data",
        input_schema={"type": "object", "properties": {}},
    )
    original_manager = tools.get_mcp_manager
    try:
        tools.get_mcp_manager = Manager
        dynamic_tool = tools.make_dynamic_tools("offline", [info])[0]
        result = asyncio.run(dynamic_tool.ainvoke({"arguments": {}}))
    finally:
        tools.get_mcp_manager = original_manager

    assert "连接失败" in result
    assert "本轮已跳过" in result


def test_manager_reuses_duplicate_server_connection_until_conversation_closes(tmp_path):
    _setup()
    for suffix in ("models", "config_store", "client", "manager"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    group_runtime = sys.modules["hatsume.plugins.hatsume-plugin.group_runtime"]
    models = sys.modules["hatsume.plugins.hatsume-plugin.mcp.models"]
    manager_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.manager"]
    store_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.config_store"]
    group_id = 654321
    runtime = group_runtime.group_runtime_registry.get_or_create(group_id)
    runtime.conversation.is_graph_running = True
    store = store_mod.MCPConfigStore(tmp_path)
    store.save_server(
        group_id,
        models.MCPServerConfig(
            name="first",
            description="first alias",
            transport="streamable-http",
            url="http://example.test/mcp",
        ),
    )
    store.save_server(
        group_id,
        models.MCPServerConfig(
            name="second",
            description="second alias",
            transport="sse",
            url="http://example.test/mcp/",
        ),
    )

    events: list[str] = []

    class FakeConnection:
        def __init__(self, config):
            self.config = config
            events.append(f"create:{config.name}")

        async def start(self):
            events.append("start")

        async def list_tools(self, server_name):
            events.append(f"list:{server_name}")
            return [
                models.MCPToolInfo(
                    server=server_name,
                    name="lookup",
                    description="lookup",
                    input_schema={},
                )
            ]

        async def call_tool(self, tool_name, arguments):
            events.append(f"call:{tool_name}")
            return "ok"

        async def close(self):
            events.append("close")

    original_connection = manager_mod.MCPConnection
    manager_mod.MCPConnection = FakeConnection
    try:
        manager = manager_mod.MCPManager(store)

        async def exercise():
            first = await manager.discover_tools("first", group_id)
            second = await manager.discover_tools("second", group_id)
            result = await manager.call("second", "lookup", {}, group_id)
            await manager.close_conversation(group_id)
            return first, second, result

        first, second, result = asyncio.run(exercise())
    finally:
        manager_mod.MCPConnection = original_connection
        group_runtime.group_runtime_registry.clear_for_tests()

    assert first[0].server == "first"
    assert second[0].server == "second"
    assert result == "ok"
    assert events == [
        "create:first",
        "start",
        "list:first",
        "call:lookup",
        "close",
    ]


def test_manager_refuses_connection_outside_conversation(tmp_path):
    _setup()
    for suffix in ("models", "config_store", "client", "manager"):
        module_name = f"hatsume.plugins.hatsume-plugin.mcp.{suffix}"
        _load(module_name, PLUGIN / "mcp" / f"{suffix}.py")

    group_runtime = sys.modules["hatsume.plugins.hatsume-plugin.group_runtime"]
    models = sys.modules["hatsume.plugins.hatsume-plugin.mcp.models"]
    manager_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.manager"]
    store_mod = sys.modules["hatsume.plugins.hatsume-plugin.mcp.config_store"]
    group_id = 765432
    store = store_mod.MCPConfigStore(tmp_path)
    store.save_server(
        group_id,
        models.MCPServerConfig(
            name="outside",
            description="outside conversation",
            transport="streamable-http",
            url="http://example.test/mcp",
        ),
    )
    manager = manager_mod.MCPManager(store)

    try:
        result = asyncio.run(manager.discover_tools("outside", group_id))
    except RuntimeError as exc:
        assert "进行中的对话" in str(exc)
    else:
        raise AssertionError(f"unexpected discovery result: {result}")
    finally:
        group_runtime.group_runtime_registry.clear_for_tests()


def test_connection_worker_owns_transport_until_close():
    _setup()
    models = _load(
        "hatsume.plugins.hatsume-plugin.mcp.models", PLUGIN / "mcp/models.py"
    )
    client = _load(
        "hatsume.plugins.hatsume-plugin.mcp.client", PLUGIN / "mcp/client.py"
    )
    events: list[tuple[str, object]] = []

    class Session:
        async def list_tools(self):
            events.append(("list", asyncio.current_task()))
            item = types.SimpleNamespace(
                name="lookup", description="lookup", inputSchema={}
            )
            return types.SimpleNamespace(tools=[item])

        async def call_tool(self, name, arguments):
            events.append(("call", asyncio.current_task()))
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="ok", type="text")],
                structuredContent=None,
                isError=False,
            )

    @asynccontextmanager
    async def fake_session(config):
        events.append(("enter", asyncio.current_task()))
        try:
            yield Session()
        finally:
            events.append(("exit", asyncio.current_task()))

    original_session = client._session
    client._session = fake_session
    try:
        connection = client.MCPConnection(
            models.MCPServerConfig(name="test", description="test", command="x")
        )

        async def exercise():
            tools = await connection.list_tools("alias")
            result = await connection.call_tool("lookup", {})
            assert events[-1][0] == "call"
            await connection.close()
            return tools, result

        tools, result = asyncio.run(exercise())
    finally:
        client._session = original_session

    assert tools[0].server == "alias"
    assert result == "ok"
    assert [event for event, _ in events] == ["enter", "list", "call", "exit"]
    assert len({id(task) for _, task in events}) == 1
