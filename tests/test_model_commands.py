import ast
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from model_provider_support import PACKAGE, PLUGIN, commands, config


@pytest.fixture
def store(tmp_path):
    result = config.ModelConfigStore(tmp_path)
    commands.provider_command(
        result,
        "add one --base-url https://example.test/v1 --api openai_chat_completions,openai_responses",
    )
    result.save_provider("one", api_key="command-private-key")
    return result


def test_group_key_command_is_rejected_without_mutation(store):
    with pytest.raises(config.ModelConfigError) as error:
        commands.provider_command(store, "key one replacement-secret")
    assert "replacement-secret" not in str(error.value)
    assert store.provider_connection("one")["api_key"] == "command-private-key"


def test_show_and_list_never_contain_credentials(store):
    assert "command-private-key" not in commands.provider_command(store, "show one")
    assert "command-private-key" not in commands.provider_command(store, "list")


def test_invalid_or_malformed_commands_do_not_echo_inputs(store):
    for text in (
        "add one --key command-private-key",
        'key "command-private-key',
        "key bad/id command-private-key",
    ):
        with pytest.raises(config.ModelConfigError) as error:
            commands.provider_command(store, text)
        assert "command-private-key" not in str(error.value)


@pytest.mark.asyncio
async def test_model_command_persists_and_shortcut_keeps_api(store):
    result = await commands.model_command(
        store, "use advance one first --api openai_responses"
    )
    assert "command-private-key" not in result
    await commands.model_command(store, "options advance reasoning_effort high")
    await commands.model_command(store, "second")
    restored = config.ModelConfigStore(store.root).resolve("advance")
    assert restored["api"] == "openai_responses" and restored["model"] == "second"
    assert restored["options"] == {}
    await commands.model_command(store, "options advance max_tokens 128")
    await commands.model_command(store, "options advance max_tokens null")
    assert store.resolve("advance")["options"] == {}


@pytest.mark.asyncio
async def test_all_role_configuration_and_invalid_commands(store):
    for role in ("advance", "lite", "mini", "coding", "vision"):
        await commands.model_command(
            store, f"use {role} one configured --api openai_chat_completions"
        )
    result = await commands.model_command(store, "list")
    for role in ("advance", "lite", "mini", "coding", "vision"):
        assert f"{role}:" in result
    with pytest.raises(config.ModelConfigError):
        await commands.model_command(store, "use advance one model --bad secret")
    with pytest.raises(config.ModelConfigError):
        await commands.model_command(store, "options advance extra_body secret")


def _handlers():
    """Exercise authorization in actual handler bodies without booting NoneBot."""
    tree = ast.parse((PLUGIN / "handlers/tools.py").read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in ("handle_provider", "handle_model")
    ]
    namespace = {
        "__name__": f"{PACKAGE}.handlers.tools",
        "__package__": f"{PACKAGE}.handlers",
        "Message": object,
        "ADMIN_QQ_ID": "42",
    }
    exec(
        compile(
            ast.Module(body=selected, type_ignores=[]),
            str(PLUGIN / "handlers/tools.py"),
            "exec",
        ),
        namespace,
    )
    return namespace


@pytest.mark.asyncio
async def test_handler_rejects_non_admin_before_mutation(store):
    handlers = _handlers()
    adapter = types.ModuleType("nonebot.adapters.onebot.v11")
    adapter.PrivateMessageEvent = type("PrivateMessageEvent", (), {})
    with (
        patch.dict(sys.modules, {"nonebot.adapters.onebot.v11": adapter}),
        patch.object(config, "_store", store),
    ):
        for name in ("handle_provider", "handle_model"):
            matcher = SimpleNamespace(finish=AsyncMock())
            await handlers[name](
                SimpleNamespace(get_user_id=lambda: "1"),
                matcher,
                SimpleNamespace(extract_plain_text=lambda: "remove one"),
            )
            assert "管理员" in matcher.finish.await_args.args[0]
    assert "one" in store.snapshot()[0]
