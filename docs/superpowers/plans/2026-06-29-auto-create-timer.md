# Auto Create Timer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the auto-respond feature and add a self-renewing "auto create" special timer task that autonomously executes creative LLM tasks daily.

**Architecture:** Extend the existing timer module with a `task_type` column to distinguish auto_create tasks from normal ones. Auto_create tasks fire, inject into the conversation graph (targeting TARGET_GROUP_ID with user_id=0 for no @-mention), and immediately reschedule themselves for a random time the next day. A `/autocreate` debug command triggers execution immediately without DB modification.

**Tech Stack:** Python 3.12+, NoneBot2, APScheduler, SQLite (via sqlite3), LangGraph

## Global Constraints

- Python 3.12+ with `from __future__ import annotations`
- Lint: ruff (config in `pyproject.toml`)
- Type annotations on all new functions
- snake_case for functions/variables, UPPER_CASE for constants
- Follow existing code patterns (print-style logging, async/await, module-level helpers)
- All new store methods covered by tests in `tests/test_timer_store.py`
- Existing tests must continue to pass after auto-respond removal

---

### Task 1: Remove auto-respond constants from config.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py:103-105`

**Interfaces:**
- Removes: `AUTO_REPLY_CURRENT_MSG_COUNT`, `AUTO_REPLY_HISTORY_MSG_COUNT`, `AUTO_RESPONSE_PROBABILITY`
- Produces: `AUTO_CREATE_GROUP_ID`, `AUTO_CREATE_TIME_START`, `AUTO_CREATE_TIME_END`, `AUTO_CREATE_PROMPT`

- [ ] **Step 1: Delete the three auto-reply constants and add auto-create constants**

In `hatsume/plugins/hatsume-plugin/config.py`, delete lines 103-105:
```python
AUTO_REPLY_CURRENT_MSG_COUNT: int = 10
AUTO_REPLY_HISTORY_MSG_COUNT: int = 20
AUTO_RESPONSE_PROBABILITY: float = 2 / 3
```

Insert at the same location:
```python
# ---------------------------------------------------------------------------
# Auto create timer
# ---------------------------------------------------------------------------
AUTO_CREATE_GROUP_ID: int = TARGET_GROUP_ID  # configured in the environment
AUTO_CREATE_TIME_START: int = 7    # 7:00 AM UTC+8
AUTO_CREATE_TIME_END: int = 22     # 10:00 PM UTC+8
AUTO_CREATE_PROMPT: str = (
    "现在是你的**自主创作时间**！你可以完全自由地使用你拥有的所有工具和技能，\n"
    "做一件你真正感兴趣、有创造性的事情。\n\n"
    "## 你可以做的事情（不限于此）\n\n"
    "1. **GitHub Trending 探索**：使用 web_search 查看今天 GitHub 上的热门仓库，\n"
    "   挑几个你感兴趣的介绍给大家，说说你为什么觉得它们有趣。\n\n"
    "2. **Fork & 改造仓库**：找到一个有意思的开源仓库，fork 它，然后用 shell 执行\n"
    "   Claude Code 对它做一些改进（加功能、修 bug、优化文档等）。\n\n"
    "3. **给仓库 Star**：回忆一下最近对话中提到的 GitHub 仓库，去给它点个 Star 以表支持。\n\n"
    "4. **AI 画图**：使用 generate_image 画一张画，表达你此刻的心情、想法，\n"
    "   或者你想象中的某个有趣场景。\n\n"
    "5. **Shell 创意项目**：用 shell 做一些有趣的事情——\n"
    "   比如用命令行工具生成 ASCII 艺术、分析某个开源项目的代码统计、写个小脚本等。\n\n"
    "6. **搜索 & 学习**：搜索一个你一直好奇的技术话题，学习后用自己的话总结分享给大家。\n\n"
    "7. **任何你想做的事**：只要是你能用工具做到的、你觉得有意义或有趣的，\n"
    "   尽管去做！创意没有边界。\n\n"
    "## 重要提示\n\n"
    "- 这个任务不需要通知或 @ 任何特定用户，这是你自己的创作时间。\n"
    "- 请用第一人称分享你的创作过程和成果，像在写一篇有趣的日记一样。\n\n"
    "## 输出要求\n\n"
    "在完成创作后，你需要向群友们做一个精彩的总结，**必须包含以下三点**：\n\n"
    "1. **动机**：说明你为什么选择做这件事——是因为你对这个领域的兴趣？\n"
    "   还是从最近的聊天记录、历史记忆中获得了灵感？让大家感受到你的「人格」。\n\n"
    "2. **成果展示**：展示你做了什么。如果是 GitHub 仓库，贴出仓库地址让大家去围观；\n"
    "   如果是画作，描述画面和创作理念；如果是研究报告，给出核心发现。\n\n"
    "3. **号召互动**：以分享者的口吻呼吁大家为你的作品点赞或互动！\n"
    "   例如：「如果觉得有趣的话，去 GitHub 给我点个 Star 吧 ⭐」、\n"
    "   「大家觉得这幅画怎么样？告诉我你的感受～」、\n"
    "   「有没有人也对这个话题感兴趣？来聊聊！」"
)
```

- [ ] **Step 2: Verify with ruff**
Run: `ruff check hatsume/plugins/hatsume-plugin/config.py`
Expected: No errors.

- [ ] **Step 3: Commit**
```bash
git add hatsume/plugins/hatsume-plugin/config.py
git commit -m "feat: remove auto-respond constants, add auto-create config

- Remove AUTO_REPLY_CURRENT_MSG_COUNT, AUTO_REPLY_HISTORY_MSG_COUNT, AUTO_RESPONSE_PROBABILITY
- Add AUTO_CREATE_GROUP_ID, AUTO_CREATE_TIME_START, AUTO_CREATE_TIME_END, AUTO_CREATE_PROMPT

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Remove auto-respond from state.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/state.py:6,12,73,110-113`

**Interfaces:**
- Removes: `should_auto_respond()` method, `has_respond_recently` field, `AUTO_RESPONSE_PROBABILITY` import, `random` import

- [ ] **Step 1: Remove AUTO_RESPONSE_PROBABILITY import**

In `state.py`, change lines 11-16 from:
```python
from .config import (
    AUTO_RESPONSE_PROBABILITY,
    CONTEXT_QUEUE_OVERLAP_LEN,
    IMAGE_RATE_LIMIT_SECONDS,
    VIDEO_RATE_LIMIT_SECONDS,
)
```
to:
```python
from .config import (
    CONTEXT_QUEUE_OVERLAP_LEN,
    IMAGE_RATE_LIMIT_SECONDS,
    VIDEO_RATE_LIMIT_SECONDS,
)
```

- [ ] **Step 2: Remove random import and has_respond_recently field**
Delete `import random` (line 6).
Delete `has_respond_recently: bool = False` (line 73).

- [ ] **Step 3: Remove should_auto_respond method**
Delete lines 110-113:
```python
def should_auto_respond(self) -> bool:
    if self.has_respond_recently:
        return False
    return random.random() < AUTO_RESPONSE_PROBABILITY
```

- [ ] **Step 4: Verify and commit**
Run: `ruff check hatsume/plugins/hatsume-plugin/state.py`
```bash
git add hatsume/plugins/hatsume-plugin/state.py
git commit -m "refactor: remove auto-respond from ConversationState

- Remove should_auto_respond() method, has_respond_recently field
- Remove AUTO_RESPONSE_PROBABILITY import, unused random import

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Remove auto-respond branch from handlers/chat.py

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py:13-14,228-275`

**Interfaces:**
- Removes: auto-respond trigger logic, `AUTO_REPLY_*` imports

- [ ] **Step 1: Remove AUTO_REPLY imports**

Change lines 12-18 from:
```python
from ..config import (
    AUTO_REPLY_CURRENT_MSG_COUNT,
    AUTO_REPLY_HISTORY_MSG_COUNT,
    CONTEXT_QUEUE_LEN,
    CONTEXT_QUEUE_OVERLAP_LEN,
    USER_INPUT_CONFIRM_DURING_TIME,
)
```
to:
```python
from ..config import (
    CONTEXT_QUEUE_LEN,
    CONTEXT_QUEUE_OVERLAP_LEN,
    USER_INPUT_CONFIRM_DURING_TIME,
)
```

- [ ] **Step 2: Replace auto-respond branch with simple flush**

Replace the entire `if len(conv_state.idle_queue) >= CONTEXT_QUEUE_LEN:` block (lines 228-275) with:
```python
        if len(conv_state.idle_queue) >= CONTEXT_QUEUE_LEN:
            print("idle queue full, flushing to auxiliary")
            conv_state.flush_idle_to_auxiliary()
        return
```

- [ ] **Step 3: Verify and commit**
Run: `ruff check hatsume/plugins/hatsume-plugin/handlers/chat.py`
```bash
git add hatsume/plugins/hatsume-plugin/handlers/chat.py
git commit -m "refactor: remove auto-respond trigger from chat handler

- Remove AUTO_REPLY_CURRENT_MSG_COUNT and AUTO_REPLY_HISTORY_MSG_COUNT imports
- Replace auto-respond decision + _auto_respond() with simple flush to auxiliary

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add task_type column and auto-create store methods

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/store.py`
- Test: `tests/test_timer_store.py`

**Interfaces:**
- Produces: `TimerStore.upsert_auto_create(trigger_at: float, prompt: str | None = None) -> int`
- Produces: `TimerStore.get_auto_create() -> dict | None`
- Produces: `TimerStore.list_auto_create_triggers() -> list[dict]`
- Modifies: `init_db()` — adds `task_type` column migration

- [ ] **Step 1: Write failing tests**

Add to `tests/test_timer_store.py` after `TestValidatePrompt`:

```python
class TestAutoCreateTask:
    """Auto-create special timer task CRUD."""

    def test_upsert_auto_create_creates_task(self, store):
        now = time.time()
        trigger_at = now + 86400
        task_id = store.upsert_auto_create(trigger_at)
        assert task_id is not None and task_id > 0
        task = store.get_task(task_id)
        assert task is not None
        assert task["task_type"] == "auto_create"
        assert task["group_id"] == 0
        assert task["user_id"] == 0

    def test_upsert_auto_create_ensures_singleton(self, store):
        now = time.time()
        t1 = store.upsert_auto_create(now + 3600)
        t2 = store.upsert_auto_create(now + 7200)
        t3 = store.upsert_auto_create(now + 10800)
        assert store.get_task(t1) is None
        assert store.get_task(t2) is None
        assert store.get_task(t3) is not None
        cur = store._conn.execute(
            "SELECT COUNT(*) as cnt FROM timer_tasks WHERE task_type = 'auto_create'"
        )
        assert cur.fetchone()["cnt"] == 1

    def test_upsert_auto_create_cascades_triggers(self, store):
        now = time.time()
        t1 = store.upsert_auto_create(now + 3600)
        assert len(store.get_triggers_for_task(t1)) == 1
        t2 = store.upsert_auto_create(now + 7200)
        assert store.get_triggers_for_task(t1) == []
        triggers = store.get_triggers_for_task(t2)
        assert len(triggers) == 1
        assert triggers[0]["trigger_at"] == now + 7200

    def test_get_auto_create_returns_none_when_empty(self, store):
        assert store.get_auto_create() is None

    def test_get_auto_create_returns_task(self, store):
        now = time.time()
        trigger_at = now + 86400
        task_id = store.upsert_auto_create(trigger_at)
        result = store.get_auto_create()
        assert result is not None
        assert result["id"] == task_id
        assert result["task_type"] == "auto_create"
        assert result["trigger_at"] == trigger_at

    def test_list_auto_create_triggers(self, store):
        now = time.time()
        store.upsert_auto_create(now + 3600)
        store.create_task(
            group_id=100, user_id=200, prompt="normal",
            trigger_times=[now + 3600],
        )
        triggers = store.list_auto_create_triggers()
        assert len(triggers) == 1
```

Run: `pytest tests/test_timer_store.py::TestAutoCreateTask -v`
Expected: FAIL — methods not defined.

- [ ] **Step 2: Add schema migration in init_db()**

In `timer/store.py`, in `init_db()`, after the `CREATE INDEX` (line 68, before `self._conn.commit()`):

```python
            # Auto-create timer support (safe migration)
            try:
                self._conn.execute(
                    "ALTER TABLE timer_tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'normal'"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists
```

- [ ] **Step 3: Add auto-create store methods**

Add after `delete_task()` (line 154), before `# CRUD: Triggers`:

```python
    # ------------------------------------------------------------------
    # Auto-create special timer
    # ------------------------------------------------------------------

    def upsert_auto_create(
        self, trigger_at: float, prompt: str | None = None,
    ) -> int:
        """Delete all old auto_create tasks and create a new one.

        Guarantees at most one auto_create row in the database.
        Returns the new task_id.
        """
        from ..config import AUTO_CREATE_PROMPT

        self._conn.execute(
            "DELETE FROM timer_tasks WHERE task_type = 'auto_create'"
        )
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO timer_tasks "
            "(group_id, user_id, prompt, created_at, updated_at, task_type) "
            "VALUES (?, ?, ?, ?, ?, 'auto_create')",
            (0, 0, prompt or AUTO_CREATE_PROMPT, now, now),
        )
        task_id = cur.lastrowid
        cur = self._conn.execute(
            "INSERT INTO timer_triggers (task_id, trigger_at) VALUES (?, ?)",
            (task_id, trigger_at),
        )
        trigger_id = cur.lastrowid
        self._conn.execute(
            "UPDATE timer_triggers SET job_id = ? WHERE id = ?",
            (f"timer_{trigger_id}", trigger_id),
        )
        self._conn.commit()
        print(
            f"🎨 [auto_create] Task upserted: id={task_id} "
            f"trigger_at={trigger_at}"
        )
        return task_id

    def get_auto_create(self) -> dict | None:
        """Get the current auto_create task with its pending trigger, or None."""
        row = self._conn.execute(
            "SELECT t.*, tr.trigger_at, tr.id as trigger_id "
            "FROM timer_tasks t "
            "LEFT JOIN timer_triggers tr "
            "  ON tr.task_id = t.id AND tr.fired = 0 "
            "WHERE t.task_type = 'auto_create' "
            "ORDER BY tr.trigger_at LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def list_auto_create_triggers(self) -> list[dict]:
        """Get all unfired triggers for auto_create tasks."""
        rows = self._conn.execute(
            "SELECT tr.* FROM timer_triggers tr "
            "JOIN timer_tasks t ON t.id = tr.task_id "
            "WHERE t.task_type = 'auto_create' AND tr.fired = 0"
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Update schema test + verify**

In `test_tasks_schema_columns`, add after `assert columns["updated_at"] == "REAL"`:
```python
        assert columns["task_type"] == "TEXT"
```

Run: `pytest tests/test_timer_store.py -v`
Expected: All PASS including TestAutoCreateTask.

- [ ] **Step 5: Commit**
```bash
git add hatsume/plugins/hatsume-plugin/timer/store.py tests/test_timer_store.py
git commit -m "feat: add task_type column and auto-create store methods

- Add task_type column migration (safe ALTER TABLE with try/except)
- Add upsert_auto_create(), get_auto_create(), list_auto_create_triggers()
- Add TestAutoCreateTask (6 tests)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Add auto-create executor logic

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py`
- Test: `tests/test_auto_create.py` (new)

**Interfaces:**
- Produces: `_random_next_trigger() -> float`
- Produces: `_execute_auto_create(task: dict, store: TimerStore) -> None`
- Produces: `reschedule_auto_create(store: TimerStore) -> None`
- Produces: `refresh_auto_create(store: TimerStore) -> None`
- Modifies: `_execute_timer()` — branches on `task_type == 'auto_create'`

- [ ] **Step 1: Write failing test for _random_next_trigger**

Create `tests/test_auto_create.py`:

```python
"""Tests for auto-create timer: random trigger generation and execution."""

from __future__ import annotations

import importlib.util
import sys
import time
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


def _ensure_package_hierarchy():
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


def _load_module(short_name: str, **stub_attrs):
    full_name = f"hatsume.plugins.hatsume-plugin.{short_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PLUGIN_DIR / f"{short_name}.py"
    )
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    for k, v in stub_attrs.items():
        setattr(mod, k, v)
    spec.loader.exec_module(mod)
    return mod


def _load_submodule(package_short: str, module_name: str, **stub_attrs):
    full_name = f"hatsume.plugins.hatsume-plugin.{module_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PLUGIN_DIR / package_short / f"{module_name.split('.')[-1]}.py"
    )
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    for k, v in stub_attrs.items():
        setattr(mod, k, v)
    spec.loader.exec_module(mod)
    return mod


_ensure_package_hierarchy()

_cfg = _load_module("config")
_timer_init = _load_submodule("timer", "timer.__init__")
_timer_store = _load_submodule("timer", "timer.store")
sys.modules["hatsume.plugins.hatsume-plugin.timer.store"] = _timer_store
_timer_executor = _load_submodule("timer", "timer.executor")

_random_next_trigger = _timer_executor._random_next_trigger


class TestRandomNextTrigger:
    """Random trigger time generation."""

    def test_returns_tomorrow(self):
        now = datetime.now(timezone(timedelta(hours=8)))
        result_ts = _random_next_trigger()
        result_dt = datetime.fromtimestamp(result_ts, tz=timezone(timedelta(hours=8)))
        tomorrow = now.date() + timedelta(days=1)
        assert result_dt.date() == tomorrow

    def test_time_in_range(self):
        result_ts = _random_next_trigger()
        result_dt = datetime.fromtimestamp(result_ts, tz=timezone(timedelta(hours=8)))
        assert 7 <= result_dt.hour < 22, f"Hour {result_dt.hour} not in [7, 22)"

    def test_random_distribution(self):
        for _ in range(100):
            result_ts = _random_next_trigger()
            result_dt = datetime.fromtimestamp(
                result_ts, tz=timezone(timedelta(hours=8))
            )
            assert 7 <= result_dt.hour < 22
            tomorrow = datetime.now(
                timezone(timedelta(hours=8))
            ).date() + timedelta(days=1)
            assert result_dt.date() == tomorrow
```

Run: `pytest tests/test_auto_create.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement executor additions**

In `executor.py`, add after existing imports:
```python
import random
from datetime import datetime, timezone, timedelta

from ..config import (
    AUTO_CREATE_GROUP_ID,
    AUTO_CREATE_TIME_START,
    AUTO_CREATE_TIME_END,
)
```

Add after `cancel_task_jobs()` (before `# Startup recovery`):

```python
# ---------------------------------------------------------------------------
# Auto Create — random trigger time
# ---------------------------------------------------------------------------

def _random_next_trigger() -> float:
    """Generate a random trigger time for tomorrow between
    AUTO_CREATE_TIME_START:00 and AUTO_CREATE_TIME_END:00 (UTC+8).
    """
    now = datetime.now(timezone(timedelta(hours=8)))
    tomorrow = now.date() + timedelta(days=1)
    start = AUTO_CREATE_TIME_START
    end = AUTO_CREATE_TIME_END
    hour = random.randint(start, end - 1)
    minute = random.randint(0, 59)
    trigger_dt = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day,
        hour, minute, 0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    return trigger_dt.timestamp()


# ---------------------------------------------------------------------------
# Auto Create — execution and lifecycle
# ---------------------------------------------------------------------------

async def _execute_auto_create(task: dict, store: TimerStore) -> None:
    """Execute an auto_create timer: inject into graph, then reschedule."""
    from ..config import AUTO_CREATE_PROMPT
    from ..graph.nodes.ai import inject_timer

    prompt = task.get("prompt") or AUTO_CREATE_PROMPT
    print("🎨 [auto_create] Executing...")
    inject_timer(
        user_id=0,
        group_id=AUTO_CREATE_GROUP_ID,
        timer_prompt=prompt,
        start_conversation_cb=_timer_start_conv_cb,
    )
    reschedule_auto_create(store)


def reschedule_auto_create(store: TimerStore) -> None:
    """Delete old auto_create task and create new one for tomorrow."""
    next_trigger = _random_next_trigger()
    task_id = store.upsert_auto_create(next_trigger)
    triggers = store.get_triggers_for_task(task_id)
    for t in triggers:
        if not t["fired"]:
            register_job(t, store)
    run_dt = datetime.fromtimestamp(next_trigger, tz=timezone(timedelta(hours=8)))
    print(
        f"🎨 [auto_create] Rescheduled: task={task_id} "
        f"next={run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def refresh_auto_create(store: TimerStore) -> None:
    """Called on startup: purge all auto_create tasks and create a fresh one."""
    store._conn.execute("DELETE FROM timer_tasks WHERE task_type = 'auto_create'")
    store._conn.commit()
    reschedule_auto_create(store)
    print("🎨 [auto_create] Startup refresh complete")
```

- [ ] **Step 3: Add task_type branch in _execute_timer**

In `_execute_timer()`, after the `task is None` check, before `group_id = task["group_id"]`:

```python
    # Auto-create tasks take a separate execution path
    if task.get("task_type") == "auto_create":
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_create(task, store)
        return
```

- [ ] **Step 4: Run tests**
Run: `pytest tests/test_auto_create.py::TestRandomNextTrigger -v`
Expected: All 3 PASS.

- [ ] **Step 5: Commit**
```bash
git add hatsume/plugins/hatsume-plugin/timer/executor.py tests/test_auto_create.py
git commit -m "feat: add auto-create executor with random trigger and self-reschedule

- Add _random_next_trigger() — tomorrow 7:00-22:00 random time
- Add _execute_auto_create(), reschedule_auto_create(), refresh_auto_create()
- Branch on task_type in _execute_timer for auto_create routing
- Add TestRandomNextTrigger (3 tests)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Wire startup + inject_timer user_id=0 + /autocreate command

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:160-180`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/commands.py`
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py`

**Interfaces:**
- Modifies: `init_scheduler()` — calls `refresh_auto_create()`
- Modifies: `inject_timer()` — handles `user_id == 0`
- Produces: `handle_autocreate(bot, event, matcher)`
- Registers: `autocreate_cmd` matcher

- [ ] **Step 1: Wire startup refresh**

In `timer/__init__.py`, update `init_scheduler()`:

```python
async def init_scheduler() -> None:
    from .executor import reload_all_triggers, refresh_auto_create

    print("⏰ [timer] Starting scheduler recovery...")
    store = get_store()
    await reload_all_triggers(store)
    await refresh_auto_create(store)
    print("⏰ [timer] Scheduler recovery complete")
```

- [ ] **Step 2: Handle user_id=0 in inject_timer**

In `graph/nodes/ai.py`, replace `inject_timer` body (lines 160-180):

```python
    if user_id == 0:
        timer_msg = (
            f"{TIMER_MARK}:0\n"
            f"(SYSTEM) 自主创作时间已到。\n"
            "以下是你的创作任务，不需要 @ 任何用户，"
            "请以第一人称自由发挥：\n\n"
            f"{timer_prompt}"
        )
        print(f"🎨 [inject_timer] Auto-create: {timer_prompt[:80]}...")
    else:
        user_name = get_group_member_name(get_bot(), group_id, user_id)
        timer_msg = (
            f"{TIMER_MARK}:{user_id}\n"
            f"(SYSTEM) 定时任务已触发。\n"
            "以下是定时任务的内容，不需要 @ 用户，"
            f"请以你的口吻告知用户 \"{user_name}\"（QQ号：{user_id}）：\n\n"
            f"{timer_prompt}"
        )
        print(f"⏰ [inject_timer] Timer message for user {user_id}: {timer_prompt[:80]}...")

    if _state and _state.is_chatting:
        _state.human_queue.append({"type": "text", "text": timer_msg})
        if user_id != 0:
            _state.chat_peers.add(str(user_id))
        print(f"⏰ [inject_timer] Injected timer into human_queue for user {user_id}")
    else:
        if start_conversation_cb is not None:
            print(f"⏰ [inject_timer] Starting new conversation for timer (user {user_id})")
            start_conversation_cb(user_id, timer_msg)
        else:
            print("❌ inject_timer: no active chat and no callback")
```

- [ ] **Step 3: Add /autocreate command**

Add to `handlers/commands.py`:

```python
async def handle_autocreate(bot, event, matcher) -> None:
    """Immediately trigger an auto-create execution (debug command)."""
    from ..config import AUTO_CREATE_PROMPT
    from ..graph.nodes.ai import inject_timer

    inject_timer(
        user_id=0,
        group_id=TARGET_GROUP_ID,
        timer_prompt=AUTO_CREATE_PROMPT,
        start_conversation_cb=None,
    )
    await matcher.finish("🎨 Auto create 已触发（调试模式，数据库未修改）")
```

In `__init__.py`, update imports and add matcher:

```python
from .handlers.commands import (
    ..., handle_autocreate  # add to existing import
)

autocreate_cmd = on_command("autocreate", priority=10, block=True)

@autocreate_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    await handle_autocreate(bot, event, autocreate_cmd)
```

- [ ] **Step 4: Verify and commit**
Run: `ruff check hatsume/plugins/hatsume-plugin/`
```bash
git add hatsume/plugins/hatsume-plugin/timer/__init__.py \
        hatsume/plugins/hatsume-plugin/graph/nodes/ai.py \
        hatsume/plugins/hatsume-plugin/handlers/commands.py \
        hatsume/plugins/hatsume-plugin/__init__.py
git commit -m "feat: wire auto-create startup, inject_timer user_id=0, /autocreate cmd

- Call refresh_auto_create() in init_scheduler on startup
- Handle user_id=0 in inject_timer (skip user lookup, auto_create msg format)
- Add /autocreate debug command (configured target group, no DB modification)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Fix existing tests broken by auto-respond removal

**Files:**
- Modify: `tests/test_chat_send.py:39-40,44`
- Modify: `tests/test_conversation.py:46-47`

- [ ] **Step 1: Remove auto-respond stubs**

In `tests/test_chat_send.py`, delete:
```python
    config_mod.AUTO_REPLY_CURRENT_MSG_COUNT = 10   # line 39
    config_mod.AUTO_REPLY_HISTORY_MSG_COUNT = 20    # line 40
    config_mod.AUTO_RESPONSE_PROBABILITY = 0.5      # line 44
```

In `tests/test_conversation.py`, delete:
```python
    mod.AUTO_REPLY_CURRENT_MSG_COUNT = 10            # line 46
    mod.AUTO_REPLY_HISTORY_MSG_COUNT = 20            # line 47
```

- [ ] **Step 2: Verify zero remaining references**
Run: `grep -rn "AUTO_REPLY\|AUTO_RESPONSE\|should_auto_respond\|has_respond_recently" hatsume/ tests/`
Expected: No results.

- [ ] **Step 3: Run full test suite**
Run: `python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**
```bash
git add tests/test_chat_send.py tests/test_conversation.py
git commit -m "test: remove auto-respond stubs from existing tests

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Final verification

- [ ] **Step 1: Full test suite**
Run: `python -m pytest tests/ -v`
Expected: ALL tests PASS.

- [ ] **Step 2: Lint**
Run: `ruff check hatsume/plugins/hatsume-plugin/`
Expected: No errors.

- [ ] **Step 3: Verify completeness**
Run: `grep -rn "AUTO_REPLY\|AUTO_RESPONSE\|should_auto_respond\|has_respond_recently" hatsume/ tests/`
Expected: No results (auto-respond fully removed).

Run: `grep -n "AUTO_CREATE" hatsume/plugins/hatsume-plugin/config.py`
Expected: Shows all 4 auto-create constants.

Run: `grep -rn "task_type" hatsume/plugins/hatsume-plugin/`
Expected: Shows references in store.py, executor.py, config.py.

- [ ] **Step 4: Final commit**
```bash
git add .
git commit -m "chore: final verification — all tests pass, auto-respond fully removed

Co-Authored-By: Claude <noreply@anthropic.com>"
```
