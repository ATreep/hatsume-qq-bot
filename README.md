# Hatsume - QQ 群聊 AI 机器人

## 这是什么

Hatsume 是一个面向 QQ 群聊的 AI 机器人，运行于 Python 3.12+，以 NoneBot2 插件形式通过 OneBot V11 接入 QQ。项目使用 LangGraph 编排多轮对话，使用 SQLite 保存长期记忆与定时任务，并提供多模态消息、联网搜索、图片与视频生成、Docker 沙盒、后台 Agent、运行时 Skill、群成员搜索和群聊互动等能力。

核心代码位于 `hatsume/plugins/hatsume-plugin/`。完整功能、运行流程、模块职责和测试索引见 `docs/arch.md`。

## 开源仓库说明

> [!WARNING]
> 本仓库不能直接启动生产 Bot。公开版本不包含运行所需的 API Key、必要的 `data/` 运行数据，以及预构建的 Docker 镜像和容器。

这些缺失项不会影响本地依赖安装、源码开发和单元测试。涉及真实 QQ、模型供应商、媒体服务、macOS Photos 或 Docker 运行环境的功能，需要维护者自己的私有配置与运行资产才能联调。

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
