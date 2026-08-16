"""Tests for the /dsbalance command handler."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


class MockFinished(Exception):
    """Simulate NoneBot's FinishedException for matcher.finish()."""

    pass


def _finish_that_stops(*args, **kwargs):
    """Mock finish that raises MockFinished to stop execution."""
    raise MockFinished


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy() -> None:
    """Ensure package hierarchy exists with hyphen-to-underscore alias."""
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

    # Alias so hatsume_plugin resolves to hatsume-plugin
    if "hatsume.plugins.hatsume_plugin" not in sys.modules:
        alias = types.ModuleType("hatsume.plugins.hatsume_plugin")
        alias.__path__ = [str(PLUGIN_DIR)]
        sys.modules["hatsume.plugins.hatsume_plugin"] = alias

    # Stub nonebot
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adap_name = "nonebot.adapters"
    if adap_name not in sys.modules:
        adap = types.ModuleType(adap_name)
        adap.__path__ = []
        sys.modules[adap_name] = adap
    if not hasattr(sys.modules[adap_name], "Bot"):
        sys.modules[adap_name].Bot = type("Bot", (), {})
    onebot_name = "nonebot.adapters.onebot"
    if onebot_name not in sys.modules:
        ob = types.ModuleType(onebot_name)
        ob.__path__ = []
        sys.modules[onebot_name] = ob
    v11_name = "nonebot.adapters.onebot.v11"
    if v11_name not in sys.modules:
        v11 = types.ModuleType(v11_name)
    else:
        v11 = sys.modules[v11_name]
    v11.Message = type("Message", (), {})
    v11.MessageSegment = types.SimpleNamespace(
        text=lambda s: s, image=lambda *a, **kw: None
    )
    v11.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    sys.modules.setdefault(v11_name, v11)

    # Stub infra module (imported by handlers/tools.py)
    infra_name = "hatsume.plugins.hatsume-plugin.infra"
    if infra_name not in sys.modules:
        infra = types.ModuleType(infra_name)
        infra.run_cmd = lambda *a, **kw: ""
        infra.run_cmd_async = AsyncMock(return_value="")
        infra.delete_container = lambda: None
        infra.cleanup_persistent_container = AsyncMock(return_value=False)
        infra.ensure_container_running = lambda: None
        infra.render_html_to_image = AsyncMock(return_value=b"")
        infra.cache_sandbox_message_image = AsyncMock()
        sys.modules[infra_name] = infra
        sys.modules["hatsume.plugins.hatsume_plugin.infra"] = infra

    infra = sys.modules[infra_name]
    if not hasattr(infra, "cache_sandbox_message_image"):
        infra.cache_sandbox_message_image = AsyncMock()
    sys.modules["hatsume.plugins.hatsume_plugin.infra"] = infra

    # Stub config module with the DeepSeek settings used by /dsbalance
    config_name = "hatsume.plugins.hatsume-plugin.config"
    if config_name not in sys.modules:
        config = types.ModuleType(config_name)
        config.ADMIN_QQ_ID = "12345"
        config.DS_API_KEY = "test-ds-key"
        config.DS_BASE_URL = "https://api.deepseek.com"
        sys.modules[config_name] = config
        sys.modules["hatsume.plugins.hatsume_plugin.config"] = config

    runtime_name = "hatsume.plugins.hatsume_plugin.group_runtime"
    runtime = types.ModuleType(runtime_name)

    @contextmanager
    def bind_group_runtime(value):
        yield value

    runtime.bind_group_runtime = bind_group_runtime
    runtime.group_runtime_registry = types.SimpleNamespace(
        get_or_create=lambda group_id: types.SimpleNamespace(group_id=group_id),
        get_existing=lambda _group_id: None,
    )
    sys.modules[runtime_name] = runtime

    # Stub state module
    state_name = "hatsume.plugins.hatsume-plugin.state"
    if state_name not in sys.modules:
        state = types.ModuleType(state_name)
        state.ConversationState = MagicMock()
        sys.modules[state_name] = state
        sys.modules["hatsume.plugins.hatsume_plugin.state"] = state


_setup_package_hierarchy()


def _get_commands_module():
    """Load and return the commands module (always reload to avoid stale stubs)."""
    # Force-set nonebot stubs (other tests may have polluted them)
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    adap_name = "nonebot.adapters"
    if adap_name not in sys.modules:
        sys.modules[adap_name] = types.ModuleType(adap_name)
        sys.modules[adap_name].__path__ = []
    sys.modules[adap_name].Bot = type("Bot", (), {})
    v11_name = "nonebot.adapters.onebot.v11"
    if v11_name not in sys.modules:
        sys.modules[v11_name] = types.ModuleType(v11_name)
    if not hasattr(sys.modules[v11_name], "Message"):
        sys.modules[v11_name].Message = type("Message", (), {})
    if not hasattr(sys.modules[v11_name], "MessageSegment"):
        sys.modules[v11_name].MessageSegment = types.SimpleNamespace(
            text=lambda s: s, image=lambda *a, **kw: None
        )
    if not hasattr(sys.modules[v11_name], "PokeNotifyEvent"):
        sys.modules[v11_name].PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    for config_name in (
        "hatsume.plugins.hatsume-plugin.config",
        "hatsume.plugins.hatsume_plugin.config",
    ):
        config = sys.modules[config_name]
        config.ADMIN_QQ_ID = "12345"
        if not hasattr(config, "DS_API_KEY"):
            config.DS_API_KEY = "test-ds-key"
        if not hasattr(config, "DS_BASE_URL"):
            config.DS_BASE_URL = "https://api.deepseek.com"
    # Reload the module
    import importlib.util

    full_name = "hatsume.plugins.hatsume_plugin.handlers.tools"
    commands_path = PLUGIN_DIR / "handlers" / "tools.py"
    if full_name in sys.modules:
        del sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, commands_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return sys.modules[full_name]


def _set_ds_api_key(value: str) -> None:
    for config_name in (
        "hatsume.plugins.hatsume-plugin.config",
        "hatsume.plugins.hatsume_plugin.config",
    ):
        sys.modules[config_name].DS_API_KEY = value


def _run_and_capture_msg(matcher, *, ds_api_key: str = "test-ds-key") -> str:
    """Run handle_dsbalance, catch MockFinished, return the finish message."""
    import asyncio

    cmd = _get_commands_module()
    _set_ds_api_key(ds_api_key)
    event = types.SimpleNamespace(group_id=101, get_user_id=lambda: "77")
    args = types.SimpleNamespace(extract_plain_text=lambda: "")
    try:
        asyncio.run(cmd.handle_dsbalance(event, matcher, args))
    except MockFinished:
        pass
    matcher.finish.assert_awaited_once()
    return matcher.finish.call_args[0][0]


def _new_matcher() -> MagicMock:
    matcher = MagicMock()
    matcher.finish = AsyncMock(side_effect=_finish_that_stops)
    return matcher


def _make_ok_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


class TestHandleDsbalance:
    """Tests for the handle_dsbalance command handler."""

    def test_success_shows_balance_in_yuan_and_availability(self, monkeypatch):
        cmd = _get_commands_module()
        payload = {
            "is_available": True,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "11000",
                    "granted_balance": "1000",
                    "topped_up_balance": "10000",
                }
            ],
        }
        get = MagicMock(return_value=_make_ok_response(payload))
        monkeypatch.setattr(cmd.requests, "get", get)

        msg = _run_and_capture_msg(_new_matcher())

        get.assert_called_once_with(
            "https://api.deepseek.com/user/balance",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer test-ds-key",
                "User-Agent": "Hatsume/1.0",
            },
            timeout=10,
        )
        assert "¥110.00" in msg
        assert "¥100.00" in msg
        assert "¥10.00" in msg
        assert "可用" in msg
        assert "test-ds-key" not in msg

    def test_success_keeps_already_yuan_decimal_strings(self, monkeypatch):
        cmd = _get_commands_module()
        payload = {
            "is_available": True,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "110.00",
                    "granted_balance": "0.00",
                    "topped_up_balance": "110.00",
                }
            ],
        }
        get = MagicMock(return_value=_make_ok_response(payload))
        monkeypatch.setattr(cmd.requests, "get", get)

        msg = _run_and_capture_msg(_new_matcher())

        assert "¥110.00" in msg
        assert "test-ds-key" not in msg

    def test_accepts_balances_key_alias(self, monkeypatch):
        cmd = _get_commands_module()
        payload = {
            "is_available": False,
            "balances": [
                {"currency": "CNY", "total_balance": "500", "granted_balance": "0", "topped_up_balance": "500"}
            ],
        }
        get = MagicMock(return_value=_make_ok_response(payload))
        monkeypatch.setattr(cmd.requests, "get", get)

        msg = _run_and_capture_msg(_new_matcher())

        assert "¥5.00" in msg
        assert "不可用" in msg
        assert "test-ds-key" not in msg

    def test_missing_api_key_does_not_make_request(self, monkeypatch):
        cmd = _get_commands_module()
        get = MagicMock()
        monkeypatch.setattr(cmd.requests, "get", get)

        msg = _run_and_capture_msg(_new_matcher(), ds_api_key="")

        assert "未配置" in msg
        get.assert_not_called()

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_http_401_403_shows_invalid_key(self, monkeypatch, status_code):
        cmd = _get_commands_module()

        def unauthorized(*args, **kwargs):
            response = MagicMock(status_code=status_code)
            raise cmd.requests.exceptions.HTTPError("denied", response=response)

        monkeypatch.setattr(cmd.requests, "get", unauthorized)

        msg = _run_and_capture_msg(_new_matcher())

        assert "无效" in msg
        assert "test-ds-key" not in msg

    def test_http_429_shows_rate_limit(self, monkeypatch):
        cmd = _get_commands_module()

        def rate_limited(*args, **kwargs):
            response = MagicMock(status_code=429)
            raise cmd.requests.exceptions.HTTPError("limited", response=response)

        monkeypatch.setattr(cmd.requests, "get", rate_limited)

        msg = _run_and_capture_msg(_new_matcher())

        assert "频繁" in msg
        assert "test-ds-key" not in msg

    def test_http_500_shows_status_code(self, monkeypatch):
        cmd = _get_commands_module()

        def server_error(*args, **kwargs):
            response = MagicMock(status_code=500)
            raise cmd.requests.exceptions.HTTPError("boom", response=response)

        monkeypatch.setattr(cmd.requests, "get", server_error)

        msg = _run_and_capture_msg(_new_matcher())

        assert "HTTP 500" in msg
        assert "test-ds-key" not in msg

    def test_ssl_error_shows_friendly_message(self, monkeypatch):
        cmd = _get_commands_module()

        def ssl_error(*args, **kwargs):
            raise cmd.requests.exceptions.SSLError("certificate verify failed")

        monkeypatch.setattr(cmd.requests, "get", ssl_error)

        msg = _run_and_capture_msg(_new_matcher())

        assert "SSL" in msg
        assert "test-ds-key" not in msg

    def test_unexpected_error_shows_generic_message(self, monkeypatch):
        cmd = _get_commands_module()

        def unexpected(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(cmd.requests, "get", unexpected)

        msg = _run_and_capture_msg(_new_matcher())

        assert "失败" in msg
        assert "test-ds-key" not in msg

    def test_timeout_shows_friendly_message(self, monkeypatch):
        cmd = _get_commands_module()

        def timeout(*args, **kwargs):
            raise cmd.requests.exceptions.Timeout("slow")

        monkeypatch.setattr(cmd.requests, "get", timeout)

        msg = _run_and_capture_msg(_new_matcher())

        assert "超时" in msg
        assert "test-ds-key" not in msg

    def test_connection_error_shows_friendly_message(self, monkeypatch):
        cmd = _get_commands_module()

        def connection_error(*args, **kwargs):
            raise cmd.requests.exceptions.ConnectionError("down")

        monkeypatch.setattr(cmd.requests, "get", connection_error)

        msg = _run_and_capture_msg(_new_matcher())

        assert "无法连接" in msg
        assert "test-ds-key" not in msg

    def test_invalid_json_shows_invalid_data_message(self, monkeypatch):
        cmd = _get_commands_module()

        def bad_json(*args, **kwargs):
            response = MagicMock()
            response.raise_for_status.return_value = None
            raise cmd.requests.exceptions.InvalidJSONError(
                "bad payload", response=response
            )

        monkeypatch.setattr(cmd.requests, "get", bad_json)

        msg = _run_and_capture_msg(_new_matcher())

        assert "无效数据" in msg
        assert "test-ds-key" not in msg

    def test_malformed_payload_shows_invalid_data_message(self, monkeypatch):
        cmd = _get_commands_module()
        get = MagicMock(return_value=_make_ok_response({"is_available": True}))
        monkeypatch.setattr(cmd.requests, "get", get)

        msg = _run_and_capture_msg(_new_matcher())

        assert "无效数据" in msg
        assert "test-ds-key" not in msg
