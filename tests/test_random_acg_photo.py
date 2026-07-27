"""Tests for random_acg_photo tool."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"


def _load_tools_module():
    """Load graph/tools.py with all external dependencies stubbed."""
    for name in list(sys.modules):
        if name.startswith("hatsume") or name in (
            "nonebot", "nonebot.adapters", "nonebot.adapters.onebot",
            "nonebot.adapters.onebot.v11",
            "langchain", "langchain.messages", "langchain.agents",
            "langchain_core", "langchain_core.messages", "langchain_core.tools",
            "langchain_community", "langchain_community.tools",
            "langgraph", "langgraph.graph",
        ):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
        ("hatsume.plugins.hatsume-plugin.graph", base / "graph"),
        ("hatsume.plugins.hatsume-plugin.memory", base / "memory"),
        ("hatsume.plugins.hatsume-plugin.infra", base / "infra"),
    ]:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

    for dash_name, underscore_name in [
        ("hatsume.plugins.hatsume-plugin", "hatsume.plugins.hatsume_plugin"),
        ("hatsume.plugins.hatsume-plugin.graph", "hatsume.plugins.hatsume_plugin.graph"),
        ("hatsume.plugins.hatsume-plugin.memory", "hatsume.plugins.hatsume_plugin.memory"),
        ("hatsume.plugins.hatsume-plugin.infra", "hatsume.plugins.hatsume_plugin.infra"),
    ]:
        if underscore_name not in sys.modules and dash_name in sys.modules:
            alias = types.ModuleType(underscore_name)
            alias.__path__ = sys.modules[dash_name].__path__
            sys.modules[underscore_name] = alias

    for cfg_name in (
        "hatsume.plugins.hatsume_plugin.config",
        "hatsume.plugins.hatsume-plugin.config",
    ):
        if cfg_name not in sys.modules:
            cfg_mod = types.ModuleType(cfg_name)
            sys.modules[cfg_name] = cfg_mod
        else:
            cfg_mod = sys.modules[cfg_name]
        cfg_mod.AGENT_QQ_EMAIL = "test@qq.com"
        cfg_mod.BOT_QQ_ID = "12345"
        cfg_mod.DOCKER_ENV_PATH = Path("/tmp/test_docker")
        cfg_mod.SHELL_MAX_OUTPUT = 1000
        cfg_mod.SHELL_TIMEOUT = 10
        cfg_mod.CONTEXT_QUEUE_LEN = 20
        cfg_mod.CONTAINER_NAME = "hatsume-space-kali"

    sys.modules["nonebot"] = types.ModuleType("nonebot")
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    sys.modules["nonebot.adapters"] = adapters_mod
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod

    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = type("Message", (), {})
    v11_mod.MessageSegment = types.SimpleNamespace(
        text=lambda s: s, image=lambda *a, **kw: None,
    )
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    nonebot_params = types.ModuleType("nonebot.params")
    nonebot_params.CommandArg = lambda: None
    sys.modules["nonebot.params"] = nonebot_params

    langchain_mod = types.ModuleType("langchain")
    langchain_mod.__path__ = []
    sys.modules["langchain"] = langchain_mod

    class _SystemMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "system"
    class _HumanMessage:
        def __init__(self, content=""):
            self.content = content; self.type = "human"

    langchain_messages = types.ModuleType("langchain.messages")
    langchain_messages.SystemMessage = _SystemMessage
    langchain_messages.HumanMessage = _HumanMessage
    sys.modules["langchain.messages"] = langchain_messages

    langchain_agents = types.ModuleType("langchain.agents")
    langchain_agents.create_agent = lambda *a, **kw: None
    sys.modules["langchain.agents"] = langchain_agents

    langchain_core_mod = types.ModuleType("langchain_core")
    langchain_core_mod.__path__ = []
    sys.modules["langchain_core"] = langchain_core_mod
    langchain_core_messages = types.ModuleType("langchain_core.messages")
    sys.modules["langchain_core.messages"] = langchain_core_messages

    langchain_core_tools = types.ModuleType("langchain_core.tools")
    def _mock_tool(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f
    langchain_core_tools.tool = _mock_tool
    sys.modules["langchain_core.tools"] = langchain_core_tools

    langchain_community = types.ModuleType("langchain_community")
    langchain_community.__path__ = []
    sys.modules["langchain_community"] = langchain_community
    langchain_community_tools = types.ModuleType("langchain_community.tools")
    langchain_community_tools.DuckDuckGoSearchRun = type("DuckDuckGoSearchRun", (), {})
    sys.modules["langchain_community.tools"] = langchain_community_tools

    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    config_mod.DOCKER_ENV_PATH = "/tmp/test"
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    config_mod.BOT_QQ_ID = 1234567890
    config_mod.AGENT_QQ_EMAIL = "test@qq.com"
    config_mod.GITHUB_ACCOUNT = "test-account"
    config_mod.GITHUB_REPO = "test/repo"
    config_mod.CONTEXT_QUEUE_LEN = 20
    config_mod.CONTAINER_NAME = "hatsume-space-kali"
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.get_lite_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"))
    async def _mock_ainvoke(*a, **kw):
        return types.SimpleNamespace(content="ok")
    models_mod.get_code_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"),
        ainvoke=_mock_ainvoke,
    )
    models_mod.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
    models_mod.choose_image_model = lambda: "4"
    models_mod.generate_image_for_volc = lambda *a, **kw: "http://example.com/img.png"
    def _generate_for_ruoli(*a, **kw):
        return "/tmp/test.png"
    models_mod.generate_image_for_ruoli = _generate_for_ruoli
    models_mod.generate_video_for = lambda *a, **kw: None
    models_mod.choose_video_model = lambda: "1.5"
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    utils_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
    utils_mod.get_qq_avatar_url = lambda qq_id: f"https://q.qlogo.cn/g?b=qq&nk={qq_id}&s=640"
    utils_mod.message_to_json = MagicMock(return_value='{"type":"text","text":"test"}')
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod

    infra_mod = sys.modules["hatsume.plugins.hatsume-plugin.infra"]
    infra_mod.run_cmd = lambda *a, **kw: ""
    async def _mock_ensure(*a, **kw): pass
    infra_mod.ensure_container_running = _mock_ensure
    infra_mod.delete_container = lambda *a, **kw: None
    async def _mock_render_html(*a, **kw):
        return b"fake_png_bytes"
    infra_mod.render_html_to_image = _mock_render_html

    memory_engine_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.engine")
    memory_engine_mod.get_mem_list = lambda: []
    memory_engine_mod.add_mem = lambda *a, **kw: None
    memory_engine_mod.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = memory_engine_mod
    # Also set directly on memory module since __init__.py re-exports from engine
    if "hatsume.plugins.hatsume-plugin.memory" in sys.modules:
        memory = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
        memory.get_mem_list = lambda: []
        memory.add_mem = lambda *a, **kw: None
        memory.query_mems = lambda *a, **kw: []

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.graph.tools", TOOLS_PATH)
    tools_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"] = tools_mod
    spec.loader.exec_module(tools_mod)
    return tools_mod


# -----------------------------------------------------------------------
# Tests: US1 & US2 — Random ACG Photo tool
# -----------------------------------------------------------------------

class TestRandomAcgPhoto:
    """Tests for random_acg_photo tool."""

    def test_tool_exists(self):
        """random_acg_photo is defined as a callable on the tools module."""
        tools = _load_tools_module()
        assert hasattr(tools, "random_acg_photo")
        assert callable(tools.random_acg_photo)

    def test_success_returns_sandbox_path(self):
        """On success, the sandbox path has a timestamp and random suffix."""
        tools = _load_tools_module()

        mock_subprocess = MagicMock()
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0, stdout=b""),
            MagicMock(returncode=0, stdout=b""),
        ]
        mock_ensure = AsyncMock()

        with (
            patch.object(tools, "subprocess", mock_subprocess),
            patch.object(tools, "ensure_container_running", mock_ensure),
            patch("os.listdir", return_value=["IMG_1234.jpg"]),
            patch("os.path.isfile", return_value=True),
            patch("shutil.rmtree"),
            patch("os.makedirs"),
            patch("datetime.datetime") as mock_datetime,
            patch.object(tools.random, "randint", return_value=42) as mock_randint,
        ):
            mock_datetime.now.return_value.strftime.return_value = "260727_143025"
            result = asyncio.run(tools.random_acg_photo())

            assert result == "/tmp/apple_photo_export_260727_143025_000042.jpg"
            cp_command = mock_subprocess.run.call_args_list[1].args[0]
            assert cp_command == [
                "docker",
                "cp",
                "/tmp/hatsume_acg_export/IMG_1234.jpg",
                "hatsume-space-kali:/tmp/apple_photo_export_260727_143025_000042.jpg",
            ]
            mock_randint.assert_called_once_with(0, 999999)
            assert mock_ensure.called

    def test_empty_album_returns_error(self):
        """When ACG album has no photos, return Chinese error."""
        tools = _load_tools_module()

        mock_subprocess = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b"ERROR:ALBUM_EMPTY"
        mock_subprocess.run.return_value = mock_result

        with (
            patch.object(tools, "subprocess", mock_subprocess),
            patch("shutil.rmtree"),
            patch("os.makedirs"),
        ):
            result = asyncio.run(tools.random_acg_photo())

            assert ("空" in result or "没有" in result or "无" in result)

    def test_photos_app_not_running_returns_error(self):
        """When osascript fails with a Photos-related error, return Chinese error."""
        tools = _load_tools_module()

        mock_subprocess = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = b""
        mock_result.stderr = b"Application isn't running (-600)"
        mock_subprocess.run.return_value = mock_result

        with (
            patch.object(tools, "subprocess", mock_subprocess),
            patch("shutil.rmtree"),
            patch("os.makedirs"),
        ):
            result = asyncio.run(tools.random_acg_photo())

            assert "错误" in result or "❌" in result

    def test_docker_cp_failure_returns_error(self):
        """When docker cp fails, return Chinese error."""
        tools = _load_tools_module()

        mock_subprocess = MagicMock()
        mock_subprocess.run.side_effect = [
            MagicMock(returncode=0, stdout=b""),
            MagicMock(returncode=1, stderr=b"Error: No such container"),
        ]

        with (
            patch.object(tools, "subprocess", mock_subprocess),
            patch("os.listdir", return_value=["photo.png"]),
            patch("os.path.isfile", return_value=True),
            patch("shutil.rmtree"),
            patch("os.makedirs"),
            patch.object(tools, "ensure_container_running", AsyncMock()),
        ):
            result = asyncio.run(tools.random_acg_photo())

            assert "❌" in result
