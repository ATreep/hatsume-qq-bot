# 初芽 Markdown 图片渲染主题 —「初芽·樱」

**Date:** 2026-07-08
**Status:** approved → ready for implementation
**Design for:** `md_to_image.py` custom CSS theme matching 初芽's character

## Overview

Replace the default GitHub-flavored markdown CSS with a custom warm "sakura" theme that reflects 初芽's personality (playful tsundere, red ponytail, "thorny little sun"), and add a randomly-selected character face image as a stamp-style footer element.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Theme tone | Warm sakura pink | Matches red hair + blushing personality + "小太阳" warmth |
| Face position | Bottom-right stamp | "Postage stamp on a letter" metaphor — like receiving mail from 初芽 |
| Implementation | Pure CSS + dynamic b64 injection | Minimal code change, easy to swap themes, no new dependencies |
| Fallback | New CSS → package default | Graceful degradation if custom CSS files are missing |

---

## Color Palette

```
┌──────────────────────────────────────────────────┐
│  Role              Hex         Usage              │
│  ───────────────── ──────────  ────────────────── │
│  bg-primary        #fef9f6    页面底色            │
│  bg-secondary      #fdf2f5    卡片/代码内联底色   │
│  bg-code-block     #2b2428    代码块底色(暗)      │
│  text-primary      #4a3340    正文文字            │
│  text-secondary    #7a5a6a    次级文字/引用       │
│  text-muted        #a09098    弱化文字            │
│  accent            #d4456a    主强调/标题         │
│  accent-light      #f0a0b8    浅强调/装饰         │
│  accent-dark       #b83852    深强调/hover        │
│  link              #e6678a    链接                │
│  link-hover        #d4456a    链接悬停            │
│  border            #edd4dc    边框                │
│  border-light      #f5e8ec    浅边框              │
│  shadow       rgba(180,120,140,0.08)  阴影        │
│  stamp-bg          #fef7f9    邮票底色            │
│  stamp-border      #edd4dc    邮票齿孔色          │
└──────────────────────────────────────────────────┘
```

---

## Layout —「初芽の手紙」(Letter from Hatsume)

```
┌──────────────────────────────────────────────┐
│  page background (#fef9f6)                   │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │  .markdown-body (信纸卡片)           │   │
│  │  bg: white, shadow, rounded 12px     │   │
│  │  padding: 40px                       │   │
│  │                                      │   │
│  │  [标题/正文/代码/表格...]            │   │
│  │                                      │   │
│  │                           ╭────────╮│   │
│  │                           │  🎭    ││   │
│  │                           │  表情  ││   │
│  │                           │ 初芽   ││← .hatsume-stamp
│  │                           ╰────────╯│   │
│  └──────┬──────────────────────────────┘   │
│         │  stamp overlaps card edge         │
│         │  ~3deg rotation, dashed border     │
│         └─ positioned bottom-right           │
└──────────────────────────────────────────────┘
```

### Stamp component (`.hatsume-stamp`)
- Position: absolute, bottom-right of `.markdown-body`, translated ~30% outside card
- Rotation: `rotate(3deg)` for casual "stuck on" feel
- Border: `3px dashed` — simulates perforation teeth
- Background: `#fef7f9` with subtle inner padding
- Face image: 100×100px, rounded 8px, centered
- Caption: small text "— 初芽 —" below image
- Box-shadow: subtle lift effect

---

## Typography

```
Element    Size       Weight  Color         Notes
──────     ────       ──────  ─────         ─────
h1         2em        600     #d4456a       bottom border
h2         1.5em      600     #d4456a       bottom border
h3         1.25em     600     #4a3340
h4         1em        600     #4a3340
h5         0.875em    600     #7a5a6a
h6         0.85em     600     #7a5a6a       italic
body       16px       400     #4a3340       line-height: 1.6
small      90%        400     #7a5a6a
strong     600+       600     #4a3340
code(inline) 85%      400     #b83852       bg: #fdf0f3, rounded 4px
code(block)  14px     400     #e8d8dd       bg: #2b2428, line-height 1.5
```

---

## Special Elements

### Code Blocks
- Background: dark `#2b2428` (contrast with light card, represents "专业模式")
- Text: `#e8d8dd`
- Rounded: 8px, padding: 16px
- Scrollbar: styled thin, warm tone

### Blockquotes
- Left border: 4px solid `#d4456a` (rose)
- Background: `#fef7f9`
- Rounded: 0 8px 8px 0
- Text color: `#7a5a6a`

### Tables
- Border: 1px solid `#edd4dc`
- Header bg: `#fdf2f5`, header text: `#d4456a`
- Stripe: `#fef9f6` / `#fef5f8` alternating
- Rounded: 8px overflow

### Horizontal Rules
- Gradient: transparent → `#e6678a` → transparent
- Or: decorative `— ♡ —` style via pseudo-element

### Task Lists
- Checkbox accent-color: `#d4456a`
- Completed items: subtle strikethrough, muted color

### Inline Code
- Background: `#fdf0f3`
- Text: `#b83852`
- Padding: 0.2em 0.4em, rounded 4px

### Links
- Color: `#e6678a`
- Hover: `#d4456a` with underline
- Subtle transition on hover

---

## Code Highlighting (sakura-pygments.css)

Dark code block background `#2b2428` with warm token colors:

```
Token        Color       Description
─────        ─────       ───────────
Keyword      #f0a0b8     if, def, class, return
String       #e6b899     "hello world"
Comment      #8a7a82     // comment, italic
Number       #d4a0c0     42, 3.14
Name.Func    #e6678a     my_function()
Name.Class   #f5c080     MyClass
Name.Tag     #f0a0b8     <div>
Operator     #c0a8b8     + - * / = 
Name.Builtin #d4a0c0     len, print, range
Error        #ff6b8a     syntax error highlight
Generic.Deleted  #ff6b8a  diff deleted line bg
Generic.Inserted #8cc0a0  diff inserted line bg
```

---

## Face Selection

### Source
- Directory: `data/hatsume-plugin/faces/`
- Files: 11 PNGs — 开心×2, 伤心×2, 害羞×2, 疑惑×2, 惊讶×1, 生气×1, 无语×1
- **Files stay in place** — no copying, base64 encoded at render time

### Selection Strategy
- `random.choice()` over all `.png` files (excluding `.DS_Store`)
- Each render gets a fresh random face
- Encoded as `data:image/png;base64,...` data URI

---

## File Changes

### New files
| File | Purpose |
|------|---------|
| `data/hatsume-plugin/sakura-markdown.css` | Complete markdown body theme (~900 lines) |
| `data/hatsume-plugin/sakura-pygments.css` | Code syntax highlighting theme (~75 lines) |

### Modified files
| File | Changes |
|------|---------|
| `hatsume/plugins/hatsume-plugin/utils/md_to_image.py` | ~35 lines added |

### md_to_image.py changes in detail

```python
# New imports: base64, os (for random face)

# New function: resolve data dir
def _get_data_dir() -> Path:
    """Resolve data/hatsume-plugin/ directory."""
    ...

# New function: random face → base64 data URI
async def _get_random_face_b64() -> str | None:
    """Pick random face PNG, return data:image/png;base64,... URI.
    Returns None if faces dir is empty/missing."""
    ...

# Modified function: try custom CSS first, fallback to package
async def _get_css() -> str:
    """Load sakura CSS from data/, fallback to package GitHub CSS."""
    data_dir = _get_data_dir()
    sakura_md = data_dir / "sakura-markdown.css"
    sakura_pyg = data_dir / "sakura-pygments.css"
    
    if sakura_md.exists() and sakura_pyg.exists():
        return await _read(sakura_md) + await _read(sakura_pyg)
    
    # Fallback to original
    tmpl = _get_templates_dir()
    return await _read(tmpl / "github-markdown-light.css") + \
           await _read(tmpl / "pygments-default.css")

# Modified function: inject stamp HTML
async def _markdown_to_html(md_text: str) -> str:
    ...
    # Build stamp footer
    face_b64 = await _get_random_face_b64()
    stamp_html = ""
    if face_b64:
        stamp_html = (
            '<div class="hatsume-stamp">'
            f'<img src="{face_b64}" alt="初芽">'
            '<span>— 初芽 —</span>'
            '</div>'
        )
    
    page = (
        ...
        f'<article class="markdown-body">{html_body}{stamp_html}</article>'
        ...
    )
    return page
```

---

## CSS Compatibility Notes

All selectors from `github-markdown-light.css` and `pygments-default.css` are preserved with the same specificity. The new CSS files are drop-in replacements — no changes needed in the markdown→HTML pipeline.

Key preserved selector groups:
- `.markdown-body` — all typography, layout, reset styles
- `.codehilite` + all `.codehilite .xx` token classes (41 classes)
- `.pl-*` — GitHub Primer syntax classes (33 classes)
- `.task-list-item`, `.task-list-item-checkbox`
- `.footnotes`, `.footnotes li`, `.footnotes .data-footnote-backref`
- `.highlight`, `.highlight pre`

---

## Self-Review Checklist

- [x] Color palette matches 初芽's character design (red hair, warm personality)
- [x] All CSS selectors preserved from original files
- [x] Stamp component matches approved layout (bottom-right, ~3deg rotation)
- [x] Face files stay in place, base64 encoded at render time
- [x] Graceful fallback to original CSS if custom files missing
- [x] No new dependencies required
- [x] Face selection handles empty/missing faces directory gracefully
