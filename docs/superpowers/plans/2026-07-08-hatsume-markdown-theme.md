# 初芽·樱 Markdown Theme — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace default GitHub markdown CSS with a warm "sakura" theme matching 初芽's character personality, with random face stamps.

**Architecture:** Two CSS files (markdown body + pygments code highlighting) placed in `data/hatsume-plugin/`, loaded preferentially over package defaults. A random face PNG from `data/hatsume-plugin/faces/` is base64-embedded as a stamp component in the rendered HTML footer.

**Tech Stack:** Python 3.12+, CSS3, `nonebot_plugin_htmlrender`, `markdown` (py3), `anyio`

## Global Constraints

- All CSS selectors from `github-markdown-light.css` and `pygments-default.css` MUST be preserved with matching specificity
- New CSS files go in `data/hatsume-plugin/` — must NOT be committed to the Python package
- Face images stay in `data/hatsume-plugin/faces/` — no copying, base64-encode at render time
- Graceful fallback: if custom CSS files are missing, silently use package defaults
- No new Python dependencies
- Existing behavior unchanged when custom CSS is absent

---

### Task 1: Create `sakura-pygments.css` — Code Syntax Highlighting

**Files:**
- Create: `data/hatsume-plugin/sakura-pygments.css`

**Interfaces:**
- Produces: CSS file with all `.codehilite .xx` token classes, loaded by `_get_css()` in md_to_image.py
- Must cover all 41 pygments token classes from pygments-default.css

- [ ] **Step 1: Write the CSS file**

```css
/* 初芽·樱 — Code Syntax Highlighting Theme */
/* Dark warm background with sakura-tinted tokens */

.codehilite { background: #2b2428; color: #e8d8dd; }
.codehilite .hll { background-color: #3d2e35; }

/* Comment — muted mauve, italic */
.codehilite .c   { color: #8a7a82; font-style: italic; }
.codehilite .ch  { color: #8a7a82; font-style: italic; }
.codehilite .cm  { color: #8a7a82; font-style: italic; }
.codehilite .cp  { color: #b8908a; }
.codehilite .cpf { color: #8a7a82; font-style: italic; }
.codehilite .c1  { color: #8a7a82; font-style: italic; }
.codehilite .cs  { color: #8a7a82; font-style: italic; }

/* Error */
.codehilite .err { border: 1px solid #ff6b8a; color: #ff8fa0; }

/* Keyword — sakura pink */
.codehilite .k  { color: #f0a0b8; font-weight: bold; }
.codehilite .kc { color: #f0a0b8; font-weight: bold; }
.codehilite .kd { color: #f0a0b8; font-weight: bold; }
.codehilite .kn { color: #f0a0b8; font-weight: bold; }
.codehilite .kp { color: #e090a8; }
.codehilite .kr { color: #f0a0b8; font-weight: bold; }
.codehilite .kt { color: #e090a8; }

/* Operator */
.codehilite .o  { color: #c0a8b8; }
.codehilite .ow { color: #d0b0c0; font-weight: bold; }

/* Literal.Number — soft lavender */
.codehilite .m  { color: #d4a0c0; }
.codehilite .mb { color: #d4a0c0; }
.codehilite .mf { color: #d4a0c0; }
.codehilite .mh { color: #d4a0c0; }
.codehilite .mi { color: #d4a0c0; }
.codehilite .mo { color: #d4a0c0; }
.codehilite .il { color: #d4a0c0; }

/* Literal.String — warm peach */
.codehilite .s  { color: #e6b899; }
.codehilite .sa { color: #e6b899; }
.codehilite .sb { color: #e6b899; }
.codehilite .sc { color: #e6b899; }
.codehilite .dl { color: #e6b899; }
.codehilite .sd { color: #e6b899; font-style: italic; }
.codehilite .s2 { color: #e6b899; }
.codehilite .se { color: #f0c0a0; font-weight: bold; }
.codehilite .sh { color: #e6b899; }
.codehilite .si { color: #e8a8c0; }
.codehilite .sx { color: #e6b899; }
.codehilite .sr { color: #e8a8c0; }
.codehilite .s1 { color: #e6b899; }
.codehilite .ss { color: #d4a0c0; }

/* Name — varied warm tones */
.codehilite .na { color: #c8b090; }
.codehilite .nb { color: #d4a0c0; }
.codehilite .nc { color: #f5c080; font-weight: bold; }
.codehilite .no { color: #e09090; }
.codehilite .nd { color: #e0a0c0; }
.codehilite .ni { color: #d0b8c8; font-weight: bold; }
.codehilite .ne { color: #e88090; font-weight: bold; }
.codehilite .nf { color: #e6678a; }
.codehilite .nl { color: #c8b090; }
.codehilite .nn { color: #f5c080; font-weight: bold; }
.codehilite .nt { color: #f0a0b8; font-weight: bold; }
.codehilite .nv { color: #d4a0c0; }
.codehilite .bp { color: #d4a0c0; }
.codehilite .fm { color: #e6678a; }
.codehilite .vc { color: #d4a0c0; }
.codehilite .vg { color: #d4a0c0; }
.codehilite .vi { color: #d4a0c0; }
.codehilite .vm { color: #d4a0c0; }

/* Generic */
.codehilite .gd { color: #ff8fa0; background-color: #3d2028; }
.codehilite .ge { font-style: italic; }
.codehilite .gr { color: #ff6b8a; }
.codehilite .gh { color: #f0a0b8; font-weight: bold; }
.codehilite .gi { color: #8cc0a0; background-color: #1d2d25; }
.codehilite .go { color: #8a7a82; }
.codehilite .gp { color: #e090a8; font-weight: bold; }
.codehilite .gs { font-weight: bold; }
.codehilite .gu { color: #e0a0c0; font-weight: bold; }
.codehilite .gt { color: #e88090; }

/* Text.Whitespace */
.codehilite .w { color: #4a3540; }

/* Line numbers */
pre { line-height: 125%; }
td.linenos .normal { color: inherit; background-color: transparent; padding-left: 5px; padding-right: 5px; }
span.linenos { color: inherit; background-color: transparent; padding-left: 5px; padding-right: 5px; }
td.linenos .special { color: #e8d8dd; background-color: #3d2e35; padding-left: 5px; padding-right: 5px; }
span.linenos.special { color: #e8d8dd; background-color: #3d2e35; padding-left: 5px; padding-right: 5px; }
```

- [ ] **Step 2: Verify file was created correctly**

Run: `wc -l data/hatsume-plugin/sakura-pygments.css`
Expected: ~80-90 lines, covers all codehilite token classes

- [ ] **Step 3: Commit**

```bash
git add data/hatsume-plugin/sakura-pygments.css
git commit -m "feat: add sakura-pygments.css — warm-token code highlighting theme"
```

---

### Task 2: Create `sakura-markdown.css` — Main Markdown Theme

**Files:**
- Create: `data/hatsume-plugin/sakura-markdown.css`

**Interfaces:**
- Produces: CSS file with all `.markdown-body` selectors from github-markdown-light.css, plus `.hatsume-stamp` component
- Must maintain CSS selector compatibility with markdown.py output (codehilite wrapper, task-list-item, footnotes, etc.)

- [ ] **Step 1: Write the CSS file**

This file is ~900 lines. See the complete CSS in the appendix below.

- [ ] **Step 2: Verify file was created**

Run: `wc -l data/hatsume-plugin/sakura-markdown.css`
Expected: ~850-950 lines

Run: `grep -c "markdown-body" data/hatsume-plugin/sakura-markdown.css`
Expected: many matches (all selector scoping)

Run: `grep ".hatsume-stamp" data/hatsume-plugin/sakura-markdown.css`
Expected: stamp component styles present

- [ ] **Step 3: Commit**

```bash
git add data/hatsume-plugin/sakura-markdown.css
git commit -m "feat: add sakura-markdown.css — 初芽·樱 warm markdown theme"
```

---

### Task 3: Modify `md_to_image.py` — Integration & Face Injection

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/utils/md_to_image.py`

**Interfaces:**
- Consumes: `sakura-markdown.css`, `sakura-pygments.css` from `data/hatsume-plugin/`
- Consumes: `data/hatsume-plugin/faces/*.png` for random face selection
- Produces: modified `_get_css()` with fallback logic, new `_get_random_face_b64()`, stamp HTML injected in `_markdown_to_html()`

- [ ] **Step 1: Add new imports**

Add `base64` and `os` to imports (base64 for encoding, os for random selection via path operations — actually `random` is better, add `random`):

```python
# Existing imports (keep all):
from __future__ import annotations

import base64
import random
import traceback
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
```

- [ ] **Step 2: Add `_get_data_dir()` function**

Insert after `_PACKAGE_TEMPLATES` / `_get_templates_dir()` section:

```python
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
```

- [ ] **Step 3: Add `_get_random_face_b64()` function**

Insert after `_get_data_dir()`:

```python
# ---- random face selection ---------------------------------------------------

_cached_face_b64: str | None = None  # session-level cache


async def _get_random_face_b64() -> str | None:
    """Pick a random face PNG, return base64 data URI.

    Returns None if the faces directory is empty or missing.
    Cached at session level — subsequent calls within the same
    Python process return the same face for visual consistency.
    """
    global _cached_face_b64
    if _cached_face_b64 is not None:
        return _cached_face_b64

    faces_dir = _get_data_dir() / "faces"
    if not faces_dir.is_dir():
        return None

    pngs = sorted(
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
        _cached_face_b64 = f"data:image/png;base64,{b64}"
    except Exception:
        return None

    return _cached_face_b64
```

- [ ] **Step 4: Modify `_get_css()` to support custom CSS with fallback**

Replace the existing `_get_css()` function:

```python
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
```

- [ ] **Step 5: Modify `_markdown_to_html()` to inject stamp HTML**

In the `_markdown_to_html()` function, add stamp HTML injection. The stamp goes inside the `markdown-body` article, after the rendered `html_body`:

```python
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
        "max-width:980px;margin:0 auto;padding:45px}"
        "@media(max-width:767px){.markdown-body{padding:15px}}"
        "</style>"
        "</head>"
        "<body>"
        f'<article class="markdown-body">{html_body}{stamp_html}</article>'
        "</body>"
        f"{extra}"
        "</html>"
    )
    return page
```

- [ ] **Step 6: Verify the modified file is syntactically valid**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/utils/md_to_image.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 7: Run existing tests to ensure no regressions**

Run: `python -m pytest tests/ -x -q --ignore=tests/test_tools.py --ignore=tests/test_graph_nodes.py -k "md_to_image or markdown or image or msg" 2>&1 | head -20`

(If no specific tests exist for md_to_image, a general smoketest is sufficient.)

- [ ] **Step 8: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/utils/md_to_image.py
git commit -m "feat: integrate sakura CSS theme + random face stamp into md_to_image"
```

---

### Task 4: End-to-End Verification

**Files:**
- (No new files — verification-only task)

- [ ] **Step 1: Verify CSS files are present and well-formed**

```bash
echo "=== sakura-markdown.css ===" && \
wc -l data/hatsume-plugin/sakura-markdown.css && \
grep -c "{" data/hatsume-plugin/sakura-markdown.css && echo "rules found" && \
echo "=== sakura-pygments.css ===" && \
wc -l data/hatsume-plugin/sakura-pygments.css && \
grep -c ".codehilite" data/hatsume-plugin/sakura-pygments.css && echo "codehilite rules found"
```

- [ ] **Step 2: Verify Python module imports correctly**

```bash
cd /path/to/hatsume && \
python -c "
from hatsume.plugins.hatsume_plugin.utils.md_to_image import (
    _get_data_dir, _get_random_face_b64, _get_css, _markdown_to_html, auto_convert_text
)
print('All imports OK')
print('data dir:', _get_data_dir())
"
```

- [ ] **Step 3: Verify face resolution works**

```bash
cd /path/to/hatsume && \
python -c "
import asyncio
from hatsume.plugins.hatsume_plugin.utils.md_to_image import _get_random_face_b64, _get_data_dir
print('faces dir:', _get_data_dir() / 'faces')
b64 = asyncio.run(_get_random_face_b64())
print('face b64 length:', len(b64) if b64 else 'None')
print('starts with data:image:', b64[:30] if b64 else 'N/A')
"
```

- [ ] **Step 4: Commit final state**

```bash
git add data/hatsume-plugin/sakura-markdown.css data/hatsume-plugin/sakura-pygments.css
git add hatsume/plugins/hatsume-plugin/utils/md_to_image.py
git commit -m "feat: complete 初芽·樱 markdown theme with face stamp integration"
```

---

## Appendix: Complete `sakura-markdown.css`

This appendix contains the full CSS for Task 2, Step 1. The file is large (~900 lines) because it must cover every selector from `github-markdown-light.css` while applying the sakura color palette.

```css
/* ═══════════════════════════════════════════════════════════════════════════
   初芽·樱 — Markdown Theme
   
   A warm sakura-inspired theme for 初芽 (Hatsume).
   Red ponytail → rose accents. JK uniform → dark contrast.
   Blushes easily → soft pink tones. "Thorny little sun" → warm but crisp.
   
   Preserves all selectors from github-markdown-light.css for compatibility
   with Python markdown's codehilite + tasklist + footnotes extensions.
   ═══════════════════════════════════════════════════════════════════════════ */

/* ---- Base & Reset -------------------------------------------------------- */

.markdown-body {
  -ms-text-size-adjust: 100%;
  -webkit-text-size-adjust: 100%;
  margin: 0;
  color: #4a3340;
  background-color: #fef9f6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica, Arial,
    sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
  font-size: 16px;
  line-height: 1.6;
  word-wrap: break-word;
}

.markdown-body .octicon {
  display: inline-block;
  fill: currentColor;
  vertical-align: text-bottom;
}

.markdown-body h1:hover .anchor .octicon-link:before,
.markdown-body h2:hover .anchor .octicon-link:before,
.markdown-body h3:hover .anchor .octicon-link:before,
.markdown-body h4:hover .anchor .octicon-link:before,
.markdown-body h5:hover .anchor .octicon-link:before,
.markdown-body h6:hover .anchor .octicon-link:before {
  width: 16px;
  height: 16px;
  content: ' ';
  display: inline-block;
  background-color: currentColor;
}

.markdown-body details,
.markdown-body figcaption,
.markdown-body figure {
  display: block;
}

.markdown-body summary {
  display: list-item;
}

.markdown-body [hidden] {
  display: none !important;
}

/* ---- Links --------------------------------------------------------------- */

.markdown-body a {
  background-color: transparent;
  color: #e6678a;
  text-decoration: none;
  transition: color 0.15s ease;
}

.markdown-body a:active,
.markdown-body a:hover {
  outline-width: 0;
}

.markdown-body a:hover {
  color: #d4456a;
  text-decoration: underline;
}

.markdown-body a:not([href]) {
  color: inherit;
  text-decoration: none;
}

/* ---- Typography ---------------------------------------------------------- */

.markdown-body abbr[title] {
  border-bottom: none;
  text-decoration: underline dotted;
}

.markdown-body b,
.markdown-body strong {
  font-weight: 600;
  color: #3d2a35;
}

.markdown-body dfn {
  font-style: italic;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  margin-top: 28px;
  margin-bottom: 18px;
  font-weight: 600;
  line-height: 1.3;
}

.markdown-body h1 {
  margin: 0.67em 0;
  padding-bottom: 0.35em;
  font-size: 2em;
  color: #d4456a;
  border-bottom: 2px solid #f5e8ec;
}

.markdown-body h2 {
  padding-bottom: 0.3em;
  font-size: 1.5em;
  color: #d4456a;
  border-bottom: 1.5px solid #f5e8ec;
}

.markdown-body h3 {
  font-size: 1.25em;
  color: #4a3340;
}

.markdown-body h4 {
  font-size: 1em;
  color: #4a3340;
}

.markdown-body h5 {
  font-size: 0.875em;
  color: #7a5a6a;
}

.markdown-body h6 {
  font-size: 0.85em;
  color: #7a5a6a;
  font-style: italic;
}

.markdown-body mark {
  background-color: #fff0e8;
  color: #4a3340;
  padding: 0.1em 0.2em;
  border-radius: 3px;
}

.markdown-body small {
  font-size: 90%;
  color: #7a5a6a;
}

.markdown-body sub,
.markdown-body sup {
  font-size: 75%;
  line-height: 0;
  position: relative;
  vertical-align: baseline;
}

.markdown-body sub {
  bottom: -0.25em;
}

.markdown-body sup {
  top: -0.5em;
}

.markdown-body p {
  margin-top: 0;
  margin-bottom: 12px;
}

/* ---- Images -------------------------------------------------------------- */

.markdown-body img {
  border-style: none;
  max-width: 100%;
  box-sizing: content-box;
  border-radius: 8px;
}

.markdown-body img[align="right"] {
  padding-left: 20px;
}

.markdown-body img[align="left"] {
  padding-right: 20px;
}

/* ---- Horizontal Rule — decorative --------------------------------------- */

.markdown-body hr {
  box-sizing: content-box;
  overflow: hidden;
  height: 0.25em;
  padding: 0;
  margin: 28px 0;
  background: transparent;
  border: 0;
  position: relative;
}

.markdown-body hr::before {
  content: "— ♡ —";
  display: block;
  text-align: center;
  color: #e6678a;
  font-size: 14px;
  letter-spacing: 4px;
}

.markdown-body hr::after {
  display: none;
}

/* ---- Code (inline) ------------------------------------------------------- */

.markdown-body code,
.markdown-body kbd,
.markdown-body pre,
.markdown-body samp {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", "Fira Code", monospace;
  font-size: 1em;
}

.markdown-body tt,
.markdown-body code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", "Fira Code", monospace;
  font-size: 85%;
  padding: 0.2em 0.45em;
  margin: 0;
  background-color: #fdf0f3;
  color: #b83852;
  border-radius: 4px;
}

.markdown-body code br,
.markdown-body tt br {
  display: none;
}

.markdown-body del code {
  text-decoration: inherit;
}

.markdown-body pre code {
  font-size: 100%;
}

.markdown-body pre > code {
  padding: 0;
  margin: 0;
  word-break: normal;
  white-space: pre;
  background: transparent;
  border: 0;
  color: inherit;
}

/* ---- Code Blocks --------------------------------------------------------- */

.markdown-body .highlight {
  margin-bottom: 18px;
}

.markdown-body .highlight pre {
  margin-bottom: 0;
  word-break: normal;
}

.markdown-body .highlight pre,
.markdown-body pre {
  padding: 18px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.5;
  background-color: #2b2428;
  color: #e8d8dd;
  border-radius: 8px;
  border: 1px solid #3d343a;
}

.markdown-body pre code,
.markdown-body pre tt {
  display: inline;
  max-width: auto;
  padding: 0;
  margin: 0;
  overflow: visible;
  line-height: inherit;
  word-wrap: normal;
  background-color: transparent;
  border: 0;
  color: inherit;
}

/* ---- Keyboard ------------------------------------------------------------ */

.markdown-body kbd {
  display: inline-block;
  padding: 3px 6px;
  font: 11px ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", monospace;
  line-height: 10px;
  color: #4a3340;
  vertical-align: middle;
  background-color: #fdf2f5;
  border: solid 1px #edd4dc;
  border-bottom-color: #dcc4cc;
  border-radius: 5px;
  box-shadow: inset 0 -1px 0 #edd4dc;
}

/* ---- Blockquotes — letter-like ------------------------------------------- */

.markdown-body blockquote {
  margin: 0 0 18px 0;
  padding: 12px 18px;
  color: #7a5a6a;
  background-color: #fef7f9;
  border-left: 4px solid #e6678a;
  border-radius: 0 8px 8px 0;
}

.markdown-body blockquote > :first-child {
  margin-top: 0;
}

.markdown-body blockquote > :last-child {
  margin-bottom: 0;
}

/* ---- Lists --------------------------------------------------------------- */

.markdown-body ul,
.markdown-body ol {
  margin-top: 0;
  margin-bottom: 0;
  padding-left: 2em;
}

.markdown-body ol ol,
.markdown-body ul ol {
  list-style-type: lower-roman;
}

.markdown-body ul ul ol,
.markdown-body ul ol ol,
.markdown-body ol ul ol,
.markdown-body ol ol ol {
  list-style-type: lower-alpha;
}

.markdown-body ul ul,
.markdown-body ul ol,
.markdown-body ol ol,
.markdown-body ol ul {
  margin-top: 0;
  margin-bottom: 0;
}

.markdown-body ul.no-list,
.markdown-body ol.no-list {
  padding: 0;
  list-style-type: none;
}

.markdown-body ol[type="1"] {
  list-style-type: decimal;
}

.markdown-body ol[type="a"] {
  list-style-type: lower-alpha;
}

.markdown-body ol[type="i"] {
  list-style-type: lower-roman;
}

.markdown-body div > ol:not([type]) {
  list-style-type: decimal;
}

.markdown-body li > p {
  margin-top: 16px;
}

.markdown-body li + li {
  margin-top: 0.25em;
}

.markdown-body dl {
  padding: 0;
}

.markdown-body dl dt {
  padding: 0;
  margin-top: 16px;
  font-size: 1em;
  font-style: italic;
  font-weight: 600;
  color: #4a3340;
}

.markdown-body dl dd {
  padding: 0 16px;
  margin-bottom: 16px;
  margin-left: 0;
}

/* ---- Tables — soft and rounded ------------------------------------------- */

.markdown-body table {
  border-spacing: 0;
  border-collapse: collapse;
  display: block;
  width: max-content;
  max-width: 100%;
  overflow: auto;
  margin-bottom: 18px;
  border-radius: 8px;
  box-shadow: 0 0 0 1px #edd4dc; /* border via shadow for rounded tables */
}

.markdown-body table th {
  font-weight: 600;
  color: #d4456a;
}

.markdown-body table th,
.markdown-body table td {
  padding: 8px 16px;
  border: 1px solid #edd4dc;
}

.markdown-body table tr {
  background-color: #fef9f6;
  border-top: 1px solid #edd4dc;
}

.markdown-body table tr:nth-child(2n) {
  background-color: #fef5f8;
}

.markdown-body table tr:first-child {
  background-color: #fdf2f5;
}

.markdown-body table img {
  background-color: transparent;
}

/* ---- Task Lists ---------------------------------------------------------- */

.markdown-body .task-list-item {
  list-style-type: none;
}

.markdown-body .task-list-item label {
  font-weight: 400;
}

.markdown-body .task-list-item.enabled label {
  cursor: pointer;
}

.markdown-body .task-list-item + .task-list-item {
  margin-top: 3px;
}

.markdown-body .task-list-item .handle {
  display: none;
}

.markdown-body .task-list-item-checkbox {
  margin: 0 0.2em 0.25em -1.6em;
  vertical-align: middle;
  accent-color: #d4456a;
}

.markdown-body
  .contains-task-list:dir(rtl)
  .task-list-item-checkbox {
  margin: 0 -1.6em 0.25em 0.2em;
}

/* ---- Footnotes ----------------------------------------------------------- */

.markdown-body .footnotes {
  font-size: 13px;
  color: #7a5a6a;
  border-top: 1.5px solid #edd4dc;
  margin-top: 32px;
  padding-top: 16px;
}

.markdown-body .footnotes ol {
  padding-left: 16px;
}

.markdown-body .footnotes li {
  position: relative;
}

.markdown-body .footnotes li:target::before {
  position: absolute;
  top: -8px;
  right: -8px;
  bottom: -8px;
  left: -24px;
  pointer-events: none;
  content: "";
  border: 2px solid #e6678a;
  border-radius: 6px;
}

.markdown-body .footnotes li:target {
  color: #4a3340;
}

.markdown-body .footnotes .data-footnote-backref g-emoji {
  font-family: monospace;
}

/* ---- Emoji --------------------------------------------------------------- */

.markdown-body .emoji {
  max-width: none;
  vertical-align: text-top;
  background-color: transparent;
}

.markdown-body g-emoji {
  font-family: "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
  font-size: 1em;
  font-style: normal !important;
  font-weight: 400;
  line-height: 1;
  vertical-align: -0.075em;
}

.markdown-body g-emoji img {
  width: 1em;
  height: 1em;
}

/* ---- Image Frame Spans --------------------------------------------------- */

.markdown-body span.frame {
  display: block;
  overflow: hidden;
}

.markdown-body span.frame > span {
  display: block;
  float: left;
  width: auto;
  padding: 7px;
  margin: 13px 0 0;
  overflow: hidden;
  border: 1px solid #edd4dc;
  border-radius: 8px;
}

.markdown-body span.frame span img {
  display: block;
  float: left;
}

.markdown-body span.frame span span {
  display: block;
  padding: 5px 0 0;
  clear: both;
  color: #4a3340;
}

.markdown-body span.align-center {
  display: block;
  overflow: hidden;
  clear: both;
}

.markdown-body span.align-center > span {
  display: block;
  margin: 13px auto 0;
  overflow: hidden;
  text-align: center;
}

.markdown-body span.align-center span img {
  margin: 0 auto;
  text-align: center;
}

.markdown-body span.align-right {
  display: block;
  overflow: hidden;
  clear: both;
}

.markdown-body span.align-right > span {
  display: block;
  margin: 13px 0 0;
  overflow: hidden;
  text-align: right;
}

.markdown-body span.align-right span img {
  margin: 0;
  text-align: right;
}

.markdown-body span.float-left {
  display: block;
  float: left;
  margin-right: 13px;
  overflow: hidden;
}

.markdown-body span.float-left span {
  margin: 13px 0 0;
}

.markdown-body span.float-right {
  display: block;
  float: right;
  margin-left: 13px;
  overflow: hidden;
}

.markdown-body span.float-right > span {
  display: block;
  margin: 13px auto 0;
  overflow: hidden;
  text-align: right;
}

/* ---- CSV Data ------------------------------------------------------------ */

.markdown-body .csv-data td,
.markdown-body .csv-data th {
  padding: 5px;
  overflow: hidden;
  font-size: 12px;
  line-height: 1;
  text-align: left;
  white-space: nowrap;
}

.markdown-body .csv-data .blob-num {
  padding: 10px 8px 9px;
  text-align: right;
  background: #fef9f6;
  border: 0;
}

.markdown-body .csv-data tr {
  border-top: 0;
}

.markdown-body .csv-data th {
  font-weight: 600;
  background: #fef5f8;
  border-top: 0;
}

/* ---- Misc ---------------------------------------------------------------- */

.markdown-body::before {
  display: table;
  content: "";
}

.markdown-body::after {
  display: table;
  clear: both;
  content: "";
}

.markdown-body > *:first-child {
  margin-top: 0 !important;
}

.markdown-body > *:last-child {
  margin-bottom: 0 !important;
}

.markdown-body .absent {
  color: #d4456a;
}

.markdown-body .anchor {
  float: left;
  padding-right: 4px;
  margin-left: -20px;
  line-height: 1;
}

.markdown-body .anchor:focus {
  outline: none;
}

.markdown-body p,
.markdown-body blockquote,
.markdown-body ul,
.markdown-body ol,
.markdown-body dl,
.markdown-body table,
.markdown-body pre,
.markdown-body details {
  margin-top: 0;
  margin-bottom: 16px;
}

.markdown-body sup > a::before {
  content: "[";
}

.markdown-body sup > a::after {
  content: "]";
}

.markdown-body h1 .octicon-link,
.markdown-body h2 .octicon-link,
.markdown-body h3 .octicon-link,
.markdown-body h4 .octicon-link,
.markdown-body h5 .octicon-link,
.markdown-body h6 .octicon-link {
  color: #4a3340;
  vertical-align: middle;
  visibility: hidden;
}

.markdown-body h1:hover .anchor,
.markdown-body h2:hover .anchor,
.markdown-body h3:hover .anchor,
.markdown-body h4:hover .anchor,
.markdown-body h5:hover .anchor,
.markdown-body h6:hover .anchor {
  text-decoration: none;
}

.markdown-body h1:hover .anchor .octicon-link,
.markdown-body h2:hover .anchor .octicon-link,
.markdown-body h3:hover .anchor .octicon-link,
.markdown-body h4:hover .anchor .octicon-link,
.markdown-body h5:hover .anchor .octicon-link,
.markdown-body h6:hover .anchor .octicon-link {
  visibility: visible;
}

.markdown-body h1 tt,
.markdown-body h1 code,
.markdown-body h2 tt,
.markdown-body h2 code,
.markdown-body h3 tt,
.markdown-body h3 code,
.markdown-body h4 tt,
.markdown-body h4 code,
.markdown-body h5 tt,
.markdown-body h5 code,
.markdown-body h6 tt,
.markdown-body h6 code {
  padding: 0 0.2em;
  font-size: inherit;
}

/* ---- Forms --------------------------------------------------------------- */

.markdown-body input {
  font: inherit;
  margin: 0;
  overflow: visible;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
  accent-color: #d4456a;
}

.markdown-body [type="button"],
.markdown-body [type="reset"],
.markdown-body [type="submit"] {
  -webkit-appearance: button;
}

.markdown-body [type="button"]::-moz-focus-inner,
.markdown-body [type="reset"]::-moz-focus-inner,
.markdown-body [type="submit"]::-moz-focus-inner {
  border-style: none;
  padding: 0;
}

.markdown-body [type="button"]:-moz-focusring,
.markdown-body [type="reset"]:-moz-focusring,
.markdown-body [type="submit"]:-moz-focusring {
  outline: 1px dotted #d4456a;
}

.markdown-body [type="checkbox"],
.markdown-body [type="radio"] {
  box-sizing: border-box;
  padding: 0;
}

.markdown-body [type="number"]::-webkit-inner-spin-button,
.markdown-body [type="number"]::-webkit-outer-spin-button {
  height: auto;
}

.markdown-body [type="search"] {
  -webkit-appearance: textfield;
  outline-offset: -2px;
}

.markdown-body [type="search"]::-webkit-search-cancel-button,
.markdown-body [type="search"]::-webkit-search-decoration {
  -webkit-appearance: none;
}

.markdown-body ::-webkit-input-placeholder {
  color: #a09098;
  opacity: 0.54;
}

.markdown-body ::-webkit-file-upload-button {
  -webkit-appearance: button;
  font: inherit;
}

.markdown-body ::placeholder {
  color: #a09098;
  opacity: 1;
}

.markdown-body input::-webkit-outer-spin-button,
.markdown-body input::-webkit-inner-spin-button {
  margin: 0;
  -webkit-appearance: none;
  appearance: none;
}

.markdown-body ::-webkit-calendar-picker-indicator {
  filter: invert(50%);
}

/* ---- Primer Syntax Classes (GitHub-flavored code highlights) ------------- */

.markdown-body .pl-c {
  color: #a09098;
  font-style: italic;
}

.markdown-body .pl-c1,
.markdown-body .pl-s .pl-v {
  color: #d4a0c0;
}

.markdown-body .pl-e,
.markdown-body .pl-en {
  color: #e6678a;
}

.markdown-body .pl-smi,
.markdown-body .pl-s .pl-s1 {
  color: #e8d8dd;
}

.markdown-body .pl-ent {
  color: #8cc0a0;
}

.markdown-body .pl-k {
  color: #f0a0b8;
  font-weight: bold;
}

.markdown-body .pl-s,
.markdown-body .pl-pds,
.markdown-body .pl-s .pl-pse .pl-s1,
.markdown-body .pl-sr,
.markdown-body .pl-sr .pl-cce,
.markdown-body .pl-sr .pl-sre,
.markdown-body .pl-sr .pl-sra {
  color: #e6b899;
}

.markdown-body .pl-v,
.markdown-body .pl-smw {
  color: #d4a0c0;
}

.markdown-body .pl-bu {
  color: #ff8fa0;
}

.markdown-body .pl-ii {
  color: #fef9f6;
  background-color: #b83852;
}

.markdown-body .pl-c2 {
  color: #fef9f6;
  background-color: #d4456a;
}

.markdown-body .pl-sr .pl-cce {
  font-weight: bold;
  color: #8cc0a0;
}

.markdown-body .pl-ml {
  color: #e6b899;
}

.markdown-body .pl-mh,
.markdown-body .pl-mh .pl-en,
.markdown-body .pl-ms {
  font-weight: bold;
  color: #e6678a;
}

.markdown-body .pl-mi {
  font-style: italic;
  color: #e8d8dd;
}

.markdown-body .pl-mb {
  font-weight: bold;
  color: #e8d8dd;
}

.markdown-body .pl-md {
  color: #ff8fa0;
  background-color: #3d2028;
}

.markdown-body .pl-mi1 {
  color: #8cc0a0;
  background-color: #1d2d25;
}

.markdown-body .pl-mc {
  color: #f5c080;
  background-color: #3d3028;
}

.markdown-body .pl-mi2 {
  color: #e8d8dd;
  background-color: #3d2e35;
}

.markdown-body .pl-mdr {
  font-weight: bold;
  color: #e6678a;
}

.markdown-body .pl-ba {
  color: #8a7a82;
}

.markdown-body .pl-sg {
  color: #7a6a72;
}

.markdown-body .pl-corl {
  text-decoration: underline;
  color: #e6b899;
}

/* ---- Catalyst (GitHub details/summary polyfill) -------------------------- */

.markdown-body [data-catalyst] {
  display: block;
}

/* ---- 初芽 Stamp Component — postage-stamp style footer ------------------ */

.markdown-body {
  position: relative; /* anchor for stamp absolute positioning */
}

.markdown-body .hatsume-stamp {
  position: absolute;
  bottom: -18px;
  right: -12px;
  z-index: 10;

  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;

  padding: 10px 10px 8px 10px;
  background: #fef7f9;
  border: 3px dashed #edd4dc;
  border-radius: 6px;

  box-shadow:
    2px 2px 8px rgba(180, 120, 140, 0.12),
    0 0 0 2px #fef9f6; /* outer white gap like stamp edge */

  transform: rotate(3deg);
  transition: transform 0.2s ease;
}

.markdown-body .hatsume-stamp img {
  display: block;
  width: 100px;
  height: 100px;
  object-fit: cover;
  border-radius: 6px;
  box-shadow: 0 1px 4px rgba(180, 120, 140, 0.15);
}

.markdown-body .hatsume-stamp span {
  font-size: 12px;
  color: #a09098;
  letter-spacing: 1px;
  user-select: none;
}
```

This CSS file contains all original selectors plus the `.hatsume-stamp` component. The file should be saved verbatim as `data/hatsume-plugin/sakura-markdown.css`.
