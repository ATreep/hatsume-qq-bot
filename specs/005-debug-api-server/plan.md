# Implementation Plan: 调试 API 数据采集层与服务器

**Branch**: `005-debug-api-server` | **Date**: 2026-06-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-debug-api-server/spec.md`

## Summary

实现 `debug.py` 数据采集模块和嵌入式 HTTP API 服务器：在 NoneBot 启动时自动启动 FastAPI 子应用，暴露 7 个 REST 端点（summary/state/queues/memory/tools/config/health），以只读方式采集约 50 个系统状态变量，返回 JSON 格式的调试数据。零新依赖，与 `004-debug-panel-v2` 的 HTML 面板共用数据采集层。

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI (已有), asyncio, nonebot2 (nonebot_plugin_apscheduler for lifecycle hooks)
**Storage**: N/A — 纯只读内存状态采集，无持久化
**Testing**: pytest + pytest-asyncio
**Target Platform**: Linux/macOS server (NoneBot 运行环境)
**Project Type**: web-service (嵌入式 HTTP 服务器)
**Performance Goals**: 单端点响应 <50ms (localhost), 数据采集 <15ms
**Constraints**: 零新外部依赖, 不阻塞 NoneBot 事件循环, 启动失败不影响主功能, 默认仅监听 127.0.0.1
**Scale/Scope**: 7 个 API 端点, ~50 个状态变量, 单文件采集器 debug.py

## Constitution Check

*GATE: 跳过（宪法模板未填充）。*

## Project Structure

### Documentation (this feature)

```text
specs/005-debug-api-server/
├── plan.md              # 本文件
├── research.md          # Phase 0 研究输出
├── data-model.md        # Phase 1 数据模型
├── quickstart.md        # Phase 1 快速开始
├── contracts/           # Phase 1 API 契约
│   └── debug-api.yaml   # OpenAPI 3.0 规范
└── tasks.md             # Phase 2 输出 (/speckit-tasks)
```

### Source Code (repository root)

```text
hatsume/plugins/hatsume-plugin/
├── debug.py             # [新增] 数据采集层 + FastAPI 子应用 + 生命周期管理
├── config.py            # [修改] 新增 debug_host/debug_port/debug_enabled 配置项
├── __init__.py          # [修改] 注册调试服务器启动/停止钩子
└── templates/
    └── debug_panel.html # 与 004-debug-panel-v2 共用

tests/
└── test_debug_api.py    # [新增] 调试 API 端点测试
```

**Structure Decision**: 所有调试逻辑集中在 `debug.py` 单文件中（数据采集 + API 路由 + 生命周期），遵循项目已有的扁平模块惯例（如 `infra.py`、`state.py`、`models.py` 等单文件模块）。配置项追加到已有 `config.py`，注册钩子追加到 `__init__.py`。

## Complexity Tracking

> 无宪法违规，无需记录。
