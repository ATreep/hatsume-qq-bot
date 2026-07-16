"""Tests for mimo model factory in models.py (RED phase).

Following TDD: these tests are written BEFORE the implementation.
They will fail until models.py has the get_mimo_api_model function.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytest.skip(allow_module_level=True, reason="MIMO provider not yet implemented")

ROOT = Path(__file__).resolve().parents[1]
MODELS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/models.py"


def _load_models_module():
    """Load models.py with external dependencies stubbed."""
    # Clean up previously loaded hatsume modules
    for name in list(sys.modules):
        if name.startswith("hatsume") or name in (
            "langchain_openai",
            "volcenginesdkarkruntime",
        ):
            del sys.modules[name]

    base = ROOT / "hatsume/plugins/hatsume-plugin"

    # Package hierarchy
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", base),
    ]:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod

    # Stub config module
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.VOLCENGINE_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    config_mod.MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    config_mod.SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
    config_mod.DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    config_mod.DEEPSEEK_V4_PRO = "deepseek-v4-pro"
    config_mod.DEEPSEEK_V4_FLASH = "deepseek-v4-flash"
    config_mod.EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
    config_mod.SEEDREAM_4_0 = "seedream-4-0"
    config_mod.SEEDREAM_4_5 = "seedream-4-5"
    config_mod.SEEDREAM_5_0 = "seedream-5-0"
    config_mod.SEEDANCE_1_0 = "seedance-1-0"
    config_mod.SEEDANCE_1_5 = "seedance-1-5"
    config_mod.DOUBAO_CODE = "doubao-code"
    config_mod.ADVANCE_MODEL_NAME = "advance"
    config_mod.LITE_MODEL_NAME = "lite"
    config_mod.MINI_MODEL_NAME = "mini"
    config_mod.MIMO_V2_5_OMNI = "mimo-v2-omni"
    config_mod.PROVIDER = "volc"
    config_mod.is_omni = True
    config_mod.get_api_key = lambda provider="mimo": "test-mimo-key"
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    # Stub langchain_openai with a real-enough ChatOpenAI
    class MockChatOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            for k, v in kwargs.items():
                setattr(self, k, v)

    class MockOpenAIEmbeddings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    langchain_openai = types.ModuleType("langchain_openai")
    langchain_openai.ChatOpenAI = MockChatOpenAI
    langchain_openai.OpenAIEmbeddings = MockOpenAIEmbeddings
    sys.modules["langchain_openai"] = langchain_openai

    # Stub volcenginesdkarkruntime
    volc_mod = types.ModuleType("volcenginesdkarkruntime")
    volc_mod.Ark = type("Ark", (), {"__init__": lambda *a, **kw: None})
    sys.modules["volcenginesdkarkruntime"] = volc_mod

    # Load models.py
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.models", MODELS_PATH
    )
    models_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod
    spec.loader.exec_module(models_mod)
    return models_mod


# ---------------------------------------------------------------------------
# Tests for get_mimo_api_model
# ---------------------------------------------------------------------------


class TestGetMimoApiModel:
    """Verify get_mimo_api_model factory function exists and works correctly."""

    def test_function_exists(self):
        """get_mimo_api_model should be defined in models.py."""
        models = _load_models_module()
        assert hasattr(models, "get_mimo_api_model"), (
            "get_mimo_api_model function missing from models.py"
        )

    def test_returns_chatopenai_instance(self):
        """get_mimo_api_model should return a ChatOpenAI instance."""
        models = _load_models_module()
        result = models.get_mimo_api_model("mimo-v2.5-pro")
        assert isinstance(result, models.ChatOpenAI)

    def test_uses_mimo_base_url(self):
        """The returned instance should use MIMO_BASE_URL."""
        models = _load_models_module()
        result = models.get_mimo_api_model("mimo-v2.5-pro")
        assert result.base_url == "https://token-plan-cn.xiaomimimo.com/v1"

    def test_uses_correct_model_name(self):
        """The returned instance should use the passed model name."""
        models = _load_models_module()
        result = models.get_mimo_api_model("mimo-v2.5-pro")
        assert result.model == "mimo-v2.5-pro"

    def test_uses_api_key_from_config(self):
        """The returned instance should use get_api_key() for the API key."""
        models = _load_models_module()
        result = models.get_mimo_api_model("mimo-v2.5-pro")
        # get_api_key() returns a callable, and get_mimo_api_model should
        # pass it as api_key (same pattern as other factories)
        assert result.api_key is not None

    def test_default_temperature_is_1_5(self):
        """Default temperature should be 1.5 for mimo."""
        models = _load_models_module()
        result = models.get_mimo_api_model("mimo-v2.5-pro")
        assert result.temperature == 1.5

    def test_custom_temperature(self):
        """Should accept a custom temperature parameter."""
        models = _load_models_module()
        result = models.get_mimo_api_model("mimo-v2.5-pro", temperature=0.5)
        assert result.temperature == 0.5


class TestMimoImportInModels:
    """Verify MIMO_BASE_URL is imported in models.py."""

    def test_mimo_base_url_imported(self):
        """models.py should import MIMO_BASE_URL from config."""
        source = MODELS_PATH.read_text()
        assert "MIMO_BASE_URL" in source, (
            "MIMO_BASE_URL not found in models.py"
        )
