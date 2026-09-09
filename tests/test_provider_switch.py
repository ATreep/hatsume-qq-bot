"""Tests for provider auto-switching (chat_agent latency trigger).

Covers the ``ProviderSwitcher`` logic (pure unit tests with injected
``now``), the module singleton wiring against the real config default, and
— in a subprocess per tests/AGENTS.md, same pattern as
``tests/test_code_model_fallback.py`` — that ``models.get_advance_model``
follows the dynamic provider while lite/mini models stay on the static
default.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "hatsume/plugins/hatsume-plugin"
CONFIG_PATH = BASE / "config.py"
PROVIDER_SWITCH_PATH = BASE / "provider_switch.py"


def _load_modules(monkeypatch):
    """Load the real config.py and provider_switch.py under a synthetic package."""
    monkeypatch.setitem(
        sys.modules,
        "dotenv",
        types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None),
    )

    pkg = types.ModuleType("provider_switch_test_pkg")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "provider_switch_test_pkg", pkg)

    config_spec = importlib.util.spec_from_file_location(
        "provider_switch_test_pkg.config", CONFIG_PATH
    )
    assert config_spec is not None and config_spec.loader is not None
    config_mod = importlib.util.module_from_spec(config_spec)
    monkeypatch.setitem(sys.modules, "provider_switch_test_pkg.config", config_mod)
    config_spec.loader.exec_module(config_mod)

    spec = importlib.util.spec_from_file_location(
        "provider_switch_test_pkg.provider_switch", PROVIDER_SWITCH_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules, "provider_switch_test_pkg.provider_switch", mod
    )
    spec.loader.exec_module(mod)
    return config_mod, mod


class TestProviderSwitcher:
    """Unit tests for the switching state machine (injected ``now``)."""

    def test_slow_invocation_switches_to_other_candidate(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        assert sw.record_elapsed(150.0, now=1000.0) == "ruoli"
        assert sw.current == "ruoli"

    def test_exactly_100s_is_not_slow(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        assert sw.record_elapsed(100.0, now=0) is None
        assert sw.current == "waw"
        assert sw.record_elapsed(100.01, now=0) == "ruoli"

    def test_second_slow_invocation_within_cooldown_stays(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        assert sw.record_elapsed(150.0, now=0) == "ruoli"
        # Both candidates now slow within the 12h cooldown: no flip-flop.
        assert sw.record_elapsed(150.0, now=1) is None
        assert sw.current == "ruoli"

    def test_cooldown_expiry_resumes_switching(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        assert sw.record_elapsed(150.0, now=0) == "ruoli"
        # After the 12h cooldown the original provider is eligible again.
        assert sw.record_elapsed(
            150.0, now=mod.SLOW_COOLDOWN_SECONDS + 1
        ) == "waw"

    def test_fast_invocation_clears_slow_mark(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        sw.record_elapsed(150.0, now=0)  # -> ruoli, waw marked slow
        sw.record_elapsed(150.0, now=1)  # both slow, stays on ruoli
        assert "ruoli" in sw._slow_until
        # Fast invocation on the current provider clears its slow mark.
        assert sw.record_elapsed(50.0, now=2) is None
        assert "ruoli" not in sw._slow_until
        # waw is still in its cooldown window, so no switch is possible.
        assert sw.record_elapsed(150.0, now=3) is None
        assert sw.current == "ruoli"

    def test_stale_provider_report_marks_without_switching(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        # A concurrent invocation that used ruoli while current is waw only
        # marks ruoli slow; it must not move the current selection.
        assert sw.record_elapsed(150.0, provider="ruoli", now=0) is None
        assert sw.current == "waw"
        assert "ruoli" in sw._slow_until

    def test_older_fast_completion_does_not_clear_newer_slow_mark(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        # Two overlapping waw invocations: the newer one is slow and switches
        # to ruoli; the older one later completes quickly.
        assert sw.record_elapsed(150.0, now=200, started_at=10) == "ruoli"
        assert sw.record_elapsed(10.0, provider="waw", now=201, started_at=1) is None
        assert "waw" in sw._slow_until
        assert sw.current == "ruoli"

    def test_newer_fast_completion_clears_slow_mark(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="waw")
        assert sw.record_elapsed(150.0, now=200, started_at=10) == "ruoli"
        assert sw.record_elapsed(10.0, provider="waw", now=201, started_at=11) is None
        assert "waw" not in sw._slow_until

    def test_default_provider_outside_candidates_falls_back(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        sw = mod.ProviderSwitcher(default_provider="ds")
        assert sw.current == "waw"

    def test_empty_candidates_rejected(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        with pytest.raises(ValueError):
            mod.ProviderSwitcher(candidates=())


class TestModuleSingleton:
    """The module-level singleton helpers used by models.py / nodes.py."""

    def test_initial_provider_follows_config_default(self, monkeypatch):
        config_mod, mod = _load_modules(monkeypatch)
        assert mod.get_chat_provider() == config_mod.PROVIDER

    def test_report_chat_elapsed_switches_singleton(self, monkeypatch):
        _, mod = _load_modules(monkeypatch)
        initial = mod.get_chat_provider()
        other = "ruoli" if initial == "waw" else "waw"
        assert mod.report_chat_elapsed(150.0) == other
        assert mod.get_chat_provider() == other
        # A fast invocation afterwards must not switch back.
        assert mod.report_chat_elapsed(10.0) is None
        assert mod.get_chat_provider() == other


def _write_models_script() -> Path:
    """Write the subprocess script exercising the real models.py factory."""
    script = f'''
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path("{ROOT}")
BASE = ROOT / "hatsume/plugins/hatsume-plugin"

for name, path in [
    ("hatsume", ROOT / "hatsume"),
    ("hatsume.plugins", ROOT / "hatsume/plugins"),
    ("hatsume.plugins.hatsume-plugin", BASE),
]:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod

requested_providers = []

config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
config_mod.PROVIDER = "waw"
config_mod.CHAT_PROVIDER_SWITCH_CANDIDATES = ("ruoli", "waw")
config_mod.CHAT_PROVIDER_SWITCH_THRESHOLD_SECONDS = 100.0
config_mod.CHAT_PROVIDER_SWITCH_COOLDOWN_SECONDS = 12 * 60 * 60
config_mod.ADVANCE_MODEL_NAME = "gemini-3.7-flash"
config_mod.LITE_MODEL_NAME = "gemini-3.7-flash"
config_mod.ALI_BASE_URL = "https://ali.example"
config_mod.ALI_API_KEY = "ali-key"
config_mod.QWEN_3_7_FLASH = "qwen3.7-flash"
config_mod.EMBEDDING_MODEL = "BAAI/bge-m3"
config_mod.GROK_IMAGINE_IMAGE = "grok-imagine-image:stable"
config_mod.KEGEAI_API_KEY = "kege-key"
config_mod.KEGEAI_BASE_URL = "https://ai.kegeai.top"
config_mod.SEEDANCE_1_0 = "seedance-1-0"
config_mod.SEEDANCE_1_5 = "seedance-1-5"
config_mod.SEEDREAM_4_0 = "seedream-4-0"
config_mod.VOLCENGINE_BASE_URL = "https://ark.cn-beijing.volces.com/api"
config_mod.WAWAPI_IMAGE_API_KEY = "waw-image-key"
config_mod._get_int_env = lambda name: 0

def _base_url(prov=None):
    requested_providers.append(("base_url", prov))
    return f"https://{{prov or 'default'}}"

def _api_key(prov=None):
    requested_providers.append(("api_key", prov))
    return lambda: f"key-{{prov or 'default'}}"

config_mod.get_base_url = _base_url
config_mod.get_api_key = _api_key
sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

provider_switch_mod = types.ModuleType(
    "hatsume.plugins.hatsume-plugin.provider_switch"
)
provider_switch_mod._current = "waw"
provider_switch_mod.get_chat_provider = lambda: provider_switch_mod._current

def _report_chat_elapsed(elapsed, provider=None, started_at=None):
    if elapsed <= 100:
        return None
    provider_switch_mod._current = "ruoli"
    return "ruoli"

provider_switch_mod.report_chat_elapsed = _report_chat_elapsed
sys.modules[provider_switch_mod.__name__] = provider_switch_mod

volc_mod = types.ModuleType("volcenginesdkarkruntime")
volc_mod.Ark = type("Ark", (), {{"__init__": lambda *a, **kw: None}})
sys.modules["volcenginesdkarkruntime"] = volc_mod

created = []

class FakeChatGoogleGenerativeAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        created.append(self)

google_mod = types.ModuleType("langchain_google_genai")
google_mod.ChatGoogleGenerativeAI = FakeChatGoogleGenerativeAI
sys.modules["langchain_google_genai"] = google_mod

spec = importlib.util.spec_from_file_location(
    "hatsume.plugins.hatsume-plugin.models", BASE / "models.py"
)
models_mod = importlib.util.module_from_spec(spec)
sys.modules["hatsume.plugins.hatsume-plugin.models"] = models_mod
spec.loader.exec_module(models_mod)

errors = []

def check(condition, message):
    if not condition:
        errors.append(message)

# Before any switch: the advance model follows the config default (waw).
adv1 = models_mod.get_advance_model()
check(isinstance(adv1, FakeChatGoogleGenerativeAI),
      "advance model must be built by get_google_api_model")
check(adv1.kwargs.get("base_url") == "https://waw",
      f"advance model must default to waw, got {{adv1.kwargs.get('base_url')}}")
check(adv1.kwargs.get("api_key") == "key-waw",
      f"advance model must use the waw key, got {{adv1.kwargs.get('api_key')}}")

# Trigger: a slow chat_agent invocation (> 100s) switches waw -> ruoli.
switched = provider_switch_mod.report_chat_elapsed(150.0)
check(switched == "ruoli",
      f"slow invocation must switch to ruoli, got {{switched}}")
check(provider_switch_mod.get_chat_provider() == "ruoli",
      "dynamic provider must be ruoli after the slow invocation")

adv2 = models_mod.get_advance_model()
check(adv2.kwargs.get("base_url") == "https://ruoli",
      f"advance model must follow ruoli after the switch, got {{adv2.kwargs.get('base_url')}}")
check(adv2.kwargs.get("api_key") == "key-ruoli",
      f"advance model must use the ruoli key, got {{adv2.kwargs.get('api_key')}}")

# A fast invocation must not switch back.
check(provider_switch_mod.report_chat_elapsed(10.0) is None,
      "fast invocation must not switch providers")
adv3 = models_mod.get_advance_model()
check(adv3.kwargs.get("base_url") == "https://ruoli",
      "advance model must stay on ruoli after a fast invocation")

# Non-advance models keep the static default provider.
lite = models_mod.get_lite_model()
check(lite.kwargs.get("base_url") == "https://waw",
      f"lite model must stay on the static default, got {{lite.kwargs.get('base_url')}}")

if errors:
    for e in errors:
        print(f"FAIL: {{e}}", file=sys.stderr)
    sys.exit(1)
print("ALL_PASSED")
sys.exit(0)
'''
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    tmp.write(script)
    tmp.close()
    return Path(tmp.name)


class TestAdvanceModelFollowsDynamicProvider:
    """Verify models.get_advance_model wiring in a clean subprocess."""

    def test_advance_model_uses_dynamic_provider(self):
        script_path = _write_models_script()
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                pytest.fail(
                    f"Subprocess tests failed:\n{result.stderr}\n{result.stdout}"
                )
            assert "ALL_PASSED" in result.stdout
        finally:
            script_path.unlink()
