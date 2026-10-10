"""Removed media roles cannot be re-enabled through config or slash commands."""

import ast
import asyncio
import importlib

import pytest

from model_provider_support import PACKAGE, PLUGIN, commands, config

REMOVED_ROLES = ("image_openai", "image_volc", "image_kege", "video_1_0", "video_1_5")


@pytest.mark.parametrize("role", REMOVED_ROLES)
def test_removed_roles_are_rejected(tmp_path, role):
    store = config.ModelConfigStore(tmp_path)
    store.save_provider(
        "probe",
        base_url="https://example.test/v1",
        supported_apis=["sensenova_images"],
        api_key="test-key",
        create=True,
    )
    before = (store.models_path.read_bytes(), store.providers_path.read_bytes())
    with pytest.raises(config.ModelConfigError):
        asyncio.run(commands.model_command(store, f"use {role} probe a-model"))
    assert (store.models_path.read_bytes(), store.providers_path.read_bytes()) == before
    assert role not in commands.MODEL_HELP


@pytest.mark.parametrize(
    "api", ("openai_images", "ark_images", "kege_images", "ark_video")
)
def test_removed_provider_apis_are_rejected(tmp_path, api):
    store = config.ModelConfigStore(tmp_path)
    with pytest.raises(config.ModelConfigError):
        store.save_provider(
            "probe",
            base_url="https://example.test/v1",
            supported_apis=[api],
            create=True,
        )


def test_removed_factories_and_video_tool_are_absent():
    models = importlib.import_module(f"{PACKAGE}.models")
    for name in (
        "generate_image_for_openai",
        "generate_image_for_volc",
        "generate_image_for_kege",
        "generate_video_for",
        "choose_video_model",
    ):
        assert not hasattr(models, name)
    tree = ast.parse((PLUGIN / "graph/tools.py").read_text())
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "generate_video" not in functions
    assert {"generate_image", "send_video"} <= functions
    chat_tools = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "CHAT_TOOLS"
            for target in node.targets
        )
    )
    assert {"generate_image", "send_video"} <= {node.id for node in chat_tools.elts}


def test_runtime_retains_image_callbacks_and_video_delivery():
    runtime_module = importlib.import_module(f"{PACKAGE}.group_runtime")
    runtime = runtime_module.GroupRuntime(group_id=123)
    assert runtime.send_video_count == 0
    assert callable(runtime.is_generate_image_rate_limited_callback)
    assert callable(runtime.update_generate_image_time_callback)
    assert not hasattr(runtime, "generate_video_used")
    assert not hasattr(runtime.conversation, "is_video_rate_limited")
