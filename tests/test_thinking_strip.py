"""Tests for strip_thinking_tags — the model thinking/reasoning cleanup util.

Reasoning-capable models (DeepSeek <think>, Gemini thought blocks,
[thinking]/[reasoning] variants) must never leak their internal reasoning
into user-visible messages, prompts, or JSON parsers.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UTILS_INIT = ROOT / "hatsume/plugins/hatsume-plugin/utils/__init__.py"


@pytest.fixture(scope="module")
def strip_thinking_tags():
    """Load utils/__init__.py with nonebot.adapters stubbed."""
    # Stub nonebot so utils/__init__.py can import Bot
    nb_mod = types.ModuleType("nonebot")
    nb_mod.__path__ = []
    sys.modules["nonebot"] = nb_mod

    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters"] = adapters_mod

    security_mod = types.ModuleType(
        "hatsume.plugins.hatsume-plugin.utils.security"
    )
    security_mod.mask_secret_keys = lambda value: value
    sys.modules["hatsume.plugins.hatsume-plugin.utils.security"] = security_mod

    utils_pkg = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
    utils_pkg.__path__ = [str(UTILS_INIT.parent)]
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_pkg

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils",
        UTILS_INIT,
    )
    utils_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    spec.loader.exec_module(utils_mod)

    return utils_mod.strip_thinking_tags


class TestStripThinkingTags:
    """Verify thinking/reasoning blocks are removed from AI output text."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("<think>内部推理</think>答案", "答案"),
            ("<think>\n多行\n推理\n</think>\n\n最终答案", "\n\n最终答案"),
            ("[thinking]推理内容[/thinking]答案", "答案"),
            ("[reasoning]r[/reasoning]答", "答"),
            ("[think]t[/think]答", "答"),
            ('<think system="deepseek">r</think>你好', "你好"),
            ("<THINK>大写</THINK>文本", "文本"),
            ("答案<think>尾巴</think>", "答案"),
            ("无标签内容", "无标签内容"),
            ("", ""),
            ("<think>未闭合标签", "<think>未闭合标签"),
            ("普通文本<think>推理</think>继续", "普通文本继续"),
        ],
    )
    def test_strips_paired_thinking_blocks(self, strip_thinking_tags, raw, expected):
        assert strip_thinking_tags(raw) == expected

    def test_keeps_visible_answer_after_thinking(self, strip_thinking_tags):
        raw = (
            "<think>用户可能在问天气</think>\n"
            "今天上海晴，气温 28°C。"
        )
        assert strip_thinking_tags(raw) == "\n今天上海晴，气温 28°C。"

    def test_strips_multiple_thinking_blocks(self, strip_thinking_tags):
        raw = "<think>第一段</think>正文<think>第二段</think>结尾"
        assert strip_thinking_tags(raw) == "正文结尾"

    def test_does_not_touch_tool_call_json(self, strip_thinking_tags):
        raw = '{"tool": "search", "args": {"q": "think about AI"}}'
        assert strip_thinking_tags(raw) == raw
