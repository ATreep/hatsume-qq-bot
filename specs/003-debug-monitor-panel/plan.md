# Implementation Plan: 实时调试监控面板

**Branch**: `003-debug-monitor-panel` | **Date**: 2026-06-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-debug-monitor-panel/spec.md`

## Summary

为 NoneBot2 QQ 机器人添加一个零依赖的实时调试监控面板。利用已有 FastAPI 驱动注册 HTTP 路由和 WebSocket 端点，前端为单文件 HTML（内联 CSS/JS，<12KB），极简日式毛玻璃风格。后端通过 StateCollector 注册表采集 6 个模块约 25 个运行时变量，每 500ms 走 WebSocket diff 推送变更。

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI (已有 via NoneBot2), asyncio (stdlib), json (stdlib) — 零新 pip 依赖

**Storage**: N/A（纯内存，不持久化）

**Testing**: pytest + pytest-asyncio (已有)

**Target Platform**: Linux/macOS 服务器，现代浏览器 (ES2020+, backdrop-filter, WebSocket)

**Project Type**: web-service 内嵌 HTML 前端（NoneBot2 插件内部路由）

**Performance Goals**: 采集循环 <10ms/轮，前端更新 <500ms，页面加载 <2s on 3G

**Constraints**: 单文件 HTML <15KB，零外部引用，不增 pip 依赖

**Scale/Scope**: 单开发者本地调试工具，6 个模块 ~25 变量，单 WebSocket 连接

## Constitution Check

*GATE: Constitution 文件为模板未填充，跳过门禁检查。*

## Project Structure

### Documentation (this feature)

```text
specs/003-debug-monitor-panel/
├── plan.md              # This file
├── research.md          # Phase 0: 技术决策记录
├── data-model.md        # Phase 1: 数据模型
├── quickstart.md        # Phase 1: 快速启动指南
├── contracts/           # Phase 1: WebSocket 协议契约
└── tasks.md             # Phase 2: 任务分解 (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── __init__.py          # [修改] 调用 setup_debug_panel(app)
├── debug.py             # [新增] StateCollector, setup_debug_panel, WS handler
└── templates/
    └── debug_panel.html # [新增] 单文件前端 (inline CSS/JS)

tests/
└── test_debug.py         # [新增] 后端单元+集成测试
```

**Structure Decision**: 所有新代码集中在 `hatsume/plugins/hatsume-plugin/` 内，遵循项目现有单插件结构。前端 HTML 放在 `templates/` 子目录。测试放在顶层 `tests/`。

## Complexity Tracking

> 无违规项。
