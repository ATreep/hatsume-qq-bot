# Research: 调试 API 数据采集层与服务器

**Feature**: 005-debug-api-server | **Date**: 2026-06-04

## R1: 如何在 NoneBot 事件循环中嵌入 HTTP 服务器

**Decision**: 使用 `uvicorn.Server` 以编程方式在同一 asyncio event loop 中启动，作为 asyncio Task 运行。

**Rationale**:
- NoneBot 基于 `nonebot.driver` 运行 asyncio 事件循环。`uvicorn.Server` 可以通过 `uvicorn.Config(app=..., host=..., port=...)` + `server = uvicorn.Server(config)` + `asyncio.create_task(server.serve())` 嵌入到已有循环中，无需额外进程或线程。
- 项目已依赖 FastAPI（来自 004-debug-panel-v2），不引入新依赖。

**Alternatives considered**:
- `aiohttp.web`: 功能足够但需要新依赖。
- 独立线程运行 uvicorn: 需要处理跨线程状态访问，增加复杂度。
- `uvicorn.run()`: 会阻塞当前事件循环。

**Key detail**: 使用 `asyncio.Event` 控制关闭，而非依赖 signal handler。

---

## R2: NoneBot 生命周期钩子选择

**Decision**: 使用 `nonebot.get_driver().on_startup` 和 `nonebot.get_driver().on_shutdown` 注册启动/停止回调。

**Rationale**:
- NoneBot Driver 提供标准生命周期钩子，在机器人初始化完成后触发 startup，关闭前触发 shutdown。
- 项目已使用类似 decorator 模式（APScheduler `@scheduler.scheduled_job`）。
- startup 中创建 asyncio Task 启动 uvicorn；shutdown 中设置退出信号并等待 task 完成。

**Alternatives considered**:
- APScheduler 事件监听: 间接依赖。
- 手动在 `__init__.py` 中调用: 时机不可靠。

---

## R3: 共享状态安全读取策略

**Decision**: 同步快照读取（snapshot pattern）——在 API handler 中直接读取模块级变量和 dataclass 字段。

**Rationale**:
- Python asyncio 单线程协作式调度：handler 中没有 `await` 的代码段是原子的。
- `ConversationState` 字段都是 Python 原生类型，读取 `.copy()` 或长度/值不会出现撕裂读。
- 队列消息摘要采集时调用 `.copy()` 获取快照，后续处理在副本上进行。

**Alternatives considered**:
- `asyncio.Lock`: 过度设计，且阻塞正常对话流程。
- 深拷贝全部状态: 浪费内存。

---

## R4: API 端点路径与结构设计

**Decision**: 使用 `/debug/api/{module}` 路径前缀，每个端点返回固定结构的 JSON dict。

**Rationale**:
- 与 004-debug-panel-v2 的 `/debug/panel` 共用 `/debug` 前缀，形成统一命名空间。
- 7 个端点对应 6 个模块 + 1 个聚合 summary。

---

## R5: 端口绑定失败处理

**Decision**: 捕获 `OSError` 后记录 WARNING 日志并跳过服务器启动，不抛出异常。

**Rationale**: 调试服务器是辅助功能，端口冲突不应阻止机器人启动（FR-011）。

---

## Summary

| # | 决策点 | 选择 |
|---|--------|------|
| R1 | HTTP 服务器嵌入 | `uvicorn.Server` + `asyncio.create_task` 同循环运行 |
| R2 | 生命周期钩子 | `nonebot.get_driver().on_startup` / `on_shutdown` |
| R3 | 状态安全读取 | 同步快照读取，不加锁 |
| R4 | API 路径设计 | `/debug/api/{module}` 前缀，7 个模块化端点 |
| R5 | 端口冲突处理 | 捕获 OSError + WARNING 日志 + 优雅降级 |
