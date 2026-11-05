from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "md2img-mermaid-demos"
SOURCE = ROOT / "hatsume" / "plugins" / "hatsume-plugin" / "utils" / "md_to_image.py"

DEMO = r'''# Mermaid 图表主题效果

下面展示同一张 Markdown 卡片中多种 Mermaid 图表的主题效果。

```python
# 代码块也使用半透明表面，让底部猫爪纹理透出
render(theme="pink")
```

## 流程与交互

```mermaid
flowchart LR
    A[用户请求] --> B{校验}
    B -->|通过| C[生成结果]
    B -->|失败| D[返回提示]
    C --> E[发送卡片]
```

```mermaid
sequenceDiagram
    participant U as 用户
    participant H as 初芽
    participant S as 服务
    U->>H: 请求图表
    H->>S: 渲染 Mermaid
    S-->>H: SVG
    H-->>U: 主题卡片
```

## 模型与数据

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Rendering: 收到请求
    Rendering --> Ready: 渲染完成
    Rendering --> Failed: 解析失败
    Failed --> Idle: 保留源码
    Ready --> [*]
```

```mermaid
classDiagram
    class Card {
      +String theme
      +render()
    }
    class Diagram {
      +String source
      +toSVG()
    }
    Card o-- Diagram
```

```mermaid
erDiagram
    USER ||--o{ REQUEST : creates
    REQUEST ||--|| CARD : renders
    CARD ||--o{ DIAGRAM : contains
```

## 计划与统计

```mermaid
gantt
    title Mermaid Demo Schedule
    dateFormat YYYY-MM-DD
    axisFormat %m/%d
    section Render
    Extract source :done, a1, 2025-01-01, 1d
    Render SVG :active, a2, after a1, 2d
    Capture card :a3, after a2, 1d
```

```mermaid
pie title 主题使用比例
    "浅色卡片" : 55
    "深色卡片" : 30
    "系统默认" : 15
```

```mermaid
mindmap
  root((主题卡片))
    浅色
      奶油节点
      玫瑰连线
    深色
      深梅背景
      粉色文字
```

```mermaid
timeline
    title 渲染演进
    2025 : Markdown 卡片
    2026 : Mermaid SVG
    2027 : 更多图表类型
```

```mermaid
xychart-beta
    title "年度涨幅速览"
    x-axis [NTC, AMD, GOOGL, TSM, AVGO]
    y-axis "涨幅 (%)" 0 --> 90
    bar [84, 77, 65, 54, 49]
```
'''


def load_renderer():
    import nonebot

    nonebot.init(driver="~fastapi", render_backend="playwright", render_storage_path="/tmp/hatsume-md2img-demo", log_level="WARNING")
    import nonebot_plugin_htmlrender as htmlrender
    if not hasattr(htmlrender, "render_html"):
        htmlrender.render_html = lambda *args, **kwargs: None
    for name in ("demo_pkg", "demo_pkg.utils"):
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
    config = types.ModuleType("demo_pkg.config")
    config.LONG_MSG_THRESHOLD = 1000
    sys.modules[config.__name__] = config
    nonebot.require = lambda *_args, **_kwargs: None
    models = types.ModuleType("demo_pkg.models")
    models.get_lite_model = lambda: None
    sys.modules[models.__name__] = models
    spec = importlib.util.spec_from_file_location("demo_pkg.utils.md_to_image", SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def render(theme: str):
    renderer = load_renderer()
    renderer._is_dark_mode = lambda: theme == "dark"
    renderer._cached_css = None
    renderer._cached_light_code_css = ""
    html = await renderer._markdown_to_html(DEMO)
    from nonebot_plugin_htmlrender import get_new_page, shutdown_browser

    OUT.mkdir(parents=True, exist_ok=True)
    async with get_new_page(viewport={"width": 1200, "height": 900}, color_scheme=theme) as page:
        await page.set_content(html, wait_until="load")
        await page.wait_for_function("window.__hatsume_mermaid_ready === true", timeout=15000)
        await page.evaluate("document.fonts.ready")
        await page.screenshot(path=str(OUT / f"mermaid-{theme}.png"), full_page=True)
        metrics = await page.evaluate("""() => ({
          svgs: document.querySelectorAll('.hatsume-mermaid-output svg').length,
          hosts: document.querySelectorAll('.hatsume-mermaid').length,
          failed: document.querySelectorAll('.hatsume-mermaid.is-failed').length,
          bodyWidth: document.body.scrollWidth,
          viewportWidth: window.innerWidth,
          cards: [...document.querySelectorAll('.hatsume-mermaid')].map(card => ({
            width: card.getBoundingClientRect().width,
            radius: getComputedStyle(card).borderTopLeftRadius,
            border: getComputedStyle(card).borderTopColor,
            background: getComputedStyle(card).backgroundColor
          }))
        })""")
        print(theme, metrics)
    await shutdown_browser()


async def main():
    await render("light")
    await render("dark")


if __name__ == "__main__":
    asyncio.run(main())
