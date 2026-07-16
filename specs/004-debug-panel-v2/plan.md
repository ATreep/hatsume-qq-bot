# Implementation Plan: 调试面板 v2

**Branch**: `004-debug-panel-v2` | **Date**: 2026-06-01 | **Spec**: [spec.md](./spec.md)

## Summary

升级调试面板：采集器返回消息摘要数组，前端新增 Dashboard 概览、消息气泡、搜索筛选、移动端响应式、JSDoc。单文件 HTML 零外部依赖。

## Technical Context

**Language/Version**: Python 3.12 (backend), vanilla JS + JSDoc (frontend)
**Primary Dependencies**: FastAPI, asyncio, json — 零新依赖
**Testing**: pytest + pytest-asyncio
**Target Platform**: Linux/macOS + 现代浏览器 + 移动端
**Performance Goals**: 采集 <15ms, 搜索 <200ms, HTML <20KB
**Constraints**: 单文件 HTML, 零外部引用

## Constitution Check

*GATE: 跳过（模板未填充）。*

## Project Structure

```text
hatsume/plugins/hatsume-plugin/
├── __init__.py          # [修改] 队列采集返回摘要
├── debug.py             # [修改] 队列序列化
└── templates/
    └── debug_panel.html # [修改] Dashboard+气泡+搜索+响应式+JSDoc

tests/
└── test_debug.py         # [修改] 队列摘要+Dashboard 测试
```
