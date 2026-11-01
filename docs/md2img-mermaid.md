# MD2IMG Mermaid 渲染

`utils/md_to_image.py` 会把 Markdown 中的 `mermaid` 围栏交给同一个无头 Chromium 页面渲染为 SVG，再随 Markdown 内容截图发送。

## 运行时实现

- Mermaid 浏览器包固定为 **12.2.0**，文件位于 `hatsume/plugins/hatsume-plugin/utils/assets/mermaid.min.js`。
- 运行时直接内联本地资源，不访问 CDN，也不调用独立的 Node CLI；因此 Mermaid 的图表语法覆盖取决于该固定版本官方包。
- 支持 Mermaid 包提供的各种图表类型，包括 flowchart、sequence、class、state、ER、Gantt、git、mindmap、timeline、pie、quadrant、requirement、C4、Sankey、block、packet、architecture 和 xychart 等。
- 使用 `securityLevel: strict`，不启用点击回调；图表源码先转义后进入页面，不能作为 HTML 或脚本拼接执行。

## 明暗主题

MD2IMG 每次渲染只解析一次当前主题，并同时用于页面 CSS 和 Mermaid `base` theme variables：

- 浅色：奶油色背景、樱花粉节点、深梅色文字和玫瑰色连线。
- 深色：`#1a1418` 背景、深梅色表面、浅粉文字和高对比连线。

生成的 SVG 限制最大宽度并允许横向滚动，避免宽图表裁剪。

## 失败回退

单个 Mermaid 图表解析失败时，仅该图表保留为转义后的 `language-mermaid` 代码块；其他图表和 Markdown 继续渲染。资源缺失、脚本初始化失败或 Mermaid 未完成时也保留源码，不会让整张 Markdown 图片失败；HTML 截图自身失败时仍按 MD2IMG 原有逻辑回退为纯文本。

## 更新资源

更新 Mermaid 资源时，应从 npm 获取固定版本的官方 `dist/mermaid.min.js`，同步修改本文件中的版本号，并检查许可证。机器人运行时不要求安装 Node.js；Node/npm 只用于维护资源。独立的 `data/hatsume-plugin/skills/pretty-mermaid.md` 是图表创作/批处理 Skill，不是 MD2IMG 的运行时依赖。
