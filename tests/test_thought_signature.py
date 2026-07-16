"""Test thought_signature preservation through LangChain message round-trips.

Gemini's OpenAI-compatible API requires thought_signature on functionCall parts.
The monkey-patch in models.py must preserve it through convert_dict → convert_msg.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_BASE = ROOT / "hatsume/plugins/hatsume-plugin"


# ---------------------------------------------------------------------------
# Module loading helpers
# ---------------------------------------------------------------------------

def _cleanup():
    for name in list(sys.modules):
        if any(
            name.startswith(p)
            for p in (
                "hatsume",
                "langchain",
                "langchain_core",
                "langchain_openai",
                "openai",
                "nonebot",
                "volcenginesdkarkruntime",
                "PIL",
                "requests",
                "pydantic",
                "pydantic_settings",
                "dotenv",
                "tenacity",
                "jsonpatch",
            )
        ):
            del sys.modules[name]


def _setup():
    """Build package hierarchy, load config, load models (triggers monkey-patch)."""
    _cleanup()

    # Build package hierarchy
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_BASE),
    ]:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

    # Stub dotenv
    dotenv_mod = types.ModuleType("dotenv")
    dotenv_mod.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = dotenv_mod

    # Load config module
    config_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.config",
        str(PLUGIN_BASE / "config.py"),
    )
    config_mod = importlib.util.module_from_spec(config_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod
    config_spec.loader.exec_module(config_mod)

    # Load models module (this triggers the monkey-patch)
    models_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.models",
        str(PLUGIN_BASE / "models.py"),
    )
    models_mod = importlib.util.module_from_spec(models_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod
    models_spec.loader.exec_module(models_mod)

    return models_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestThoughtSignatureRoundTrip:
    """Verify thought_signature survives convert_dict → convert_msg round-trip."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.models = _setup()

    def test_patch_applied(self):
        """Monkey-patch replaces both conversion functions."""
        import langchain_openai.chat_models.base as base_mod

        assert hasattr(self.models, "_orig_convert_dict")
        assert hasattr(self.models, "_orig_convert_msg")
        assert base_mod._convert_dict_to_message is not self.models._orig_convert_dict
        assert base_mod._convert_message_to_dict is not self.models._orig_convert_msg

    def test_capture_and_restore_thought_signature(self):
        """thought_signature in API response → round-trip → preserved in request."""
        import langchain_openai.chat_models.base as base_mod

        response_dict = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Tokyo"}',
                    },
                    "thought_signature": "sig_abc123_value",
                },
                {
                    "id": "call_def456",
                    "type": "function",
                    "function": {
                        "name": "get_time",
                        "arguments": '{"timezone": "UTC"}',
                    },
                    "thought_signature": "sig_def456_value",
                },
            ],
        }

        # Response → LangChain message
        msg = base_mod._convert_dict_to_message(response_dict)

        # Verify capture
        sigs = msg.additional_kwargs.get("thought_signatures", {})
        assert sigs == {
            "call_abc123": "sig_abc123_value",
            "call_def456": "sig_def456_value",
        }, f"thought_signatures not captured: {sigs}"

        # LangChain message → request dict
        request_dict = base_mod._convert_message_to_dict(msg)

        # Verify restore
        assert "tool_calls" in request_dict
        tc_by_id = {tc["id"]: tc for tc in request_dict["tool_calls"]}
        assert tc_by_id["call_abc123"].get("thought_signature") == "sig_abc123_value"
        assert tc_by_id["call_def456"].get("thought_signature") == "sig_def456_value"

    def test_no_thought_signature_graceful(self):
        """Tool calls without thought_signature (e.g., from Luna) pass through."""
        import langchain_openai.chat_models.base as base_mod

        response_dict = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_xyz",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city": "Tokyo"}',
                    },
                },
            ],
        }

        msg = base_mod._convert_dict_to_message(response_dict)
        # Should not have thought_signatures key
        assert "thought_signatures" not in msg.additional_kwargs

        request_dict = base_mod._convert_message_to_dict(msg)
        assert "tool_calls" in request_dict
        # Should not add thought_signature when none was present
        assert "thought_signature" not in request_dict["tool_calls"][0]


class TestAdvanceModelSelection:
    """Verify runtime model selection still uses the standard provider factory."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.models = _setup()

    def test_runtime_model_name_is_forwarded_to_standard_factory(self):
        captured_calls: list[tuple[str, str | None]] = []
        sentinel = object()

        def _capture(model_name: str, reasoning_effort: str | None = None):
            captured_calls.append((model_name, reasoning_effort))
            return sentinel

        self.models._config.ADVANCE_MODEL_NAME = "target-model:v2"
        self.models.get_standard_api_model = _capture

        assert self.models.get_advance_model() is sentinel
        assert captured_calls == [("target-model:v2", "xhigh")]

    def test_reasoning_effort_is_configurable_and_disabled_with_thinking(self):
        captured_efforts: list[str | None] = []

        def _capture(model_name: str, reasoning_effort: str | None = None):
            captured_efforts.append(reasoning_effort)
            return object()

        self.models.get_standard_api_model = _capture

        self.models.get_advance_model(reasoning_effort="medium")
        self.models.get_advance_model(thinking=False, reasoning_effort="high")

        assert captured_efforts == ["medium", "none"]
