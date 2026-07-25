"""Tests for group member search: core function, tool, and command handler."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UTILS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/utils/__init__.py"
TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"
COMMANDS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/handlers/tools.py"


def _load_utils_module():
    """Load utils.py with nonebot stubs."""
    for name in list(sys.modules):
        if name.startswith("hatsume.plugins.hatsume-plugin") and "utils" in name:
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    if "nonebot.adapters" not in sys.modules:
        adapters_mod = types.ModuleType("nonebot.adapters")
        adapters_mod.__path__ = []
        sys.modules["nonebot.adapters"] = adapters_mod
    adapters_mod = sys.modules["nonebot.adapters"]
    if not hasattr(adapters_mod, "Bot"):
        adapters_mod.Bot = type("Bot", (), {})

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", UTILS_PATH
    )
    utils_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    spec.loader.exec_module(utils_mod)
    return utils_mod


# -----------------------------------------------------------------------
# Fake Bot for testing
# -----------------------------------------------------------------------

class FakeBot:
    """Fake NoneBot Bot that returns configurable member lists and info."""

    def __init__(self, members=None, member_info=None):
        self._members = members or []
        self._member_info = member_info or {}

    async def get_group_member_list(self, group_id=None):
        return self._members

    async def get_group_member_info(self, group_id=None, user_id=None, no_cache=False):
        uid = str(user_id)
        return self._member_info.get(uid, {})


def _make_member(user_id, nickname="", card=""):
    """Create a member dict matching OneBot V11 get_group_member_list format."""
    return {"user_id": user_id, "nickname": nickname, "card": card}


def _make_member_info(nickname="", card="", level="活跃LV1"):
    """Create a member info dict matching OneBot V11 get_group_member_info format."""
    return {"nickname": nickname, "card": card, "level": level}


class _FakeMatcher:
    """Minimal matcher stub that records finish calls."""
    def __init__(self):
        self.finished_with = None

    async def finish(self, msg=None):
        self.finished_with = msg
        raise _MatcherFinished(msg)


class _MatcherFinished(Exception):
    """Raised by matcher.finish to simulate NoneBot behavior."""
    pass


class _FakeEvent:
    """Fake GroupMessageEvent for testing command handlers."""
    def __init__(self, group_id=12345, user_id=999):
        self.group_id = group_id
        self.user_id = user_id


class _FakeBotForCommand:
    """Fake bot that returns configurable member data."""
    def __init__(self, members=None, member_info=None):
        self._members = members or []
        self._member_info = member_info or {}

    async def get_group_member_list(self, group_id=None):
        return self._members

    async def get_group_member_info(self, group_id=None, user_id=None, no_cache=False):
        return self._member_info.get(str(user_id), {})


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


# -----------------------------------------------------------------------
# Tests: search_group_members
# -----------------------------------------------------------------------

class TestSearchGroupMembers:
    """Tests for the core search_group_members function."""

    async def _search(self, bot, query, max_results=5):
        """Helper to call search_group_members and clear cache between tests."""
        utils = _load_utils_module()
        if hasattr(utils, "_member_list_cache"):
            utils._member_list_cache.clear()
        return await utils.search_group_members(bot, 12345, query, max_results)

    @pytest.mark.asyncio
    async def test_substring_match(self):
        """Substring match should return members whose name contains the query."""
        bot = FakeBot(members=[
            _make_member(111, nickname="张三", card=""),
            _make_member(222, nickname="李四", card="菠萝面包"),
            _make_member(333, nickname="王五", card=""),
        ], member_info={
            "111": _make_member_info(nickname="张三", level="活跃LV1"),
            "222": _make_member_info(nickname="李四", card="菠萝面包", level="活跃LV6"),
            "333": _make_member_info(nickname="王五", level="活跃LV2"),
        })
        results = await self._search(bot, "菠萝")
        assert len(results) == 1
        assert results[0]["username"] == "菠萝面包"
        assert results[0]["id"] == "222"
        assert results[0]["level"] == "活跃LV6"

    @pytest.mark.asyncio
    async def test_card_priority_over_nickname(self):
        """Username should use card if non-empty, else nickname."""
        bot = FakeBot(members=[
            _make_member(111, nickname="张三", card="三爷"),
        ], member_info={
            "111": _make_member_info(nickname="张三", card="三爷", level="活跃LV3"),
        })
        results = await self._search(bot, "三")
        assert results[0]["username"] == "三爷"

    @pytest.mark.asyncio
    async def test_nickname_fallback_when_card_empty(self):
        """When card is empty, username should be nickname."""
        bot = FakeBot(members=[
            _make_member(111, nickname="张三", card=""),
        ], member_info={
            "111": _make_member_info(nickname="张三", card="", level="活跃LV3"),
        })
        results = await self._search(bot, "张")
        assert results[0]["username"] == "张三"

    @pytest.mark.asyncio
    async def test_substring_before_character_overlap(self):
        """Substring matches must appear before character-overlap matches."""
        bot = FakeBot(members=[
            _make_member(111, nickname="测试菠萝二号", card=""),
            _make_member(222, nickname="菠萝", card=""),
        ], member_info={
            "111": _make_member_info(nickname="测试菠萝二号", level="活跃LV1"),
            "222": _make_member_info(nickname="菠萝", level="活跃LV2"),
        })
        results = await self._search(bot, "菠萝")
        assert len(results) == 2
        assert results[0]["username"] == "菠萝"
        assert results[1]["username"] == "测试菠萝二号"

    @pytest.mark.asyncio
    async def test_character_overlap_fallback(self):
        """When no substring matches, character-overlap should return results."""
        bot = FakeBot(members=[
            _make_member(111, nickname="菠萝包", card=""),
            _make_member(222, nickname="水蜜桃", card=""),
            _make_member(333, nickname="哈密瓜", card=""),
        ], member_info={
            "111": _make_member_info(nickname="菠萝包", level="活跃LV1"),
            "222": _make_member_info(nickname="水蜜桃", level="活跃LV2"),
            "333": _make_member_info(nickname="哈密瓜", level="活跃LV3"),
        })
        results = await self._search(bot, "菠蜜")
        assert len(results) > 0
        usernames = [r["username"] for r in results]
        assert "水蜜桃" in usernames or "菠萝包" in usernames

    @pytest.mark.asyncio
    async def test_max_results_truncated_to_5(self):
        """Results must be truncated to max_results (default 5)."""
        members = []
        infos = {}
        for i in range(10):
            name = f"菠萝{i}号"
            uid = 100 + i
            members.append(_make_member(uid, nickname=name, card=""))
            infos[str(uid)] = _make_member_info(nickname=name, level="活跃LV1")

        bot = FakeBot(members=members, member_info=infos)
        results = await self._search(bot, "菠萝")
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        """No match should return an empty list."""
        bot = FakeBot(members=[
            _make_member(111, nickname="张三", card=""),
        ], member_info={
            "111": _make_member_info(nickname="张三", level="活跃LV1"),
        })
        results = await self._search(bot, "xyzabc")
        assert results == []

    @pytest.mark.asyncio
    async def test_level_defaults_to_unknown_on_api_failure(self):
        """When get_group_member_info fails, level should default to '未知'."""
        bot = FakeBot(members=[
            _make_member(111, nickname="菠萝", card=""),
        ])

        async def _failing_info(group_id=None, user_id=None, no_cache=False):
            raise RuntimeError("API error")
        bot.get_group_member_info = _failing_info

        results = await self._search(bot, "菠萝")
        assert len(results) == 1
        assert results[0]["level"] == "未知"

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self):
        """Substring matching should be case-insensitive."""
        bot = FakeBot(members=[
            _make_member(111, nickname="BoLuo", card=""),
        ], member_info={
            "111": _make_member_info(nickname="BoLuo", level="活跃LV1"),
        })
        results = await self._search(bot, "boluo")
        assert len(results) == 1
        assert results[0]["username"] == "BoLuo"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        """Empty query should return empty results."""
        bot = FakeBot(members=[
            _make_member(111, nickname="张三", card=""),
        ], member_info={
            "111": _make_member_info(nickname="张三", level="活跃LV1"),
        })
        results = await self._search(bot, "")
        assert results == []

    @pytest.mark.asyncio
    async def test_member_list_cache(self):
        """Member list should be cached per group_id for 300 seconds."""
        utils = _load_utils_module()
        if hasattr(utils, "_member_list_cache"):
            utils._member_list_cache.clear()

        call_count = [0]
        members = [_make_member(111, nickname="菠萝", card="")]

        async def _counting_get_members(group_id=None):
            call_count[0] += 1
            return members

        bot = FakeBot(members=members, member_info={
            "111": _make_member_info(nickname="菠萝", level="活跃LV1"),
        })
        bot.get_group_member_list = _counting_get_members

        await utils.search_group_members(bot, 12345, "菠萝")
        assert call_count[0] == 1

        await utils.search_group_members(bot, 12345, "菠萝")
        assert call_count[0] == 1, "Cache should prevent second API call"


# -----------------------------------------------------------------------
# Tests: membersearch @tool
# -----------------------------------------------------------------------

def _load_tools_module_for_membersearch():
    """Load graph/tools.py with all external dependencies stubbed."""
    for name in list(sys.modules):
        if name.startswith("hatsume"):
            del sys.modules[name]
    for name in ("nonebot", "nonebot.adapters", "nonebot.adapters.onebot",
                 "nonebot.adapters.onebot.v11", "nonebot.params",
                 "langchain", "langchain.messages", "langchain.agents",
                 "langchain_core", "langchain_core.messages", "langchain_core.tools",
                 "langchain_community", "langchain_community.tools"):
        if name in sys.modules:
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
        ("hatsume.plugins.hatsume-plugin.graph", base / "graph"),
        ("hatsume.plugins.hatsume-plugin.memory", base / "memory"),
        ("hatsume.plugins.hatsume-plugin.infra", base / "infra"),
        ("hatsume.plugins.hatsume-plugin.handlers", base / "handlers"),
    ]:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.get_bot = lambda: None
    sys.modules["nonebot"] = nonebot_mod
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    adapters_mod.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters"] = adapters_mod
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = type("Message", (), {})
    v11_mod.MessageSegment = types.SimpleNamespace(text=lambda s: s, image=lambda *a, **kw: None)
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11_mod.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod
    sys.modules["nonebot.params"] = types.ModuleType("nonebot.params")

    sys.modules["langchain"] = types.ModuleType("langchain")
    langchain_messages = types.ModuleType("langchain.messages")
    langchain_messages.SystemMessage = type("SystemMessage", (), {"__init__": lambda s, c="": None})
    langchain_messages.HumanMessage = type("HumanMessage", (), {"__init__": lambda s, c="": None})
    sys.modules["langchain.messages"] = langchain_messages
    sys.modules["langchain.agents"] = types.ModuleType("langchain.agents")
    langchain_core = types.ModuleType("langchain_core")
    langchain_core.__path__ = []
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.messages"] = types.ModuleType("langchain_core.messages")
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
    config_mod.ADMIN_QQ_ID = 999999
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    config_mod.DOCKER_ENV_PATH = "/tmp"
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    config_mod.BOT_QQ_ID = 1234567890
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.get_lite_model = lambda **kw: types.SimpleNamespace(invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"))
    models_mod.get_code_model = lambda **kw: types.SimpleNamespace(
        invoke=lambda *a, **kw: types.SimpleNamespace(content="ok"),
        ainvoke=lambda *a, **kw: types.SimpleNamespace(content="ok"),
    )
    models_mod.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
    models_mod.choose_image_model = lambda: "4"
    models_mod.generate_video_for = lambda *a, **kw: None
    models_mod.choose_video_model = lambda: "1.5"
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    memory_engine = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.engine")
    memory_engine.get_mem_list = lambda: []
    memory_engine.add_mem = lambda *a, **kw: None
    memory_engine.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = memory_engine
    # Also set directly on memory module since __init__.py re-exports from engine
    if "hatsume.plugins.hatsume-plugin.memory" in sys.modules:
        memory = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
        memory.get_mem_list = lambda: []
        memory.add_mem = lambda *a, **kw: None
        memory.query_mems = lambda *a, **kw: []

    infra_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.ensure_container_running = lambda *a, **kw: None
    infra_mod.delete_container = lambda *a, **kw: None
    infra_mod.render_html_to_image = lambda *a, **kw: b"fake_png"
    sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_mod

    utils_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", UTILS_PATH
    )
    utils_mod = importlib.util.module_from_spec(utils_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    utils_spec.loader.exec_module(utils_mod)

    skills_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
    skills_mod.get_skill_manager = lambda: types.SimpleNamespace(
        load_skill=lambda name: f"skill '{name}' content",
        remove_skill=lambda name: f"skill '{name}' removed",
        list_skills=lambda: [],
    )
    sys.modules["hatsume.plugins.hatsume-plugin.skills"] = skills_mod

    timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
    timer_mod.get_store = lambda: types.SimpleNamespace(
        create_task=lambda *a, **kw: 1,
        list_tasks_by_group=lambda gid: [],
        get_task=lambda tid: None,
        get_points_for_task=lambda tid: [],
        validate_prompt=lambda p: None,
        delete_task=lambda tid: None,
        replace_task_with_exact_plan=lambda tid, p, plan: None,
    )
    sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.graph.tools", TOOLS_PATH
    )
    tools_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"] = tools_mod
    spec.loader.exec_module(tools_mod)
    return tools_mod


class TestMembersearchTool:
    """Tests for the membersearch @tool."""

    def _setup_tool(self, group_id=99999):
        """Load tools module and set _current_group_id."""
        tools = _load_tools_module_for_membersearch()
        tools.set_current_group_id(group_id)
        return tools

    @pytest.mark.asyncio
    async def test_membersearch_returns_json_array(self):
        """membersearch tool should return a JSON array string of results."""
        tools = self._setup_tool()
        utils_stub = sys.modules["hatsume.plugins.hatsume-plugin.utils"]

        async def _mock_search(bot, group_id, query, max_results=5):
            return [
                {"username": "菠萝面包", "id": "123456", "level": "活跃LV6"},
                {"username": "测试菠萝二号", "id": "000002", "level": "未知"},
            ]

        original_search = utils_stub.search_group_members
        utils_stub.search_group_members = _mock_search

        import json
        result = await tools.membersearch("菠萝")
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["username"] == "菠萝面包"
        assert parsed[0]["id"] == "123456"
        assert parsed[0]["level"] == "活跃LV6"

        utils_stub.search_group_members = original_search

    @pytest.mark.asyncio
    async def test_membersearch_empty_results(self):
        """membersearch should return a message when no matches."""
        tools = self._setup_tool()
        utils_stub = sys.modules["hatsume.plugins.hatsume-plugin.utils"]

        async def _mock_search(bot, group_id, query, max_results=5):
            return []

        original_search = utils_stub.search_group_members
        utils_stub.search_group_members = _mock_search

        result = await tools.membersearch("zzzz")
        assert "未找到" in result

        utils_stub.search_group_members = original_search

    @pytest.mark.asyncio
    async def test_membersearch_no_group_id(self):
        """membersearch should return error when _current_group_id is None."""
        tools = _load_tools_module_for_membersearch()
        tools.set_current_group_id(None)

        result = await tools.membersearch("菠萝")
        assert "错误" in result


# -----------------------------------------------------------------------
# Tests: handle_membersearch command handler
# -----------------------------------------------------------------------

def _load_commands_for_membersearch(patch_search=None):
    """Load commands.py with stubs, optionally patching search_group_members."""
    for name in list(sys.modules):
        if name.startswith("hatsume"):
            del sys.modules[name]
    for name in ("nonebot", "nonebot.adapters", "nonebot.adapters.onebot",
                 "nonebot.adapters.onebot.v11", "nonebot.params"):
        if name in sys.modules:
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
        ("hatsume.plugins.hatsume-plugin.handlers", base / "handlers"),
        ("hatsume.plugins.hatsume-plugin.memory", base / "memory"),
        ("hatsume.plugins.hatsume-plugin.infra", base / "infra"),
        ("hatsume.plugins.hatsume-plugin.graph", base / "graph"),
    ]:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

    nonebot_mod = types.ModuleType("nonebot")
    sys.modules["nonebot"] = nonebot_mod
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    adapters_mod.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters"] = adapters_mod
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = type("Message", (), {})
    v11_mod.MessageSegment = types.SimpleNamespace(text=lambda s: s, image=lambda *a, **kw: None)
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11_mod.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod
    sys.modules["nonebot.params"] = types.ModuleType("nonebot.params")

    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.ADMIN_QQ_ID = 999999
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    config_mod.BOT_QQ_ID = 1234567890
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    state_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.state")
    state_mod.ConversationState = type("ConversationState", (), {})
    sys.modules["hatsume.plugins.hatsume-plugin.state"] = state_mod

    infra_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.delete_container = lambda *a, **kw: None
    infra_mod.cleanup_persistent_container = lambda: None
    sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_mod

    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
    models_mod.choose_image_model = lambda: "4"
    models_mod.generate_video_for = lambda *a, **kw: None
    models_mod.choose_video_model = lambda: "1.5"
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    mem_engine = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.engine")
    mem_engine.get_mem_list = lambda: []
    mem_engine.add_mem = lambda *a, **kw: None
    mem_engine.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.engine"] = mem_engine
    # Also set directly on memory module since __init__.py re-exports from engine
    if "hatsume.plugins.hatsume-plugin.memory" in sys.modules:
        memory = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
        memory.get_mem_list = lambda: []
        memory.add_mem = lambda *a, **kw: None
        memory.query_mems = lambda *a, **kw: []

    timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
    timer_mod.get_store = lambda: types.SimpleNamespace(
        create_task=lambda *a, **kw: 1,
        list_tasks_by_group=lambda gid: [],
        get_task=lambda tid: None,
        get_points_for_task=lambda tid: [],
        validate_prompt=lambda p: None,
        delete_task=lambda tid: None,
        replace_task_with_exact_plan=lambda tid, p, plan: None,
    )
    sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

    skills_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
    skills_mod.get_skill_manager = lambda: types.SimpleNamespace(
        list_skills=lambda: [],
        load_skill=lambda n: f"skill: {n}",
        remove_skill=lambda n: f"removed: {n}",
    )
    sys.modules["hatsume.plugins.hatsume-plugin.skills"] = skills_mod

    utils_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", UTILS_PATH
    )
    utils_mod = importlib.util.module_from_spec(utils_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    utils_spec.loader.exec_module(utils_mod)

    if patch_search is not None:
        utils_mod.search_group_members = patch_search

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.handlers.tools", COMMANDS_PATH
    )
    commands_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.handlers.tools"] = commands_mod
    spec.loader.exec_module(commands_mod)
    return commands_mod


class TestHandleMembersearchCommand:
    """Tests for the handle_membersearch command handler."""

    @pytest.mark.asyncio
    async def test_command_returns_formatted_results(self):
        """handle_membersearch should format search results as readable text."""
        async def _mock_search(bot, group_id, query, max_results=5):
            return [
                {"username": "菠萝面包", "id": "123456", "level": "活跃LV6"},
            ]

        commands_mod = _load_commands_for_membersearch(patch_search=_mock_search)

        bot = _FakeBotForCommand()
        event = _FakeEvent(group_id=12345)
        matcher = _FakeMatcher()
        args = MessageStub("菠萝")

        with pytest.raises(_MatcherFinished):
            await commands_mod.handle_membersearch(bot, event, matcher, args)

        assert "菠萝面包" in str(matcher.finished_with)
        assert "123456" in str(matcher.finished_with)
        assert "活跃LV6" in str(matcher.finished_with)

    @pytest.mark.asyncio
    async def test_command_empty_query_shows_help(self):
        """Empty query should show usage help."""
        commands_mod = _load_commands_for_membersearch()

        bot = _FakeBotForCommand()
        event = _FakeEvent()
        matcher = _FakeMatcher()
        args = MessageStub("")

        with pytest.raises(_MatcherFinished):
            await commands_mod.handle_membersearch(bot, event, matcher, args)

        assert "用法" in str(matcher.finished_with) or "/membersearch" in str(matcher.finished_with)

    @pytest.mark.asyncio
    async def test_command_no_results(self):
        """When no members match, show no-results message."""
        async def _empty_search(bot, group_id, query, max_results=5):
            return []

        commands_mod = _load_commands_for_membersearch(patch_search=_empty_search)

        bot = _FakeBotForCommand()
        event = _FakeEvent()
        matcher = _FakeMatcher()
        args = MessageStub("zzzznobody")

        with pytest.raises(_MatcherFinished):
            await commands_mod.handle_membersearch(bot, event, matcher, args)

        assert "未找到" in str(matcher.finished_with)
