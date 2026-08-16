"""Focused tests for the code model fallback (OpenCode Zen -> official DeepSeek).

The code model factory must keep OpenCode Zen's ``deepseek-v4-flash-free`` as
its primary and automatically retry with the official DeepSeek
``deepseek-v4-flash`` (base URL ``https://api.deepseek.com``, existing
``DS_API_KEY``) only when the primary call raises (request failure, HTTP
error, timeout). Normal responses must never touch the fallback, and non-code
model factories must stay plain.

``models.py`` monkey-patches langchain_openai at import time, so per
tests/AGENTS.md the real factory is exercised in a subprocess (same pattern as
``tests/test_reasoning_content.py``).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _write_test_script() -> Path:
    """Write the subprocess script that loads the real models.py."""
    script = f'''
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path("{ROOT}")
BASE = ROOT / "hatsume/plugins/hatsume-plugin"
MODELS_PATH = BASE / "models.py"

# ------------------------------------------------------------------
# Stub config so every provider value is deterministic.
# ------------------------------------------------------------------
for name, path in [
    ("hatsume", ROOT / "hatsume"),
    ("hatsume.plugins", ROOT / "hatsume/plugins"),
    ("hatsume.plugins.hatsume-plugin", BASE),
]:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod

config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
config_mod.OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen"
config_mod.OPENCODE_API_KEY = "zen-key"
config_mod.DEEPSEEK_V4_FLASH = "deepseek-v4-flash-free"
config_mod.DEEPSEEK_V4_FLASH_FALLBACK = "deepseek-v4-flash"
config_mod.DS_BASE_URL = "https://api.deepseek.com"
config_mod.DS_API_KEY = "ds-key"
config_mod.ADVANCE_MODEL_NAME = "deepseek-v4-flash-free"
config_mod.LITE_MODEL_NAME = "gpt-5.6-luna"
config_mod.GPT_5_6_LUNA = "gpt-5.6-luna"
config_mod.EMBEDDING_MODEL = "BAAI/bge-m3"
config_mod.GROK_IMAGINE_IMAGE = "grok-imagine-image:stable"
config_mod.KEGEAI_API_KEY = "kege-key"
config_mod.KEGEAI_BASE_URL = "https://ai.kegeai.top"
config_mod.SEEDANCE_1_0 = "seedance-1-0"
config_mod.SEEDANCE_1_5 = "seedance-1-5"
config_mod.SEEDREAM_4_0 = "seedream-4-0"
config_mod.SEEDREAM_5_0_LITE = "seedream-5-0-lite"
config_mod.VOLCENGINE_BASE_URL = "https://ark.cn-beijing.volces.com/api"
config_mod.WAWAPI_IMAGE_API_KEY = "waw-key"
config_mod.get_base_url = lambda prov=None: "https://default"
config_mod.get_api_key = lambda prov=None: lambda: "default-key"
sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

volc_mod = types.ModuleType("volcenginesdkarkruntime")
volc_mod.Ark = type("Ark", (), {{"__init__": lambda *a, **kw: None}})
sys.modules["volcenginesdkarkruntime"] = volc_mod

# ``models.py`` imports the Google provider for a separate model factory;
# this regression test only exercises the OpenAI-compatible code models.
google_mod = types.ModuleType("langchain_google_genai")
google_mod.ChatGoogleGenerativeAI = type("ChatGoogleGenerativeAI", (), {{}})
sys.modules["langchain_google_genai"] = google_mod

# ------------------------------------------------------------------
# Load the real models.py (triggers the langchain_openai monkey-patch).
# ------------------------------------------------------------------
spec = importlib.util.spec_from_file_location(
    "hatsume.plugins.hatsume-plugin.models", MODELS_PATH
)
models_mod = importlib.util.module_from_spec(spec)
sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod
spec.loader.exec_module(models_mod)

errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


# ------------------------------------------------------------------
# Phase A: real ChatOpenAI construction with the real factory.
# ------------------------------------------------------------------
code = models_mod.get_code_model()
check(hasattr(code, "primary") and hasattr(code, "fallback"),
      "get_code_model() must return a fallback wrapper with primary/fallback")

primary = code.primary
check(primary.openai_api_base == "https://opencode.ai/zen",
      f"primary base_url must be OpenCode Zen, got {{primary.openai_api_base}}")
check(primary.model_name == "deepseek-v4-flash-free",
      f"primary model must stay deepseek-v4-flash-free, got {{primary.model_name}}")
check(primary.openai_api_key() == "zen-key",
      f"primary key must be OPENCODE_API_KEY, got {{primary.openai_api_key()}}")

fallback = code.fallback
check(fallback.openai_api_base == "https://api.deepseek.com",
      f"fallback base_url must be official DeepSeek, got {{fallback.openai_api_base}}")
check(fallback.model_name == "deepseek-v4-flash",
      f"fallback model must be deepseek-v4-flash, got {{fallback.model_name}}")
check(fallback.openai_api_key() == "ds-key",
      f"fallback key must be DS_API_KEY, got {{fallback.openai_api_key()}}")

# ``_CodeModelWithFallback.bind_tools`` must preserve ChatOpenAI's tool-schema
# conversion.  The coding agent mixes a normal function tool with the
# Responses API ``web_search`` built-in; invoking the request payload builder
# must therefore not try to subscript a raw StructuredTool.
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool


def local_tool(value: str) -> str:
    """Return a value for the local payload-construction regression test."""
    return value


bound = code.bind_tools(
    [StructuredTool.from_function(local_tool), {{"type": "web_search"}}]
)
bound_kwargs = bound.kwargs
check(
    all(isinstance(tool, dict) for tool in bound_kwargs["tools"]),
    "bound tools must be converted to dictionaries before invocation",
)
try:
    code.primary._get_request_payload(
        [HumanMessage("hi")], **bound_kwargs
    )
except Exception as exc:
    errors.append(
        f"mixed function/builtin tools must build a payload without error: {{exc}}"
    )

# Non-code model factories stay plain (no primary/fallback attributes).
for factory, args in [
    (models_mod.get_advance_model, ()),
    (models_mod.get_lite_model, ()),
    (models_mod.get_mini_model, ()),
    (models_mod.get_standard_api_model, ("test-model",)),
    (models_mod.get_view_image_model, ()),
]:
    m = factory(*args)
    check(not hasattr(m, "primary") and not hasattr(m, "fallback"),
          f"{{factory.__name__}} must not carry fallback semantics")
    check(isinstance(m, models_mod.ChatOpenAI),
          f"{{factory.__name__}} must return a plain ChatOpenAI")

# ------------------------------------------------------------------
# Phase B: fake ChatOpenAI exercising the fallback behavior.
# ------------------------------------------------------------------
from typing import ClassVar

from langchain_core.language_models.chat_models import BaseChatModel as LCB
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from pydantic import ConfigDict, Field


def _chat_result(content):
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


class FakeChatOpenAI(LCB):
    """BaseChatModel drop-in for langchain_openai.ChatOpenAI.

    ``extra="allow"`` lets it accept the same construction kwargs as the real
    ChatOpenAI (base_url, model, extra_body, reasoning_effort, api_key) while
    keeping the model name reachable via ``self.model``.
    """

    instances: ClassVar[list] = []
    fail_primary: ClassVar[bool] = True
    fail_fallback: ClassVar[bool] = False
    calls: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        FakeChatOpenAI.instances.append(self)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _should_fail(self) -> bool:
        model = getattr(self, "model", None)
        if model == "deepseek-v4-flash-free" and FakeChatOpenAI.fail_primary:
            return True
        if model == "deepseek-v4-flash" and FakeChatOpenAI.fail_fallback:
            return True
        return False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append("generate")
        if self._should_fail():
            raise RuntimeError(f"{{self.model}} provider error")
        return _chat_result(f"ok:{{self.model}}")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append("agenerate")
        if self._should_fail():
            raise RuntimeError(f"{{self.model}} provider error")
        return _chat_result(f"ok:{{self.model}}")


models_mod.ChatOpenAI = FakeChatOpenAI


def run():
    # 1. async ainvoke: primary error -> official DeepSeek fallback used
    FakeChatOpenAI.fail_primary, FakeChatOpenAI.fail_fallback = True, False
    FakeChatOpenAI.instances = []
    code = models_mod.get_code_model()
    result = asyncio.run(code.ainvoke([HumanMessage("hi")]))
    check(result.content == "ok:deepseek-v4-flash",
          f"ainvoke must fall back on primary error, got {{result.content}}")
    check(FakeChatOpenAI.instances[0].calls == ["agenerate"],
          "primary must be invoked exactly once on failure")
    check(FakeChatOpenAI.instances[1].calls == ["agenerate"],
          "fallback must be invoked exactly once on primary error")

    # 2. primary success -> fallback never touched
    FakeChatOpenAI.fail_primary = False
    FakeChatOpenAI.instances = []
    code = models_mod.get_code_model()
    result = asyncio.run(code.ainvoke([HumanMessage("hi")]))
    check(result.content == "ok:deepseek-v4-flash-free",
          f"normal responses must come from the Zen primary, got {{result.content}}")
    check(FakeChatOpenAI.instances[1].calls == [],
          "fallback must not be invoked when the primary succeeds")

    # 3. sync invoke: primary error -> fallback used
    FakeChatOpenAI.fail_primary, FakeChatOpenAI.fail_fallback = True, False
    FakeChatOpenAI.instances = []
    code = models_mod.get_code_model()
    result = code.invoke([HumanMessage("hi")])
    check(result.content == "ok:deepseek-v4-flash",
          f"invoke must fall back on primary error, got {{result.content}}")
    check(FakeChatOpenAI.instances[1].calls == ["generate"],
          "sync fallback must be invoked on primary error")

    # 4. both models fail -> the fallback error propagates (never swallowed)
    FakeChatOpenAI.fail_fallback = True
    FakeChatOpenAI.instances = []
    code = models_mod.get_code_model()
    try:
        asyncio.run(code.ainvoke([HumanMessage("hi")]))
        errors.append("both-fail must raise, got success")
    except RuntimeError as exc:
        check("deepseek-v4-flash provider error" in str(exc),
              f"fallback error must propagate, got {{exc}}")

    # 5. bind_tools keeps the wrapper as the invocation target
    FakeChatOpenAI.fail_primary, FakeChatOpenAI.fail_fallback = True, False
    FakeChatOpenAI.instances = []
    code = models_mod.get_code_model()
    bound = code.bind_tools([{{"type": "web_search"}}], tool_choice=None, strict=None)
    result = asyncio.run(bound.ainvoke([HumanMessage("hi")]))
    check(result.content == "ok:deepseek-v4-flash",
          f"bound model must still fall back, got {{result.content}}")
    check(FakeChatOpenAI.instances[1].calls == ["agenerate"],
          "fallback must be invoked through the tool binding")

    # 6. astream also falls back
    FakeChatOpenAI.instances = []
    code = models_mod.get_code_model()

    async def stream_check():
        return [c async for c in code.astream([HumanMessage("hi")])]

    chunks = asyncio.run(stream_check())
    check(bool(chunks) and chunks[-1].content == "ok:deepseek-v4-flash",
          f"astream must fall back on primary error, got {{[c.content for c in chunks]}}")


run()

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


class TestCodeModelFallback:
    """Verify Zen primary + official DeepSeek fallback wiring."""

    def test_fallback_wiring_and_behavior(self):
        """Run all code-model fallback assertions in a clean subprocess."""
        script_path = _write_test_script()
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                pytest.fail(f"Subprocess tests failed:\n{result.stderr}\n{result.stdout}")
            assert "ALL_PASSED" in result.stdout
        finally:
            script_path.unlink()
