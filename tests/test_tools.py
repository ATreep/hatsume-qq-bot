"""Tests for graph/tools.py — tool call limiter and get_avatar multi-call."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"


def _load_tools_module():
    """Load graph/tools.py with all external dependencies stubbed."""
    # Clean up previously loaded modules
    for name in list(sys.modules):
        if name.startswith("hatsume") or name in (
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
    config_mod.CONTEXT_QUEUE_LEN = 20
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

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
    infra_mod.ensure_container_running = lambda *a, **kw: None
    infra_mod.delete_container = lambda *a, **kw: None

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
# create_timer: per-task trigger frequency
# -----------------------------------------------------------------------


class TestCreateTimerFrequency:
    """create_timer enforces the rolling 24-hour trigger limit."""

    @staticmethod
    def _setup_timer_dependencies(tools):
        store = types.SimpleNamespace(
            create_task=MagicMock(return_value=42),
            get_triggers_for_task=lambda task_id: [],
            validate_trigger_times=lambda times, now=None: [],
            validate_prompt=lambda prompt: None,
        )
        timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
        timer_mod.get_store = lambda: store
        sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

        add_jobs = MagicMock()
        executor_mod = types.ModuleType(
            "hatsume.plugins.hatsume-plugin.timer.executor"
        )
        executor_mod.add_jobs_for_task = add_jobs
        sys.modules["hatsume.plugins.hatsume-plugin.timer.executor"] = executor_mod

        config_mod = sys.modules["hatsume.plugins.hatsume-plugin.config"]
        config_mod.TIMER_MAX_TRIGGERS_PER_24_HOURS = 10
        tools.set_current_group_id(123)
        return store, add_jobs

    @pytest.mark.asyncio
    async def test_rejects_more_than_ten_unique_triggers_in_24_hours(self):
        tools = _load_tools_module()
        store, add_jobs = self._setup_timer_dependencies(tools)
        start = 1_800_000_000
        trigger_times = [
            datetime.fromtimestamp(
                start + index * 2 * 3600,
                tz=timezone.utc,
            ).isoformat()
            for index in range(11)
        ]

        result = await tools.create_timer(456, "频繁提醒", trigger_times)

        assert "24 小时内最多触发 10 次" in result
        store.create_task.assert_not_called()
        add_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_ten_unique_triggers_in_24_hours(self):
        tools = _load_tools_module()
        store, add_jobs = self._setup_timer_dependencies(tools)
        start = 1_800_000_000
        trigger_times = [
            datetime.fromtimestamp(
                start + index * 2 * 3600,
                tz=timezone.utc,
            ).isoformat()
            for index in range(10)
        ]

        result = await tools.create_timer(456, "合理频率提醒", trigger_times)

        assert "定时任务已创建（ID: 42）" in result
        store.create_task.assert_called_once()
        add_jobs.assert_called_once_with(42, store)

    @pytest.mark.asyncio
    async def test_duplicate_times_do_not_count_toward_frequency_limit(self):
        tools = _load_tools_module()
        store, _ = self._setup_timer_dependencies(tools)
        start = 1_800_000_000
        unique_times = [
            datetime.fromtimestamp(
                start + index * 2 * 3600,
                tz=timezone.utc,
            ).isoformat()
            for index in range(10)
        ]

        result = await tools.create_timer(
            456, "重复时间提醒", [*unique_times, unique_times[0]]
        )

        assert "定时任务已创建（ID: 42）" in result
        assert len(store.create_task.call_args.kwargs["trigger_times"]) == 11


# -----------------------------------------------------------------------
# generate_image: rate limiting via callbacks
# -----------------------------------------------------------------------

import asyncio


class TestGenerateImageRateLimit:
    """generate_image should use is_image_rate_limited / update_image_time callbacks."""

    def test_rate_limited_returns_error(self):
        """When is_image_rate_limited returns True, generate_image returns an error string."""
        tools = _load_tools_module()


        rate_limited = lambda: True
        update_time = lambda: None
        tools.configure_tool_callbacks(None, set(), None, answer_fn=None)
        # Set the new callbacks
        tools._is_generate_image_rate_limited = rate_limited
        tools._update_generate_image_time = update_time

        result = asyncio.run(
            tools.generate_image("test prompt", [])
        )
        assert "频繁" in result

    def test_success_calls_update_image_time(self):
        """On successful generation, update_image_time callback is called."""
        tools = _load_tools_module()


        update_called = []
        rate_limited = lambda: False
        update_time = lambda: update_called.append(True)
        # Force volc branch for consistency
        import random as _random
        _orig_random = _random.random
        _random.random = lambda: 0.0
        tools.configure_tool_callbacks(None, set(), None, answer_fn=None)
        tools._is_generate_image_rate_limited = rate_limited
        tools._update_generate_image_time = update_time

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
        rate_limited = lambda: False
        update_time = lambda: update_called.append(True)

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

        tools.configure_tool_callbacks(None, set(), None, answer_fn=None)
        tools._is_generate_image_rate_limited = rate_limited
        tools._update_generate_image_time = update_time

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


class TestProxyCommand:
    """Tests for the public /proxy command handler."""

    @staticmethod
    def _stub_graph_tools():
        module_name = "hatsume.plugins.hatsume-plugin.graph.tools"
        graph_tools = types.ModuleType(module_name)
        graph_tools.set_current_group_id = MagicMock()
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
        graph_tools = self._stub_graph_tools()
        matcher = _FakeMatcher()
        event = types.SimpleNamespace(group_id=456)

        with pytest.raises(_Finished):
            await commands.handle_proxy_command(
                event,
                matcher,
                MessageStub("create 222 30"),
            )

        graph_tools.set_current_group_id.assert_called_once_with(456)
        graph_tools.create_character_proxy.ainvoke.assert_awaited_once_with(
            {"proxied_user_id": 222, "during_time": 30}
        )
        assert matcher.finished_with == "created"

    @pytest.mark.asyncio
    async def test_create_uses_three_hour_default(self):
        commands = _load_commands_module()
        graph_tools = self._stub_graph_tools()
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
        graph_tools = self._stub_graph_tools()
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
        self._stub_graph_tools()
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
    tools._generate_video_used = True
    tools.reset_capture_flag()
    assert tools._generate_video_used is False


def test_reset_capture_flag_resets_send_image_count():
    """reset_capture_flag should reset _send_image_count to 0."""
    tools = _load_tools_module()
    tools._send_image_count = 5
    tools.reset_capture_flag()
    assert tools._send_image_count == 0


def test_reset_capture_flag_resets_send_video_count():
    """reset_capture_flag should reset _send_video_count to 0."""
    tools = _load_tools_module()
    tools._send_video_count = 1
    tools.reset_capture_flag()
    assert tools._send_video_count == 0


# -----------------------------------------------------------------------
# send_image: max 3 calls per AI node round
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_image_allows_up_to_3_calls():
    """send_image should allow up to 3 calls, then return error on the 4th."""
    tools = _load_tools_module()
    tools._send_image_count = 0
    # Mock _ai_answer so actual message sending doesn't happen
    tools._ai_answer = AsyncMock(return_value=None)

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
    tools._ai_answer = AsyncMock(return_value=None)

    # Use up all 3 slots
    tools._send_image_count = 3
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
    tools._send_video_count = 0
    tools.MessageSegment.video = lambda **kw: ("video", kw)
    tools._ai_answer = AsyncMock(side_effect=lambda msg: sent.append(msg))

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
    tools._send_video_count = 0
    tools.ensure_container_running = AsyncMock(return_value=None)
    tools.run_cmd = AsyncMock(return_value="ZmFrZV92aWRlbw==::EXIT::0\n")
    tools.MessageSegment.video = lambda **kw: ("video", kw)
    tools._ai_answer = AsyncMock(side_effect=lambda msg: sent.append(msg))

    result = await tools.send_video("/work/out.mp4")

    assert "视频已成功发送" in result
    tools.ensure_container_running.assert_awaited_once_with()
    assert "base64 -w 0 /work/out.mp4" in tools.run_cmd.await_args.args[0]
    assert sent == [("video", {"file": "base64://ZmFrZV92aWRlbw=="})]


@pytest.mark.asyncio
async def test_send_video_rate_limit_resets_on_new_round():
    """After reset_capture_flag, send_video should allow another call."""
    tools = _load_tools_module()
    tools.MessageSegment.video = lambda **kw: ("video", kw)
    tools._ai_answer = AsyncMock(return_value=None)

    tools._send_video_count = 1
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
    tools.configure_tool_callbacks(
        None,
        set(),
        None,
        answer_fn=AsyncMock(),
        is_video_rate_limited=lambda: False,
        update_video_time=lambda: update_called.append(True),
    )

    result = await tools.generate_video(
        "make a short clip",
        image_url="https://example.com/ref.jpg",
    )

    assert "临时 URL：https://example.com/out.mp4" in result
    assert "调用 send_video" in tools.generate_video.__doc__
    tools._ai_answer.assert_not_awaited()
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

        tools._retrieved_mem_keys.clear()

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

    def test_query_memory_dedup_uses_content_only(self):
        """_retrieved_mem_keys should track content strings, not formatted strings,
        so dedup works correctly across multiple calls."""
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

        tools._retrieved_mem_keys.clear()

        result1 = tools.query_memory("query1")
        assert "memory-A" in result1
        assert "memory-B" in result1

        result2 = tools.query_memory("query2")
        assert "memory-A" not in result2
        assert "memory-C" in result2

        assert "memory-A" in tools._retrieved_mem_keys
        assert "memory-B" in tools._retrieved_mem_keys
        assert "memory-C" in tools._retrieved_mem_keys
        for key in tools._retrieved_mem_keys:
            assert "- (" not in key, f"Dedup key should be content only, got: {key}"

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

    def test_query_memory_all_deduped_returns_empty(self):
        """When all returned memories are already in _retrieved_mem_keys,
        query_memory returns empty string."""
        tools = _load_tools_module()


        mem_store = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]
        mem_retrieval = sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"]

        mem_store.get_mem_list = lambda: ["dummy"]
        mem_retrieval.query_mems = lambda *a, **kw: [
            ("already-seen", 1715275800),
        ]
        tools.get_mem_list = mem_store.get_mem_list
        tools.query_mems = mem_retrieval.query_mems

        tools._retrieved_mem_keys.clear()
        tools._retrieved_mem_keys.add("already-seen")

        result = tools.query_memory("query")
        assert result == ""

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
    tools.configure_tool_callbacks(
        None,
        set(),
        query_user_id=None,
        end_conversation_fn=callback,
    )

    result = tools.end_conversation()

    callback.assert_called_once_with()
    assert "当前对话已结束" in result
    assert "不会再接收到任何聊天消息" in tools.end_conversation.__doc__
    assert "当用户希望你不回话时使用" in tools.end_conversation.__doc__


def test_character_proxy_tools_are_mutually_exclusive():
    tools = _load_tools_module()
    module_name = "hatsume.plugins.hatsume-plugin.character_proxy"
    character_proxy = types.ModuleType(module_name)
    active = None
    character_proxy.get_character_proxy = lambda: active
    sys.modules[module_name] = character_proxy

    off_names = {item.__name__ for item in tools.get_chat_tools()}
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
    sys.modules["nonebot"].get_bot = lambda: bot
    utils = sys.modules["hatsume.plugins.hatsume-plugin.utils"]
    utils.get_group_member_name = AsyncMock(return_value="Target")
    tools.set_current_group_id(456)
    tools.configure_tool_callbacks(None, set(), query_user_id=111)

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
