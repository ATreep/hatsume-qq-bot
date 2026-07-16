# Quickstart: 实时调试监控面板

**Feature**: 003-debug-monitor-panel

## 前置条件

- Python 3.12
- NoneBot2 项目已有 FastAPI 驱动（`.env.prod` 中 `DRIVER=~fastapi`）
- 项目依赖已安装

## 启动

```bash
# 正常启动机器人，调试面板自动注册
nb run
```

启动后访问: `http://localhost:6999/hatsume-debug/`

## 快速验证

1. 打开 `http://localhost:6999/hatsume-debug/`
2. 确认左上角连接状态显示绿色圆点 "connected"
3. 观察左侧列出 6 个模块（conv_state, ai_node, tools, memory, infra, night_comic）
4. 点击 "conv_state" 查看会话状态变量
5. 触发机器人对话 → 观察 `is_chatting` 变为 true 并闪烁

## 自定义轮询间隔

```
http://localhost:6999/hatsume-debug/?interval=200   # 200ms
http://localhost:6999/hatsume-debug/?interval=2000  # 2s
```

## 运行测试

```bash
pytest tests/test_debug.py -v
```

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 页面 404 | 插件未加载 | 检查 `__init__.py` 是否调用 `setup_debug_panel` |
| WebSocket 断开 | app 对象错误 | 确认使用 `nonebot.get_app()` |
| 变量显示 `—` | 采集器异常 | 查看终端 `[debug]` 日志 |
| 样式异常 | 浏览器不兼容 | Chrome 76+ / Firefox 103+ / Safari 9+ |
