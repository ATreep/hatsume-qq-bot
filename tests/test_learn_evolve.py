"""Focused tests for group-scoped, midnight learning evolution."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import sqlite3
import sys
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


class MockFinished(Exception):
    """Simulate NoneBot matcher.finish stopping handler execution."""


REGISTERED_JOBS: dict[str, dict] = {}
STUBBED_MODULE_PREFIXES = (
    "apscheduler",
    "hatsume",
    "nonebot",
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_localstore",
)


def _is_stubbed_module(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in STUBBED_MODULE_PREFIXES
    )


@pytest.fixture(autouse=True)
def _restore_stubbed_modules():
    original = {
        name: module for name, module in sys.modules.items() if _is_stubbed_module(name)
    }
    yield
    for name in list(sys.modules):
        if _is_stubbed_module(name):
            del sys.modules[name]
    sys.modules.update(original)


def _recording_scheduled_job(*args, **kwargs):
    if "replace_existing" in kwargs:
        raise TypeError(
            "scheduled_job already supplies replace_existing to add_job"
        )
    REGISTERED_JOBS[str(kwargs.get("id"))] = {"args": args, "kwargs": kwargs}

    def decorator(function):
        return function

    return decorator


def _install_package_tree() -> None:
    for prefix in (
        "apscheduler",
        "hatsume",
        "hatsume.plugins",
        "hatsume.plugins.hatsume-plugin",
        "hatsume.plugins.hatsume_plugin",
        "nonebot",
        "nonebot_plugin_apscheduler",
    ):
        for name in list(sys.modules):
            if name == prefix or name.startswith(prefix + "."):
                del sys.modules[name]

    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
    alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
    alias.__path__ = [str(PLUGIN_DIR)]
    sys.modules["hatsume.plugins.hatsume_plugin"] = alias


def _install_evolution_stubs() -> None:
    _install_package_tree()
    REGISTERED_JOBS.clear()

    scheduler = types.SimpleNamespace(scheduled_job=_recording_scheduled_job)
    nonebot = types.ModuleType("nonebot")
    nonebot.require = lambda _name: types.SimpleNamespace(scheduler=scheduler)
    scheduler_module = types.ModuleType("nonebot_plugin_apscheduler")
    scheduler_module.scheduler = scheduler
    sys.modules["nonebot"] = nonebot
    sys.modules["nonebot_plugin_apscheduler"] = scheduler_module

    config = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config.ADMIN_QQ_ID = "12345"
    config.LEARN_EVOLVE_MEMORY_LIMIT = 100
    config.LEARN_EVOLVE_WINDOW_HOURS = 24
    sys.modules[config.__name__] = config
    sys.modules[config.__name__.replace("hatsume-plugin", "hatsume_plugin")] = config

    memory = types.ModuleType("hatsume.plugins.hatsume-plugin.memory")
    memory.get_db = MagicMock(return_value="connection")
    memory.get_activated_group_ids = MagicMock(return_value=(101, 202, 303))
    memory.query_recent_memories = MagicMock(return_value=[])
    sys.modules[memory.__name__] = memory
    sys.modules[memory.__name__.replace("hatsume-plugin", "hatsume_plugin")] = memory

    prompts = types.ModuleType("hatsume.plugins.hatsume-plugin.prompts")
    prompts.build_learn_evolve_prompt = MagicMock(return_value="SYSTEM-PROMPT")
    sys.modules[prompts.__name__] = prompts
    sys.modules[prompts.__name__.replace("hatsume-plugin", "hatsume_plugin")] = prompts

    nodes = types.ModuleType("hatsume.plugins.hatsume-plugin.graph.nodes")
    nodes.inject_learn_evolve = MagicMock()
    graph = types.ModuleType("hatsume.plugins.hatsume-plugin.graph")
    graph.__path__ = [str(PLUGIN_DIR / "graph")]
    sys.modules[graph.__name__] = graph
    sys.modules[graph.__name__.replace("hatsume-plugin", "hatsume_plugin")] = graph
    sys.modules[nodes.__name__] = nodes
    sys.modules[nodes.__name__.replace("hatsume-plugin", "hatsume_plugin")] = nodes

    registry = types.SimpleNamespace(
        routed_group_ids=MagicMock(return_value=(101, 303, 404)),
        get_bot=MagicMock(return_value=object()),
    )
    runtime = types.ModuleType("hatsume.plugins.hatsume-plugin.group_runtime")
    runtime.group_runtime_registry = registry
    sys.modules[runtime.__name__] = runtime
    sys.modules[runtime.__name__.replace("hatsume-plugin", "hatsume_plugin")] = runtime


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.modules[name.replace("hatsume-plugin", "hatsume_plugin")] = module
    spec.loader.exec_module(module)
    return module


def _load_engine_module() -> types.ModuleType:
    _install_package_tree()
    config = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config.MEMORY_EXPIRY_DAYS = 150
    config.SCORE_THRESHOLD = 0.1
    config.EMBEDDING_WEIGHT = 0.5
    config.EMBEDDING_SIMILARITY_THRESHOLD = 0.3
    config.MAX_MEMORY_LIMIT = 50
    sys.modules[config.__name__] = config
    sys.modules[config.__name__.replace("hatsume-plugin", "hatsume_plugin")] = config

    nonebot = types.ModuleType("nonebot")
    nonebot.require = MagicMock()
    sys.modules["nonebot"] = nonebot
    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = MagicMock(
        side_effect=lambda name: Path("/tmp") / name
    )
    sys.modules["nonebot_plugin_localstore"] = localstore

    tokenizer = types.ModuleType("hatsume.plugins.hatsume-plugin.memory.tokenizer")
    tokenizer.tokenize_with_pos = lambda text: [(text, "n")]
    sys.modules[tokenizer.__name__] = tokenizer
    vector_store = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.memory.vector_store"
    )
    vector_store.MilvusVectorStore = MagicMock()
    vector_store.VectorSearchResult = MagicMock()
    sys.modules[vector_store.__name__] = vector_store

    runtime = types.ModuleType("hatsume.plugins.hatsume-plugin.group_runtime")

    @contextlib.contextmanager
    def bind_group_runtime(value):
        yield value

    runtime.bind_group_runtime = bind_group_runtime
    runtime.get_current_group_id = lambda: None
    runtime.group_runtime_registry = types.SimpleNamespace(
        get_or_create=lambda group_id: types.SimpleNamespace(group_id=group_id)
    )
    runtime.validate_group_id = lambda group_id: int(group_id)
    sys.modules[runtime.__name__] = runtime

    return _load_module(
        "hatsume.plugins.hatsume-plugin.memory.engine",
        PLUGIN_DIR / "memory" / "engine.py",
    )


def _load_prompts_module() -> types.ModuleType:
    _install_package_tree()
    config = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config.ADMIN_QQ_ID = "12345"
    config.AGENT_QQ_EMAIL = ""
    config.BOT_QQ_ID = 0
    config.GITHUB_ACCOUNT = ""
    config.GITHUB_REPO = ""
    config.HUGGINGFACE_ACCOUNT = ""
    sys.modules[config.__name__] = config
    return _load_module(
        "hatsume.plugins.hatsume-plugin.prompts",
        PLUGIN_DIR / "prompts.py",
    )


def _load_evolution_module() -> types.ModuleType:
    _install_evolution_stubs()
    return _load_module(
        "hatsume.plugins.hatsume-plugin.evolution",
        PLUGIN_DIR / "evolution.py",
    )


def _install_command_stubs() -> types.SimpleNamespace:
    _install_package_tree()
    config = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config.ADMIN_QQ_ID = "12345"
    config.DS_API_KEY = ""
    config.DS_BASE_URL = ""
    sys.modules[config.__name__] = config

    registry = types.SimpleNamespace(get_bot=MagicMock(return_value=object()))
    runtime = types.ModuleType("hatsume.plugins.hatsume-plugin.group_runtime")
    runtime.bind_group_runtime = contextlib.nullcontext
    runtime.group_runtime_registry = registry
    sys.modules[runtime.__name__] = runtime

    infra = types.ModuleType("hatsume.plugins.hatsume-plugin.infra")
    infra.cache_sandbox_message_image = AsyncMock()
    infra.cleanup_persistent_container = AsyncMock(return_value=False)
    infra.run_cmd = AsyncMock(return_value="")
    sys.modules[infra.__name__] = infra

    adapters = types.ModuleType("nonebot.adapters")
    adapters.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters"] = adapters
    onebot = types.ModuleType("nonebot.adapters.onebot")
    onebot.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot
    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.Message = type("Message", (), {})
    v11.MessageSegment = types.SimpleNamespace(text=lambda text: text, image=MagicMock())
    v11.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules[v11.__name__] = v11

    evolution = types.ModuleType("hatsume.plugins.hatsume-plugin.evolution")
    evolution.run_learn_evolve = AsyncMock(return_value="学习进化请求已注入群 202。")
    sys.modules[evolution.__name__] = evolution
    return registry


def _load_commands_module() -> tuple[types.ModuleType, types.SimpleNamespace]:
    registry = _install_command_stubs()
    module = _load_module(
        "hatsume.plugins.hatsume-plugin.handlers.tools",
        PLUGIN_DIR / "handlers" / "tools.py",
    )
    return module, registry


def _new_matcher() -> MagicMock:
    matcher = MagicMock()

    async def finish(message):
        raise MockFinished(message)

    matcher.finish = AsyncMock(side_effect=finish)
    return matcher


def test_query_recent_memories_filters_one_group():
    engine = _load_engine_module()
    connection = engine.init_db(sqlite3.connect(":memory:"))
    base = 1_700_000_000
    engine.insert_memory(connection, 101, "target-new", base + 30, [], [])
    engine.insert_memory(connection, 202, "other", base + 40, [], [])
    engine.insert_memory(connection, 101, "target-old", base + 10, [], [])

    rows = engine.query_recent_memories(
        connection,
        group_id=101,
        since_time=base,
        limit=100,
    )

    assert [row["content"] for row in rows] == ["target-new", "target-old"]
    assert {row["group_id"] for row in rows} == {101}


def test_query_recent_memories_without_group_keeps_global_behavior():
    engine = _load_engine_module()
    connection = engine.init_db(sqlite3.connect(":memory:"))
    engine.insert_memory(connection, 101, "group-a", 100, [], [])
    engine.insert_memory(connection, 202, "group-b", 200, [], [])

    rows = engine.query_recent_memories(connection, since_time=0, limit=100)

    assert [row["content"] for row in rows] == ["group-b", "group-a"]


def test_prompt_requires_one_direction_and_self_evolution():
    prompts = _load_prompts_module()
    text = prompts.build_learn_evolve_prompt(
        [{"id": 1, "group_id": 101, "content": "图片发送偶发失败", "time": 1_700_000_000}]
    )

    assert "选择一个" in text
    assert "进化方向" in text
    assert "self-evolution" in text
    assert "skill_loader" in text
    assert "图片发送偶发失败" in text
    assert "3 至 8 条" not in text
    assert "web_search" not in text


def test_run_separates_memory_source_from_chat_target():
    evolution = _load_evolution_module()
    memory = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
    nodes = sys.modules["hatsume.plugins.hatsume-plugin.graph.nodes"]
    before = time.time()

    result = asyncio.run(
        evolution.run_learn_evolve(memory_group_id=202, chat_group_id=101)
    )

    assert result == "已读取群 202 的记忆并注入当前群 chat_agent。"
    memory.query_recent_memories.assert_called_once()
    assert memory.query_recent_memories.call_args.kwargs["group_id"] == 202
    assert memory.query_recent_memories.call_args.kwargs["limit"] == 100
    assert memory.query_recent_memories.call_args.kwargs["since_time"] <= before
    nodes.inject_learn_evolve.assert_called_once_with(
        user_id=0,
        group_id=101,
        learn_prompt="SYSTEM-PROMPT",
    )


def test_run_without_memory_group_queries_all_groups():
    evolution = _load_evolution_module()
    memory = sys.modules["hatsume.plugins.hatsume-plugin.memory"]
    nodes = sys.modules["hatsume.plugins.hatsume-plugin.graph.nodes"]

    result = asyncio.run(
        evolution.run_learn_evolve(memory_group_id=None, chat_group_id=101)
    )

    assert result == "已读取全部群最近 24 小时记忆并注入当前群 chat_agent。"
    assert memory.query_recent_memories.call_args.kwargs["group_id"] is None
    nodes.inject_learn_evolve.assert_called_once_with(
        user_id=0,
        group_id=101,
        learn_prompt="SYSTEM-PROMPT",
    )


def test_daily_midnight_job_runs_each_routed_activated_group(monkeypatch):
    evolution = _load_evolution_module()
    job = REGISTERED_JOBS["daily_learn_evolve"]
    trigger = job["args"][0]
    assert "replace_existing" not in job["kwargs"]
    assert str(trigger.timezone) in {"Asia/Shanghai", "UTC+08:00"}
    assert str(trigger.fields[5]) == "0"
    assert str(trigger.fields[6]) == "0"
    assert str(trigger.fields[7]) == "0"

    run = AsyncMock(return_value="ok")
    monkeypatch.setattr(evolution, "run_learn_evolve", run)
    asyncio.run(evolution.daily_learn_evolve())

    assert [call.kwargs for call in run.await_args_list] == [
        {"memory_group_id": 101, "chat_group_id": 101},
        {"memory_group_id": 303, "chat_group_id": 303},
    ]


def test_plugin_entry_imports_daily_job_at_startup():
    source = (PLUGIN_DIR / "__init__.py").read_text(encoding="utf-8")

    assert "from .evolution import daily_learn_evolve" in source


def test_command_uses_explicit_group_only_as_memory_source():
    commands, registry = _load_commands_module()
    evolution = sys.modules["hatsume.plugins.hatsume-plugin.evolution"]
    matcher = _new_matcher()
    event = types.SimpleNamespace(group_id=101, get_user_id=lambda: "12345")
    args = types.SimpleNamespace(extract_plain_text=lambda: "202")

    with pytest.raises(MockFinished):
        asyncio.run(commands.handle_learn_evolve(event, matcher, args))

    registry.get_bot.assert_not_called()
    evolution.run_learn_evolve.assert_awaited_once_with(
        memory_group_id=202,
        chat_group_id=101,
    )


def test_command_without_group_keeps_global_memory_source():
    commands, _registry = _load_commands_module()
    evolution = sys.modules["hatsume.plugins.hatsume-plugin.evolution"]
    matcher = _new_matcher()
    event = types.SimpleNamespace(group_id=101, get_user_id=lambda: "12345")
    args = types.SimpleNamespace(extract_plain_text=lambda: "")

    with pytest.raises(MockFinished):
        asyncio.run(commands.handle_learn_evolve(event, matcher, args))

    evolution.run_learn_evolve.assert_awaited_once_with(
        memory_group_id=None,
        chat_group_id=101,
    )


def test_command_allows_memory_source_without_a_live_bot_route():
    commands, registry = _load_commands_module()
    evolution = sys.modules["hatsume.plugins.hatsume-plugin.evolution"]
    registry.get_bot.side_effect = LookupError("not routed")
    matcher = _new_matcher()
    event = types.SimpleNamespace(group_id=101, get_user_id=lambda: "12345")
    args = types.SimpleNamespace(extract_plain_text=lambda: "202")

    with pytest.raises(MockFinished):
        asyncio.run(commands.handle_learn_evolve(event, matcher, args))

    evolution.run_learn_evolve.assert_awaited_once_with(
        memory_group_id=202,
        chat_group_id=101,
    )
