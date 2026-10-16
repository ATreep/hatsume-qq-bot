# md2img 浅色代码块配色候选

三种候选只覆盖代码块的背景、边框与语法高亮；卡片外观、排版和行内代码沿用当前样式。生产浅色默认现已采用第四款「莓莓糖」。

| 文件 | 配色 | 示例中最低文字对比度 |
| --- | --- | --- |
| `01-cherry-ink.css` | 樱桃墨：淡粉背景，莓红关键字 | 5.63:1 |
| `02-sea-salt.css` | 海盐蓝：淡蓝背景，靛紫关键字 | 5.29:1 |
| `03-bamboo.css` | 竹林绿：淡绿背景，紫色关键字 | 5.11:1 |

每种方案配有同名 HTML 和 PNG，`00-current` 是原始样式对照。`sample.md` 是三种方案共用的示例，`contrast.json` 保存浏览器实际计算的颜色和对比度。

`render.py` 加载项目原有 `_markdown_to_html`，追加候选 CSS，通过 `nonebot_plugin_htmlrender.render_html` 生成图片。固定浅色模式、800px 视口和 2 倍像素密度；检查示例全部非空语法 token 的对比度，以及代码块是否横向溢出。随后人工查看三张 PNG。

用本地独立 Python 环境运行，不使用项目 `.venv`：

```sh
python examples/md2img-code-palettes/render.py
```

需要项目的 Markdown、NoneBot、OneBot、htmlrender（本次使用锁文件的 0.7.2）、Playwright 和 FastAPI 依赖。预览浏览器缓存放在 `/tmp/hatsume-md2img-preview-browser`。

这些 CSS 为浅色预览覆盖文件。选定后应在生产浅色分支加载，保留现有夜间高亮；不能直接无条件追加到深色模式。

## 第二轮：莓莓糖

`04-berry-candy.css` 保留淡粉色背景，改用糖果粉关键字、玫粉字符串、亮紫函数、蓝紫数字和少量明蓝类型名。普通变量改为柔和紫灰色，注释取消斜体。示例中浏览器实际最低文字对比度为 4.63:1，没有横向溢出，已查看实际 PNG。

单独重新渲染：

```sh
python examples/md2img-code-palettes/render.py 04-berry-candy
```

已接入生产浅色默认样式，CSS 位于 `hatsume/plugins/hatsume-plugin/utils/styles/berry-candy-code.css`；夜间模式与浏览器深色模式保留原有高亮。`production-light.png` 和 `production-dark.png` 是不追加预览覆盖文件的实际生产渲染结果。
