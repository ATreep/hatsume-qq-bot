# Group Member Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fuzzy group member search as both an LLM tool and `/membersearch` slash command, sharing core logic in utils.py.

**Architecture:** Core `search_group_members()` in utils.py fetches the group member list, runs two-pass matching (substring → character-overlap, max 5 results), and fetches level per match. The LLM tool in graph/tools.py wraps it reading `_current_group_id`. The command handler in handlers/commands.py wraps it reading `event.group_id`. Member list is cached per group_id for 300s TTL.

**Tech Stack:** Python 3.12+, NoneBot2 (OneBot V11), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `hatsume/plugins/hatsume-plugin/utils.py` | Modify | Add `search_group_members()` — core fuzzy search logic + cache |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Modify | Add `membersearch` @tool — LLM-facing wrapper |
| `hatsume/plugins/hatsume-plugin/handlers/commands.py` | Modify | Add `handle_membersearch()` — command handler |
| `hatsume/plugins/hatsume-plugin/__init__.py` | Modify | Register `on_command("membersearch")` matcher + handler |
| `tests/test_membersearch.py` | Create | Tests for core search, tool, and command handler |

---

### Task 1: Core search function in utils.py

**Files:**
- Create: `tests/test_membersearch.py`
- Modify: `hatsume/plugins/hatsume-plugin/utils.py`

- [ ] **Step 1: Write the failing test for `search_group_members`**

```python
"""Tests for group member search: core function, tool, and command handler."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UTILS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/utils.py"


def _load_utils_module():
    """Load utils.py with nonebot stubs."""
    for name in list(sys.modules):
        if name.startswith("hatsume.plugins.hatsume-plugin") and "utils" in name:
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    # Package hierarchy
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Stub nonebot
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    if "nonebot.adapters" not in sys.modules:
        adapters_mod = types.ModuleType("nonebot.adapters")
        adapters_mod.__path__ = []
        sys.modules["nonebot.adapters"] = adapters_mod

    # Load utils.py
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
        info = self._member_info.get(uid, {})
        return info


def _make_member(user_id, nickname="", card=""):
    """Create a member dict matching OneBot V11 get_group_member_list format."""
    return {"user_id": user_id, "nickname": nickname, "card": card}


def _make_member_info(nickname="", card="", level="活跃LV1"):
    """Create a member info dict matching OneBot V11 get_group_member_info format."""
    return {"nickname": nickname, "card": card, "level": level}


# -----------------------------------------------------------------------
# Tests: search_group_members
# -----------------------------------------------------------------------

class TestSearchGroupMembers:
    """Tests for the core search_group_members function."""

    async def _search(self, bot, query, max_results=5):
        """Helper to call search_group_members and clear cache between tests."""
        utils = _load_utils_module()
        # Clear module-level cache
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
        # Exact substring match "菠萝" should come before longer match
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
        # "菠蜜" — no substring match, but "菠" overlaps with "菠萝包", "蜜" with "水蜜桃"
        results = await self._search(bot, "菠蜜")
        assert len(results) > 0
        # "水蜜桃" has overlap "蜜", "菠萝包" has overlap "菠"
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
        # member_info dict is empty — simulates API failure (KeyError)
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

        # First call — should hit API
        await utils.search_group_members(bot, 12345, "菠萝")
        assert call_count[0] == 1

        # Second call (same group_id) — should use cache
        await utils.search_group_members(bot, 12345, "菠萝")
        assert call_count[0] == 1, "Cache should prevent second API call"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_membersearch.py -v`
Expected: FAIL — `search_group_members` not defined, or `AttributeError: module ... has no attribute 'search_group_members'`

- [ ] **Step 3: Write minimal implementation in utils.py**

Add to the end of `hatsume/plugins/hatsume-plugin/utils.py`:

```python
# ---------------------------------------------------------------------------
# Group member fuzzy search
# ---------------------------------------------------------------------------
import time as _time

_member_list_cache: dict[int, tuple[float, list[dict]]] = {}


async def search_group_members(
    bot: Bot, group_id: int, query: str, max_results: int = 5
) -> list[dict[str, str]]:
    """Fuzzy search group members by nickname/card.

    Two-pass matching:
    1. Substring match (case-insensitive) — ranked first (most accurate)
    2. Character-overlap — for remaining members, ranked by overlap ratio

    Returns up to max_results matches sorted by relevance.
    Each result: {"username": str, "id": str, "level": str}
    """
    if not query.strip():
        return []

    # Fetch member list (with TTL cache per group_id)
    now = _time.time()
    if group_id in _member_list_cache:
        cached_at, cached_list = _member_list_cache[group_id]
        if now - cached_at < 300:
            members = cached_list
        else:
            del _member_list_cache[group_id]
            members = await bot.get_group_member_list(group_id=group_id)
            _member_list_cache[group_id] = (now, members)
    else:
        members = await bot.get_group_member_list(group_id=group_id)
        _member_list_cache[group_id] = (now, members)

    query_lower = query.lower()

    # Build username list: (user_id, username)
    entries: list[tuple[int, str]] = []
    for m in members:
        username = m["card"].strip() if m.get("card", "").strip() else m.get("nickname", "")
        if username:
            entries.append((m["user_id"], username))

    # Pass 1: substring match
    substring_matches: list[dict[str, str]] = []
    remaining: list[tuple[int, str]] = []
    for uid, username in entries:
        if query_lower in username.lower():
            substring_matches.append({"username": username, "id": str(uid)})
        else:
            remaining.append((uid, username))

    # Pass 2: character-overlap match
    query_chars = set(query)
    char_matches: list[tuple[float, int, str]] = []  # (neg_overlap, uid, username)
    for uid, username in remaining:
        username_chars = set(username)
        overlap = len(query_chars & username_chars)
        if overlap > 0:
            ratio = overlap / max(len(query_chars), len(username_chars))
            char_matches.append((-ratio, uid, username))

    # Sort by overlap ratio descending (neg → ascending = highest ratio first)
    char_matches.sort()
    for neg_ratio, uid, username in char_matches:
        substring_matches.append({"username": username, "id": str(uid)})

    # Truncate
    results = substring_matches[:max_results]

    # Fetch level for each result
    for r in results:
        try:
            info = await bot.get_group_member_info(
                group_id=group_id, user_id=int(r["id"]), no_cache=True
            )
            r["level"] = info.get("level", "未知") if isinstance(info, dict) else "未知"
        except Exception:
            r["level"] = "未知"

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_membersearch.py::TestSearchGroupMembers -v`
Expected: ALL PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/utils.py tests/test_membersearch.py
git commit -m "feat: add search_group_members() core function with fuzzy matching"
```

---

### Task 2: LLM tool in graph/tools.py

**Files:**
- Modify: `tests/test_membersearch.py` (append tests)
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

- [ ] **Step 1: Write the failing test for `membersearch` tool**

Append to `tests/test_membersearch.py`:

```python
# -----------------------------------------------------------------------
# Tests: membersearch @tool
# -----------------------------------------------------------------------

TOOLS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/graph/tools.py"


def _load_tools_module_for_membersearch():
    """Load graph/tools.py with all external dependencies stubbed, including our new utils."""
    # Clean up
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

    # Package hierarchy
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

    # Stub nonebot
    sys.modules["nonebot"] = types.ModuleType("nonebot")
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    sys.modules["nonebot.adapters"] = adapters_mod
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = type("Message", (), {})
    v11_mod.MessageSegment = types.SimpleNamespace(text=lambda s: s, image=lambda *a, **kw: None)
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod
    sys.modules["nonebot.params"] = types.ModuleType("nonebot.params")

    # Stub langchain
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
    # Real mock: @tool decorator passes function through
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

    # Stub config
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.ADMIN_QQ_ID = 999999
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    config_mod.DOCKER_ENV_PATH = "/tmp"
    config_mod.SHELL_MAX_OUTPUT = 1000
    config_mod.SHELL_TIMEOUT = 10
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    # Stub models
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

    # Stub memory
    memory_store = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.store")
    memory_store.get_mem_list = lambda: []
    memory_store.add_mem = lambda *a, **kw: None
    memory_store.resolve_active_memory_people = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.store"] = memory_store
    memory_retrieval = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.retrieval")
    memory_retrieval.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.retrieval"] = memory_retrieval

    # Stub infra
    infra_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.ensure_container_running = lambda *a, **kw: None
    infra_mod.delete_container = lambda *a, **kw: None
    infra_mod.render_html_to_image = lambda *a, **kw: b"fake_png"
    sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_mod

    # --- Stub utils with our real search_group_members ---
    # Load the real utils.py so tests can test the tool calling through to real search
    utils_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", UTILS_PATH
    )
    utils_mod = importlib.util.module_from_spec(utils_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    utils_spec.loader.exec_module(utils_mod)

    # Stub skills
    skills_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
    skills_mod.get_skill_manager = lambda: types.SimpleNamespace(
        load_skill=lambda name: f"skill '{name}' content",
        remove_skill=lambda name: f"skill '{name}' removed",
        list_skills=lambda: [],
    )
    sys.modules["hatsume.plugins.hatsume-plugin.skills"] = skills_mod

    # Stub timer
    timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
    timer_mod.get_store = lambda: types.SimpleNamespace(
        create_task=lambda *a, **kw: 1,
        list_tasks_by_group=lambda gid: [],
        get_task=lambda tid: None,
        get_triggers_for_task=lambda tid: [],
        validate_trigger_times=lambda times, now=None: [],
        validate_prompt=lambda p: None,
        delete_task=lambda tid: None,
        update_task=lambda tid, p, ts: None,
    )
    sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

    # Load tools.py
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
        tools.reset_tool_call_counts()
        return tools

    @pytest.mark.asyncio
    async def test_membersearch_returns_json_array(self):
        """membersearch tool should return a JSON array string of results."""
        tools = self._setup_tool()
        # Patch search_group_members in the loaded utils module
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
        tools.reset_tool_call_counts()

        result = await tools.membersearch("菠萝")
        assert "错误" in result
        assert "群聊" in result or "group" in result.lower()

    @pytest.mark.asyncio
    async def test_membersearch_respects_check_tool_call(self):
        """Second call to membersearch should be blocked by check_tool_call."""
        tools = self._setup_tool()
        utils_stub = sys.modules["hatsume.plugins.hatsume-plugin.utils"]

        async def _mock_search(bot, group_id, query, max_results=5):
            return [{"username": "菠萝", "id": "111", "level": "活跃LV1"}]

        original_search = utils_stub.search_group_members
        utils_stub.search_group_members = _mock_search

        result1 = await tools.membersearch("菠萝")
        assert "错误" not in result1

        result2 = await tools.membersearch("菠萝")
        assert "错误" in result2
        assert "membersearch" in result2

        utils_stub.search_group_members = original_search
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_membersearch.py::TestMembersearchTool -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'membersearch'`

- [ ] **Step 3: Write minimal implementation in graph/tools.py**

Add to the end of `hatsume/plugins/hatsume-plugin/graph/tools.py` (after the skill_download tool):

```python
@tool
async def membersearch(query: str) -> str:
    """
    在当前群聊中模糊搜索群成员。根据用户提供的模糊/不完整昵称，查找匹配的群成员信息。

    ## 参数：
    - query: 模糊搜索关键词，支持部分昵称、群名片等。如 "菠萝"

    ## 返回：
    返回一个 JSON 数组，每个元素包含：
    - username: 群成员的用户名（优先群名片，无群名片则使用昵称）
    - id: 成员的 QQ 号
    - level: 成员的活跃等级

    列表最多返回 5 个结果，排在越前面的结果越准确。

    ## 使用场景：
    - 用户提到某个不完整的名字，你需要确定具体是谁
    - 有人提到"那个叫什么菠萝的"，你搜索 "菠萝" 来找出可能的成员
    """
    import json
    from nonebot import get_bot
    from ..utils import search_group_members

    global _current_group_id

    if _current_group_id is None:
        return json.dumps({"error": "错误：无法确定当前群聊 ID。"}, ensure_ascii=False)

    err = check_tool_call("membersearch")
    if err:
        return err

    try:
        bot = get_bot()
        results = await search_group_members(bot, _current_group_id, query)
    except Exception as e:
        print(f"❌ membersearch failed: {e}")
        import traceback
        traceback.print_exc()
        return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)

    if not results:
        return "未找到匹配的群成员。"

    return json.dumps(results, ensure_ascii=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_membersearch.py::TestMembersearchTool -v`
Expected: ALL PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py tests/test_membersearch.py
git commit -m "feat: add membersearch @tool for LLM fuzzy group member search"
```

---

### Task 3: Command handler + registration

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/commands.py` (append handler)
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py` (register command)
- Modify: `tests/test_membersearch.py` (append tests)

- [ ] **Step 1: Write the failing test for command handler**

Append to `tests/test_membersearch.py`:

```python
# -----------------------------------------------------------------------
# Tests: handle_membersearch command handler
# -----------------------------------------------------------------------

COMMANDS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/handlers/commands.py"


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

    sys.modules["nonebot"] = types.ModuleType("nonebot")
    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    sys.modules["nonebot.adapters"] = adapters_mod
    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod
    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = type("Message", (), {})
    v11_mod.MessageSegment = types.SimpleNamespace(text=lambda s: s, image=lambda *a, **kw: None)
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod
    sys.modules["nonebot.params"] = types.ModuleType("nonebot.params")

    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.ADMIN_QQ_ID = 999999
    config_mod.IMAGE_RATE_LIMIT_SECONDS = 30
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    state_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.state")
    state_mod.ConversationState = type("ConversationState", (), {})
    sys.modules["hatsume.plugins.hatsume-plugin.state"] = state_mod

    infra_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
    infra_mod.run_cmd = lambda *a, **kw: ""
    infra_mod.delete_container = lambda *a, **kw: None
    sys.modules["hatsume.plugins.hatsume-plugin.infra"] = infra_mod

    models_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.models")
    models_mod.generate_image_for = lambda *a, **kw: "http://example.com/img.png"
    models_mod.choose_image_model = lambda: "4"
    models_mod.generate_video_for = lambda *a, **kw: None
    models_mod.choose_video_model = lambda: "1.5"
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod

    mem_store = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.store")
    mem_store.get_mem_list = lambda: []
    mem_store.add_mem = lambda *a, **kw: None
    sys.modules["hatsume.plugins.hatsume-plugin.memory.store"] = mem_store
    mem_retrieval = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.retrieval")
    mem_retrieval.query_mems = lambda *a, **kw: []
    sys.modules["hatsume.plugins.hatsume-plugin.memory.retrieval"] = mem_retrieval

    timer_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.timer")
    timer_mod.get_store = lambda: types.SimpleNamespace(
        create_task=lambda *a, **kw: 1,
        list_tasks_by_group=lambda gid: [],
        get_task=lambda tid: None,
        get_triggers_for_task=lambda tid: [],
        validate_trigger_times=lambda times, now=None: [],
        validate_prompt=lambda p: None,
        delete_task=lambda tid: None,
        update_task=lambda tid, p, ts: None,
    )
    sys.modules["hatsume.plugins.hatsume-plugin.timer"] = timer_mod

    skills_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.skills")
    skills_mod.get_skill_manager = lambda: types.SimpleNamespace(
        list_skills=lambda: [],
        load_skill=lambda n: f"skill: {n}",
        remove_skill=lambda n: f"removed: {n}",
    )
    sys.modules["hatsume.plugins.hatsume-plugin.skills"] = skills_mod

    # Load real utils.py and optionally patch search_group_members
    utils_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", UTILS_PATH
    )
    utils_mod = importlib.util.module_from_spec(utils_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    utils_spec.loader.exec_module(utils_mod)

    if patch_search is not None:
        utils_mod.search_group_members = patch_search

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.handlers.commands", COMMANDS_PATH
    )
    commands_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.handlers.commands"] = commands_mod
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_membersearch.py::TestHandleMembersearchCommand -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'handle_membersearch'`

- [ ] **Step 3a: Write the command handler in handlers/commands.py**

Add to the end of `hatsume/plugins/hatsume-plugin/handlers/commands.py` (after `handle_list_skills`):

```python
async def handle_membersearch(bot, event, matcher, args: Message) -> None:
    """Handle /membersearch command: fuzzy search group members."""
    from ..utils import search_group_members

    query = args.extract_plain_text().strip()

    if not query:
        await matcher.finish(
            "用法：/membersearch <昵称关键词>\n"
            "示例：/membersearch 菠萝\n\n"
            "模糊搜索当前群聊中的成员，最多返回 5 个结果。"
        )

    try:
        results = await search_group_members(bot, event.group_id, query)
    except Exception as e:
        print(f"❌ membersearch command failed: {e}")
        import traceback
        traceback.print_exc()
        await matcher.finish(f"搜索失败：{e}")

    if not results:
        await matcher.finish(f"未找到匹配 '{query}' 的群成员。")

    lines = [f"搜索 '{query}' 的结果："]
    for i, r in enumerate(results):
        lines.append(f"{i + 1}. {r['username']} (QQ: {r['id']}) - {r['level']}")
    await matcher.finish("\n".join(lines))
```

- [ ] **Step 3b: Register the command in \_\_init\_\_.py**

Two edits to `hatsume/plugins/hatsume-plugin/__init__.py`:

Edit 1: Update the import line (~line 15) to include `handle_membersearch`:

Change:
```python
from .handlers.commands import handle_shell, handle_generate_image, handle_generate_video, handle_timer, handle_list_skills
```
To:
```python
from .handlers.commands import handle_shell, handle_generate_image, handle_generate_video, handle_timer, handle_list_skills, handle_membersearch
```

Edit 2: Add command matcher after `likerank_cmd` (~line 41):

```python
membersearch_cmd = on_command("membersearch", priority=10, block=True)
```

Edit 3: Add handler after the likerank handler block (~line 111):

```python
@membersearch_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_membersearch(bot, event, membersearch_cmd, args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_membersearch.py::TestHandleMembersearchCommand -v`
Expected: ALL PASS (3 tests)

- [ ] **Step 5: Run ALL tests to verify nothing broken**

Run: `python -m pytest tests/test_membersearch.py -v`
Expected: ALL 16 tests PASS (9 core + 4 tool + 3 command)

Run: `python -m pytest tests/ -v`
Expected: All existing tests continue to PASS

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/handlers/commands.py hatsume/plugins/hatsume-plugin/__init__.py tests/test_membersearch.py
git commit -m "feat: add /membersearch slash command and wire to search_group_members"
```
