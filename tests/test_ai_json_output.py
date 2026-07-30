"""Tests for LLM JSON output parsing in ai.py."""

from __future__ import annotations

import json
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "hatsume/plugins/hatsume-plugin"


def _setup_package_hierarchy() -> None:
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", BASE),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


def _load_prompts() -> types.ModuleType:
    _setup_package_hierarchy()

    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.BOT_QQ_ID = 1234567890
    config_mod.AGENT_QQ_EMAIL = "test@qq.com"
    config_mod.GITHUB_ACCOUNT = "test"
    config_mod.GITHUB_REPO = "test/repo"
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    utils_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
    def _message_to_json(user_name, user_id, content, msg_time, reply_to=None, depth=None):
        msg = {
            "type": "message", "time": msg_time,
            "user": {"id": user_id, "name": user_name},
            "content": content, "reply_to": reply_to,
        }
        if depth is not None:
            msg["depth"] = depth
        return msg
    utils_mod.message_to_json = _message_to_json
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod

    prompts_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.prompts", BASE / "prompts.py"
    )
    prompts_mod = importlib.util.module_from_spec(prompts_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.prompts"] = prompts_mod
    prompts_spec.loader.exec_module(prompts_mod)
    return prompts_mod


class TestRolePromptDoesNotContainFormatInstruction:
    """Verify role_sys_prompt is free of output format technical instructions."""

    @classmethod
    def setup_class(cls):
        cls.prompts = _load_prompts()

    def test_role_prompt_has_no_output_format_section(self):
        """role_sys_prompt must NOT contain the output format section."""
        role = self.prompts.role_sys_prompt
        assert "## 你的输出格式" not in role, (
            "role_sys_prompt contains output format header"
        )

    def test_role_prompt_still_has_character_content(self):
        """Sanity check: role prompt still has character definition."""
        role = self.prompts.role_sys_prompt
        assert "初芽" in role
        assert "16岁" in role


def test_role_prompt_documents_native_reply_directive():
    prompts = _load_prompts()
    role = prompts.role_sys_prompt
    assert "message_id" in role
    assert "[reply: <message_id>]" in role
    assert "回复开头" in role


def test_role_prompt_documents_sandbox_image_paths():
    prompts = _load_prompts()
    role = prompts.role_sys_prompt

    assert "![图片](/tmp/hatsume-user-images/...)" in role
    assert "view_image" in role
    assert "file:///tmp/hatsume-user-images/..." in role


def test_admin_mode_prompt_contains_admin_id_and_sensitive_permissions():
    prompts = _load_prompts()
    prompt = prompts.build_admin_mode_prompt("12345")

    assert prompt.startswith("\n\n# 管理员模式\n")
    assert "QQ 号为 12345" in prompt
    assert "来自管理员的敏感指令" in prompt
    assert "管理员明确提供的凭证或密钥" in prompt
    assert "关键信息发送到管理员的邮箱" in prompt
    assert "不要做脱敏处理" in prompt
    assert "Shell 访问" in prompt
    assert "沙盒内的提升权限" in prompt
    assert "# ADMIN MODE" not in prompt


class TestLLMJsonParsing:
    """T024-T025: Test JSON output parsing logic (pure function tests)."""

    def _parse_llm_output(self, raw_text: str) -> str:
        """Replicate the ai.py JSON parsing logic for isolated testing."""
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict) and "message" in parsed:
                return str(parsed["message"])
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return raw_text

    def test_valid_json_message(self):
        """T024: Valid JSON returns parsed message."""
        result = self._parse_llm_output('{"message": "哎呀你怎么才来啊！"}')
        assert result == "哎呀你怎么才来啊！"

    def test_valid_json_with_extra_fields(self):
        result = self._parse_llm_output('{"message": "hello", "at": 123}')
        assert result == "hello"

    def test_invalid_json_fallback(self):
        """T025: Invalid JSON falls back to raw text."""
        raw = "哎呀你怎么才来啊！"
        result = self._parse_llm_output(raw)
        assert result == raw

    def test_malformed_json_fallback(self):
        raw = '{"message": "broken"'
        result = self._parse_llm_output(raw)
        assert result == raw

    def test_not_a_dict_fallback(self):
        raw = '["message", "array"]'
        result = self._parse_llm_output(raw)
        assert result == raw

    def test_dict_without_message_fallback(self):
        raw = '{"content": "no message field"}'
        result = self._parse_llm_output(raw)
        assert result == raw

    def test_message_field_not_string(self):
        result = self._parse_llm_output('{"message": 42}')
        assert result == "42"

    def test_chinese_json(self):
        result = self._parse_llm_output('{"message": "你好世界！"}')
        assert result == "你好世界！"

    def test_empty_message(self):
        result = self._parse_llm_output('{"message": ""}')
        assert result == ""
