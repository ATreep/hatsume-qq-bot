"""Focused tests: search-result URL output rules in the chat system prompt.

覆盖三个场景：
a. 默认情况下不输出搜索结果的原始网络链接（系统提示词包含"不输出原始链接"规则，
   且允许保留非链接来源名称/简短归因）；
b. 用户明确要求链接/来源/引用/原文/直接打开页面时，允许输出 URL（例外条款）；
c. 搜索工具仍注册在 CHAT_TOOLS 中可调用，展示层仅在文本已含链接时才追加链接段，
   不强制输出 URL。
"""

from __future__ import annotations

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
    """Load prompts.py with only its config dependency stubbed."""
    _setup_package_hierarchy()

    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.BOT_QQ_ID = 1234567890
    config_mod.AGENT_QQ_EMAIL = "test@qq.com"
    config_mod.GITHUB_ACCOUNT = "test"
    config_mod.GITHUB_REPO = "test/repo"
    config_mod.HUGGINGFACE_ACCOUNT = "test-huggingface"
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    prompts_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.prompts", BASE / "prompts.py"
    )
    prompts_mod = importlib.util.module_from_spec(prompts_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.prompts"] = prompts_mod
    prompts_spec.loader.exec_module(prompts_mod)
    return prompts_mod


# ---- 场景 a：默认不输出 URL -------------------------------------------------


def test_role_prompt_defaults_to_no_raw_search_urls():
    """默认系统提示词必须包含"不输出搜索原始链接"规则。"""
    prompts = _load_prompts()
    role = prompts.role_sys_prompt
    assert "默认不输出搜索结果的原始网络链接" in role
    assert "http(s)://" in role or "http://" in role


def test_role_prompt_allows_non_link_source_attribution():
    """规则允许保留非链接来源名称/简短归因（如只写来源站点名而不附链接）。"""
    prompts = _load_prompts()
    role = prompts.role_sys_prompt
    assert "简短归因" in role
    assert "来源站点名" in role


# ---- 场景 b：用户明确要求时允许输出 URL -------------------------------------


def test_role_prompt_allows_urls_on_explicit_request():
    """例外条款：用户明确要求链接/来源/引用/原文/直接打开页面时除外。"""
    prompts = _load_prompts()
    role = prompts.role_sys_prompt
    assert "明确要求链接、来源、引用、原文或直接打开页面" in role
    assert "才输出相应的 URL" in role


# ---- 场景 c：搜索工具仍可调用，展示层不强制 URL -----------------------------


def test_search_tool_still_registered_in_chat_tools():
    """搜索工具仍注册在 CHAT_TOOLS 中（可调用），提示词规则不得取消工具。"""
    src = (BASE / "graph" / "tools.py").read_text(encoding="utf-8")
    assert "def search_web(" in src
    assert '{"type": "web_search"}' in src
    assert src.index("CHAT_TOOLS") < src.index('{"type": "web_search"}')


def test_display_layer_appends_links_only_when_present():
    """展示层仅在文本已含链接时追加链接段，不强制输出 URL。"""
    src = (BASE / "utils" / "md_to_image.py").read_text(encoding="utf-8")
    assert "if links:" in src
    assert "segments.append(MessageSegment.text(_format_links(links)))" in src
