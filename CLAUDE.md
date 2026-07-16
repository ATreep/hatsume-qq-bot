# Hatsume Claude Code Guide

本文件是 Claude Code 在 Hatsume 仓库中的工作入口。项目简介与开发方式位于 `README.md`；完整功能、架构和所有 Python 模块说明以 `docs/arch.md` 为准；通用 Agent 规则位于 `AGENTS.md`；运行时代码还受 `hatsume/plugins/hatsume-plugin/AGENTS.md` 约束，测试代码还受 `tests/AGENTS.md` 约束。

## Project Summary

Hatsume 是 Python 3.12+ 的 NoneBot2 / OneBot V11 QQ 群聊机器人。核心能力包括：

- LangGraph 多轮对话、@/关键词触发、消息防抖、旁听上下文和自动结束判断。
- 文本、回复、图片、多模态输入与递归合并转发解析。
- SQLite 长期记忆、显式记忆标签、BM25 + BGE-M3 混合检索、150 天清理。
- SQLite + APScheduler 定时任务、重启恢复、漏触发补偿、自动创作与自动回复。
- 联网搜索、图片/视频生成、图片发送、QQ 头像、成员搜索和随机 ACG 图片。
- Docker Shell、编码 Agent、后台 Shell Agent、中间通知和交互式 stdin。
- Markdown 图片化、QQ 点赞、排行榜、Skill 动态加载/创建/下载/删除和密钥脱敏。

## Read Order

1. `README.md`：项目简介、开源仓库限制与 Agent 开发方式。
2. `AGENTS.md`：仓库级所有权、不变量、扩展规则和 Git 规则。
3. `docs/arch.md`：完整功能、命令、模块索引以及已验证的图、队列、持久化和并发流程。
4. `hatsume/plugins/hatsume-plugin/AGENTS.md` 或 `tests/AGENTS.md`：目录级规则。

## Runtime Module Map

- `hatsume/plugins/hatsume-plugin/__init__.py`：插件启动、matcher、@ 检测修补、记忆初始化、Timer 恢复。
- `hatsume/plugins/hatsume-plugin/config.py`：环境、模型、限流、队列、记忆、Timer、Docker 和 Skill 常量。
- `hatsume/plugins/hatsume-plugin/state.py`：`ConversationState` 和会话可变状态。
- `hatsume/plugins/hatsume-plugin/models.py`：运行时高级模型选择、LLM/Embedding/图片/视频工厂与 LangChain 消息兼容补丁。
- `hatsume/plugins/hatsume-plugin/prompts.py`：角色、图节点、Agent、自动任务与 Shell 决策 Prompt。
- `hatsume/plugins/hatsume-plugin/infra.py`：Docker 前台/后台进程、stdin、超时、引用计数和延迟停止。
- `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`：OneBot 消息标准化、图片输入、队列、防抖、图启动、发送重试。
- `hatsume/plugins/hatsume-plugin/handlers/forward.py`：合并转发兼容与递归解析。
- `hatsume/plugins/hatsume-plugin/handlers/tools.py`：命令、戳一戳、Timer 管理、/model、Agent 查询和对话清理。
- `hatsume/plugins/hatsume-plugin/handlers/social.py`：点赞与排行榜。
- `hatsume/plugins/hatsume-plugin/handlers/__init__.py`：handlers 包说明。
- `hatsume/plugins/hatsume-plugin/graph/builder.py`：LangGraph 组装与条件路由。
- `hatsume/plugins/hatsume-plugin/graph/nodes.py`：Human/Detect/AI/Finish、记忆、辅助上下文、Agent/Timer 通知。
- `hatsume/plugins/hatsume-plugin/graph/tools.py`：全部聊天工具和 `CHAT_TOOLS` 注册。
- `hatsume/plugins/hatsume-plugin/graph/agents.py`：Agent 注册表、实例状态、coding/background-shell 和 stdin。
- `hatsume/plugins/hatsume-plugin/graph/__init__.py`：graph 包说明。
- `hatsume/plugins/hatsume-plugin/memory/engine.py`：记忆 SQLite、迁移、索引、写入、检索、每日维护。
- `hatsume/plugins/hatsume-plugin/memory/tokenizer.py`：Jieba 词性分词。
- `hatsume/plugins/hatsume-plugin/memory/__init__.py`：记忆 API 导出。
- `hatsume/plugins/hatsume-plugin/timer/store.py`：Timer 表、CRUD、特殊任务和验证。
- `hatsume/plugins/hatsume-plugin/timer/executor.py`：APScheduler 作业、恢复、补偿和图注入。
- `hatsume/plugins/hatsume-plugin/timer/__init__.py`：TimerStore 单例与启动恢复。
- `hatsume/plugins/hatsume-plugin/skills/manager.py`：Skill frontmatter、扫描、缓存、去重和增删。
- `hatsume/plugins/hatsume-plugin/skills/__init__.py`：SkillManager 单例。
- `hatsume/plugins/hatsume-plugin/utils/__init__.py`：QQ 辅助、消息 JSON 和成员搜索。
- `hatsume/plugins/hatsume-plugin/utils/md_to_image.py`：Markdown/公式/代码渲染与链接保留。
- `hatsume/plugins/hatsume-plugin/utils/security.py`：API Key 脱敏。

## Key Logic

### Conversation

`handlers/dialogue.py` 把 QQ 事件转换为统一 JSON/多模态内容。非活跃对话进入 idle 队列；活跃会话消息进入 pending 队列并等待 10 秒合并；LangGraph 运行中新增消息进入 human 队列；其他群友消息进入 `graph/nodes.py` 的 auxiliary 队列。图按 `human → chat_end_detect → chat_llm → human` 循环，5 分钟无输入或结束检测返回 yes 后进入 finish。

### Memory

长期记忆不是完整聊天自动归档。只有模型输出 `[memoryrecord: ...]` 时，`graph/nodes.py` 才会调用 `memory/engine.py::add_mem()` 写入 `memory.db`；`[memorykeyman: ...]` 可关联 QQ 用户。检索先查相关用户最近 24 小时记忆，再补充全局候选，并融合 BM25 与向量分数。

### Timers

`timer/store.py` 用 `timer_tasks` 与 `timer_triggers` 保存任务和具体触发时间。创建/更新/删除必须同步 APScheduler。Bot 连接后恢复未来触发器，补偿 5 分钟内漏触发，过早记录标记 fired。触发时统一通过 `graph/nodes.py::inject_timer()` 进入当前或新 LangGraph 对话。

### Agents and Tools

聊天工具只在 `graph/tools.py::CHAT_TOOLS` 注册。后台 Agent 只通过 `graph/agents.py::register_agent()` 注册。Agent 结果使用特殊标记注入图；`background_shell` 的 stdin 请求通过 `respond_to_shell_prompt` 和请求队列回传。

## Non-Negotiable Rules

1. OneBot 实现差异必须在 `handlers/dialogue.py` 或 `handlers/forward.py` 归一化。
2. 新会话状态优先加入 `ConversationState`，并提供初始化、结束和 `/clear` 清理逻辑。
3. 修改图边、队列顺序、模块所有权、持久化表或外部集成时更新 `docs/arch.md`；只有项目简介或开发方式变化时才更新 `README.md`。
4. 新聊天工具加入 `graph/tools.py` 和 `CHAT_TOOLS`；新 Agent 使用 `register_agent()`。
5. SQLite 使用参数化 SQL、显式 commit 和幂等迁移。
6. 不打印、提交或写入文档真实 `.env.prod` 密钥。
7. 不改写 `data/` 数据库、WAL/SHM、likes、Skill、生成图片或 `virtual/script.sh`。
8. 保留所有无关工作树修改，开始和结束都检查 `git status --short`。

## Required Checks

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

先跑聚焦测试，再跑完整检查；不要屏蔽 collection error、resource warning 或类型错误。除非用户明确要求，否则不要创建提交。
