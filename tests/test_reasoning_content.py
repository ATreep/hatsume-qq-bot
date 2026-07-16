"""Tests for reasoning_content round-trip preservation.

DeepSeek-compatible APIs (e.g. mimo) require reasoning_content to be passed
back in subsequent requests. langchain_openai strips it; our monkey-patch
preserves it through AIMessage.additional_kwargs.

These tests run in a subprocess to avoid contamination from other test files
that stub langchain_openai as a flat module.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _write_test_script() -> Path:
    """Write the test script to a temp file."""
    script = f'''
import sys, types, importlib.util
from pathlib import Path

ROOT = Path("{ROOT}")
MODELS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/models.py"

# Stub config
base = ROOT / "hatsume/plugins/hatsume-plugin"
for name, path in [
    ("hatsume", ROOT / "hatsume"),
    ("hatsume.plugins", ROOT / "hatsume/plugins"),
    ("hatsume.plugins.hatsume-plugin", base),
]:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod

config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
config_mod.VOLCENGINE_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
config_mod.SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
config_mod.OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
config_mod.KEGEAI_BASE_URL = "https://ai.kegeai.top/v1"
config_mod.PROVIDER = "kege"
config_mod.EMBEDDING_MODEL = "BAAI/bge-m3"
config_mod.SEEDREAM_5_0_LITE = "doubao-seedream-5.0-lite"
config_mod.SEEDANCE_1_0 = "doubao-seedance-1-0-pro-250528"
config_mod.SEEDANCE_1_5 = "doubao-seedance-1-5-pro-251215"
config_mod.GROK_IMAGINE_IMAGE = "grok-imagine-image:stable"
config_mod.GPT_5_6_LUNA = "gpt-5.6-luna-max:stable"
config_mod.GPT_5_6_TERRA = "gpt-5.6-terra:stable"
config_mod.DOUBAO_2_LITE = "doubao-seed-2-0-lite"
config_mod.DOUBAO_2_MINI = "doubao-seed-2-0-mini"
config_mod.DEEPSEEK_V4_FLASH_FREE = "deepseek-v4-flash-free"
config_mod.GPT_5_4_NANO = "gpt-5.4-nano-2026-03-17:stable"
config_mod.KEGEAI_API_KEY = "test-key"
config_mod.OPENCODE_API_KEY = "test-key"
config_mod.get_api_key = lambda prov=None: "test-key"
config_mod.get_base_url = lambda prov=None: "https://ai.kegeai.top/v1"
sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

volc_mod = types.ModuleType("volcenginesdkarkruntime")
volc_mod.Ark = type("Ark", (), {{"__init__": lambda *a, **kw: None}})
sys.modules["volcenginesdkarkruntime"] = volc_mod

# Load models.py (triggers monkey-patch)
spec = importlib.util.spec_from_file_location(
    "hatsume.plugins.hatsume-plugin.models", MODELS_PATH
)
models_mod = importlib.util.module_from_spec(spec)
sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod
spec.loader.exec_module(models_mod)

from langchain_openai.chat_models.base import _convert_dict_to_message, _convert_message_to_dict
from langchain_core.messages import AIMessage

errors = []

# Test 1: extract reasoning_content from API dict
msg = _convert_dict_to_message({{"role": "assistant", "content": "Hi", "reasoning_content": "thinking..."}})
if msg.additional_kwargs.get("reasoning_content") != "thinking...":
    errors.append("Test 1 failed: reasoning_content not extracted")

# Test 2: no reasoning_content when absent
msg = _convert_dict_to_message({{"role": "assistant", "content": "Hi"}})
if "reasoning_content" in msg.additional_kwargs:
    errors.append("Test 2 failed: reasoning_content present when absent")

# Test 3: serialize includes reasoning_content
msg = AIMessage(content="Hi", additional_kwargs={{"reasoning_content": "thinking..."}})
d = _convert_message_to_dict(msg)
if d.get("reasoning_content") != "thinking...":
    errors.append("Test 3 failed: reasoning_content not in serialized dict")

# Test 4: serialize without reasoning_content
msg = AIMessage(content="Hi")
d = _convert_message_to_dict(msg)
if "reasoning_content" in d:
    errors.append("Test 4 failed: reasoning_content present when absent in AIMessage")

# Test 5: full round-trip
original = {{"role": "assistant", "content": "Answer.", "reasoning_content": "Step by step..."}}
msg = _convert_dict_to_message(original)
result = _convert_message_to_dict(msg)
if result.get("reasoning_content") != "Step by step...":
    errors.append("Test 5 failed: round-trip lost reasoning_content")
if result.get("content") != "Answer.":
    errors.append("Test 5 failed: content changed")

# Test 6: round-trip with tool_calls
tc = [{{"id": "c1", "type": "function", "function": {{"name": "search", "arguments": "{{}}"}}}}]
original = {{"role": "assistant", "content": None, "reasoning_content": "Searching...", "tool_calls": tc}}
msg = _convert_dict_to_message(original)
result = _convert_message_to_dict(msg)
if result.get("reasoning_content") != "Searching...":
    errors.append("Test 6 failed: reasoning_content lost with tool_calls")
if "tool_calls" not in result:
    errors.append("Test 6 failed: tool_calls lost")

# Test 7: patch is applied
import langchain_openai.chat_models.base as _base
if _base._convert_dict_to_message.__name__ != "_patched_convert_dict":
    errors.append("Test 7 failed: patch not applied")

if errors:
    for e in errors:
        print(f"FAIL: {{e}}", file=sys.stderr)
    sys.exit(1)
else:
    print("ALL_PASSED")
    sys.exit(0)
'''
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    tmp.write(script)
    tmp.close()
    return Path(tmp.name)


class TestReasoningContentRoundTrip:
    """Verify reasoning_content survives AIMessage -> dict -> AIMessage round-trip."""

    def test_all_round_trip_tests(self):
        """Run all reasoning_content round-trip tests in a clean subprocess."""
        script_path = _write_test_script()
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                pytest.fail(f"Subprocess tests failed:\n{result.stderr}\n{result.stdout}")
            assert "ALL_PASSED" in result.stdout
        finally:
            script_path.unlink()
