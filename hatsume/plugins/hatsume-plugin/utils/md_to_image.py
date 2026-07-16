"""Utility: automatically convert long text messages to images.

Uses ``nonebot_plugin_htmlrender``'s ``render_html`` with inlined CSS,
bypassing a Jinja2 autoescape bug in its ``render_markdown`` template.
"""

from __future__ import annotations

import base64
import random
import re
import traceback
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import markdown
from nonebot import require
from nonebot.adapters.onebot.v11 import MessageSegment

from ..config import LONG_MSG_THRESHOLD

require("nonebot_plugin_htmlrender")
from nonebot_plugin_htmlrender import render_html  # noqa: E402

if TYPE_CHECKING:
    pass

# ---- CSS / template assets (lazy-loaded & cached) --------------------------

_PACKAGE_TEMPLATES: Path | None = None


def _get_templates_dir() -> Path:
    """Resolve the markdown templates directory inside the installed package."""
    global _PACKAGE_TEMPLATES
    if _PACKAGE_TEMPLATES is None:
        htmlrender = import_module("nonebot_plugin_htmlrender")
        if htmlrender.__file__ is None:
            raise RuntimeError("nonebot_plugin_htmlrender package has no __file__")
        _PACKAGE_TEMPLATES = (
            Path(htmlrender.__file__).resolve().parent / "templates" / "markdown"
        )
    return _PACKAGE_TEMPLATES


# ---- data directory resolution ----------------------------------------------

_DATA_DIR: Path | None = None


def _get_data_dir() -> Path:
    """Resolve the hatsume-plugin data directory (data/hatsume-plugin/)."""
    global _DATA_DIR
    if _DATA_DIR is None:
        # md_to_image.py is at hatsume/plugins/hatsume-plugin/utils/md_to_image.py
        # data/ is at the project root
        _DATA_DIR = (
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "data" / "hatsume-plugin"
        )
    return _DATA_DIR


# ---- dark mode --------------------------------------------------------------


def _is_dark_mode() -> bool:
    """Return True during nighttime hours (22:00–04:00)."""
    hour = datetime.now().hour
    return hour >= 22 or hour < 4


_DARK_MODE_CSS = """
body{background-color:#1a1418}
.markdown-body{background-color:#2d1f28;color:#d8cdd2}
.markdown-body h1,.markdown-body h2{color:#f0a0b8;border-bottom-color:#3d2a35}
.markdown-body h3,.markdown-body h4{color:#d8cdd2}
.markdown-body h5,.markdown-body h6{color:#b0a0a8}
.markdown-body a{color:#f0a0b8}
.markdown-body a:hover{color:#f5c0d0}
.markdown-body strong,.markdown-body b{color:#e8dde2}
.markdown-body blockquote{background-color:#241720;color:#b0a0a8;border-left-color:#d4456a}
.markdown-body hr::before{color:#f0a0b8}
.markdown-body hr{border-bottom-color:#3d2a35;background-color:#3d2a35}
.markdown-body code,.markdown-body tt{background-color:#3d2535;color:#f0a0b8}
.markdown-body kbd{background-color:#2d1f2a;color:#d8cdd2;border-color:#3d2a35;box-shadow:inset 0 -1px 0 #3d2a35}
.markdown-body table tr{background-color:#2d1f28;border-top-color:#3d2a35}
.markdown-body table tr:nth-child(2n){background-color:#261a24}
.markdown-body table tr:first-child{background-color:#2d1f2a}
.markdown-body table td,.markdown-body table th{border-color:#3d2a35}
.markdown-body table th{color:#f0a0b8}
.markdown-body .footnotes{color:#b0a0a8;border-top-color:#3d2a35}
.markdown-body .footnotes li:target{color:#d8cdd2}
.markdown-body dl dt{color:#d8cdd2}
.markdown-body .absent{color:#f0a0b8}
.markdown-body .hatsume-stamp{background:#5e3e52;border-color:#b678a0;box-shadow:2px 4px 16px rgba(0,0,0,0.3),0 0 0 0}
.markdown-body .hatsume-stamp span{color:#b0a0a8}
.markdown-body .pl-c{color:#908088}
.markdown-body .pl-ent{color:#8cc0a0}
.markdown-body .pl-k{color:#f0a0b8}
.markdown-body .pl-s,.markdown-body .pl-pds,.markdown-body .pl-sr{color:#e6b899}
.markdown-body .pl-c1,.markdown-body .pl-s .pl-v{color:#d4a0c0}
.markdown-body .pl-e,.markdown-body .pl-en{color:#f0a0b8}
.markdown-body .pl-v,.markdown-body .pl-smw{color:#d4a0c0}
.katex{color:#d8cdd2}
.katex .mathnormal,.katex .mord{color:#d8cdd2}
"""


# ---- markdown feature detection -----------------------------------------------

# Patterns that indicate rich Markdown formatting — when any of these are found
# in a message, it should be rendered as an image even if the text is short.
_MD_FEATURE_PATTERN = re.compile(
    r"```"              # fenced code blocks (triple backtick)
    r"|^#{1,6}\s"       # ATX headers (#, ##, ###, …)
    r"|\$\$"            # display LaTeX $$…$$
    r"|\$[^$]+\$"       # inline LaTeX $…$
    r"|\*\*[^*]+\*\*"   # bold **text**
    , re.MULTILINE,
)


def _has_md_features(text: str) -> bool:
    """Return True if *text* contains rich Markdown formatting."""
    return bool(_MD_FEATURE_PATTERN.search(text))


# ---- link extraction ---------------------------------------------------------

# Regex to match raw URLs (https?:// followed by non-whitespace)
_LINK_PATTERN = re.compile(r"https?://\S+")


def _extract_links(text: str) -> list[str]:
    """Extract all URLs from *text*.

    Matches both raw URLs (``https?://...``) and Markdown link targets
    (``[label](url)``).  Returns a deduplicated, order-preserving list.
    Returns an empty list if no links are found.

    First replaces each ``[label](url)`` with the bare URL, then extracts
    all ``https?://`` URLs in a single pass — preserving original order.
    """
    # Replace Markdown links [label](url) → url so both are found in one pass
    unified = re.sub(
        r"\[([^\]]*)\]\(((?:https?://)[^\)]+)\)",
        r"\2",
        text,
    )
    # Extract all URLs in order of appearance, deduplicate
    return list(dict.fromkeys(_LINK_PATTERN.findall(unified)))


def _format_links(links: list[str]) -> str:
    """Format a list of URLs as a numbered list under a LINKS header.

    Returns an empty string when *links* is empty.
    """
    if not links:
        return ""
    lines = ["LINKS", ""]
    for i, url in enumerate(links, start=1):
        lines.append(f"{i}. {url}")
    return "\n".join(lines)


# ---- random face selection ---------------------------------------------------


async def _get_random_face_b64() -> str | None:
    """Pick a random face PNG, return base64 data URI.

    Returns None if the faces directory is empty or missing.
    Each call selects a fresh random face for visual variety.
    """
    faces_dir = _get_data_dir() / "faces"
    if not faces_dir.is_dir():
        return None

    pngs = list(
        f for f in faces_dir.iterdir()
        if f.suffix.lower() == ".png"
    )
    if not pngs:
        return None

    chosen = random.choice(pngs)
    try:
        f = await anyio.open_file(str(chosen), mode="rb")
        async with f:
            content = await f.read()
        b64 = base64.b64encode(content).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


_cached_css: str | None = None
_cached_katex: tuple[str, str, str, str] | None = None  # css, js, mhchem, mathtex


async def _read(path: str | Path) -> str:
    """Async file read helper."""
    f = await anyio.open_file(str(path), mode="r", encoding="utf-8")
    async with f:
        return await f.read()


async def _get_css() -> str:
    """Load CSS — prefer sakura theme from data/, fallback to package defaults."""
    global _cached_css
    if _cached_css is None:
        data_dir = _get_data_dir()
        sakura_md = data_dir / "sakura-markdown.css"
        sakura_pyg = data_dir / "sakura-pygments.css"

        if sakura_md.exists() and sakura_pyg.exists():
            md_css = await _read(sakura_md)
            pyg_css = await _read(sakura_pyg)
            _cached_css = md_css + pyg_css
        else:
            # Fallback to package defaults
            tmpl = _get_templates_dir()
            github_css = await _read(tmpl / "github-markdown-light.css")
            pygments_css = await _read(tmpl / "pygments-default.css")
            _cached_css = github_css + pygments_css
    return _cached_css


async def _get_katex() -> tuple[str, str, str, str] | None:
    """Load & cache KaTeX assets for math rendering. Returns None if not found."""
    global _cached_katex
    if _cached_katex is None:
        try:
            tmpl = _get_templates_dir()
            css = await _read(tmpl / "katex/katex.min.b64_fonts.css")
            js = await _read(tmpl / "katex/katex.min.js")
            mhchem = await _read(tmpl / "katex/mhchem.min.js")
            mathtex = await _read(tmpl / "katex/mathtex-script-type.min.js")
            _cached_katex = (css, js, mhchem, mathtex)
        except Exception:
            _cached_katex = False  # type: ignore[assignment]
    return _cached_katex if _cached_katex and _cached_katex is not False else None


# ---- Markdown → image -------------------------------------------------------

_MD_EXTENSIONS = [
    "pymdownx.tasklist",
    "tables",
    "fenced_code",
    "codehilite",
    "mdx_math",
    "pymdownx.tilde",
]

_MD_EXTENSION_CONFIGS = {"mdx_math": {"enable_dollar_delimiter": True}}


async def _markdown_to_html(md_text: str) -> str:
    """Convert Markdown to a self-contained HTML page ready for ``render_html``."""
    html_body = markdown.markdown(
        md_text,
        extensions=_MD_EXTENSIONS,
        extension_configs=_MD_EXTENSION_CONFIGS,
    )

    needs_katex = "math/tex" in html_body
    css = await _get_css()

    extra = ""
    if needs_katex:
        katex = await _get_katex()
        if katex:
            katex_css, katex_js, mhchem_js, mathtex_js = katex
            extra = (
                f'<style type="text/css">{katex_css}</style>'
                f"<script defer>{katex_js}</script>"
                f"<script defer>{mhchem_js}</script>"
                f"<script defer>{mathtex_js}</script>"
            )

    # ---- Build stamp footer ----
    stamp_html = ""
    face_b64 = await _get_random_face_b64()
    if face_b64:
        stamp_html = (
            '<div class="hatsume-stamp">'
            f'<img src="{face_b64}" alt="初芽" />'
            "<span>— 初芽 —</span>"
            "</div>"
        )

    page = (
        '<!DOCTYPE html><html>'
        '<head>'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta charset="utf-8">'
        f"<style>{css}</style>"
        "<style>"
        ".markdown-body{box-sizing:border-box;min-width:200px;"
        "max-width:980px;margin:48px;padding:45px}"
        + (_DARK_MODE_CSS if _is_dark_mode() else "") +
        "</style>"
        "</head>"
        "<body>"
        f'<article class="markdown-body">{html_body}{stamp_html}</article>'
        "</body>"
        f"{extra}"
        "</html>"
    )
    return page


# ---- Public API -------------------------------------------------------------


async def auto_convert_text(text: str) -> list[MessageSegment]:
    """Convert text to one or more MessageSegments.

    Triggers image rendering when **any** of these conditions are met:

    - Length exceeds ``LONG_MSG_THRESHOLD``.
    - Contains rich Markdown: fenced code blocks (`` ``` ``), ATX headers
      (``# …``), LaTeX math (``$…$`` / ``$$…$$``), or bold (``**…**``).

    When rendering as an image, any URLs found in the original text are
    extracted and appended as a separate text segment so they remain
    clickable in the QQ client.

    Returns ``[MessageSegment.text(text)]`` for plain text.  On any
    exception the function silently falls back to plain text.

    Args:
        text: The message text (may contain Markdown formatting).

    Returns:
        A ``list[MessageSegment]`` — one or more segments to send.
    """
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff]",
        flags=re.UNICODE
    )
    
    text = emoji_pattern.sub("", text)
    if len(text) <= LONG_MSG_THRESHOLD and not _has_md_features(text):
        return [MessageSegment.text(text)]
    try:
        html_page = await _markdown_to_html(text)
        img_bytes = await render_html(html_page, full_page=True)
        segments: list[MessageSegment] = [MessageSegment.image(img_bytes)]
        links = _extract_links(text)
        if links:
            segments.append(MessageSegment.text(_format_links(links)))
        return segments
    except Exception:
        traceback.print_exc()
        return [MessageSegment.text(text)]
