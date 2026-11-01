from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "hatsume/plugins/hatsume-plugin/utils/md_to_image.py"
)


@pytest.fixture
def md_module(monkeypatch):
    nonebot = types.ModuleType("nonebot")
    nonebot.require = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "nonebot", nonebot)
    adapters = types.ModuleType("nonebot.adapters")
    onebot = types.ModuleType("nonebot.adapters.onebot")
    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.MessageSegment = types.SimpleNamespace(
        text=lambda value: value,
        image=lambda value: value,
    )
    monkeypatch.setitem(sys.modules, "nonebot.adapters", adapters)
    monkeypatch.setitem(sys.modules, "nonebot.adapters.onebot", onebot)
    monkeypatch.setitem(sys.modules, "nonebot.adapters.onebot.v11", v11)
    monkeypatch.setattr(v11, "MessageSegment", v11.MessageSegment)
    htmlrender = types.ModuleType("nonebot_plugin_htmlrender")
    htmlrender.render_html = None
    htmlrender.__file__ = str(MODULE_PATH)
    monkeypatch.setitem(sys.modules, "nonebot_plugin_htmlrender", htmlrender)
    package_names = [
        "hatsume",
        "hatsume.plugins",
        "hatsume.plugins.hatsume_plugin",
        "hatsume.plugins.hatsume_plugin.utils",
    ]
    for package_name in package_names:
        package = types.ModuleType(package_name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, package_name, package)
    config = types.ModuleType("hatsume.plugins.hatsume_plugin.config")
    config.LONG_MSG_THRESHOLD = 500
    monkeypatch.setitem(sys.modules, config.__name__, config)
    models = types.ModuleType("hatsume.plugins.hatsume_plugin.models")
    models.get_lite_model = lambda: None
    monkeypatch.setitem(sys.modules, models.__name__, models)
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume_plugin.utils.md_to_image", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(__import__("sys").modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_extract_mermaid_blocks_supports_backticks_and_tildes(md_module):
    text = """before
```Mermaid
flowchart LR
  A --> B
```
after
~~~ mermaid
sequenceDiagram
  A->>B: hello
~~~
"""

    remaining, blocks = md_module._extract_mermaid_blocks(text)

    assert len(blocks) == 2
    assert "flowchart LR" in blocks[0]
    assert "sequenceDiagram" in blocks[1]
    assert "HATSUME_MERMAID_BLOCK_" in remaining
    assert "```Mermaid" not in remaining
    assert "~~~ mermaid" not in remaining


def test_extract_mermaid_blocks_preserves_non_mermaid_code(md_module):
    text = "```python\nprint('keep me')\n```\n"

    remaining, blocks = md_module._extract_mermaid_blocks(text)

    assert blocks == []
    assert remaining == text


def test_mermaid_feature_detection(md_module):
    assert md_module._has_md_features("```mermaid\nflowchart LR\nA-->B\n```")
    assert md_module._has_md_features("~~~ MERMAID\nflowchart TD\nA-->B\n~~~")


def test_mermaid_theme_has_light_and_dark_palettes(md_module):
    light = md_module._mermaid_theme(False)
    dark = md_module._mermaid_theme(True)

    assert light["background"] != dark["background"]
    assert light["primaryTextColor"] != dark["primaryTextColor"]
    assert light["fontFamily"] == dark["fontFamily"]


def test_markdown_to_html_contains_mermaid_contract(md_module, monkeypatch):
    async def async_value(value):
        return value

    monkeypatch.setattr(md_module, "_get_css", lambda: async_value(""))
    monkeypatch.setattr(md_module, "_get_light_code_css", lambda: async_value(""))
    monkeypatch.setattr(md_module, "_get_mermaid_js", lambda: async_value("window.mermaid={};"))
    md_module._MD_EXTENSIONS = []
    monkeypatch.setattr(md_module, "_is_dark_mode", lambda: False)

    import asyncio

    page = asyncio.run(md_module._markdown_to_html(
        "```mermaid\nflowchart LR\nA[开始] --> B[结束]\n```"
    ))

    assert "hatsume-mermaid" in page
    assert "securityLevel:'strict'" in page
    assert "themeVariables" in page
    assert "开始" in page
    assert "window.__hatsume_mermaid_ready" in page
    assert "<script>window.mermaid={};</script>" in page

