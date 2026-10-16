"""Render palette candidates through the actual md2img HTML and image pipeline.

Use a local Python environment with the project's Markdown/htmlrender dependencies.
The project .venv is not used. Default production styling is never overwritten.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PALETTES = ("01-cherry-ink", "02-sea-salt", "03-bamboo", "04-berry-candy")


def load_renderer():
    import nonebot

    nonebot.init(driver="~fastapi", render_backend="playwright", render_storage_path="/tmp/hatsume-md2img-preview-browser", log_level="WARNING")
    # Load just the rendering utility, avoiding bot startup and external services.
    for name in ("palette_preview", "palette_preview.utils"):
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
    config = types.ModuleType("palette_preview.config")
    config.LONG_MSG_THRESHOLD = 1000
    sys.modules[config.__name__] = config
    source = ROOT / "hatsume/plugins/hatsume-plugin/utils/md_to_image.py"
    spec = importlib.util.spec_from_file_location("palette_preview.utils.md_to_image", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._is_dark_mode = lambda: False
    return module


def luminance(rgb):
    channels = [v / 255 for v in rgb]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(foreground, background):
    import re

    light, dark = sorted((luminance([int(v) for v in re.findall(r"\d+", color)[:3]]) for color in (foreground, background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


async def main():
    renderer = load_renderer()

    async def no_production_palette():
        return ""

    # Compare candidates against the original theme, even after one is adopted.
    renderer._get_light_code_css = no_production_palette
    from nonebot_plugin_htmlrender import get_new_page, shutdown_render

    baseline_css = await renderer._get_css()
    sample = (OUT / "sample.md").read_text()
    report_path = OUT / "contrast.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    requested = tuple(sys.argv[1:]) or ("00-current", *PALETTES)
    if any(slug not in ("00-current", *PALETTES) for slug in requested):
        raise ValueError("Unknown palette name")
    try:
        # All candidates use the same Markdown and viewport.
        for slug in requested:
            override = "" if slug == "00-current" else (OUT / f"{slug}.css").read_text()
            renderer._cached_css = baseline_css + override
            html = await renderer._markdown_to_html(sample)
            (OUT / f"{slug}.html").write_text(html)
            image_bytes = await renderer.render_html(html, full_page=True, viewport={"width": 800, "height": 600}, device_scale_factor=2, color_scheme="light")
            (OUT / f"{slug}.png").write_bytes(image_bytes)
            async with get_new_page(viewport={"width": 800, "height": 600}, color_scheme="light") as page:
                await page.set_content(html)
                await page.evaluate("document.fonts.ready")
                styles = await page.evaluate('''() => {
                  const pre = document.querySelector('.codehilite pre');
                  const canvas = document.createElement('canvas');
                  canvas.width = canvas.height = 1;
                  const ctx = canvas.getContext('2d');
                  const normalize = color => {
                    ctx.clearRect(0, 0, 1, 1);
                    ctx.fillStyle = color;
                    ctx.fillRect(0, 0, 1, 1);
                    const rgba = ctx.getImageData(0, 0, 1, 1).data;
                    return `rgb(${rgba[0]}, ${rgba[1]}, ${rgba[2]})`;
                  };
                  const tokens = [pre, ...pre.querySelectorAll('span')]
                    .filter(e => e.textContent.trim());
                  return {
                    background: normalize(getComputedStyle(pre).backgroundColor),
                    overflow: pre.scrollWidth > pre.clientWidth,
                    colors: [...new Set(tokens.map(e => normalize(getComputedStyle(e).color)))]
                  };
                }''')
            ratios = {color: round(contrast(color, styles['background']), 2) for color in styles['colors']}
            report[slug] = {**styles, "contrast": ratios, "minimum_contrast": min(ratios.values())}
            if slug != "00-current":
                assert report[slug]['minimum_contrast'] >= 4.5, report[slug]
                assert not styles['overflow'], slug
            print(slug, report[slug]['minimum_contrast'])
        (OUT / "contrast.json").write_text(json.dumps(report, indent=2))
    finally:
        await shutdown_render()


if __name__ == "__main__":
    asyncio.run(main())
