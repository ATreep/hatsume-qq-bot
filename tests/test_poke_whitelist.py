"""Tests for poke notice group filtering."""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
BASE_NAME = "hatsume.plugins.hatsume-plugin"
ALLOWED_GROUP_ID = 738458661


def _load_handler():
    for name in list(sys.modules):
        if name == "hatsume" or name.startswith("hatsume.") or name.startswith(
            "nonebot"
        ):
            del sys.modules[name]

    for name, path in (
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        (BASE_NAME, PLUGIN_DIR),
        (f"{BASE_NAME}.handlers", PLUGIN_DIR / "handlers"),
        (f"{BASE_NAME}.graph", PLUGIN_DIR / "graph"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package

    nonebot = types.ModuleType("nonebot")
    adapters = types.ModuleType("nonebot.adapters")
    adapters.__path__ = []
    adapters.Bot = type("Bot", (), {})
    onebot = types.ModuleType("nonebot.adapters.onebot")
    onebot.__path__ = []
    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.Message = type("Message", (), {})
    v11.MessageSegment = types.SimpleNamespace(image=lambda value: value)
    v11.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules["nonebot"] = nonebot
    sys.modules["nonebot.adapters"] = adapters
    sys.modules["nonebot.adapters.onebot"] = onebot
    sys.modules["nonebot.adapters.onebot.v11"] = v11

    config = types.ModuleType(f"{BASE_NAME}.config")
    config.ADMIN_QQ_ID = "1"
    config.POKE_GROUP_WHITELIST = frozenset({ALLOWED_GROUP_ID})
    sys.modules[config.__name__] = config

    runtime = types.SimpleNamespace(group_id=ALLOWED_GROUP_ID)
    registry = types.SimpleNamespace(bind_bot=MagicMock(return_value=runtime))
    group_runtime = types.ModuleType(f"{BASE_NAME}.group_runtime")
    group_runtime.group_runtime_registry = registry
    group_runtime.bind_group_runtime = lambda value: contextlib.nullcontext(value)
    sys.modules[group_runtime.__name__] = group_runtime

    infra = types.ModuleType(f"{BASE_NAME}.infra")
    infra.cleanup_persistent_container = AsyncMock()
    infra.run_cmd = AsyncMock()
    sys.modules[infra.__name__] = infra

    graph_tools = types.ModuleType(f"{BASE_NAME}.graph.tools")
    graph_tools._export_random_acg_photo = AsyncMock(return_value="error")
    graph_tools._cleanup_exported_acg_photo = MagicMock()
    sys.modules[graph_tools.__name__] = graph_tools

    module_name = f"{BASE_NAME}.handlers.tools"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "handlers/tools.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, graph_tools, registry


@pytest.mark.asyncio
async def test_poke_outside_whitelist_is_silent():
    handler, graph_tools, registry = _load_handler()
    bot = types.SimpleNamespace(send=AsyncMock())
    event = types.SimpleNamespace(group_id=123456789)

    await handler.handle_poke(bot, event)

    graph_tools._export_random_acg_photo.assert_not_awaited()
    registry.bind_bot.assert_not_called()
    bot.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_poke_in_whitelist_reaches_photo_export():
    handler, graph_tools, registry = _load_handler()
    bot = types.SimpleNamespace(send=AsyncMock())
    event = types.SimpleNamespace(group_id=ALLOWED_GROUP_ID)

    await handler.handle_poke(bot, event)

    registry.bind_bot.assert_called_once_with(ALLOWED_GROUP_ID, bot)
    graph_tools._export_random_acg_photo.assert_awaited_once_with()
