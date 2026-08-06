"""Focused tests for runtime model-provider configuration."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "hatsume/plugins/hatsume-plugin/config.py"


def _load_config(monkeypatch):
    monkeypatch.setenv("DS_API_KEY", "test-ds-key")
    monkeypatch.setitem(
        sys.modules,
        "dotenv",
        types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None),
    )

    module_name = "hatsume_test_config"
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_ds_provider_resolves_deepseek_endpoint_and_credentials(monkeypatch):
    config = _load_config(monkeypatch)

    assert config.PROVIDER == "ds"
    assert config.get_base_url("ds") == config.DS_BASE_URL
    assert config.get_api_key("ds")() == "test-ds-key"


def test_advanced_model_defaults_to_deepseek_v4_flash(monkeypatch):
    config = _load_config(monkeypatch)

    assert config.ADVANCE_MODEL_NAME == config.DEEPSEEK_V4_FLASH
