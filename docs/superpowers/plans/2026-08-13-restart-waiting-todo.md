# 重启等候 Todo（Restart-Waiting Todo）与 DeepSeek 备用模型核查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**

1. 主任务：让自动重启路径创建的等待 Todo 忠实满足任务需求 —— 名为「重启等候」，内容与完成条件完整表达"仅当当前没有任何活跃 Agent 时执行重启；否则等待所有 Agent 完成后再执行重启"。核心机制（`evolution.py` 的 `restart_after_self_evolution` / `create_restart_todo` / `_wait_for_agents_then_restart` / `has_unfinished_agents` / todo store 去重）已存在且测试通过，仅需对齐「重启等候」命名与完成条件语义的文本契约。
2. 附带子任务：核查 `api.deepseek.com/deepseek-v4-flash` 是否已配置为 `deepseek-v4-flash-free` 出错时的备用模型（fallback model）；已配置则报告确认，未配置则补齐。

## 调研结论（2026-08-13）

### 主任务现状

- 唯一程序化自动重启路径：`hatsume/plugins/hatsume-plugin/evolution.py::restart_after_self_evolution`（未跟踪新文件）：
  - 检查（ruff/pyright/pytest 退出码）通过且无未完成 Agent → 直接 `request_bot_restart()`；
  - 有未完成 Agent → `create_restart_todo()` 创建 Todo（content=`RESTART_TODO_CONTENT`，finish_condition=`RESTART_TODO_COMPLETION_EVENT`）→ `_wait_for_agents_then_restart()` 轮询等待 → 全部完成后 `mark_item` 标记完成 → 重启。
- 去重：todo store（`todo/store.py`）唯一索引 `(group_id, initiator_qq_id, content, finish_condition)` + `create_item` duplicate 检测；`request_bot_restart` 另有 `_restart_in_flight` 并发去重。
- Agent 活跃判定：`evolution.py::has_unfinished_agents` → `graph/agents.py::get_unfinished_agent_instances`（status=running 实例 + 未完成任务，跨全部群）。
- 契约文本已就位：根/插件 `AGENTS.md`（Self-Hosted Runtime #6）、运行时 skill `data/hatsume-plugin/skills/self-evolution.md`、`tests/test_self_evolution_runtime.py` 均描述"未完成 Agent → 创建 Todo（完成条件『所有 Agent 执行完毕后自动重启』）→ 等待 → 重启；无则直接重启"。
- 测试：`tests/test_self_evolution_auto_restart.py`（未跟踪）+ `tests/test_container_lifecycle.py` 共 41 个测试全部通过。
- **差距**：`RESTART_TODO_CONTENT = "自我进化改动待生效：等待所有 Agent 执行完毕后自动重启"` —— 不含「重启等候」命名，未显式表达"仅当当前没有任何活跃 Agent 时执行重启"（需求 1/3 的字面契约）。该常量无任何测试断言其值，可安全调整。

### 附带子任务现状（deepseek 备用模型）

- `config.py`（未提交工作区改动）：已定义 `DEEPSEEK_V4_FLASH = "deepseek-v4-flash-free"` 与 `DEEPSEEK_V4_FLASH_FALLBACK = "deepseek-v4-flash"`（注释：code 模型出错时的备用模型名）。
- `models.py`（未提交工作区改动）：已实现 `_CodeModelWithFallback(BaseChatModel)`（primary/fallback 字段，`_generate`/`_agenerate` 出错自动切换），`get_code_model()` 返回 primary=OpenCode Zen（`OPENCODE_ZEN_BASE_URL` + `OPENCODE_API_KEY`）的 `deepseek-v4-flash-free`、fallback=官方 DeepSeek（`DS_BASE_URL` + `DS_API_KEY`）的 `deepseek-v4-flash`。非 code 工厂保持 plain。
- `tests/test_code_model_fallback.py`（已提交，RED→GREEN 契约测试）：单独运行通过；全量运行曾出现 1 次失败（顺序敏感，第二次全量通过）。
- **遗留破损**：`tests/test_reasoning_content.py` 的 config stub 缺 `DEEPSEEK_V4_FLASH_FALLBACK`、`WAWAPI_IMAGE_API_KEY`（models.py 现在导入它们）→ ImportError 失败（基线 1 个）。最小修复：stub 补 2 个属性，不改任何断言。
- 结论：**备用模型配置已存在（常量+实现+测试），本次仅需报告确认 + 修复遗留 stub 破损**。

### 基线失败（与本任务无关，如实记录，不修）

全量 `pytest tests -q`：98 failed / 640 passed / 14 skipped（两次运行间 `test_code_model_fallback.py` 有 1 次顺序敏感失败）。
- `test_tools.py` 84（stub 与工作区 `graph/tools.py` 不兼容，ImportError 类）
- `test_omni_model.py` 4、`test_membersearch.py` 3、`test_image_pack.py` 2、`test_timer_schedule.py` 1、`test_auto_response.py` 1
- `test_config.py` 2（`PROVIDER`/`ADVANCE_MODEL_NAME` 契约漂移：测试期望 ds/deepseek，工作区为 zhth/gpt-5.6-luna）
- `test_reasoning_content.py` 1（stub 缺 2 属性 → 本次修复）

---

### Task 1: TDD RED —— 「重启等候」Todo 契约测试（主任务）

**Files:**
- Modify: `tests/test_self_evolution_auto_restart.py`

- [ ] **Step 1: 在 `TestUnfinishedAgentsDeferRestart` 增加契约断言**

在 `test_unfinished_agents_create_todo_and_defer_restart` 中补充断言（或新增一个测试）：
- `items[0]["content"]` 含「重启等候」；
- `items[0]["content"]` 表达"仅当当前没有任何活跃 Agent 时执行重启"与"等待所有 Agent 完成后自动重启"两层语义。

- [ ] **Step 2: 运行聚焦测试记录 RED**

`.venv/bin/python -m pytest tests/test_self_evolution_auto_restart.py -q` —— 新断言失败（content 不含「重启等候」）。

### Task 2: GREEN —— 调整 `RESTART_TODO_CONTENT`（主任务）

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/evolution.py`

- [ ] **Step 1: 更新常量**

`RESTART_TODO_CONTENT` 改为：`"自我进化重启等候：仅当当前没有任何活跃 Agent 时执行重启；否则等待所有 Agent 完成后自动重启"`
（`RESTART_TODO_COMPLETION_EVENT` / `RESTART_TODO_PERMITTED_FINISHER` 保持不动；返回文本与 finish_condition 断言不受影响）。

- [ ] **Step 2: 运行聚焦测试确认 GREEN**

`.venv/bin/python -m pytest tests/test_self_evolution_auto_restart.py tests/test_self_evolution_runtime.py -q` 全绿。

### Task 3: 附带子任务收尾 —— 修复 `test_reasoning_content.py` stub（最小改动）

**Files:**
- Modify: `tests/test_reasoning_content.py`

- [ ] **Step 1: stub 补 2 个 config 属性**

`config_mod.DEEPSEEK_V4_FLASH_FALLBACK = "deepseek-v4-flash"`、`config_mod.WA WAPI_IMAGE_API_KEY = "test-key"`（与 `test_code_model_fallback.py` 的 stub 约定一致）。不改断言。

- [ ] **Step 2: 验证**

`.venv/bin/python -m pytest tests/test_reasoning_content.py tests/test_code_model_fallback.py -q` 全绿。

### Task 4: 全量验证与报告

- [ ] **Step 1: 聚焦测试**：`test_self_evolution_auto_restart.py` + `test_container_lifecycle.py` + `test_self_evolution_runtime.py` + `test_code_model_fallback.py` + `test_reasoning_content.py`
- [ ] **Step 2: ruff**：`.venv/bin/ruff check hatsume/plugins/hatsume-plugin`
- [ ] **Step 3: pyright**：`npx --no-install pyright`
- [ ] **Step 4: 全量 pytest**：`.venv/bin/python -m pytest tests -q`，对比基线
- [ ] **Step 5: 报告**：git status 确认仅修改目标文件、保留所有既有未提交改动；不提交、不推送、不创建分支。
