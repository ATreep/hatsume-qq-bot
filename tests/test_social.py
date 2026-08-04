"""Tests for group-isolated likes and /likerank routing."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
SOCIAL_PATH = PLUGIN_DIR / "handlers/social.py"


def _load_social(monkeypatch, tmp_path: Path):
    packages = [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
        ("hatsume.plugins.hatsume-plugin.handlers", PLUGIN_DIR / "handlers"),
    ]
    for name, path in packages:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, module)

    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_file = lambda _name: tmp_path / "likes.json"
    monkeypatch.setitem(sys.modules, localstore.__name__, localstore)

    adapters = types.ModuleType("nonebot.adapters")
    adapters.__path__ = []
    adapters.Bot = type("Bot", (), {})
    monkeypatch.setitem(sys.modules, adapters.__name__, adapters)
    onebot = types.ModuleType("nonebot.adapters.onebot")
    onebot.__path__ = []
    monkeypatch.setitem(sys.modules, onebot.__name__, onebot)
    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11.Message = type("Message", (), {})
    monkeypatch.setitem(sys.modules, v11.__name__, v11)

    config = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config.ADMIN_QQ_ID = "999"
    monkeypatch.setitem(sys.modules, config.__name__, config)

    group_runtime = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.group_runtime"
    )

    def validate_group_id(group_id):
        if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id <= 0:
            raise ValueError("group_id must be a positive integer")
        return group_id

    group_runtime.validate_group_id = validate_group_id
    monkeypatch.setitem(sys.modules, group_runtime.__name__, group_runtime)

    utils = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")

    async def get_group_member_name(_bot, _group_id, user_id):
        return f"user-{user_id}"

    utils.get_group_member_name = get_group_member_name
    monkeypatch.setitem(sys.modules, utils.__name__, utils)

    module_name = "hatsume.plugins.hatsume-plugin.handlers.social"
    spec = importlib.util.spec_from_file_location(module_name, SOCIAL_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Finished(Exception):
    pass


class _Matcher:
    def __init__(self):
        self.message = None

    async def finish(self, message=None):
        self.message = message
        raise _Finished(message)


class _Args:
    def __init__(self, text: str):
        self.text = text

    def extract_plain_text(self):
        return self.text


def test_flat_likes_are_rejected_without_rewriting(monkeypatch, tmp_path):
    social = _load_social(monkeypatch, tmp_path)
    path = tmp_path / "likes.json"
    original = json.dumps({"7": 12, "8": 3})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="group-scoped"):
        social._load_like_groups(path)

    assert path.read_text(encoding="utf-8") == original


def test_group_like_accumulation_is_isolated(monkeypatch, tmp_path):
    social = _load_social(monkeypatch, tmp_path)

    assert social._cumulate_user_like(101, "7", 10) == 10
    assert social._cumulate_user_like(202, "7", 20) == 20
    assert social._cumulate_user_like(101, "7", 5) == 15
    assert social._get_like_times(101, "7") == 15
    assert social._get_like_times(202, "7") == 20

    stored = json.loads((tmp_path / "likes.json").read_text(encoding="utf-8"))
    assert stored == {"101": {"7": 15}, "202": {"7": 20}}

    with pytest.raises(ValueError, match="non-negative integer"):
        social._cumulate_user_like(101, "7", 1.5)


@pytest.mark.parametrize("invalid_count", [True, 1.5, "2"])
def test_invalid_flat_counter_does_not_replace_file(
    monkeypatch,
    tmp_path,
    invalid_count,
):
    social = _load_social(monkeypatch, tmp_path)
    path = tmp_path / "likes.json"
    original = json.dumps({"7": invalid_count})
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="group-scoped"):
        social._load_like_groups(path)

    assert path.read_text(encoding="utf-8") == original


def test_likerank_group_argument_requires_admin_for_cross_group(
    monkeypatch,
    tmp_path,
):
    social = _load_social(monkeypatch, tmp_path)
    non_admin = types.SimpleNamespace(
        group_id=101,
        get_user_id=lambda: "7",
    )
    matcher = _Matcher()

    with pytest.raises(_Finished):
        asyncio.run(
            social._resolve_rank_group(non_admin, matcher, _Args("202"))
        )
    assert matcher.message == "只有管理员可以访问其他群的数据。"

    admin = types.SimpleNamespace(
        group_id=101,
        get_user_id=lambda: "999",
    )
    assert asyncio.run(
        social._resolve_rank_group(admin, _Matcher(), _Args("202"))
    ) == 202
    assert asyncio.run(
        social._resolve_rank_group(non_admin, _Matcher(), _Args(""))
    ) == 101


@pytest.mark.parametrize("argument", ["abc", "0", "-1", "202 extra"])
def test_likerank_rejects_invalid_group_argument(monkeypatch, tmp_path, argument):
    social = _load_social(monkeypatch, tmp_path)
    event = types.SimpleNamespace(
        group_id=101,
        get_user_id=lambda: "999",
    )
    matcher = _Matcher()

    with pytest.raises(_Finished):
        asyncio.run(social._resolve_rank_group(event, matcher, _Args(argument)))

    assert matcher.message == "群号必须是正整数。\n用法：/likerank [群号]"
