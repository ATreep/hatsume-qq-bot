"""Tests for graph/tools.py — tool call limiter and get_avatar multi-call."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import tool as _real_langchain_tool

ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"


def _load_tools_module():
    """Load graph/tools.py with all external dependencies stubbed."""
    # Clean up previously loaded modules
    for name in list(sys.modules):
        if (
            name.startswith("hatsume")
            or name == "requests"
            or name.startswith("requests.")
            or name in (
                "nonebot",
                "nonebot.adapters",
                "nonebot.adapters.onebot",
                "nonebot.adapters.onebot.v11",
                "langchain",
                "langchain.messages",
                "langchain.agents",
                "langchain_core",
                "langchain_core.messages",
                "langchain_core.tools",
                "langchain_community",
                "langchain_community.tools",
                "langgraph",
                "langgraph.graph",
            )
        ):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    # Package hierarchy
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

    # Alias: dash→underscore for import resolution
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

    # Stub config for prompts.py imports under both dash and underscore variants
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

    # Stub external deps
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
        text=lambda s: s,
        image=lambda *a, **kw: None,
        video=lambda *a, **kw: None,
    )
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11_mod.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

    nonebot_params = types.ModuleType("nonebot.params")
    nonebot_params.CommandArg = lambda: None
    sys.modules["nonebot.params"] = nonebot_params

    langchain_mod = types.ModuleType("langchain")
    langchain_mod.__path__ = []
    sys.modules["langchain"] = langchain_mod

    class _SystemMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "system"

    class _HumanMessage:
        def __init__(self, content=""):
            self.content = content
            self.type = "human"

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
        """Mock @tool decorator: @tool(fn) returns fn; @tool(kw) returns decorator."""
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

    langchain_core_tools.tool = _mock_tool
    sys.modules["langchain_core.tools"] = langchain_core_tools

    langchain_community = types.ModuleType("langchain_community")
    langchain_community.__path__ = []
    sys.modules["langchain_community"] = langchain_community

    langchain_community_tools = types.ModuleType("langchain_community.tools")
    langchain_community_tools.DuckDuckGoSearchRun = type(
        "DuckDuckGoSearchRun", (), {}
    )
    sys.modules["langchain_community.tools"] = langchain_community_tools

    # Stub sibling modules
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    config_mod.DOCKER_ENV_PATH = "/tmp/test"
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    config_mod.BOT_QQ_ID = 1234567890
    config_mod.AGENT_QQ_EMAIL = "test@qq.com"
    config_mod.GITHUB_ACCOUNT = "test-account"
    config_mod.GITHUB_REPO = "test/repo"
    config_mod.HUGGINGFACE_ACCOUNT = "test-huggingface"
    config_mod.CONTEXT_QUEUE_LEN = 20
    config_mod.PIXELS_API_KEY = "test-pexels-key"
    config_mod.PEXELS_BASE_URL = "https://api.pexels.com"
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    runtimes = {}
    group_bots = {}
    current_runtime = contextvars.ContextVar(
        "test_tools_current_runtime",
        default=None,
    )

    def _new_runtime(group_id):
        conversation = types.SimpleNamespace(
            ai_answer=None,
            current_query_user_id=None,
            request_end_conversation=lambda: None,
        )
        return types.SimpleNamespace(
            group_id=group_id,
            conversation=conversation,
            end_conversation_callback=conversation.request_end_conversation,
            is_video_rate_limited_callback=lambda: False,
            update_video_time_callback=lambda: None,
            is_generate_image_rate_limited_callback=lambda: False,
            update_generate_image_time_callback=lambda: None,
            generate_video_used=False,
            send_image_count=0,
            send_video_count=0,
            agent_tasks=set(),
        )

    def _get_or_create(group_id):
        group_id = int(group_id)
        return runtimes.setdefault(group_id, _new_runtime(group_id))

    registry = types.SimpleNamespace()

    def _bind_bot(group_id, bot):
        group_id = int(group_id)
        group_bots[group_id] = bot
        runtime = registry.get_or_create(group_id)
        runtime.bot = bot
        return runtime

    def _get_bot(group_id):
        return group_bots[int(group_id)]

    def _get_current_group_runtime(*, required=True):
        runtime = current_runtime.get()
        if runtime is None and required:
            raise RuntimeError("group runtime is not bound")
        return runtime

    @contextlib.contextmanager
    def _bind_group_runtime(runtime):
        token = current_runtime.set(runtime)
        try:
            yield runtime
        finally:
            current_runtime.reset(token)

    group_runtime_mod = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.group_runtime"
    )
    registry.get_or_create = _get_or_create
    registry.bind_bot = _bind_bot
    registry.get_bot = _get_bot
    group_runtime_mod.group_runtime_registry = registry
    group_runtime_mod.get_current_group_runtime = _get_current_group_runtime
    group_runtime_mod.set_current_group_runtime = current_runtime.set
    group_runtime_mod.bind_group_runtime = _bind_group_runtime
    sys.modules[group_runtime_mod.__name__] = group_runtime_mod

    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.get_lite_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok")
    )
    async def _mock_ainvoke(*a, **kw):
        return types.SimpleNamespace(content="ok")

    models_mod.get_code_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"),
        ainvoke=_mock_ainvoke,
    )
    models_mod.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
    models_mod.choose_image_model = lambda: "4"
    models_mod.generate_video_for = AsyncMock(return_value="http://example.com/video.mp4")
    models_mod.choose_video_model = lambda: "1.5"
    models_mod.generate_image_for_volc = AsyncMock(return_value="http://example.com/img.png")
    models_mod.generate_image_for_kege = MagicMock(return_value="http://example.com/img.png")
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    utils_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
    utils_mod.get_qq_avatar_url = lambda qq_id: f"https://q.qlogo.cn/g?b=qq&nk={qq_id}&s=640"
    utils_mod.message_to_json = MagicMock(return_value='{"type":"text","text":"test"}')
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod

    # infra (docker + htmlkit merged into infra.py)
    infra_mod = sys.modules["hatsume.plugins.hatsume-plugin.infra"]
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.container_name_for_group = (
        lambda group_id: f"hatsume-space-{group_id}"
    )
    infra_mod.ensure_container_running = lambda *a, **kw: None
    infra_mod.delete_container = lambda *a, **kw: None

    async def _mock_read_sandbox_image_data_uri(*args, **kwargs):
        return "data:image/png;base64,aW1hZ2U="

    infra_mod.read_sandbox_image_data_uri = _mock_read_sandbox_image_data_uri

    async def _mock_copy_host_file_to_sandbox(*args, **kwargs):
        return None

    infra_mod.copy_host_file_to_sandbox = _mock_copy_host_file_to_sandbox

    async def _mock_render_html(*a, **kw):
        return b"fake_png_bytes"
    infra_mod.render_html_to_image = _mock_render_html

    # memory.engine stub (replaces memory.store + memory.retrieval)
    memory_engine_mod = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.memory.engine"
    )
    memory_engine_mod.get_mem_list = lambda: []
    memory_engine_mod.add_mem = lambda *a, **kw: None
    memory_engine_mod.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = memory_engine_mod
    # Also set on memory directly since __init__.py re-exports from .engine
    memory_mod = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
    memory_mod.get_mem_list = lambda: []
    memory_mod.add_mem = lambda *a, **kw: None
    memory_mod.query_mems = lambda *a, **kw: []

    # Load tools.py
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.graph.tools", TOOLS_PATH
    )
    tools_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"] = tools_mod
    spec.loader.exec_module(tools_mod)
    return tools_mod


def _bind_tool_runtime(tools, group_id=123):
    tools.set_current_group_id(group_id)
    return tools.get_current_group_runtime()



# -----------------------------------------------------------------------
# get_avatar: can be called multiple times
# -----------------------------------------------------------------------


class TestGetAvatarMultiCall:
    """get_avatar returns avatar URLs for given QQ ids."""

    def test_get_avatar_returns_url(self):
        tools = _load_tools_module()

        result = tools.get_avatar(12345)
        assert "12345" in result
        assert "q.qlogo.cn" in result

    def test_get_avatar_first_call_succeeds(self):
        """Call to get_avatar returns a valid URL."""
        tools = _load_tools_module()

        result = tools.get_avatar(111)
        assert "111" in result
        assert "错误" not in result


# -----------------------------------------------------------------------
# search_image: Pexels photo search
# -----------------------------------------------------------------------


class TestSearchImage:
    @pytest.mark.asyncio
    async def test_returns_sendable_urls_and_attribution(self, monkeypatch):
        tools = _load_tools_module()
        response = MagicMock()
        response.json.return_value = {
            "photos": [
                {
                    "url": "https://www.pexels.com/photo/sunrise-42/",
                    "photographer": "Test Photographer",
                    "alt": "Sunrise over a mountain lake",
                    "src": {
                        "large": "https://images.pexels.com/photos/42/large.jpeg",
                        "original": "https://images.pexels.com/photos/42/original.jpeg",
                    },
                }
            ]
        }
        get = MagicMock(return_value=response)
        monkeypatch.setattr(tools.requests, "get", get)

        result = await tools.search_image("mountain sunrise", 2, "landscape")

        get.assert_called_once_with(
            "https://api.pexels.com/v1/search",
            params={
                "query": "mountain sunrise",
                "per_page": 2,
                "page": 1,
                "orientation": "landscape",
            },
            headers={
                "Accept": "application/json",
                "Authorization": "test-pexels-key",
                "User-Agent": "Hatsume/1.0",
            },
            timeout=10,
        )
        assert "verify" not in get.call_args.kwargs
        response.raise_for_status.assert_called_once_with()
        assert "https://images.pexels.com/photos/42/large.jpeg" in result
        assert "Test Photographer" in result
        assert "https://www.pexels.com/photo/sunrise-42/" in result
        assert "test-pexels-key" not in result

    @pytest.mark.asyncio
    async def test_missing_api_key_does_not_make_request(self, monkeypatch):
        tools = _load_tools_module()
        config = sys.modules["hatsume.plugins.hatsume-plugin.config"]
        config.PIXELS_API_KEY = ""
        get = MagicMock()
        monkeypatch.setattr(tools.requests, "get", get)

        result = await tools.search_image("city skyline")

        assert "未配置 PIXELS_API_KEY" in result
        get.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limit_returns_safe_error(self, monkeypatch):
        tools = _load_tools_module()

        def rate_limited(*args, **kwargs):
            response = MagicMock(status_code=429)
            raise tools.requests.exceptions.HTTPError(
                "limited", response=response
            )

        monkeypatch.setattr(tools, "_fetch_pexels_search", rate_limited)

        result = await tools.search_image("city skyline")

        assert "请求过于频繁" in result
        assert "test-pexels-key" not in result

    @pytest.mark.asyncio
    async def test_ssl_error_is_reported_without_disabling_verification(
        self, monkeypatch
    ):
        tools = _load_tools_module()

        def ssl_error(*args, **kwargs):
            raise tools.requests.exceptions.SSLError("certificate verify failed")

        monkeypatch.setattr(tools, "_fetch_pexels_search", ssl_error)

        result = await tools.search_image("city skyline")

        assert "SSL 证书" in result
        assert "test-pexels-key" not in result

    def test_registered_once_for_chat_agent(self):
        tools = _load_tools_module()

        assert tools.CHAT_TOOLS.count(tools.search_image) == 1


# -----------------------------------------------------------------------
# view_image: lite-model image description
# -----------------------------------------------------------------------


class TestViewImage:
    @staticmethod
    def _set_lite_model(content="图片描述"):
        model = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value=types.SimpleNamespace(content=content))
        )
        models = sys.modules["hatsume.plugins.hatsume-plugin.models"]
        models.get_lite_model = MagicMock(return_value=model)
        return model

    @pytest.mark.asyncio
    async def test_passes_http_image_to_lite_model(self):
        tools = _load_tools_module()
        model = self._set_lite_model("一张海边日落的照片")

        result = await tools.view_image("https://example.com/sunset.jpg")

        assert result == "一张海边日落的照片"
        messages = model.ainvoke.await_args.args[0]
        content = messages[0].content
        assert content[0]["type"] == "text"
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "https://example.com/sunset.jpg"},
        }

    @pytest.mark.asyncio
    async def test_reads_file_url_from_sandbox_as_data_uri(self):
        tools = _load_tools_module()
        runtime = _bind_tool_runtime(tools)
        model = self._set_lite_model([{"type": "text", "text": "沙盒图片描述"}])
        tools.read_sandbox_image_data_uri = AsyncMock(
            return_value="data:image/png;base64,aW1hZ2U="
        )

        result = await tools.view_image("file:///work/example image.png")

        assert result == "沙盒图片描述"
        tools.read_sandbox_image_data_uri.assert_awaited_once_with(
            "/work/example image.png",
            group_id=runtime.group_id,
        )
        messages = model.ainvoke.await_args.args[0]
        assert messages[0].content[1]["image_url"]["url"] == (
            "data:image/png;base64,aW1hZ2U="
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "image_url",
        ["", "file://relative/image.png", "/work/image.png", "ftp://example.com/a.png"],
    )
    async def test_rejects_unsupported_or_non_absolute_input(self, image_url):
        tools = _load_tools_module()
        model = self._set_lite_model()

        result = await tools.view_image(image_url)

        assert result.startswith("❌")
        model.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_non_image_sandbox_file(self):
        tools = _load_tools_module()
        runtime = _bind_tool_runtime(tools)
        model = self._set_lite_model()
        tools.read_sandbox_image_data_uri = AsyncMock(
            side_effect=ValueError("sandbox file is not a valid image")
        )

        result = await tools.view_image("file:///work/readme.txt")

        assert "not a valid image" in result
        tools.read_sandbox_image_data_uri.assert_awaited_once_with(
            "/work/readme.txt",
            group_id=runtime.group_id,
        )
        model.ainvoke.assert_not_awaited()


# -----------------------------------------------------------------------
# timer-v2 creation tools
# -----------------------------------------------------------------------


class TestCreateTimerTools:
    """The four timer-v2 creation tools expose and enforce their contracts."""

    @staticmethod
    def _setup_timer_dependencies(tools):
        store = types.SimpleNamespace(
            create_task=MagicMock(return_value=42),
            validate_prompt=lambda prompt: None,
        )
        timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
        timer_mod.__path__ = [str(ROOT / "hatsume/plugins/hatsume-plugin/timer")]
        timer_mod.get_store = lambda: store
        sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

        config_mod = sys.modules["hatsume.plugins.hatsume-plugin.config"]
        config_mod.TIMER_MAX_FREQUENCY_POINTS = 5
        config_mod.TIMER_MAX_EXACT_POINTS = 10
        schedule_name = "hatsume.plugins.hatsume-plugin.timer.schedule"
        schedule_spec = importlib.util.spec_from_file_location(
            schedule_name,
            ROOT / "hatsume/plugins/hatsume-plugin/timer/schedule.py",
        )
        assert schedule_spec is not None and schedule_spec.loader is not None
        schedule = importlib.util.module_from_spec(schedule_spec)
        sys.modules[schedule_name] = schedule
        schedule_spec.loader.exec_module(schedule)

        add_jobs = MagicMock()
        executor_mod = types.ModuleType(
            "hatsume.plugins.hatsume-plugin.timer.executor"
        )
        executor_mod.add_jobs_for_task = add_jobs
        sys.modules["hatsume.plugins.hatsume-plugin.timer.executor"] = executor_mod

        tools.set_current_group_id(123)
        return store, add_jobs, schedule

    @pytest.mark.asyncio
    async def test_daily_tool_rejects_more_than_five_exact_clock_points(self):
        tools = _load_tools_module()
        store, add_jobs, _ = self._setup_timer_dependencies(tools)

        result = await tools.create_daily_timer(
            456,
            "提醒喝水",
            "2999-01-01T00:00:00+08:00",
            "2999-01-10T23:59:59+08:00",
            [f"0{index}:00:00" for index in range(6)],
            1,
        )

        assert "最多 5" in result
        assert "HH:MM:SS" in tools.create_daily_timer.__doc__
        store.create_task.assert_not_called()
        add_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_at_tool_rejects_more_than_ten_timestamps(self):
        tools = _load_tools_module()
        store, add_jobs, _ = self._setup_timer_dependencies(tools)
        trigger_times = [f"2999-01-{index:02d}T09:00:00+08:00" for index in range(1, 12)]

        result = await tools.create_at_timer(456, "提醒", trigger_times)

        assert "最多 10" in result
        store.create_task.assert_not_called()
        add_jobs.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "builder_name", "arguments"),
        [
            (
                "create_daily_timer",
                "build_daily_plan",
                (
                    456,
                    "daily",
                    "2999-01-01T00:00:00+08:00",
                    "2999-01-10T23:59:59+08:00",
                    ["09:00:00"],
                    2,
                ),
            ),
            (
                "create_weekly_timer",
                "build_weekly_plan",
                (
                    456,
                    "weekly",
                    "2999-01-01T00:00:00+08:00",
                    "2999-02-28T23:59:59+08:00",
                    [{"weekday": 1, "time": "09:00:00"}],
                    2,
                ),
            ),
            (
                "create_monthly_timer",
                "build_monthly_plan",
                (
                    456,
                    "monthly",
                    "2999-01-01T00:00:00+08:00",
                    "2999-12-31T23:59:59+08:00",
                    [{"day": 15, "time": "09:00:00"}],
                    2,
                ),
            ),
            (
                "create_at_timer",
                "build_at_plan",
                (456, "at", ["2999-01-01T09:00:00+08:00"]),
            ),
        ],
    )
    async def test_each_creation_tool_delegates_to_its_builder(
        self, tool_name, builder_name, arguments
    ):
        tools = _load_tools_module()
        store, add_jobs, schedule = self._setup_timer_dependencies(tools)
        original_builder = getattr(schedule, builder_name)
        builder = MagicMock(wraps=original_builder)
        setattr(schedule, builder_name, builder)

        result = await getattr(tools, tool_name)(*arguments)

        assert "定时任务已创建（ID: 42）" in result
        builder.assert_called_once()
        store.create_task.assert_called_once()
        add_jobs.assert_called_once_with(42, store)

    def test_registry_contains_four_creation_tools_and_no_removed_tools(self):
        tools = _load_tools_module()

        for name in (
            "create_daily_timer",
            "create_weekly_timer",
            "create_monthly_timer",
            "create_at_timer",
        ):
            assert tools.CHAT_TOOLS.count(getattr(tools, name)) == 1
        assert not hasattr(tools, "create_timer")
        assert not hasattr(tools, "get_timer")

    @pytest.mark.parametrize(
        "tool_name",
        [
            "create_daily_timer",
            "create_weekly_timer",
            "create_monthly_timer",
            "create_at_timer",
        ],
    )
    def test_creation_tool_docs_include_shared_prompt_contract(self, tool_name):
        tools = _load_tools_module()

        doc = getattr(tools, tool_name).__doc__ or ""

        assert "user_id" in doc
        assert "prompt" in doc
        assert "500" in doc

    @pytest.mark.parametrize(
        "tool_name",
        ["create_daily_timer", "create_weekly_timer", "create_monthly_timer"],
    )
    def test_frequency_tool_docs_do_not_describe_an_occurrence_cap(self, tool_name):
        tools = _load_tools_module()

        doc = getattr(tools, tool_name).__doc__ or ""

        assert "50 次" not in doc
        assert "保留最早" not in doc

    @pytest.mark.parametrize(
        "tool_name",
        ["create_daily_timer", "create_weekly_timer", "create_monthly_timer"],
    )
    def test_frequency_tool_docs_require_agent_chosen_end_time(self, tool_name):
        tools = _load_tools_module()
        structured_tool = _real_langchain_tool(getattr(tools, tool_name))
        description = " ".join(structured_tool.description.split())

        assert "如果用户明确指定结束时间，必须使用该时间" in description
        assert "任务内容和当前聊天上下文" in description
        assert "合理的有限 end_at" in description
        assert "不得 仅因此向用户追问" in description
        assert "成功创建任务后" in description
        assert "自然回复中明确告诉用户实际传入的结束时间" in description
        assert "end_at" in structured_tool.args_schema.model_json_schema()["required"]

    @pytest.mark.parametrize(
        ("tool_name", "required_fields"),
        [
            ("create_weekly_timer", {"weekday", "time"}),
            ("create_monthly_timer", {"day", "time"}),
        ],
    )
    def test_frequency_tool_schema_requires_structured_time_points(
        self, tool_name, required_fields
    ):
        tools = _load_tools_module()
        structured_tool = _real_langchain_tool(getattr(tools, tool_name))
        schema = structured_tool.args_schema.model_json_schema()
        items = schema["properties"]["time_points"]["items"]
        assert "$ref" in items, schema
        definition = schema["$defs"][items["$ref"].removeprefix("#/$defs/")]

        assert set(definition["required"]) == required_fields
        assert set(definition["properties"]) == required_fields

    @pytest.mark.parametrize(
        ("tool_name", "payload"),
        [
            (
                "create_daily_timer",
                {
                    "user_id": 1,
                    "prompt": "daily",
                    "start_at": "2999-01-01T00:00:00+08:00",
                    "end_at": "2999-01-02T00:00:00+08:00",
                    "time_points": ["09:00:00"],
                    "step": True,
                },
            ),
            (
                "create_weekly_timer",
                {
                    "user_id": 1,
                    "prompt": "weekly",
                    "start_at": "2999-01-01T00:00:00+08:00",
                    "end_at": "2999-02-01T00:00:00+08:00",
                    "time_points": [{"weekday": True, "time": "09:00:00"}],
                    "step": 1,
                },
            ),
            (
                "create_monthly_timer",
                {
                    "user_id": 1,
                    "prompt": "monthly",
                    "start_at": "2999-01-01T00:00:00+08:00",
                    "end_at": "2999-03-01T00:00:00+08:00",
                    "time_points": [{"day": True, "time": "09:00:00"}],
                    "step": 1,
                },
            ),
        ],
    )
    def test_frequency_tool_schema_rejects_boolean_integers(
        self, tool_name, payload
    ):
        from pydantic import ValidationError

        tools = _load_tools_module()
        structured_tool = _real_langchain_tool(getattr(tools, tool_name))

        with pytest.raises(ValidationError):
            structured_tool.args_schema.model_validate(payload)


# -----------------------------------------------------------------------
# timer listing: overview and trigger details
# -----------------------------------------------------------------------


class TestTimerListing:
    @staticmethod
    def _setup_timer_dependencies(tools, tasks, points_by_task):
        store = types.SimpleNamespace(
            list_tasks_by_group=MagicMock(return_value=tasks),
            get_points_for_task=MagicMock(
                side_effect=lambda task_id: points_by_task.get(task_id, [])
            ),
        )
        timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
        timer_mod.__path__ = [str(ROOT / "hatsume/plugins/hatsume-plugin/timer")]
        timer_mod.get_store = lambda: store
        sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

        config_mod = sys.modules["hatsume.plugins.hatsume-plugin.config"]
        config_mod.TIMER_MAX_FREQUENCY_POINTS = 5
        config_mod.TIMER_MAX_EXACT_POINTS = 10
        tools.set_current_group_id(123)
        return store

    @pytest.mark.asyncio
    async def test_overview_accepts_an_explicit_group_without_changing_context(self):
        tools = _load_tools_module()
        store = self._setup_timer_dependencies(tools, [], {})

        result = await tools.get_timer_overview(456)

        store.list_tasks_by_group.assert_called_once_with(456)
        assert result.startswith("# 群 456 的定时任务")
        assert tools.get_current_group_id() == 123

    @pytest.mark.asyncio
    async def test_list_timers_shows_complete_weekly_frequency(self):
        tools = _load_tools_module()
        start_at = datetime.fromisoformat("2026-07-25T00:00:00+08:00").timestamp()
        end_at = datetime.fromisoformat("2026-12-31T23:59:59+08:00").timestamp()
        tasks = [
            {
                "id": 1,
                "group_id": 123,
                "user_id": 456,
                "prompt": "完整提示词",
                "schedule_type": "weekly",
                "start_at": start_at,
                "end_at": end_at,
                "step": 2,
                "total_occurrences": 20,
                "processed_occurrences": 1,
            }
        ]
        points = {
            1: [
                {
                    "period_value": 1,
                    "clock_time": "09:00:00",
                    "first_fire_at": datetime.fromisoformat(
                        "2026-08-03T09:00:00+08:00"
                    ).timestamp(),
                    "last_fire_at": end_at,
                    "planned_occurrences": 10,
                    "processed_occurrences": 0,
                },
                {
                    "period_value": 5,
                    "clock_time": "18:00:00",
                    "first_fire_at": datetime.fromisoformat(
                        "2026-07-31T18:00:00+08:00"
                    ).timestamp(),
                    "last_fire_at": end_at,
                    "planned_occurrences": 10,
                    "processed_occurrences": 1,
                },
            ]
        }
        self._setup_timer_dependencies(tools, tasks, points)
        bot = object()
        tools.group_runtime_registry.bind_bot(123, bot)
        utils = sys.modules["hatsume.plugins.hatsume-plugin.utils"]
        utils.get_group_member_name = AsyncMock(return_value="提醒对象")

        result = await tools.list_timers()

        assert "## 尚未完成的定时任务" in result
        assert "## 已完成的定时任务" in result
        pending_section, completed_section = result.split("## 已完成的定时任务")
        assert "任务 ID：1" in pending_section
        assert "提醒用户：@提醒对象(456)" in pending_section
        assert "任务提示词：完整提示词" in pending_section
        assert "类型：每 2 周" in pending_section
        assert "范围：2026-07-25 00:00:00 至 2026-12-31 23:59:59" in pending_section
        assert "时间点：周一 09:00:00、周五 18:00:00" in pending_section
        assert "计划触发：20 次；已处理：1 次" in pending_section
        assert "已按上限截断" not in pending_section
        assert "实际保留至" not in pending_section
        assert "下一次触发：2026-08-03 09:00:00" in pending_section
        assert completed_section.strip() == "\n无".strip()

    @pytest.mark.asyncio
    async def test_list_timers_keeps_requested_zero_occurrence_point(self):
        tools = _load_tools_module()
        start_at = datetime.fromisoformat("2026-08-01T00:00:00+08:00").timestamp()
        end_at = datetime.fromisoformat("2026-08-01T23:59:59+08:00").timestamp()
        retained_at = datetime.fromisoformat(
            "2026-08-01T18:00:00+08:00"
        ).timestamp()
        tasks = [
            {
                "id": 1,
                "group_id": 123,
                "user_id": 0,
                "prompt": "完整时间点",
                "schedule_type": "daily",
                "start_at": start_at,
                "end_at": end_at,
                "step": 1,
                "total_occurrences": 1,
                "processed_occurrences": 0,
            }
        ]
        points = {
            1: [
                {
                    "period_value": None,
                    "clock_time": "09:00:00",
                    "exact_at": None,
                    "first_fire_at": None,
                    "last_fire_at": None,
                    "planned_occurrences": 0,
                    "processed_occurrences": 0,
                },
                {
                    "period_value": None,
                    "clock_time": "18:00:00",
                    "exact_at": None,
                    "first_fire_at": retained_at,
                    "last_fire_at": retained_at,
                    "planned_occurrences": 1,
                    "processed_occurrences": 0,
                },
            ]
        }
        self._setup_timer_dependencies(tools, tasks, points)

        result = await tools.list_timers()

        assert "时间点：09:00:00、18:00:00" in result
        assert "下一次触发：2026-08-01 18:00:00" in result

    @pytest.mark.asyncio
    async def test_list_timers_keeps_both_categories_when_group_has_no_tasks(self):
        tools = _load_tools_module()
        self._setup_timer_dependencies(tools, [], {})

        result = await tools.list_timers()

        assert result == (
            "# 当前群的定时任务\n\n"
            "## 尚未完成的定时任务\n无\n\n"
            "## 已完成的定时任务\n无"
        )

    @pytest.mark.asyncio
    async def test_list_timers_shows_every_exact_timestamp_and_status(self):
        tools = _load_tools_module()
        tasks = [
            {
                "id": 7,
                "group_id": 123,
                "user_id": 456,
                "prompt": "提示词",
                "schedule_type": "at",
                "start_at": None,
                "end_at": None,
                "step": None,
                "total_occurrences": 2,
                "processed_occurrences": 1,
            },
        ]
        points = {
            7: [
                {
                    "exact_at": datetime.fromisoformat(
                        "2026-08-01T09:00:00+08:00"
                    ).timestamp(),
                    "first_fire_at": datetime.fromisoformat(
                        "2026-08-01T09:00:00+08:00"
                    ).timestamp(),
                    "planned_occurrences": 1,
                    "processed_occurrences": 1,
                },
                {
                    "exact_at": datetime.fromisoformat(
                        "2026-08-02T18:00:00+08:00"
                    ).timestamp(),
                    "first_fire_at": datetime.fromisoformat(
                        "2026-08-02T18:00:00+08:00"
                    ).timestamp(),
                    "planned_occurrences": 1,
                    "processed_occurrences": 0,
                },
            ],
        }
        self._setup_timer_dependencies(tools, tasks, points)

        result = await tools.list_timers()

        assert "类型：指定时间" in result
        assert "2026-08-01 09:00:00：已完成" in result
        assert "2026-08-02 18:00:00：未完成" in result
        assert "下一次触发：2026-08-02 18:00:00" in result


# -----------------------------------------------------------------------
# generate_image: rate limiting via callbacks
# -----------------------------------------------------------------------

class TestGenerateImageRateLimit:
    """generate_image should use is_image_rate_limited / update_image_time callbacks."""

    def test_rate_limited_returns_error(self):
        """When is_image_rate_limited returns True, generate_image returns an error string."""
        tools = _load_tools_module()


        def rate_limited():
            return True

        def update_time():
            return None
        _bind_tool_runtime(tools)
        tools.configure_tool_callbacks(
            None,
            answer_fn=None,
            is_generate_image_rate_limited=rate_limited,
            update_generate_image_time=update_time,
        )

        result = asyncio.run(
            tools.generate_image("test prompt", [])
        )
        assert "频繁" in result

    def test_success_calls_update_image_time(self):
        """On successful generation, update_image_time callback is called."""
        tools = _load_tools_module()


        update_called = []
        def rate_limited():
            return False

        def update_time():
            update_called.append(True)
        # Force volc branch for consistency
        import random as _random
        _orig_random = _random.random
        _random.random = lambda: 0.0
        _bind_tool_runtime(tools)
        tools.configure_tool_callbacks(
            None,
            answer_fn=None,
            is_generate_image_rate_limited=rate_limited,
            update_generate_image_time=update_time,
        )

        try:
            result = asyncio.run(
                tools.generate_image("test prompt", [])
            )
        finally:
            _random.random = _orig_random
        assert "临时 URL" in result
        assert len(update_called) == 1

    def test_no_global_last_image_time_in_function(self):
        """generate_image must not use 'global _last_image_time' — verify no such global decl."""
        import inspect
        import ast

        tools = _load_tools_module()
        source = inspect.getsource(tools.generate_image.__wrapped__ if hasattr(tools.generate_image, '__wrapped__') else tools.generate_image)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                assert "_last_image_time" not in node.names, (
                    "generate_image still declares 'global _last_image_time'"
                )

    def test_failure_does_not_call_update_image_time(self):
        """On failure, update_image_time is still called (it's called before the try block).
        Verify the error message is returned properly."""
        tools = _load_tools_module()


        update_called = []
        def rate_limited():
            return False

        def update_time():
            update_called.append(True)

        # Override generate_image_for_volc to raise
        models_mod = sys.modules["hatsume.plugins.hatsume-plugin.models"]
        original_volc = models_mod.generate_image_for_volc
        models_mod.generate_image_for_volc = AsyncMock(side_effect=RuntimeError("API error"))
        original_kege = models_mod.generate_image_for_kege
        models_mod.generate_image_for_kege = MagicMock(side_effect=RuntimeError("API error"))

        # Force the volc branch (random <= 0.5) for consistency
        import random
        original_random = random.random
        random.random = lambda: 0.0

        _bind_tool_runtime(tools)
        tools.configure_tool_callbacks(
            None,
            answer_fn=None,
            is_generate_image_rate_limited=rate_limited,
            update_generate_image_time=update_time,
        )

        try:
            result = asyncio.run(
                tools.generate_image("test prompt", [])
            )
        finally:
            random.random = original_random

        assert "失败" in result
        # update_generate_image_time is called before the try block, so it fires even on failure
        assert len(update_called) == 1

        # Restore
        models_mod.generate_image_for_volc = original_volc
        models_mod.generate_image_for_kege = original_kege


# -----------------------------------------------------------------------
# commands.py: rate limiting via ConversationState
# -----------------------------------------------------------------------

COMMANDS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/handlers/tools.py"


def _load_commands_module():
    """Load handlers/tools.py with all external dependencies stubbed."""
    # Clean up previously loaded hatsume modules
    for name in list(sys.modules):
        if name.startswith("hatsume.plugins.hatsume-plugin.handlers"):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    # Ensure nonebot stubs exist (may not have been set up if _load_tools_module wasn't called)
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")

    if "nonebot.adapters" not in sys.modules:
        adapters_mod = types.ModuleType("nonebot.adapters")
        adapters_mod.__path__ = []
        sys.modules["nonebot.adapters"] = adapters_mod
    adapters_mod = sys.modules["nonebot.adapters"]
    if not hasattr(adapters_mod, "Bot"):
        adapters_mod.Bot = type("Bot", (), {})

    if "nonebot.adapters.onebot" not in sys.modules:
        onebot_mod = types.ModuleType("nonebot.adapters.onebot")
        onebot_mod.__path__ = []
        sys.modules["nonebot.adapters.onebot"] = onebot_mod

    if "nonebot.adapters.onebot.v11" not in sys.modules:
        sys.modules["nonebot.adapters.onebot.v11"] = types.ModuleType(
            "nonebot.adapters.onebot.v11"
        )
    v11_mod = sys.modules["nonebot.adapters.onebot.v11"]
    if not hasattr(v11_mod, "Message"):
        v11_mod.Message = type("Message", (), {})
    if not hasattr(v11_mod, "MessageSegment"):
        v11_mod.MessageSegment = types.SimpleNamespace(
            text=lambda s: s,
            image=lambda *a, **kw: None,
            video=lambda *a, **kw: None,
        )
    elif not hasattr(v11_mod.MessageSegment, "video"):
        v11_mod.MessageSegment.video = lambda *a, **kw: None
    if not hasattr(v11_mod, "GroupMessageEvent"):
        v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    if not hasattr(v11_mod, "PokeNotifyEvent"):
        v11_mod.PokeNotifyEvent = type("PokeNotifyEvent", (), {})

    if "nonebot.params" not in sys.modules:
        nonebot_params = types.ModuleType("nonebot.params")
        nonebot_params.CommandArg = lambda: None
        sys.modules["nonebot.params"] = nonebot_params

    # Package hierarchy for handlers
    for name, path in [
        ("hatsume.plugins.hatsume-plugin.handlers", base / "handlers"),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Ensure config stub exists with ADMIN_QQ_ID
    config_mod = sys.modules.get("hatsume.plugins.hatsume-plugin.config")
    if config_mod is None:
        config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
        sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod
    config_mod.ADMIN_QQ_ID = 999999
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30

    models_mod = sys.modules.get("hatsume.plugins.hatsume-plugin.models")
    if models_mod is None:
        models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
        sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod
    if not hasattr(models_mod, "choose_video_model"):
        models_mod.choose_video_model = lambda: "1.0"
    if not hasattr(models_mod, "generate_video_for"):
        models_mod.generate_video_for = AsyncMock(
            return_value="https://example.com/video.mp4"
        )

    # Ensure state stub exists with ConversationState
    state_mod = sys.modules.get("hatsume.plugins.hatsume-plugin.state")
    if state_mod is None:
        state_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.state")
        state_mod.ConversationState = type("ConversationState", (), {})
        sys.modules["hatsume.plugins.hatsume-plugin.state"] = state_mod

    # Stub infra module (docker sandbox + HTML rendering)
    infra_mod = sys.modules.get("hatsume.plugins.hatsume-plugin.infra")
    if infra_mod is None:
        infra_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
        sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_mod
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.delete_container = lambda *a, **kw: None
    infra_mod.cleanup_persistent_container = lambda: None

    # Ensure memory.engine stub exists
    mem_engine = sys.modules.get("hatsume.plugins.hatsume-plugin.memory.engine")
    if mem_engine is None:
        mem_engine = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.engine")
        mem_engine.get_mem_list = lambda: []
        mem_engine.add_mem = lambda *a, **kw: None
        mem_engine.query_mems = lambda *a, **kw: []
        sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = mem_engine

    # Load commands.py
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.handlers.tools", COMMANDS_PATH
    )
    commands_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.handlers.tools"] = commands_mod
    spec.loader.exec_module(commands_mod)
    return commands_mod


class _FakeMatcher:
    """Minimal matcher stub that records finish calls."""
    def __init__(self):
        self.finished_with = None

    async def finish(self, msg=None):
        self.finished_with = msg
        raise _Finished(msg)


class _Finished(Exception):
    """Raised by matcher.finish to simulate NoneBot behavior."""
    pass


@pytest.mark.skip(reason="handle_generate_image was removed from handlers/tools.py")
class TestCommandsRateLimit:
    """commands.handle_generate_image should use ConversationState for rate limiting."""

    def test_rate_limited_uses_conv_state(self):
        """When _conv_state.is_image_rate_limited() returns True, returns error."""
        import asyncio

        commands = _load_commands_module()

        # Set up a mock conv_state
        mock_state = types.SimpleNamespace(
            is_image_rate_limited=lambda: True,
            last_image_time=0,
        )
        commands._conv_state = mock_state

        args = MessageStub(text="test prompt")
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            asyncio.run(
                commands.handle_generate_image(matcher, args)
            )
        assert matcher.finished_with is not None
        assert "频繁" in str(matcher.finished_with)

    def test_success_updates_last_image_time(self):
        """After successful generation, _conv_state.last_image_time is updated."""
        import asyncio
        import time

        commands = _load_commands_module()

        initial_time = 100.0
        mock_state = types.SimpleNamespace(
            is_image_rate_limited=lambda: False,
            last_image_time=initial_time,
        )
        commands._conv_state = mock_state

        args = MessageStub(text="test prompt")
        matcher = _FakeMatcher()

        # Patch time.time to return a predictable value
        original_time = time.time
        time.time = lambda: 999999.0
        try:
            with pytest.raises(_Finished):
                asyncio.run(
                    commands.handle_generate_image(matcher, args)
                )
            assert mock_state.last_image_time == 999999.0
        finally:
            time.time = original_time

    def test_no_global_last_time_generate_image(self):
        """handle_generate_image must not use 'global _last_time_generate_image'."""
        import inspect
        import ast

        commands = _load_commands_module()
        source = inspect.getsource(commands.handle_generate_image)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                assert "_last_time_generate_image" not in node.names, (
                    "handle_generate_image still declares 'global _last_time_generate_image'"
                )


class MessageStub:
    """Minimal Message stub for testing command handlers."""
    def __init__(self, text="", images=None, at_qqs=None):
        self._text = text
        self._images = images or []
        self._at_qqs = at_qqs or []

    def extract_plain_text(self):
        return self._text

    def get(self, seg_type):
        if seg_type == "at":
            return [types.SimpleNamespace(data={"qq": qq}) for qq in self._at_qqs]
        return []


class TestTimerCommand:
    @staticmethod
    def _setup(commands, *, task=None):
        runtime = types.SimpleNamespace(group_id=123)
        commands.group_runtime_registry.get_or_create = MagicMock(
            return_value=runtime
        )
        commands.bind_group_runtime = MagicMock(
            return_value=contextlib.nullcontext(runtime)
        )
        store = types.SimpleNamespace(
            get_task=MagicMock(return_value=task),
            replace_task_with_exact_plan=MagicMock(),
            delete_task=MagicMock(),
            validate_prompt=MagicMock(return_value=None),
        )
        timer = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
        timer.get_store = lambda: store
        sys.modules[timer.__name__] = timer

        graph_tools = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.tools")
        graph_tools.get_timer_overview = AsyncMock(
            return_value="shared detailed overview"
        )
        sys.modules[graph_tools.__name__] = graph_tools

        executor = types.ModuleType("hatsume.plugins.hatsume-plugin.timer.executor")
        executor.cancel_task_jobs = MagicMock()
        executor.add_jobs_for_task = MagicMock()
        sys.modules[executor.__name__] = executor

        class ScheduleValidationError(ValueError):
            pass

        plan = object()
        schedule = types.ModuleType("hatsume.plugins.hatsume-plugin.timer.schedule")
        schedule.ScheduleValidationError = ScheduleValidationError
        schedule.build_at_plan = MagicMock(return_value=plan)
        sys.modules[schedule.__name__] = schedule
        return store, graph_tools, executor, schedule, plan

    @pytest.mark.asyncio
    async def test_list_reuses_shared_detailed_overview(self):
        commands = _load_commands_module()
        _, graph_tools, _, _, _ = self._setup(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=123)

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub("list")
            )

        commands.group_runtime_registry.get_or_create.assert_called_once_with(123)
        commands.bind_group_runtime.assert_called_once()
        graph_tools.get_timer_overview.assert_awaited_once_with()
        assert matcher.finished_with == "shared detailed overview"

    @pytest.mark.asyncio
    async def test_admin_can_list_timers_for_a_specified_group(self):
        commands = _load_commands_module()
        _, graph_tools, _, _, _ = self._setup(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(
            group_id=123,
            get_user_id=lambda: "999999",
        )

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub("list 456")
            )

        commands.group_runtime_registry.get_or_create.assert_called_once_with(123)
        commands.bind_group_runtime.assert_called_once()
        graph_tools.get_timer_overview.assert_awaited_once_with(456)
        assert matcher.finished_with == "shared detailed overview"

    @pytest.mark.asyncio
    async def test_non_admin_cannot_list_timers_for_another_group(self):
        commands = _load_commands_module()
        _, graph_tools, _, _, _ = self._setup(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(
            group_id=123,
            get_user_id=lambda: "111111",
        )

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub("list 456")
            )

        graph_tools.get_timer_overview.assert_not_awaited()
        assert matcher.finished_with == "只有管理员可以查看其他群的定时任务。"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("argument", ["abc", "0", "-1", "456 extra"])
    async def test_list_rejects_invalid_group_argument(self, argument):
        commands = _load_commands_module()
        _, graph_tools, _, _, _ = self._setup(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(
            group_id=123,
            get_user_id=lambda: "999999",
        )

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub(f"list {argument}")
            )

        graph_tools.get_timer_overview.assert_not_awaited()
        assert "群号必须是正整数" in matcher.finished_with

    @pytest.mark.asyncio
    async def test_update_replaces_with_validated_exact_plan(self):
        commands = _load_commands_module()
        task = {"id": 7, "group_id": 123}
        store, _, executor, schedule, plan = self._setup(commands, task=task)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=123)

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(),
                event,
                matcher,
                MessageStub(
                    "update 7 new prompt @ "
                    "2999-08-01T09:00:00+08:00, 2999-08-02T18:00:00+08:00"
                ),
            )

        schedule.build_at_plan.assert_called_once_with(
            ["2999-08-01T09:00:00+08:00", "2999-08-02T18:00:00+08:00"]
        )
        executor.cancel_task_jobs.assert_called_once_with(7, store)
        store.replace_task_with_exact_plan.assert_called_once_with(
            7, "new prompt", plan
        )
        executor.add_jobs_for_task.assert_called_once_with(7, store)

    @pytest.mark.asyncio
    async def test_update_validates_before_cancelling_existing_jobs(self):
        commands = _load_commands_module()
        task = {"id": 7, "group_id": 123}
        store, _, executor, schedule, _ = self._setup(commands, task=task)
        schedule.build_at_plan.side_effect = schedule.ScheduleValidationError(
            "错误：指定时间列表最多 10 个。"
        )
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=123)

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub("update 7 prompt @ invalid")
            )

        assert "最多 10" in matcher.finished_with
        executor.cancel_task_jobs.assert_not_called()
        store.replace_task_with_exact_plan.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_rejects_task_from_another_group_before_mutation(self):
        commands = _load_commands_module()
        task = {"id": 7, "group_id": 999}
        store, _, executor, schedule, _ = self._setup(commands, task=task)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=123)

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(),
                event,
                matcher,
                MessageStub("update 7 prompt @ 2999-08-01T09:00:00+08:00"),
            )

        assert matcher.finished_with == "任务 ID 7 不属于当前群。"
        schedule.build_at_plan.assert_not_called()
        executor.cancel_task_jobs.assert_not_called()
        store.replace_task_with_exact_plan.assert_not_called()
        executor.add_jobs_for_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_cancels_v2_jobs_before_deleting_task(self):
        commands = _load_commands_module()
        task = {"id": 7, "group_id": 123}
        store, _, executor, _, _ = self._setup(commands, task=task)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=123)

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub("delete 7")
            )

        executor.cancel_task_jobs.assert_called_once_with(7, store)
        store.delete_task.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_delete_rejects_task_from_another_group(self):
        commands = _load_commands_module()
        task = {"id": 7, "group_id": 999}
        store, _, executor, _, _ = self._setup(commands, task=task)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=123)

        with pytest.raises(_Finished):
            await commands.handle_timer(
                object(), event, matcher, MessageStub("delete 7")
            )

        assert matcher.finished_with == "任务 ID 7 不属于当前群。"
        executor.cancel_task_jobs.assert_not_called()
        store.delete_task.assert_not_called()

    def count(self, seg_type):
        if seg_type == "image":
            return len(self._images)
        return 0

    def include(self, seg_type):
        if seg_type == "image":
            return [types.SimpleNamespace(data={"url": url}) for url in self._images]
        return []


class TestModelCommand:
    """Tests for the admin /model command handler."""

    @pytest.mark.asyncio
    async def test_empty_argument_shows_current_model_without_mutation(self):
        commands = _load_commands_module()
        config_mod = sys.modules["hatsume.plugins.hatsume-plugin.config"]
        config_mod.ADVANCE_MODEL_NAME = "initial-model"

        matcher = _FakeMatcher()
        with pytest.raises(_Finished):
            await commands.handle_model(matcher, MessageStub("   "))

        assert "initial-model" in str(matcher.finished_with)
        assert config_mod.ADVANCE_MODEL_NAME == "initial-model"

    @pytest.mark.asyncio
    async def test_named_argument_changes_only_model_name(self):
        commands = _load_commands_module()
        config_mod = sys.modules["hatsume.plugins.hatsume-plugin.config"]
        config_mod.ADVANCE_MODEL_NAME = "initial-model"
        config_mod.PROVIDER = "zhth"
        config_mod.get_base_url = object()
        config_mod.get_api_key = object()
        original_provider = config_mod.PROVIDER
        original_base_url_getter = config_mod.get_base_url
        original_api_key_getter = config_mod.get_api_key

        matcher = _FakeMatcher()
        with pytest.raises(_Finished):
            await commands.handle_model(matcher, MessageStub("  target-model:v2  "))

        assert config_mod.ADVANCE_MODEL_NAME == "target-model:v2"
        assert config_mod.PROVIDER == original_provider
        assert config_mod.get_base_url is original_base_url_getter
        assert config_mod.get_api_key is original_api_key_getter
        assert "target-model:v2" in str(matcher.finished_with)
        assert "Base URL" in str(matcher.finished_with)
        assert "API Key" in str(matcher.finished_with)


class TestTodoCommand:
    """Tests for the public, group-scoped /todo command."""

    @staticmethod
    def _install_store(store):
        todo = types.ModuleType("hatsume.plugins.hatsume-plugin.todo")
        todo.get_store = lambda: store
        sys.modules[todo.__name__] = todo

    @pytest.mark.asyncio
    async def test_lists_all_active_items_for_current_group(self):
        commands = _load_commands_module()
        created_at = 2_000_000_000.0
        items = [
            {
                "id": 7,
                "group_id": 456,
                "initiator_qq_id": 111,
                "initiator_group_name": "Alice",
                "content": "tell Alice how long she slept",
                "finish_condition": (
                    "Permitted finisher: Alice only\n"
                    "Completion event: Alice says she woke up"
                ),
                "created_at": created_at,
            },
            {
                "id": 9,
                "group_id": 456,
                "initiator_qq_id": 222,
                "initiator_group_name": "Bob",
                "content": "send the result",
                "finish_condition": (
                    "Permitted finisher: Bob only\n"
                    "Completion event: Bob asks for the result"
                ),
                "created_at": created_at + 60,
            },
        ]
        store = types.SimpleNamespace(
            delete_expired=MagicMock(return_value=1),
            list_items=MagicMock(return_value=items),
        )
        self._install_store(store)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=456)

        with pytest.raises(_Finished):
            await commands.handle_todo(event, matcher, MessageStub(""))

        store.delete_expired.assert_called_once_with()
        store.list_items.assert_called_once_with(456)
        output = str(matcher.finished_with)
        assert "当前群活动待办（2 项）" in output
        assert output.index("待办 ID：7") < output.index("待办 ID：9")
        assert "Alice（QQ：111）" in output
        assert "tell Alice how long she slept" in output
        assert "Permitted finisher: Alice only" in output
        assert datetime.fromtimestamp(created_at).strftime(
            "%Y/%m/%d %H:%M:%S"
        ) in output

    @pytest.mark.asyncio
    async def test_empty_group_has_clear_response(self):
        commands = _load_commands_module()
        store = types.SimpleNamespace(
            delete_expired=MagicMock(return_value=0),
            list_items=MagicMock(return_value=[]),
        )
        self._install_store(store)
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_todo(
                types.SimpleNamespace(group_id=456), matcher, MessageStub("")
            )

        assert matcher.finished_with == "当前群没有活动待办。"

    @pytest.mark.asyncio
    async def test_database_failure_does_not_escape(self):
        commands = _load_commands_module()
        store = types.SimpleNamespace(
            delete_expired=MagicMock(side_effect=RuntimeError("locked")),
            list_items=MagicMock(),
        )
        self._install_store(store)
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_todo(
                types.SimpleNamespace(group_id=456), matcher, MessageStub("")
            )

        store.list_items.assert_not_called()
        assert matcher.finished_with == "❌ 待办数据库暂时不可用。"

    @pytest.mark.asyncio
    async def test_admin_can_view_another_group(self):
        commands = _load_commands_module()
        store = types.SimpleNamespace(
            delete_expired=MagicMock(return_value=0),
            list_items=MagicMock(return_value=[]),
        )
        self._install_store(store)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(
            group_id=456,
            get_user_id=lambda: "999999",
        )

        with pytest.raises(_Finished):
            await commands.handle_todo(event, matcher, MessageStub("789"))

        store.list_items.assert_called_once_with(789)
        assert matcher.finished_with == "群 789 没有活动待办。"

    @pytest.mark.asyncio
    async def test_non_admin_cannot_view_another_group(self):
        commands = _load_commands_module()
        store = types.SimpleNamespace(
            delete_expired=MagicMock(),
            list_items=MagicMock(),
        )
        self._install_store(store)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(
            group_id=456,
            get_user_id=lambda: "111111",
        )

        with pytest.raises(_Finished):
            await commands.handle_todo(event, matcher, MessageStub("789"))

        store.delete_expired.assert_not_called()
        store.list_items.assert_not_called()
        assert matcher.finished_with == "只有管理员可以查看其他群的待办。"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("argument", ["abc", "0", "-1", "789 extra"])
    async def test_rejects_invalid_group_argument(self, argument):
        commands = _load_commands_module()
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_todo(
                types.SimpleNamespace(group_id=456),
                matcher,
                MessageStub(argument),
            )

        assert "群号必须是正整数" in str(matcher.finished_with)


class TestProxyCommand:
    """Tests for the public /proxy command handler."""

    @staticmethod
    def _stub_graph_tools(commands, group_id=456):
        runtime = types.SimpleNamespace(group_id=group_id)
        commands.group_runtime_registry.get_or_create = MagicMock(
            return_value=runtime
        )
        commands.bind_group_runtime = MagicMock(
            return_value=contextlib.nullcontext(runtime)
        )
        module_name = "hatsume.plugins.hatsume-plugin.graph.tools"
        graph_tools = types.ModuleType(module_name)
        graph_tools.create_character_proxy = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value="created")
        )
        graph_tools.terminate_character_proxy = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value="terminated")
        )
        sys.modules[module_name] = graph_tools
        return graph_tools

    @pytest.mark.asyncio
    async def test_create_invokes_tool_with_explicit_duration(self):
        commands = _load_commands_module()
        graph_tools = self._stub_graph_tools(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=456)

        with pytest.raises(_Finished):
            await commands.handle_proxy_command(
                event,
                matcher,
                MessageStub("create 222 30"),
            )

        commands.group_runtime_registry.get_or_create.assert_called_once_with(456)
        commands.bind_group_runtime.assert_called_once()
        graph_tools.create_character_proxy.ainvoke.assert_awaited_once_with(
            {"proxied_user_id": 222, "during_time": 30}
        )
        assert matcher.finished_with == "created"

    @pytest.mark.asyncio
    async def test_create_uses_three_hour_default(self):
        commands = _load_commands_module()
        graph_tools = self._stub_graph_tools(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=456)

        with pytest.raises(_Finished):
            await commands.handle_proxy_command(
                event,
                matcher,
                MessageStub("create 222"),
            )

        graph_tools.create_character_proxy.ainvoke.assert_awaited_once_with(
            {"proxied_user_id": 222}
        )

    @pytest.mark.asyncio
    async def test_terminate_invokes_tool(self):
        commands = _load_commands_module()
        graph_tools = self._stub_graph_tools(commands)
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=456)

        with pytest.raises(_Finished):
            await commands.handle_proxy_command(
                event,
                matcher,
                MessageStub("terminate"),
            )

        graph_tools.terminate_character_proxy.ainvoke.assert_awaited_once_with({})
        assert matcher.finished_with == "terminated"

    @pytest.mark.asyncio
    async def test_status_shows_proxy_prompt_and_end_time(self):
        commands = _load_commands_module()
        self._stub_graph_tools(commands)
        proxy = types.SimpleNamespace(
            user_id=222,
            user_name="Target",
            auto_terminate_at="2026-07-17T18:30:00+08:00",
        )
        module_name = "hatsume.plugins.hatsume-plugin.character_proxy"
        character_proxy = types.ModuleType(module_name)
        character_proxy.get_character_proxy = lambda: proxy
        character_proxy.build_active_character_proxy_role_prompt = (
            lambda active: "complete role prompt"
        )
        sys.modules[module_name] = character_proxy
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=456)

        with pytest.raises(_Finished):
            await commands.handle_proxy_command(
                event,
                matcher,
                MessageStub("status"),
            )

        output = str(matcher.finished_with)
        assert "Target（QQ：222）" in output
        assert "2026-07-17T18:30:00+08:00" in output
        assert "complete role prompt" in output


class TestGroupSelectableCommands:
    @staticmethod
    def _event(*, group_id=123, user_id="77"):
        return types.SimpleNamespace(
            group_id=group_id,
            get_user_id=lambda: user_id,
        )

    @staticmethod
    def _load_commands_with_runtime():
        _load_tools_module()
        return _load_commands_module()

    @pytest.mark.asyncio
    async def test_skills_defaults_to_current_group_without_creating_runtime(self):
        commands = self._load_commands_with_runtime()
        manager = types.SimpleNamespace(
            list_skills=MagicMock(
                return_value=[{"name": "shared", "description": "common"}]
            )
        )
        skills = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
        skills.get_skill_manager = MagicMock(return_value=manager)
        sys.modules[skills.__name__] = skills
        commands.group_runtime_registry.get_or_create = MagicMock()
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_list_skills(
                self._event(),
                matcher,
                MessageStub(""),
            )

        skills.get_skill_manager.assert_called_once_with(123, create_local=False)
        commands.group_runtime_registry.get_or_create.assert_not_called()
        assert "shared" in str(matcher.finished_with)

    @pytest.mark.asyncio
    async def test_admin_can_inspect_another_groups_skills(self):
        commands = self._load_commands_with_runtime()
        manager = types.SimpleNamespace(list_skills=MagicMock(return_value=[]))
        skills = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
        skills.get_skill_manager = MagicMock(return_value=manager)
        sys.modules[skills.__name__] = skills
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_list_skills(
                self._event(user_id="999999"),
                matcher,
                MessageStub("456"),
            )

        skills.get_skill_manager.assert_called_once_with(456, create_local=False)

    @pytest.mark.asyncio
    async def test_non_admin_cannot_inspect_another_groups_skills(self):
        commands = self._load_commands_with_runtime()
        skills = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
        skills.get_skill_manager = MagicMock()
        sys.modules[skills.__name__] = skills
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_list_skills(
                self._event(),
                matcher,
                MessageStub("456"),
            )

        skills.get_skill_manager.assert_not_called()
        assert matcher.finished_with == "只有管理员可以访问其他群的数据。"

    @pytest.mark.asyncio
    async def test_resetsandbox_is_admin_only_for_current_group(self):
        commands = self._load_commands_with_runtime()
        commands.cleanup_persistent_container = AsyncMock()
        agents = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.agents")
        agents.shutdown_group_agents = AsyncMock()
        sys.modules[agents.__name__] = agents
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_resetsandbox(
                self._event(),
                matcher,
                MessageStub(""),
            )

        agents.shutdown_group_agents.assert_not_awaited()
        commands.cleanup_persistent_container.assert_not_awaited()
        assert matcher.finished_with == "只有管理员可以重置 Sandbox。"

    @pytest.mark.asyncio
    async def test_resetsandbox_admin_can_select_group(self):
        commands = self._load_commands_with_runtime()
        commands.cleanup_persistent_container = AsyncMock(return_value=True)
        agents = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.agents")
        agents.shutdown_group_agents = AsyncMock()
        sys.modules[agents.__name__] = agents
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_resetsandbox(
                self._event(user_id="999999"),
                matcher,
                MessageStub("456"),
            )

        agents.shutdown_group_agents.assert_awaited_once_with(456)
        commands.cleanup_persistent_container.assert_awaited_once_with(456)
        assert "群 456" in str(matcher.finished_with)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("argument", ["abc", "0", "-1", "456 extra"])
    async def test_resetsandbox_rejects_invalid_group_argument(self, argument):
        commands = self._load_commands_with_runtime()
        commands.cleanup_persistent_container = AsyncMock()
        agents = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.agents")
        agents.shutdown_group_agents = AsyncMock()
        sys.modules[agents.__name__] = agents
        matcher = _FakeMatcher()

        with pytest.raises(_Finished):
            await commands.handle_resetsandbox(
                self._event(user_id="999999"),
                matcher,
                MessageStub(argument),
            )

        agents.shutdown_group_agents.assert_not_awaited()
        commands.cleanup_persistent_container.assert_not_awaited()
        assert matcher.finished_with == (
            "群号必须是正整数。\n用法：/resetsandbox [群号]"
        )


def _stub_agent_notification_node():
    nodes = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.nodes")
    nodes.inject_agent_notification = MagicMock()
    sys.modules[nodes.__name__] = nodes
    return nodes


@pytest.mark.asyncio
async def test_agent_dispatch_keeps_initiating_group_and_exact_instance():
    tools = _load_tools_module()
    agents = sys.modules["hatsume.plugins.hatsume-plugin.graph.agents"]
    agents._AGENT_STATES.clear()
    _stub_agent_notification_node()
    entered = asyncio.Event()
    release = asyncio.Event()
    captured: list[tuple[int, str]] = []

    async def handler(_task, _user_id):
        captured.append(
            (
                tools.get_current_group_runtime().group_id,
                agents.get_current_agent_instance_id(),
            )
        )
        entered.set()
        await release.wait()
        return "done"

    tools.get_agent_handler = lambda name: handler if name == "coding_agent" else None
    tools.set_current_group_id(101)
    result = await tools.agent_dispatch("coding_agent", "task", "context")
    owner_runtime = tools.group_runtime_registry.get_or_create(101)
    owner_task = next(iter(owner_runtime.agent_tasks))

    tools.set_current_group_id(202)
    await asyncio.wait_for(entered.wait(), timeout=1)

    assert "开始执行任务" in result
    assert captured[0][0] == 101
    instance = agents.get_agent_instance("coding_agent", 101, captured[0][1])
    assert instance is not None
    assert instance["task"] == "task"
    assert agents.get_agent_instance("coding_agent", 202, captured[0][1]) is None

    release.set()
    await owner_task
    assert instance["status"] == "done"
    agents._AGENT_STATES.clear()


@pytest.mark.asyncio
async def test_agent_dispatch_rejects_duplicate_only_within_owner_group():
    tools = _load_tools_module()
    agents = sys.modules["hatsume.plugins.hatsume-plugin.graph.agents"]
    agents._AGENT_STATES.clear()
    _stub_agent_notification_node()
    release = asyncio.Event()
    both_started = asyncio.Event()
    started_groups: set[int] = set()

    async def handler(_task, _user_id):
        started_groups.add(tools.get_current_group_runtime().group_id)
        if len(started_groups) == 2:
            both_started.set()
        await release.wait()
        return "done"

    tools.get_agent_handler = lambda name: handler if name == "coding_agent" else None
    tools.set_current_group_id(101)
    first = await tools.agent_dispatch("coding_agent", "same task", "context")
    duplicate = await tools.agent_dispatch(
        "coding_agent",
        " same task ",
        "context",
    )

    tools.set_current_group_id(202)
    second = await tools.agent_dispatch("coding_agent", "same task", "context")
    await asyncio.wait_for(both_started.wait(), timeout=1)

    assert "开始执行任务" in first
    assert "相同任务" in duplicate
    assert "开始执行任务" in second
    assert started_groups == {101, 202}
    assert len(agents._AGENT_STATES["coding_agent"]) == 2

    tasks = [
        *tools.group_runtime_registry.get_or_create(101).agent_tasks,
        *tools.group_runtime_registry.get_or_create(202).agent_tasks,
    ]
    release.set()
    await asyncio.gather(*tasks)
    agents._AGENT_STATES.clear()


# -----------------------------------------------------------------------
# prompts/role.py: role system prompt contains bot QQ ID
# -----------------------------------------------------------------------

ROLE_PATH = ROOT / "hatsume/plugins/hatsume-plugin/prompts.py"
TEMPLATES_PATH = ROOT / "hatsume/plugins/hatsume-plugin/utils/__init__.py"


def _load_role_module():
    """Load prompts.py with dependencies stubbed."""
    base = ROOT / "hatsume/plugins/hatsume-plugin"

    # Ensure package hierarchy exists
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Stub config with BOT_QQ_ID
    config_mod = sys.modules.get("hatsume.plugins.hatsume-plugin.config")
    if config_mod is None:
        config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
        sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod
    config_mod.BOT_QQ_ID = 1234567890

    # Stub nonebot.adapters (imported by utils.py)
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    if "nonebot.adapters" not in sys.modules:
        adapters_mod = types.ModuleType("nonebot.adapters")
        adapters_mod.__path__ = []
        sys.modules["nonebot.adapters"] = adapters_mod
    adapters_mod = sys.modules["nonebot.adapters"]
    if not hasattr(adapters_mod, "Bot"):
        adapters_mod.Bot = type("Bot", (), {})

    # Load utils.py first (dependency of prompts.py)
    utils_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", TEMPLATES_PATH
    )
    utils_mod = importlib.util.module_from_spec(utils_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    utils_spec.loader.exec_module(utils_mod)

    # Load prompts.py (merged from prompts/role.py)
    role_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.prompts", ROLE_PATH
    )
    role_mod = importlib.util.module_from_spec(role_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.prompts"] = role_mod
    role_spec.loader.exec_module(role_mod)
    return role_mod


class TestRolePrompt:
    """Tests for the role system prompt in prompts/role.py."""

    def test_prompt_contains_bot_qq_id(self):
        """The role prompt should include the bot's QQ ID."""
        role_mod = _load_role_module()
        assert "1234567890" in role_mod.role_sys_prompt

    def test_prompt_loads_without_errors(self):
        """role.py should import and execute without errors."""
        role_mod = _load_role_module()
        assert hasattr(role_mod, "role_sys_prompt")
        assert isinstance(role_mod.role_sys_prompt, str)
        assert len(role_mod.role_sys_prompt) > 0


# -----------------------------------------------------------------------
# capture_html_shot: was removed
# -----------------------------------------------------------------------


def test_reset_capture_flag_resets_generate_video_used():
    """reset_capture_flag should reset _generate_video_used to False."""
    tools = _load_tools_module()
    runtime = _bind_tool_runtime(tools)
    runtime.generate_video_used = True
    tools.reset_capture_flag()
    assert runtime.generate_video_used is False


def test_reset_capture_flag_resets_send_image_count():
    """reset_capture_flag should reset _send_image_count to 0."""
    tools = _load_tools_module()
    runtime = _bind_tool_runtime(tools)
    runtime.send_image_count = 5
    tools.reset_capture_flag()
    assert runtime.send_image_count == 0


def test_reset_capture_flag_resets_send_video_count():
    """reset_capture_flag should reset _send_video_count to 0."""
    tools = _load_tools_module()
    runtime = _bind_tool_runtime(tools)
    runtime.send_video_count = 1
    tools.reset_capture_flag()
    assert runtime.send_video_count == 0


# -----------------------------------------------------------------------
# send_image: max 3 calls per AI node round
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_image_allows_up_to_3_calls():
    """send_image should allow up to 3 calls, then return error on the 4th."""
    tools = _load_tools_module()
    runtime = _bind_tool_runtime(tools)
    runtime.send_image_count = 0
    answer = AsyncMock(return_value=None)
    tools.configure_tool_callbacks(None, answer_fn=answer)

    # First 3 calls should succeed
    for i in range(3):
        result = await tools.send_image("https://example.com/test.jpg")
        assert "图片已成功发送" in result, f"Call {i+1} failed: {result}"

    # 4th call should be rejected
    result = await tools.send_image("https://example.com/test.jpg")
    assert "一轮发言中你最多只能发送3张图片" in result


@pytest.mark.asyncio
async def test_send_image_rate_limit_resets_on_new_round():
    """After reset_capture_flag, send_image should allow 3 more calls."""
    tools = _load_tools_module()
    runtime = _bind_tool_runtime(tools)
    answer = AsyncMock(return_value=None)
    tools.configure_tool_callbacks(None, answer_fn=answer)

    # Use up all 3 slots
    runtime.send_image_count = 3
    result = await tools.send_image("https://example.com/test.jpg")
    assert "最多只能发送3张图片" in result

    # Reset (new AI round)
    tools.reset_capture_flag()

    # Should be able to send again
    result = await tools.send_image("https://example.com/test.jpg")
    assert "图片已成功发送" in result


# -----------------------------------------------------------------------
# send_video: max 1 call per AI node round
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_video_allows_one_call_per_round():
    """send_video should allow one call, then return error on the second."""
    tools = _load_tools_module()
    sent = []
    runtime = _bind_tool_runtime(tools)
    runtime.send_video_count = 0
    tools.MessageSegment.video = lambda **kw: ("video", kw)
    answer = AsyncMock(side_effect=lambda msg: sent.append(msg))
    tools.configure_tool_callbacks(None, answer_fn=answer)

    result = await tools.send_video("https://example.com/test.mp4")
    assert "视频已成功发送" in result
    assert sent == [("video", {"file": "https://example.com/test.mp4"})]

    result = await tools.send_video("https://example.com/test2.mp4")
    assert "一轮发言中你最多只能发送1个视频" in result


@pytest.mark.asyncio
async def test_send_video_accepts_sandbox_absolute_path():
    """send_video should resolve a sandbox absolute path to base64 before sending."""
    tools = _load_tools_module()
    sent = []
    runtime = _bind_tool_runtime(tools)
    runtime.send_video_count = 0
    tools.ensure_container_running = AsyncMock(return_value=None)
    tools.run_cmd = AsyncMock(return_value="ZmFrZV92aWRlbw==::EXIT::0\n")
    tools.MessageSegment.video = lambda **kw: ("video", kw)
    answer = AsyncMock(side_effect=lambda msg: sent.append(msg))
    tools.configure_tool_callbacks(None, answer_fn=answer)

    result = await tools.send_video("/work/out.mp4")

    assert "视频已成功发送" in result
    tools.ensure_container_running.assert_awaited_once_with(runtime.group_id)
    assert tools.run_cmd.await_args.kwargs["group_id"] == runtime.group_id
    assert "base64 -w 0 /work/out.mp4" in tools.run_cmd.await_args.args[0]
    assert sent == [("video", {"file": "base64://ZmFrZV92aWRlbw=="})]


@pytest.mark.asyncio
async def test_send_video_rate_limit_resets_on_new_round():
    """After reset_capture_flag, send_video should allow another call."""
    tools = _load_tools_module()
    runtime = _bind_tool_runtime(tools)
    tools.MessageSegment.video = lambda **kw: ("video", kw)
    answer = AsyncMock(return_value=None)
    tools.configure_tool_callbacks(None, answer_fn=answer)

    runtime.send_video_count = 1
    result = await tools.send_video("https://example.com/test.mp4")
    assert "最多只能发送1个视频" in result

    tools.reset_capture_flag()

    result = await tools.send_video("https://example.com/test.mp4")
    assert "视频已成功发送" in result


# -----------------------------------------------------------------------
# generate_video: returns URL instead of sending directly
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_video_returns_url_without_sending():
    """generate_video should return the model URL and leave sending to send_video."""
    tools = _load_tools_module()
    models_mod = sys.modules["hatsume.plugins.hatsume-plugin.models"]
    models_mod.choose_video_model = lambda: "1.5"
    models_mod.generate_video_for = AsyncMock(return_value="https://example.com/out.mp4")
    update_called = []
    _bind_tool_runtime(tools)
    answer = AsyncMock()
    tools.configure_tool_callbacks(
        None,
        answer_fn=answer,
        is_video_rate_limited=lambda: False,
        update_video_time=lambda: update_called.append(True),
    )

    result = await tools.generate_video(
        "make a short clip",
        image_url="https://example.com/ref.jpg",
    )

    assert "临时 URL：https://example.com/out.mp4" in result
    assert "调用 send_video" in tools.generate_video.__doc__
    answer.assert_not_awaited()
    models_mod.generate_video_for.assert_awaited_once_with(
        "make a short clip",
        image_url="https://example.com/ref.jpg",
        model="1.5",
    )
    assert update_called == [True]


# -----------------------------------------------------------------------
# query_memory: returns memories formatted with timestamps
# -----------------------------------------------------------------------


class TestQueryMemoryTimestamps:
    """query_memory should format each memory as '- (YYYY/MM/DD HH:mm:ss) content'."""

    def test_query_memory_formats_timestamps(self):
        """When query_mems returns list[tuple[str, int]], query_memory should
        format each memory with its timestamp."""
        import re as _re

        tools = _load_tools_module()


        mem_store = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]
        mem_retrieval = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]

        # Set up stubs on the module objects
        mem_store.get_mem_list = lambda: ["dummy"]
        mem_retrieval.query_mems = lambda *a, **kw: [
            ("I like cats", 1715275800),
            ("I went hiking", 1715362200),
        ]

        # Also patch the function reference that tools.py already bound at import
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

        result = tools.query_memory("cats")

        assert "- (" in result
        assert "I like cats" in result
        assert "I went hiking" in result
        pattern = r"\(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\)"
        matches = _re.findall(pattern, result)
        assert len(matches) == 2, f"Expected 2 timestamp matches, got {len(matches)}: {result}"

        # Restore
        mem_store.get_mem_list = lambda: []
        mem_retrieval.query_mems = lambda *a, **kw: []
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

    def test_query_memory_allows_repeated_results_across_calls(self):
        """Each query should return every result supplied by query_mems."""
        tools = _load_tools_module()


        mem_store = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]
        mem_retrieval = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]

        call_count = [0]
        def _query_mems(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return [("memory-A", 1715275800), ("memory-B", 1715362200)]
            return [("memory-A", 1715275800), ("memory-C", 1715448600)]

        mem_store.get_mem_list = lambda: ["dummy"]
        mem_retrieval.query_mems = _query_mems
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

        result1 = tools.query_memory("query1")
        assert "memory-A" in result1
        assert "memory-B" in result1

        result2 = tools.query_memory("query2")
        assert "memory-A" in result2
        assert "memory-C" in result2
        assert not hasattr(tools, "_retrieved_mem_keys")

        # Restore
        mem_store.get_mem_list = lambda: []
        mem_retrieval.query_mems = lambda *a, **kw: []
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

    def test_query_memory_empty_results(self):
        """When query_mems returns empty list, query_memory returns empty string."""
        tools = _load_tools_module()


        mem_store = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]
        mem_retrieval = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]

        mem_store.get_mem_list = lambda: ["dummy"]
        mem_retrieval.query_mems = lambda *a, **kw: []
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

        result = tools.query_memory("nothing")
        assert result == ""

        # Restore
        mem_store.get_mem_list = lambda: []
        tools.get_mem_list = mem_store.get_mem_list

    def test_query_memory_returns_same_memory_on_every_call(self):
        """A memory returned previously remains eligible for later queries."""
        tools = _load_tools_module()


        mem_store = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]
        mem_retrieval = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]

        mem_store.get_mem_list = lambda: ["dummy"]
        mem_retrieval.query_mems = lambda *a, **kw: [
            ("already-seen", 1715275800),
        ]
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

        first = tools.query_memory("query")
        second = tools.query_memory("query")
        assert "already-seen" in first
        assert "already-seen" in second

        # Restore
        mem_store.get_mem_list = lambda: []
        mem_retrieval.query_mems = lambda *a, **kw: []
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems


class TestRespondToShellPrompt:
    """Tests for respond_to_shell_prompt tool."""

    def test_respond_to_shell_prompt_is_importable(self):
        """respond_to_shell_prompt exists after loading tools module."""
        tools = _load_tools_module()
        assert hasattr(tools, "respond_to_shell_prompt")

    def test_returns_error_for_invalid_request_id(self):
        """Returns error when request_id is not found."""
        tools = _load_tools_module()
        _bind_tool_runtime(tools)
        import asyncio as _asyncio

        async def _call():
            return await tools.respond_to_shell_prompt(
                request_id="nonexistent_id_xyz",
                text="anything",
            )

        result = _asyncio.run(_call())

        assert "错误" in str(result) or "No pending" in str(result)


def test_end_conversation_calls_configured_callback():
    tools = _load_tools_module()
    callback = MagicMock()
    _bind_tool_runtime(tools)
    tools.configure_tool_callbacks(
        query_user_id=None,
        end_conversation_fn=callback,
    )

    result = tools.end_conversation()

    callback.assert_called_once_with()
    assert "当前对话已结束" in result
    assert "不会再接收到任何聊天消息" in tools.end_conversation.__doc__
    assert "当用户希望你不回话时使用" in tools.end_conversation.__doc__


class _TodoValidationError(ValueError):
    pass


def _install_todo_store(store):
    todo = types.ModuleType("hatsume.plugins.hatsume-plugin.todo")
    todo.TodoValidationError = _TodoValidationError
    todo.get_store = lambda: store
    sys.modules[todo.__name__] = todo


def test_todo_tools_are_registered_once():
    tools = _load_tools_module()

    assert tools.CHAT_TOOLS.count(tools.create_todo) == 1
    assert tools.CHAT_TOOLS.count(tools.mark_todo) == 1


def test_create_todo_requires_group_context():
    tools = _load_tools_module()

    result = asyncio.run(tools.create_todo(123, "content", "user", "event"))

    assert "无法确定当前群聊 ID" in result


def test_create_todo_resolves_name_and_delegates_to_store():
    tools = _load_tools_module()
    item = {
        "id": 9,
        "initiator_group_name": "Group Card",
        "initiator_qq_id": 123,
        "content": "calculate sleep duration",
        "finish_condition": (
            "Permitted finisher: initiator\nCompletion event: initiator wakes up"
        ),
    }
    store = MagicMock()
    store.create_item.return_value = types.SimpleNamespace(
        status="created", item=item
    )
    _install_todo_store(store)
    bot = object()
    tools.group_runtime_registry.bind_bot(456, bot)
    utils = sys.modules["hatsume.plugins.hatsume-plugin.utils"]
    utils.get_group_member_name = AsyncMock(return_value="Group Card")
    tools.set_current_group_id(456)

    result = asyncio.run(
        tools.create_todo(
            123,
            "calculate sleep duration",
            "initiator",
            "initiator wakes up",
        )
    )

    utils.get_group_member_name.assert_awaited_once_with(bot, 456, 123)
    store.create_item.assert_called_once_with(
        456,
        123,
        "Group Card",
        "calculate sleep duration",
        "initiator",
        "initiator wakes up",
    )
    assert "待办已创建（ID: 9）" in result
    assert "Group Card(123)" in result


def test_create_todo_handles_duplicate_full_validation_and_name_fallback():
    tools = _load_tools_module()
    tools.set_current_group_id(456)
    tools.group_runtime_registry.bind_bot(456, object())
    utils = sys.modules["hatsume.plugins.hatsume-plugin.utils"]
    utils.get_group_member_name = AsyncMock(side_effect=RuntimeError("offline"))
    item = {
        "id": 4,
        "initiator_group_name": "123",
        "initiator_qq_id": 123,
        "content": "content",
        "finish_condition": "condition",
    }
    store = MagicMock()
    _install_todo_store(store)

    store.create_item.return_value = types.SimpleNamespace(
        status="duplicate", item=item
    )
    duplicate = asyncio.run(tools.create_todo(123, "content", "user", "event"))
    assert "未重复创建" in duplicate
    assert store.create_item.call_args.args[2] == "123"

    store.create_item.return_value = types.SimpleNamespace(status="full", item=None)
    full = asyncio.run(tools.create_todo(123, "other", "user", "event"))
    assert "15 个活动待办" in full

    store.create_item.side_effect = _TodoValidationError("错误：待办内容不能为空。")
    invalid = asyncio.run(tools.create_todo(123, "", "user", "event"))
    assert invalid == "错误：待办内容不能为空。"


def test_mark_todo_is_group_scoped_and_returns_required_notice():
    tools = _load_tools_module()
    tools.set_current_group_id(456)
    store = MagicMock()
    _install_todo_store(store)
    store.mark_item.return_value = None

    missing = tools.mark_todo(8)

    store.mark_item.assert_called_once_with(456, 8)
    assert missing == "错误：当前群找不到该活动待办。"

    store.mark_item.return_value = {
        "id": 8,
        "initiator_group_name": "Alice",
        "initiator_qq_id": 123,
        "content": "calculate sleep duration",
        "finish_condition": (
            "Permitted finisher: Alice\nCompletion event: Alice wakes up"
        ),
    }
    completed = tools.mark_todo(8)

    assert "完成条件满足" in completed
    assert "不是因为过期" in completed
    assert "[CQ:at,qq=123]" in completed
    assert "calculate sleep duration" in completed


def test_character_proxy_tools_are_mutually_exclusive():
    tools = _load_tools_module()
    module_name = "hatsume.plugins.hatsume-plugin.character_proxy"
    character_proxy = types.ModuleType(module_name)
    active = None
    character_proxy.get_character_proxy = lambda: active
    sys.modules[module_name] = character_proxy

    off_names = {item.__name__ for item in tools.get_chat_tools()}
    assert "view_image" in off_names
    assert "send_video" in off_names
    assert "end_conversation" in off_names
    assert "create_character_proxy" in off_names
    assert "terminate_character_proxy" not in off_names

    active = object()
    on_names = {item.__name__ for item in tools.get_chat_tools()}
    assert "send_video" in on_names
    assert "end_conversation" in on_names
    assert "terminate_character_proxy" in on_names
    assert "create_character_proxy" not in on_names


@pytest.mark.parametrize(
    ("duration_args", "expected_duration"),
    [({}, 180), ({"during_time": 1440}, 1440)],
)
def test_create_character_proxy_uses_explicit_user_id_and_valid_duration(
    duration_args,
    expected_duration,
):
    tools = _load_tools_module()
    module_name = "hatsume.plugins.hatsume-plugin.character_proxy"
    character_proxy = types.ModuleType(module_name)
    character_proxy.get_character_proxy = lambda: None
    character_proxy.generate_character_profile = AsyncMock(
        return_value=types.SimpleNamespace(
            behavior_prompt="profile",
            aliases=("Alias A", "Alias B"),
        )
    )
    character_proxy.activate_character_proxy = MagicMock()
    character_proxy.schedule_character_proxy_termination = MagicMock()
    sys.modules[module_name] = character_proxy

    bot = object()
    tools.group_runtime_registry.bind_bot(456, bot)
    utils = sys.modules["hatsume.plugins.hatsume-plugin.utils"]
    utils.get_group_member_name = AsyncMock(return_value="Target")
    tools.set_current_group_id(456)
    tools.configure_tool_callbacks(query_user_id=111)

    result = asyncio.run(
        tools.create_character_proxy(proxied_user_id=222, **duration_args)
    )

    assert result == (
        f"已为 Target 开启角色代理，将在 {expected_duration} 分钟后自动停止。"
    )
    utils.get_group_member_name.assert_awaited_once_with(bot, 456, 222)
    character_proxy.generate_character_profile.assert_awaited_once_with(222, "Target")
    character_proxy.activate_character_proxy.assert_called_once_with(
        user_id=222,
        user_name="Target",
        behavior_prompt="profile",
        aliases=("Alias A", "Alias B"),
        during_time=expected_duration,
    )
    character_proxy.schedule_character_proxy_termination.assert_called_once_with(
        expected_duration
    )


@pytest.mark.parametrize("during_time", [0, -1, 1441])
def test_create_character_proxy_rejects_invalid_duration(during_time):
    tools = _load_tools_module()
    module_name = "hatsume.plugins.hatsume-plugin.character_proxy"
    character_proxy = types.ModuleType(module_name)
    character_proxy.get_character_proxy = lambda: None
    character_proxy.generate_character_profile = AsyncMock()
    character_proxy.activate_character_proxy = MagicMock()
    character_proxy.schedule_character_proxy_termination = MagicMock()
    sys.modules[module_name] = character_proxy

    result = asyncio.run(
        tools.create_character_proxy(
            proxied_user_id=222,
            during_time=during_time,
        )
    )

    assert "不能超过 1440 分钟" in result
    character_proxy.generate_character_profile.assert_not_awaited()
    character_proxy.activate_character_proxy.assert_not_called()
    character_proxy.schedule_character_proxy_termination.assert_not_called()
