# Hatsume - QQ 群聊 AI 机器人

## 这是什么

Hatsume 是一个面向 QQ 群聊的 AI 机器人，运行于 Python 3.12+，以 NoneBot2 插件形式通过 OneBot V11 接入 QQ。项目使用 LangGraph 编排多轮对话：同一群内串行处理，不同群可并行；长期记忆、自动回复 Timer、可变 Skill、角色代理、后台 Agent 和点赞均按群隔离。SQLite 保存长期记忆与定时任务；拥有长期记忆的群会进入进程内 activated-group 集合，用于自动回复排期和新成员欢迎。消息管线统一解析回复、合并转发和 QQ 系统表情，并把收发图片按群缓存供回复引用。自动回复只在目标群没有进行中对话时注入。机器人还提供多模态消息、联网搜索、容器内本地 Shell、图片与视频生成、群成员搜索和白名单群聊互动等能力。

核心代码位于 `hatsume/plugins/hatsume-plugin/`。完整功能、运行流程、模块职责和测试索引见 `docs/arch.md`。

## 开源仓库说明

> [!WARNING]
> 本仓库不能直接启动生产 Bot。公开版本不包含运行所需的 API Key、必要的 `data/` 运行数据，以及预构建的 Docker 镜像和容器。

这些缺失项不会影响本地依赖安装、源码开发和单元测试。涉及真实 QQ、模型供应商、媒体服务、macOS Photos 或 Docker 运行环境的功能，需要维护者自己的私有配置与运行资产才能联调。

## 当前容器化运行副本

当前部署副本运行在 `hatsume-containerization` 容器中，默认工作目录为 `/work`，home 目录为 `/root`，项目目录挂载到 `/work/hatsume`，容器时区固定为 `Asia/Shanghai`（UTC+8）。Shell 工具、后台 Agent 和媒体文件操作都在同一容器内执行，并继续按群追踪进程与 stdin 所有权。NapCat 通过 `shared-net` 的 Docker DNS 连接 `ws://hatsume-containerization:6999/onebot/v11/ws`。

容器 PID 1 使用 `/work/hatsume/.container/supervise.sh` 启动 NoneBot。自我进化流程在完成功能修改与聚焦测试后自动运行 `hatsume-restart` 请求重启（无需用户确认）；重启前会检查是否存在未完成的 Agent，存在则创建或复用唯一的“重启等候”Todo，仅当收到 Agent 运行完成报告且当前没有任何正在运行的 Agent 时完成 Todo 并重启，否则保持未完成且不重启，不存在则直接重启。supervisor 会重新从当前源码启动进程。具体约束由 `data/hatsume-plugin/skills/self-evolution.md` 提供给运行时 Agent。

要从预构建镜像归档启动容器并自动运行 bot，可在项目根目录执行：

```bash
./start_hatsume_container.sh
```

脚本会加载镜像归档、创建或复用 `shared-net`、删除旧的 `hatsume-containerization` 容器，并将当前项目目录挂载到 `/work/hatsume`。迁移时还会清理上一版误创建的 `hatsume-space` 运行容器；镜像名称仍为 `hatsume-space:1.0`。镜像归档路径可通过 `HATSUME_IMAGE_ARCHIVE` 覆盖，启动超时可通过 `HATSUME_START_TIMEOUT_SECONDS` 调整。

## 使用 Codex 或 Claude Code 开发

本项目采用 coding agent 驱动的开发方式，建议所有贡献都由 Codex 或 Claude Code 完成，不建议脱离 coding agent 直接手工修改代码。Agent 会依据仓库规则检查模块边界、保护运行数据，并执行与改动范围匹配的测试。

### 环境准备

- Python 3.12+
- Node.js 与 npm
- Git

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci
```

### 让 Agent 读取项目上下文

使用 Codex 或 Claude Code 时，让 Agent 按以下顺序读取：

1. `AGENTS.md`
2. `docs/arch.md`
3. 修改目录内更具体的 `AGENTS.md`，例如运行时代码下的 `hatsume/plugins/hatsume-plugin/AGENTS.md` 或测试目录下的 `tests/AGENTS.md`
4. 对应功能在 `specs/` 与 `docs/superpowers/` 中的历史规格和设计记录

向 Agent 描述目标、预期行为和允许修改的范围即可。要求它先检查当前工作树与相关源码，保留无关改动，先运行聚焦测试，再执行完整检查。

### 验证

聚焦测试应根据改动模块选择，例如：

```bash
.venv/bin/python -m pytest tests/test_graph_nodes.py tests/test_tools.py -q
```

完成修改后运行：

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

不得忽略测试收集错误、资源警告或类型错误来制造绿色结果。
