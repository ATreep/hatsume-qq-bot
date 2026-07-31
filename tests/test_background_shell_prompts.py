"""Tests for background shell prompt constants."""
from __future__ import annotations

import types
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _load_prompts_module():
    """Load prompts.py with minimal stubs."""
    packages = [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]
    for name, path in packages:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias

    import importlib.util
    prompts_path = PLUGIN_DIR / "prompts.py"
    prompts_name = "hatsume.plugins.hatsume_plugin.prompts"
    if prompts_name in sys.modules:
        del sys.modules[prompts_name]

    # Stub config for prompts.py imports
    cfg_name = "hatsume.plugins.hatsume_plugin.config"
    if cfg_name not in sys.modules:
        cfg_mod = types.ModuleType(cfg_name)
        sys.modules[cfg_name] = cfg_mod
    sys.modules[cfg_name].AGENT_QQ_EMAIL = "test@qq.com"
    sys.modules[cfg_name].BOT_QQ_ID = "12345"
    sys.modules[cfg_name].GITHUB_ACCOUNT = "test-account"
    sys.modules[cfg_name].GITHUB_REPO = "test/repo"
    sys.modules[cfg_name].HUGGINGFACE_ACCOUNT = "test-huggingface"

    spec = importlib.util.spec_from_file_location(prompts_name, prompts_path)
    prompts_mod = importlib.util.module_from_spec(spec)
    sys.modules[prompts_name] = prompts_mod
    spec.loader.exec_module(prompts_mod)
    return prompts_mod


def test_decision_prompt_has_input_needed():
    """BACKGROUND_SHELL_DECISION_PROMPT includes INPUT_NEEDED decision."""
    prompts = _load_prompts_module()
    prompt = prompts.BACKGROUND_SHELL_DECISION_PROMPT
    assert "INPUT_NEEDED" in prompt


def test_decision_prompt_kill_no_longer_mentions_stdin_wait():
    """KILL decision no longer treats stdin wait as kill reason."""
    prompts = _load_prompts_module()
    prompt = prompts.BACKGROUND_SHELL_DECISION_PROMPT
    assert "非预期的 stdin 等待" not in prompt


def test_stdin_resolution_prompt_exists():
    """BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT constant exists with expected
    decision types."""
    prompts = _load_prompts_module()
    prompt = prompts.BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT
    assert "FINAL_INPUT:" in prompt
    assert "REISSUE:" in prompt
    assert "KILL" in prompt
