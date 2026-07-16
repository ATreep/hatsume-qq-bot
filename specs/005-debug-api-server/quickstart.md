# Quickstart: 调试 API 服务器

**Feature**: 005-debug-api-server

## 使用方式

调试 API 服务器随 NoneBot 自动启动，无需手动操作。

### 获取状态摘要

```bash
curl http://127.0.0.1:8899/debug/api/summary
```

### 查看特定模块

```bash
curl http://127.0.0.1:8899/debug/api/state     # 会话状态
curl http://127.0.0.1:8899/debug/api/queues    # 消息队列（默认 20 条）
curl "http://127.0.0.1:8899/debug/api/queues?limit=5"  # 最近 5 条
curl http://127.0.0.1:8899/debug/api/memory    # 记忆系统
curl http://127.0.0.1:8899/debug/api/tools     # 工具调用
curl http://127.0.0.1:8899/debug/api/config    # 配置快照
curl http://127.0.0.1:8899/debug/api/health    # 健康指标
```

### 自定义端口和地址

在 `.env.prod` 或环境变量中设置：

```bash
DEBUG_HOST=0.0.0.0    # 允许远程访问（默认 127.0.0.1）
DEBUG_PORT=8080        # 自定义端口（默认 8899）
DEBUG_ENABLED=false    # 禁用调试服务器
```

### 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEBUG_ENABLED` | `true` | 是否启用调试服务器 |
| `DEBUG_HOST` | `127.0.0.1` | 监听地址 |
| `DEBUG_PORT` | `8899` | 监听端口 |

## 故障排除

- **端口被占用**: 查看启动日志中的 WARNING 信息
- **远程无法访问**: 确认 `DEBUG_HOST=0.0.0.0` 且防火墙放行
- **响应慢**: 本地访问应 <50ms；远程访问考虑网络延迟

## 注意事项

- 默认仅监听 `127.0.0.1`，生产环境勿开放公网
- `/debug/api/config` 中 API 密钥仅显示 bool 存在性，不暴露值
- 与 HTML 调试面板 (`/debug/panel`) 共用 FastAPI 应用实例
