"""Tests for md_to_image — link extraction and auto_convert_text."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _ensure_package_hierarchy():
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
        ("hatsume.plugins.hatsume_plugin", PLUGIN_DIR),  # alias for relative imports
        ("hatsume.plugins.hatsume_plugin.utils", PLUGIN_DIR / "utils"),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


_ensure_package_hierarchy()


# ---- stub nonebot ------------------------------------------------------------

# Stub nonebot before importing md_to_image
_nonebot_mod = types.ModuleType("nonebot")
_nonebot_mod.require = MagicMock()

_nonebot_adapters = types.ModuleType("nonebot.adapters")
_nonebot_onebot = types.ModuleType("nonebot.adapters.onebot")
_nonebot_onebot_v11 = types.ModuleType("nonebot.adapters.onebot.v11")


class FakeMessageSegment:
    """Minimal stub for MessageSegment with text() and image() factories."""
    def __init__(self, type_: str, data: dict | str):
        self.type = type_
        self.data = data if isinstance(data, dict) else {"text": data}

    @classmethod
    def text(cls, text: str):
        return cls("text", text)

    @classmethod
    def image(cls, data: bytes | str):
        d = data if isinstance(data, str) else {"file": data}
        return cls("image", d)

    def __eq__(self, other):
        if not isinstance(other, FakeMessageSegment):
            return NotImplemented
        return self.type == other.type and self.data == other.data

    def __repr__(self):
        return f"FakeMessageSegment(type={self.type!r}, data={self.data!r})"


_nonebot_onebot_v11.MessageSegment = FakeMessageSegment

sys.modules["nonebot"] = _nonebot_mod
sys.modules["nonebot.adapters"] = _nonebot_adapters
sys.modules["nonebot.adapters.onebot"] = _nonebot_onebot
sys.modules["nonebot.adapters.onebot.v11"] = _nonebot_onebot_v11

# Stub nonebot_plugin_htmlrender
_htmlrender_mod = types.ModuleType("nonebot_plugin_htmlrender")
_htmlrender_mod.render_html = AsyncMock(return_value=b"fake_image_bytes")
sys.modules["nonebot_plugin_htmlrender"] = _htmlrender_mod

# Now load md_to_image — but first ensure config is properly loaded
# (other tests may have registered a bare stub without LONG_MSG_THRESHOLD)
_cfg_spec = importlib.util.spec_from_file_location(
    "hatsume.plugins.hatsume_plugin.config",
    PLUGIN_DIR / "config.py",
)
_cfg_mod = importlib.util.module_from_spec(_cfg_spec)
sys.modules["hatsume.plugins.hatsume_plugin.config"] = _cfg_mod
_cfg_spec.loader.exec_module(_cfg_mod)
# Also register under the hyphen form so everything is consistent
sys.modules.setdefault("hatsume.plugins.hatsume-plugin.config", _cfg_mod)

spec = importlib.util.spec_from_file_location(
    "hatsume.plugins.hatsume_plugin.utils.md_to_image",
    PLUGIN_DIR / "utils" / "md_to_image.py",
)
md_to_image_mod = importlib.util.module_from_spec(spec)
md_to_image_mod.__package__ = "hatsume.plugins.hatsume_plugin.utils"
sys.modules["hatsume.plugins.hatsume_plugin.utils.md_to_image"] = md_to_image_mod
spec.loader.exec_module(md_to_image_mod)

_extract_links = md_to_image_mod._extract_links
_format_links = md_to_image_mod._format_links
auto_convert_text = md_to_image_mod.auto_convert_text
LONG_MSG_THRESHOLD = md_to_image_mod.LONG_MSG_THRESHOLD


# ---- _extract_links tests ----------------------------------------------------

def test_extract_links_raw_urls():
    """Extract raw https?:// URLs from text."""
    result = _extract_links("Check https://example.com and http://foo.bar/page")
    assert result == ["https://example.com", "http://foo.bar/page"]


def test_extract_links_markdown_links():
    """Extract URLs from Markdown [label](url) syntax."""
    result = _extract_links(
        "See [GitHub](https://github.com) and [Docs](https://docs.python.org/3/)"
    )
    assert result == ["https://github.com", "https://docs.python.org/3/"]


def test_extract_links_mixed_raw_and_md():
    """Extract both raw URLs and Markdown link targets."""
    result = _extract_links(
        "Raw https://example.com and [link](https://github.com) mixed"
    )
    assert result == ["https://example.com", "https://github.com"]


def test_extract_links_deduplicates():
    """Duplicate URLs appear only once, first occurrence preserved."""
    result = _extract_links(
        "https://example.com and https://github.com and https://example.com"
    )
    assert result == ["https://example.com", "https://github.com"]


def test_extract_links_deduplicates_across_raw_and_md():
    """URL appearing as both raw and Markdown target is deduplicated."""
    result = _extract_links(
        "https://example.com and also [link](https://example.com)"
    )
    assert result == ["https://example.com"]


def test_extract_links_no_links():
    """Return empty list when no URLs found."""
    result = _extract_links("Hello, this has no links at all!")
    assert result == []


def test_extract_links_ignores_non_http_urls():
    """Only https?:// URLs are matched; ftp, www without protocol are ignored."""
    result = _extract_links("ftp://files.example.com www.example.com")
    assert result == []


def test_extract_links_empty_string():
    """Empty input returns empty list."""
    result = _extract_links("")
    assert result == []


def test_extract_links_markdown_link_with_special_chars():
    """Markdown links with query strings and fragments are extracted."""
    result = _extract_links(
        "[search](https://example.com/search?q=hello&lang=en#section)"
    )
    assert result == ["https://example.com/search?q=hello&lang=en#section"]


def test_extract_links_excludes_angle_brackets_and_fullwidth_punctuation():
    """URL delimiters and adjacent fullwidth punctuation are not extracted."""
    result = _extract_links(
        "链接：<https://example.com/a%20b?q=hello%20world&lang=zh#section>，下一条"
    )
    assert result == [
        "https://example.com/a%20b?q=hello%20world&lang=zh#section"
    ]


def test_extract_links_stops_before_adjacent_chinese_text():
    """Raw Chinese text immediately following a URL is not part of the URL."""
    result = _extract_links("查看 https://example.com/api/v1中文说明。")
    assert result == ["https://example.com/api/v1"]


def test_extract_links_urls_in_code_blocks():
    """URLs inside Markdown code blocks are still extracted."""
    result = _extract_links("```\nhttps://example.com/api\n```")
    assert result == ["https://example.com/api"]


# ---- _format_links tests -----------------------------------------------------

def test_format_links_single():
    result = _format_links(["https://example.com"])
    assert result == "LINKS\n\n1. https://example.com"


def test_format_links_multiple():
    result = _format_links([
        "https://example.com",
        "https://github.com",
        "https://docs.python.org",
    ])
    assert result == (
        "LINKS\n\n"
        "1. https://example.com\n"
        "2. https://github.com\n"
        "3. https://docs.python.org"
    )


def test_format_links_empty():
    result = _format_links([])
    assert result == ""


# ---- auto_convert_text integration tests -------------------------------------

@pytest.mark.asyncio
async def test_auto_convert_text_short_plain():
    """Short plain text returns [text_segment] — no image, no links."""
    msg = "x" * 10  # well under LONG_MSG_THRESHOLD
    result = await auto_convert_text(msg)
    assert len(result) == 1
    assert result[0].type == "text"
    assert "LINKS" not in result[0].data.get("text", "")


@pytest.mark.asyncio
async def test_auto_convert_text_long_with_links():
    """Long text triggers image rendering + LINKS follow-up with URLs."""
    links_line = "See https://example.com and [GitHub](https://github.com)"
    msg = "x" * (LONG_MSG_THRESHOLD + 1) + "\n" + links_line
    result = await auto_convert_text(msg)
    assert len(result) == 2
    assert result[0].type == "image"
    assert result[1].type == "text"
    text_data = result[1].data.get("text", "")
    assert "LINKS" in text_data
    assert "1. https://example.com" in text_data
    assert "2. https://github.com" in text_data


@pytest.mark.asyncio
async def test_auto_convert_text_long_no_links():
    """Long text without links renders as image only, no LINKS segment."""
    msg = "x" * (LONG_MSG_THRESHOLD + 1)
    result = await auto_convert_text(msg)
    assert len(result) == 1
    assert result[0].type == "image"


@pytest.mark.asyncio
async def test_auto_convert_text_short_with_md_features_and_links():
    """Short text with Markdown features + links → image + LINKS."""
    msg = "```python\nprint(1)\n```\nSee https://docs.python.org"
    result = await auto_convert_text(msg)
    assert len(result) == 2
    assert result[0].type == "image"
    assert result[1].type == "text"
    assert "https://docs.python.org" in result[1].data.get("text", "")


@pytest.mark.asyncio
async def test_auto_convert_text_short_markdown_table():
    """A short Markdown table renders as an image regardless of length."""
    msg = "| Name | Score |\n| :--- | ---: |\n| Hatsume | 100 |"
    result = await auto_convert_text(msg)
    assert len(result) == 1
    assert result[0].type == "image"


@pytest.mark.asyncio
async def test_auto_convert_text_short_pipe_text_stays_text():
    """A pipe without a Markdown table separator does not force rendering."""
    msg = "Choose tea | coffee"
    result = await auto_convert_text(msg)
    assert len(result) == 1
    assert result[0].type == "text"


@pytest.mark.asyncio
async def test_auto_convert_text_latex_with_link():
    """LaTeX math triggers image rendering; link is extracted."""
    msg = "$$x^2$$ Check https://example.com"
    result = await auto_convert_text(msg)
    assert result[0].type == "image"
    assert any(
        seg.type == "text" and "https://example.com" in seg.data.get("text", "")
        for seg in result
    )
