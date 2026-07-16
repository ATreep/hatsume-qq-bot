# Research: 调试面板 v2

**Feature**: 004-debug-panel-v2

## R1: 队列消息摘要格式

**Decision**: 采集器返回 `[{user, content, time}]` 数组，截断 50 字，最多 20 条
**Rationale**: 50 字判断消息意图，20 条覆盖典型对话窗口

## R2: JSDoc 类型注解

**Decision**: 内联 `@type` + `@typedef`，不引入 TS 编译器
**Rationale**: 单文件零编译，VS Code 原生支持

## R3: Dashboard 状态派生

**Decision**: 纯前端从 snapshot 派生，不新增采集器
**Rationale**: 所有 Dashboard 指标可从现有变量计算

## R4: 移动端响应式

**Decision**: CSS `@media (max-width: 767px)`，侧栏变底部 Tab
**Rationale**: 简单可靠，无需 JS 框架

## R5: 搜索筛选

**Decision**: `String.includes()` 实时过滤，200ms debounce
**Rationale**: ~25 变量无需索引
