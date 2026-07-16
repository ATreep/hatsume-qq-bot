# Research: 实时调试监控面板

**Feature**: 003-debug-monitor-panel
**Date**: 2026-06-01

## R1: WebSocket 通信协议

**Decision**: 自订最小 JSON 协议，首次全量 + 后续 diff

**Rationale**:
- 已有 FastAPI + websockets 无需额外库
- diff 推送最小化带宽（25 变量中通常每轮仅 1-3 个变化）
- JSON 在前端零成本解析

**Alternatives considered**:
- Server-Sent Events (SSE): 单向，缺少首次握手灵活性
- 轮询 HTTP: 延迟高、开销大
- MQTT/Redis pub-sub: 过度工程化

**Protocol design**:
```json
// 连接建立 → 服务端立即发送全量快照
{ "type": "snapshot", "data": { "conv_state": {...}, "ai_node": {...}, ... } }

// 后续每 500ms → 仅推送变更
{ "type": "diff", "data": { "conv_state.is_chatting": true, "conv_state.pending_queue#": 3 } }
```

---

## R2: 状态采集机制

**Decision**: 惰性 lambda 注册模式，采集循环中顺序调用

**Rationale**:
- 每个采集器仅在被轮询时执行，零持续开销
- lambda 闭包直接捕获模块变量引用，无需反射或 import hook
- 单轮顺序执行 ≤10 个采集器 <10ms（每个仅是 dict 构建）

**Alternatives considered**:
- `sys.modules` 反射扫描: 侵入性强、类型不安全
- `threading.local` 代理对象: 过度设计
- `ContextVar`: asyncio 原生但不适合此场景

**Design**:
```python
class StateCollector:
    name: str
    collect: Callable[[], dict[str, Any]]

# 注册示例
StateCollector("conv_state", lambda: {
    "is_chatting": conv_state.is_chatting,
    "pending_queue#": len(conv_state.pending_queue),
})
```

---

## R3: 前端架构

**Decision**: 单文件 HTML，无框架、无构建工具、无外部依赖

**Rationale**:
- 目标 <12KB，React/Vue 本身远超此限制
- 调试面板复杂度低（2 面板 + 卡片列表），原生 DOM 操作足够
- 免构建意味着开发者可以直接编辑 `debug_panel.html` 并刷新

**Alternatives considered**:
- React + Vite SPA: ~50KB+ min+gzip，引入构建链
- htmx: 仍需后端模板渲染，不适用 WebSocket 实时场景
- Alpine.js: 13KB CDN，但引入外部依赖违反 FR-009

**Tech stack**: vanilla HTML + CSS custom properties + ES2020

---

## R4: 集成点

**Decision**: `__init__.py` 末尾调用 `setup_debug_panel(app)`，从 `nonebot.get_app()` 获取 FastAPI 实例

**Rationale**:
- 插件加载时 all modules 已初始化，可安全捕获变量引用
- 直接注册路由即可，无需钩子或信号

---

## R5: 测试策略

**Decision**: pytest + pytest-asyncio，WebSocket 测试使用 FastAPI TestClient

**Rationale**:
- 项目已有 pytest，零新增测试依赖
- FastAPI TestClient 原生支持 WebSocket 测试

**Test plan**:
1. collector registration/unregistration
2. collector execution returns expected values
3. WebSocket handshake connect/disconnect
4. initial snapshot on connect
5. diff on value change
6. HTML served with correct Content-Type
7. HTML contains no external references
