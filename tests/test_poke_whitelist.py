"""Tests for poke notice group filtering."""

from __future__ import annotations

import contextlib
import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
GRAPH_TOOLS_PATH = PLUGIN_DIR / "graph/tools.py"
BASE_NAME = "hatsume.plugins.hatsume-plugin"
ALLOWED_GROUP_ID = 738458661


def test_random_acg_photo_is_not_exposed_as_a_graph_tool():
    module = ast.parse(GRAPH_TOOLS_PATH.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "random_acg_photo" not in names
    assert "_export_random_acg_photo" not in names


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
    infra.cache_sandbox_message_image = AsyncMock()
    infra.cleanup_persistent_container = AsyncMock()
    infra.run_cmd = AsyncMock()
    sys.modules[infra.__name__] = infra

    module_name = f"{BASE_NAME}.handlers.tools"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN_DIR / "handlers/tools.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, registry


@pytest.mark.asyncio
async def test_poke_outside_whitelist_is_silent():
    handler, registry = _load_handler()
    bot = types.SimpleNamespace(send=AsyncMock())
    event = types.SimpleNamespace(group_id=123456789)
    export_photo = AsyncMock(return_value="error")

    with patch.object(handler, "_export_random_acg_photo", export_photo):
        await handler.handle_poke(bot, event)

    export_photo.assert_not_awaited()
    registry.bind_bot.assert_not_called()
    bot.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_poke_in_whitelist_reaches_photo_export():
    handler, registry = _load_handler()
    bot = types.SimpleNamespace(send=AsyncMock())
    event = types.SimpleNamespace(group_id=ALLOWED_GROUP_ID)
    export_photo = AsyncMock(return_value="error")

    with patch.object(handler, "_export_random_acg_photo", export_photo):
        await handler.handle_poke(bot, event)

    registry.bind_bot.assert_called_once_with(ALLOWED_GROUP_ID, bot)
    export_photo.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_poke_image_is_cached_by_sent_message_id(tmp_path):
    handler, _ = _load_handler()
    image_path = tmp_path / "poke.png"
    image_bytes = b"bot image bytes"
    image_path.write_bytes(image_bytes)
    bot = types.SimpleNamespace(
        send=AsyncMock(return_value={"message_id": 2468})
    )
    event = types.SimpleNamespace(group_id=ALLOWED_GROUP_ID)
    infra = sys.modules[f"{BASE_NAME}.infra"]
    export_photo = AsyncMock(return_value=str(image_path))
    cleanup_photo = MagicMock()

    with (
        patch.object(handler, "_export_random_acg_photo", export_photo),
        patch.object(handler, "_cleanup_exported_acg_photo", cleanup_photo),
    ):
        await handler.handle_poke(bot, event)

    infra.cache_sandbox_message_image.assert_awaited_once_with(
        image_bytes,
        2468,
        1,
        group_id=ALLOWED_GROUP_ID,
    )
    cleanup_photo.assert_called_once_with(str(image_path))


@pytest.mark.asyncio
async def test_handler_export_returns_host_path_from_unique_directory():
    handler, _ = _load_handler()
    process = MagicMock(returncode=0, stdout=b"", stderr=b"")

    with (
        patch.object(handler.subprocess, "run", return_value=process),
        patch.object(
            handler.tempfile,
            "mkdtemp",
            return_value="/tmp/hatsume-acg-export-test",
        ),
        patch.object(handler._os, "listdir", return_value=["IMG_1234.jpg"]),
        patch.object(handler._os.path, "isfile", return_value=True),
        patch("shutil.rmtree") as remove_tree,
    ):
        result = await handler._export_random_acg_photo()

    assert result == "/tmp/hatsume-acg-export-test/IMG_1234.jpg"
    remove_tree.assert_not_called()


@pytest.mark.asyncio
async def test_handler_export_cleans_directory_when_album_is_empty():
    handler, _ = _load_handler()
    process = MagicMock(
        returncode=0,
        stdout=b"ERROR:ALBUM_EMPTY",
        stderr=b"",
    )

    with (
        patch.object(handler.subprocess, "run", return_value=process),
        patch.object(
            handler.tempfile,
            "mkdtemp",
            return_value="/tmp/hatsume-acg-export-test",
        ),
        patch("shutil.rmtree") as remove_tree,
    ):
        result = await handler._export_random_acg_photo()

    assert "没有照片" in result
    remove_tree.assert_called_once_with(
        "/tmp/hatsume-acg-export-test",
        ignore_errors=True,
    )


@pytest.mark.asyncio
async def test_handler_export_reports_when_photos_is_not_running():
    handler, _ = _load_handler()
    process = MagicMock(
        returncode=1,
        stdout=b"",
        stderr=b"Application isn't running (-600)",
    )

    with (
        patch.object(handler.subprocess, "run", return_value=process),
        patch.object(
            handler.tempfile,
            "mkdtemp",
            return_value="/tmp/hatsume-acg-export-test",
        ),
        patch("shutil.rmtree") as remove_tree,
    ):
        result = await handler._export_random_acg_photo()

    assert "无法访问 Photos 应用" in result
    remove_tree.assert_called_once_with(
        "/tmp/hatsume-acg-export-test",
        ignore_errors=True,
    )
