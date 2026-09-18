# 群聊消息记录库（message-db）设计

日期：2026-09-11
状态：设计已确认，待实现

## 1. 背景与目标

Hatsume 目前只有两类"消息"持久化：

- `memory-db`：由模型主动输出的 `[memory: ...]` 记忆卡，是**被提炼过的结论**，不是原始聊天记录。
- `ConversationState` 的内存队列（`idle_queue` / `pending_queue` / `human_queue`）：进程重启即丢失，且只覆盖当前对话窗口。

结果是 bot 无法回答"上周群里聊过什么""谁提过那家店"这类需要**回看原始聊天记录**的问题。

本设计新增一个按群隔离的 SQLite 消息库 `message-db`，记录 bot 能观察到的群消息原文，并为 chat_agent 提供一个检索工具 `search_history_messages`，让它能浏览当前群的历史聊天记录。

### 目标

- 记录所有 bot 能看到的群消息（含旁听的、非 @ 的消息）。
- 记录 bot 自己**通过 `ai_answer` 成功发出**的消息。
- 图片只存沙盒内绝对路径，以 Markdown 内联进正文。
- 提供限定当前群的关键词 / 发言人 / 时间范围检索工具。

### 非目标（YAGNI）

- 不做消息摘要、向量化或语义检索（现有 `find_memory` 已覆盖语义场景）。
- 不做自动过期清理（已确认永久保留）。
- 不记录表情、`@`、合并转发的结构化字段（折叠进正文即可）。
- 不记录命令消息（`/todo`、`/timer` 等），它们是 bot 命令而非群聊内容。

## 2. 已确认的设计决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 内容粒度 | 仅文本 + 图片 | 结构最简，够用 |
| 图片存法 | 内联进 `content` 的 `![图片](路径)` | 与 `get_human_message` 现有渲染方式一致，无需额外列 |
| 原始 URL | 不保留，仅沙盒路径 | 已确认；路径可能随 `/tmp` 失效 |
| 保留策略 | 永久保留，不清理 | 已确认 |
| 搜索条件 | 关键词 + 发言人 QQ + 起止时间 | 覆盖"翻聊天记录"主场景 |
| 时间参数 | `start_time` / `end_time` 字符串（`YYYY-MM-DD HH:MM`） | 最灵活 |
| 工具名 | `search_history_messages` | 语义清晰 |
| bot 消息 `sender_name` | 固定字符串 `初芽` | 零解析、零失败 |

## 3. 数据模型

**库位置**：`data/hatsume-plugin/message-db/message.db`

经 `nonebot_plugin_localstore.get_plugin_data_file("message-db/message.db")` 解析，与 `todo-db`、`memory-db`、`timer-v2-db` 同构。

### 主表 `messages`

| 字段 | 类型 | 约束 / 说明 |
|---|---|---|
| `id` | INTEGER | `PRIMARY KEY AUTOINCREMENT` |
| `group_id` | INTEGER | `NOT NULL CHECK(group_id > 0)`。**消息来源群号**，所有检索按此隔离 |
| `role` | TEXT | `NOT NULL CHECK(role IN ('user','assistant'))`，区分群友与 bot |
| `sender_qq_id` | INTEGER | `NOT NULL`。发送者 QQ；bot 消息为 `BOT_QQ_ID` |
| `sender_name` | TEXT | `NOT NULL`。发送时解析的昵称快照（昵称会变，故冗余存储） |
| `content` | TEXT | `NOT NULL`。纯文本正文，图片以 `![图片](/tmp/...)` 内联；`@`、QQ 表情、合并转发摘要已折叠 |
| `reply_to_message_id` | INTEGER | `NULL` 允许。被回复消息的 QQ `message_id` |
| `platform_message_id` | INTEGER | `NULL` 允许。本条 QQ `message_id`，用于幂等去重 |
| `created_at` | REAL | `NOT NULL`。消息发生时间（epoch 秒） |
| `inserted_at` | REAL | `NOT NULL`。落库时间 |

### 索引

```sql
CREATE INDEX IF NOT EXISTS idx_messages_group_created
    ON messages(group_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_messages_group_sender
    ON messages(group_id, sender_qq_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_group_platform
    ON messages(group_id, platform_message_id)
    WHERE platform_message_id IS NOT NULL;
```

- `group_created`：按时间倒序浏览主路径。
- `group_sender`：按发言人过滤。
- `group_platform`：部分唯一索引，重试发送 / 重复事件不产生重复行。

### 连接与 schema 守卫

沿用 `todo/store.py` 的做法：

- `sqlite3.connect(path, check_same_thread=False)`，`row_factory = sqlite3.Row`
- `PRAGMA busy_timeout=5000`、`PRAGMA journal_mode=WAL`、`PRAGMA foreign_keys=ON`
- 打开已存在的库时校验表名集合与列集合，不符即 `RuntimeError("incompatible message database schema")`
- 写入用 `BEGIN IMMEDIATE` 事务；单事件循环线程访问，无需额外锁

## 4. 写入时机

### 4.1 群友消息

钩子位置：`handlers/dialogue.py::get_human_message()` 返回前。

该函数是唯一的群消息解析入口（`user_chat_handle` 的两条路径——旁听 auxiliary 与待处理 pending——都经过它），且 `user_chat = on_message(priority=100)` 无 rule，对每条群消息都触发，因此**所有 bot 能看到的群消息都会入库**。

- `group_id` = `event.group_id`
- `role` = `'user'`
- `sender_qq_id` = `event.user_id`
- `sender_name` = `get_group_member_name(...)` 结果
- `content` = 解析出的 `plain_message`（含内联图片 Markdown）
- `reply_to_message_id` = `event.reply.message_id`（若有）
- `platform_message_id` = `event.message_id`
- `created_at` = 解析时点 `time.time()`

守卫：`event.user_id == event.self_id` 时跳过，避免回声重复。

### 4.2 bot 消息

钩子位置：`handlers/dialogue.py::_send_group_ai_message()` **发送成功之后**。

该函数是文本 / `send_image` / 人脸图 / `send_video` 全部 `ai_answer` 调用的唯一出口：

```
ai_answer → ai_cb → handle_ai_message → _send_group_ai_message → bot.send_group_msg
```

- 仅在 `bot.send_group_msg(...)` 成功后落库，失败 / 重试不落库。
- 新增 `record: bool = True` 参数；`handle_ai_message` 的"电波受到干扰…"错误提示传 `record=False`。
- `role` = `'assistant'`
- `sender_qq_id` = `BOT_QQ_ID`
- `sender_name` = `初芽`（固定常量）
- `content` = 由 `segments` 拼出的文本；图片段替换为 `![图片](沙盒路径)`
- `platform_message_id` = `send_result["message_id"]`
- `reply_to_message_id` = 传入的 `reply_to_message_id`

图片路径来源：`_cache_sent_images()` 已经把发出的图片落到沙盒（`save_sandbox_user_image` 返回路径），但目前丢弃返回值。改为返回路径列表供记录使用。

### 4.3 容错

写入一律 `try/except` 只打印日志，绝不向上抛出，不打断对话主流程（与 `_dispatch_message_hooks` 的容错方式一致）。

## 5. 搜索工具 `search_history_messages`

**注册**：加入 `graph/tools.py` 的 `CHAT_TOOLS`（唯一注册点），随 `get_chat_tools()` 暴露给 chat_agent。

**群隔离**：工具内部用 `get_current_group_id()` 取当前群，**不暴露群号参数**，模型无法跨群检索。

**参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `keyword` | `str \| None` | 对 `content` 做 `LIKE %kw%`（中文用 LIKE，与 memory 引擎既有策略一致） |
| `sender_qq_id` | `int \| None` | 只看某人发言；看 bot 自己发言传 `BOT_QQ_ID` |
| `start_time` | `str \| None` | 起始时间，`YYYY-MM-DD HH:MM` |
| `end_time` | `str \| None` | 结束时间，`YYYY-MM-DD HH:MM` |
| `limit` | `int` | 默认 20，上限 50 |

**排序与返回**：按 `created_at DESC, id DESC` 取最多 `limit` 条，再按时间正序拼成文本：

```
[2026-09-11 22:30:01] 张三(10001): 今晚吃啥 ![图片](/tmp/hatsume-user-images/123/456-1.jpg)
[2026-09-11 22:30:15] 初芽(99999): 火锅走起
```

无结果返回中文提示串。返回体附带说明"图片路径位于沙盒 `/tmp`，可能已失效，需要时请重新获取"。

**工具描述（面向模型）**：引导在"用户询问之前聊过什么 / 回忆某件事 / 谁说过什么"时调用；说明只检索本群。

**参数非法处理**：时间格式错误或 `limit` 越界时返回中文提示串，不抛异常。

## 6. 文件结构

```
hatsume/plugins/hatsume-plugin/
├── message_db/
│   ├── __init__.py          # 暴露 MessageStore / MessageRecord / parse_local_time / get_store() 懒加载单例
│   └── store.py             # MessageStore(init_db/close/insert_message/search_messages) + _validate_schema
├── message_render.py        # build_bot_record_content()：纯函数，把发出的 segments 渲染成入库正文
├── graph/tools.py           # 新增 search_history_messages，追加进 CHAT_TOOLS
├── handlers/dialogue.py     # get_human_message 末尾 + _send_group_ai_message 成功后 两处写入钩子
└── config.py                # 新增 BOT_DISPLAY_NAME = "初芽"

data/hatsume-plugin/message-db/message.db   # 运行时自动创建
```

`message_db/__init__.py` 照抄 `todo/__init__.py` 的懒加载单例写法（`get_store()` 内 `init_db()`，失败即 `close()` 并抛出）。

### 实现期调整

- **正文渲染抽成独立模块**：`build_bot_record_content()` 放在无重依赖的 `message_render.py`，而不是内联在 `handlers/dialogue.py`。原因：`dialogue.py` 的导入图很重（nonebot / PIL / langgraph），内联会导致该纯逻辑无法单测；抽离后可直接单元测试。`dialogue.py` 顶层导入它（仅依赖 stdlib）。
- **存储包保持懒导入**：`dialogue.py` 与 `graph/tools.py` 都在函数内部 `from ..message_db import ...`，与 `todo` / `timer` / `hooks` 的既有约定一致，避免插件入口加载期就拉入 `nonebot_plugin_localstore`。
- **`_cache_sent_images` 改为返回路径**：由 `-> None` 改为 `-> list[str | None]`，按图片顺序对齐，供入库使用。
- **回复回退时清空 `reply_to_message_id`**：回复目标被拒而回退为不带回复的发送时，记录中的 `reply_to_message_id` 置空，避免记录一条并未真正发出的回复关系。
- **`created_at` 取事件时间**：群友消息优先用 `event.time`（真实发送时间），缺失时回退 `time.time()`。

## 7. 测试计划

遵守 `AGENTS.md`：用本地 Python 环境跑 pytest，**不碰 `.venv`**。

新增两个测试文件，镜像 `tests/test_todo_store.py` 的隔离加载风格（stub `nonebot_plugin_localstore`，直接加载目标模块）：

- `tests/test_message_db_store.py`（16 例）
  - 默认路径落在 `message-db/`、schema/索引/WAL/foreign_keys/busy_timeout 断言
  - 重开库幂等、不兼容 schema 被拒
  - 字段往返一致、空昵称回退 QQ 号
  - `(group_id, platform_message_id)` 去重；`platform_message_id` 为空时不去重
  - 群隔离、按时间倒序、关键词 / 发言人 / 时间范围过滤、LIKE 通配符转义
  - `limit` 上限收敛为 50、非法参数抛错、`parse_local_time` 解析
- `tests/test_message_render.py`（6 例）
  - 纯文本、文本+图片（用缓存路径）、图片无路径时跳过、`[视频]` 占位、reply/at 段跳过、多图按序取路径

> 注：`handlers/dialogue.py` 与 `graph/tools.py` 依赖 nonebot / PIL / langchain 等第三方库，本机测试环境不具备，故未做模块级集成测试；写入逻辑通过「纯渲染函数单测 + 存储层单测 + 代码审查」覆盖。

## 8. 已知限制

- **图片路径会失效**：沙盒 `/tmp` 路径在容器重建后失效；库中只保留路径，不保留图片副本或原始 URL。检索结果会提示该限制。
- **命令消息不入库**：`/todo`、`/timer` 等 `block=True` 命令不会进入 `user_chat_handle`，因此不被记录。
- **无清理**：永久保留，DB 会持续增长（参考 `memory.db` 已 59MB）。
- **同步写库**：写入为同步 SQLite 调用，会短暂占用事件循环；与 `todo` / `memory` 现状一致。
