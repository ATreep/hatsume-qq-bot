"""Tests for the single RAM-only character proxy."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"
PACKAGE = "hatsume.plugins.hatsume-plugin"


@pytest.fixture(autouse=True)
def _restore_hatsume_modules():
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == "hatsume" or name.startswith("hatsume.")
    }
    yield
    for name in list(sys.modules):
        if name == "hatsume" or name.startswith("hatsume."):
            del sys.modules[name]
    sys.modules.update(saved)


def _package(name: str, path: Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load_character_proxy(
    memories: list[dict] | None = None,
    model_content: str = '{"behavior_prompt":"说话简短直接","aliases":["阿树"]}',
):
    _package("hatsume", ROOT / "hatsume")
    _package("hatsume.plugins", ROOT / "hatsume/plugins")
    _package(PACKAGE, PLUGIN_DIR)

    memory = types.ModuleType(f"{PACKAGE}.memory")
    memory.get_recent_user_memories = lambda user_id, limit: (memories or [])[:limit]
    sys.modules[memory.__name__] = memory

    class Model:
        calls = 0

        async def ainvoke(self, messages):
            Model.calls += 1
            return types.SimpleNamespace(content=model_content)

    models = types.ModuleType(f"{PACKAGE}.models")
    models.get_mini_model = lambda **kwargs: Model()
    sys.modules[models.__name__] = models

    prompts = types.ModuleType(f"{PACKAGE}.prompts")
    prompts.build_character_profile_generation_prompt = (
        lambda items, user_name: f"{user_name}: {items}"
    )
    prompts.build_character_proxy_role_prompt = lambda **kwargs: (
        f"ROLE PROMPT: {kwargs['user_name']} / {kwargs['behavior_prompt']} / "
        f"{kwargs['aliases']} / {kwargs['auto_terminate_at']}"
    )
    sys.modules[prompts.__name__] = prompts

    name = f"{PACKAGE}.character_proxy"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "character_proxy.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, Model


def test_only_one_ram_proxy_exists_and_termination_destroys_it():
    proxy, _ = _load_character_proxy()

    first = proxy.activate_character_proxy(
        user_id=1, user_name="A", behavior_prompt="profile A"
    )
    assert proxy.get_character_proxy() is first
    assert first.auto_terminate_at
    with pytest.raises(RuntimeError):
        proxy.activate_character_proxy(
            user_id=2, user_name="B", behavior_prompt="profile B"
        )

    removed = proxy.terminate_character_proxy_state()
    assert removed is first
    assert proxy.get_character_proxy() is None


def test_activation_records_auto_termination_time(monkeypatch):
    proxy, _ = _load_character_proxy()
    now = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(proxy, "datetime", types.SimpleNamespace(now=lambda: now))

    active = proxy.activate_character_proxy(
        user_id=1,
        user_name="A",
        behavior_prompt="profile A",
        during_time=30,
    )

    expected = (now.astimezone() + timedelta(minutes=30)).isoformat(
        timespec="seconds"
    )
    assert active.auto_terminate_at == expected


def test_activation_prints_complete_role_prompt(capsys):
    proxy, _ = _load_character_proxy()

    active = proxy.activate_character_proxy(
        user_id=1,
        user_name="A",
        behavior_prompt="profile A",
        during_time=30,
    )

    output = capsys.readouterr().out
    assert "[character_proxy] Activated role prompt:" in output
    assert "ROLE PROMPT: A / profile A" in output
    assert active.auto_terminate_at in output


def test_scheduled_termination_uses_minutes_and_clears_proxy(monkeypatch):
    proxy, _ = _load_character_proxy()
    proxy.activate_character_proxy(
        user_id=1, user_name="A", behavior_prompt="profile A"
    )
    callbacks: list[object] = []

    class Handle:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    handle = Handle()

    class Loop:
        def call_later(self, delay, callback):
            callbacks.extend([delay, callback])
            return handle

    monkeypatch.setattr(proxy.asyncio, "get_running_loop", lambda: Loop())

    proxy.schedule_character_proxy_termination(3)

    assert callbacks[0] == 180
    callbacks[1]()
    assert proxy.get_character_proxy() is None
    assert handle.cancelled


def test_manual_termination_cancels_scheduled_timeout(monkeypatch):
    proxy, _ = _load_character_proxy()
    proxy.activate_character_proxy(
        user_id=1, user_name="A", behavior_prompt="profile A"
    )

    class Handle:
        cancelled = False

        def cancel(self):
            self.cancelled = True

    handle = Handle()
    loop = types.SimpleNamespace(call_later=lambda *_: handle)
    monkeypatch.setattr(proxy.asyncio, "get_running_loop", lambda: loop)
    proxy.schedule_character_proxy_termination(180)

    proxy.terminate_character_proxy_state()

    assert handle.cancelled


def test_explicit_at_adds_other_user_to_chat_peers():
    proxy, _ = _load_character_proxy()
    proxy.activate_character_proxy(
        user_id=123, user_name="A", behavior_prompt="profile"
    )
    state = types.SimpleNamespace(activate_chat=lambda session: peers.add(session))
    peers: set[str] = set()
    message = [types.SimpleNamespace(type="at", data={"qq": "123"})]

    activated = proxy.activate_character_proxy_peer(
        state,
        message=message,
        sender_id=456,
        session_id="group_1_456",
    )

    assert activated
    assert peers == {"group_1_456"}


def test_proxy_user_cannot_trigger_their_own_proxy():
    proxy, _ = _load_character_proxy()
    proxy.activate_character_proxy(
        user_id=123, user_name="A", behavior_prompt="profile"
    )
    message = [types.SimpleNamespace(type="at", data={"qq": "123"})]

    assert not proxy.message_targets_character_proxy(message, sender_id=123)


def test_message_text_matches_nickname_or_alias_but_not_sender_metadata():
    proxy, _ = _load_character_proxy()
    proxy.activate_character_proxy(
        user_id=123,
        user_name="树",
        behavior_prompt="profile",
        aliases=("阿树", "队长"),
    )

    alias_message = [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "user": {"id": 456, "name": "B"},
                    "content": "队长在吗？",
                },
                ensure_ascii=False,
            ),
        }
    ]
    nickname_message = [{"type": "text", "text": "树，看看这个"}]
    metadata_only = [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "user": {"id": 456, "name": "队长"},
                    "content": "大家好",
                },
                ensure_ascii=False,
            ),
        }
    ]

    assert proxy.message_mentions_character_proxy(alias_message)
    assert proxy.message_mentions_character_proxy(nickname_message)
    assert not proxy.message_mentions_character_proxy(metadata_only)


def test_numeric_fallback_nickname_is_matched_as_plain_text():
    proxy, _ = _load_character_proxy()
    proxy.activate_character_proxy(
        user_id=123,
        user_name="123",
        behavior_prompt="profile",
    )

    assert proxy.message_mentions_character_proxy("123")


def test_profile_generation_reads_memories_once_and_returns_aliases():
    memories = [{"content": str(index)} for index in range(150)]
    proxy, model = _load_character_proxy(
        memories,
        model_content=(
            '{"behavior_prompt":"说话简短直接",'
            '"aliases":["阿树","队长","阿树","Target"]}'
        ),
    )

    profile = asyncio.run(proxy.generate_character_profile(123, "Target"))

    assert profile.behavior_prompt == "说话简短直接"
    assert profile.aliases == ("阿树", "队长")
    assert model.calls == 1


def test_role_prompt_scopes_proxy_and_preserves_notification_identity():
    config = types.ModuleType(f"{PACKAGE}.config")
    config.AGENT_QQ_EMAIL = "test@qq.com"
    config.BOT_QQ_ID = 999
    config.GITHUB_ACCOUNT = "test"
    config.GITHUB_REPO = "test/repo"
    config.HUGGINGFACE_ACCOUNT = "test-huggingface"
    sys.modules[config.__name__] = config
    _package("hatsume", ROOT / "hatsume")
    _package("hatsume.plugins", ROOT / "hatsume/plugins")
    _package(PACKAGE, PLUGIN_DIR)
    sys.modules[config.__name__] = config
    name = f"{PACKAGE}.prompts"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "prompts.py")
    assert spec is not None and spec.loader is not None
    prompts = importlib.util.module_from_spec(spec)
    sys.modules[name] = prompts
    spec.loader.exec_module(prompts)

    generation_prompt = prompts.build_character_profile_generation_prompt(
        [{"content": "大家会叫 A 阿A"}],
        "A",
    )
    assert '"behavior_prompt"' in generation_prompt
    assert '"aliases"' in generation_prompt
    assert '["外号1", "外号2"]' in generation_prompt

    prompt = prompts.build_character_proxy_role_prompt(
        user_id=123,
        user_name="A",
        behavior_prompt="说话简短",
        aliases=("阿A", "队长"),
        auto_terminate_at="2026-07-17T18:30:00+08:00",
    )

    assert "2026-07-17T18:30:00+08:00" in prompt
    assert "结束" in prompt
    assert "已知外号是：阿A、队长" in prompt
    assert "只有当前消息明确 @ A" in prompt
    assert "和初芽说话" in prompt
    assert "Agent 通知和 Timer 通知" in prompt
    assert "terminate_character_proxy" in prompt
