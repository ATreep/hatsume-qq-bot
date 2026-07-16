# Auto Response Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a self-renewing "auto response" timer that periodically injects a short-topic-reply prompt into the conversation graph, mirroring the existing auto_create architecture.

**Architecture:** Reuse auto_create's fire-and-forget pattern — APScheduler triggers execution, prompt is injected into the graph via `inject_timer()`, and the timer immediately reschedules itself. New `task_type='auto_response'` row in the existing `timer_tasks` table, symmetric store/executor methods, and an admin-only debug command.

**Tech Stack:** Python 3.12+, SQLite, APScheduler (nonebot-plugin-apscheduler), NoneBot2

## Global Constraints

- New `task_type` value `'auto_response'` — no schema migration needed (column already exists)
- `inject_timer()` is NOT modified — reused as-is with `user_id=0, is_auto_create=False`
- All new code mirrors existing auto_create patterns exactly
- Admin-only debug command (same `ADMIN_QQ_ID` rule as autocreate)
- Test file follows existing `test_auto_create.py` pattern (stub-heavy module loading)

---

### Task 1: Config constant

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py:130`

**Interfaces:**
- Produces: `AUTO_RESPONSE_GROUP_ID: int = TARGET_GROUP_ID`

- [ ] **Step 1: Add AUTO_RESPONSE_GROUP_ID constant**

```python
# After line 130 (the commented-out AUTO_CREATE_GROUP_ID line), insert:

# ---------------------------------------------------------------------------
# Auto response timer
# ---------------------------------------------------------------------------
AUTO_RESPONSE_GROUP_ID: int = TARGET_GROUP_ID
```

Edit: replace the line `# AUTO_CREATE_GROUP_ID: int = TARGET_GROUP_ID` with itself plus the new block:

```python
# AUTO_CREATE_GROUP_ID: int = TARGET_GROUP_ID
# ---------------------------------------------------------------------------
# Auto response timer
# ---------------------------------------------------------------------------
AUTO_RESPONSE_GROUP_ID: int = TARGET_GROUP_ID
# ---------------------------------------------------------------------------
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/config.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/config.py
git commit -m "feat: add AUTO_RESPONSE_GROUP_ID config constant

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Prompt function

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py:362-364`

**Interfaces:**
- Consumes: (none — standalone, uses `random`)
- Produces: `get_auto_response_prompt() -> str`

- [ ] **Step 1: Add get_auto_response_prompt() function**

Insert after line 362 (end of `get_auto_create_prompt`), before the `# ---- Timer prompts ----` separator:

```python

def get_auto_response_prompt() -> str:
    """Core: pick a topic from chat history, reply in ≤30 chars.

    Fixed task with minor random wording variations so responses don't
    feel mechanically identical.
    """
    import random

    variations = [
        "(SYSTEM)从聊天记录与最近的历史记录中挑选一个话题进行一句话回复，不超过30字。",
        "(SYSTEM)看看最近的聊天记录，选一个有意思的话题，用一句话回复，别超过30个字。",
        "(SYSTEM)浏览最近的群聊内容，找一个话题进行简短的一句话回复（30字以内）。",
        "(SYSTEM)翻翻最近的聊天，挑个话题插一句嘴，一句话就好，不要超过30字。",
        "(SYSTEM)从最近的群聊里选一个你感兴趣的话题，简短回复一句，控制在30字内。",
    ]
    return random.choice(variations)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/prompts.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py
git commit -m "feat: add get_auto_response_prompt() with minor variations

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Store methods

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/store.py:226-227` (after `list_auto_create_triggers`)

**Interfaces:**
- Consumes: `prompts.get_auto_response_prompt` (imported lazily inside method)
- Produces:
  - `upsert_auto_response(self, trigger_at: float, prompt: str | None = None) -> int`
  - `get_auto_response(self) -> dict | None`
  - `list_auto_response_triggers(self) -> list[dict]`

- [ ] **Step 1: Add three methods to TimerStore**

Insert after the `list_auto_create_triggers` method (after line 227, before `# ---- CRUD: Triggers ----`):

```python
    # ------------------------------------------------------------------
    # Auto-response special timer
    # ------------------------------------------------------------------

    def upsert_auto_response(
        self, trigger_at: float, prompt: str | None = None,
    ) -> int:
        """Delete all old auto_response tasks and create a new one.

        Guarantees at most one auto_response row in the database.
        Returns the new task_id.
        """
        from ..prompts import get_auto_response_prompt

        self._conn.execute(
            "DELETE FROM timer_tasks WHERE task_type = 'auto_response'"
        )
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO timer_tasks "
            "(group_id, user_id, prompt, created_at, updated_at, task_type) "
            "VALUES (?, ?, ?, ?, ?, 'auto_response')",
            (0, 0, prompt or get_auto_response_prompt(), now, now),
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
        run_dt = datetime.fromtimestamp(trigger_at, tz=timezone(timedelta(hours=8)))
        ts_str = run_dt.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"💬 [auto_response] Task upserted: id={task_id} "
            f"trigger_at={ts_str}"
        )
        return task_id

    def get_auto_response(self) -> dict | None:
        """Get the current auto_response task with its pending trigger, or None."""
        row = self._conn.execute(
            "SELECT t.*, tr.trigger_at, tr.id as trigger_id "
            "FROM timer_tasks t "
            "LEFT JOIN timer_triggers tr "
            "  ON tr.task_id = t.id AND tr.fired = 0 "
            "WHERE t.task_type = 'auto_response' "
            "ORDER BY tr.trigger_at LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def list_auto_response_triggers(self) -> list[dict]:
        """Get all unfired triggers for auto_response tasks."""
        rows = self._conn.execute(
            "SELECT tr.* FROM timer_triggers tr "
            "JOIN timer_tasks t ON t.id = tr.task_id "
            "WHERE t.task_type = 'auto_response' AND tr.fired = 0"
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/timer/store.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/timer/store.py
git commit -m "feat: add auto_response store methods (upsert, get, list triggers)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Executor functions + routing

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py:87-96` (after `_random_next_trigger`, before `_execute_auto_create`)

**Interfaces:**
- Consumes:
  - `AUTO_RESPONSE_GROUP_ID` from config
  - `get_auto_response_prompt` from prompts
  - `inject_timer` from graph.nodes.ai
  - `register_job` (local)
  - `store.upsert_auto_response()`, `store.get_triggers_for_task()`, `store.mark_trigger_fired()`
- Produces:
  - `_random_response_trigger() -> float`
  - `_execute_auto_response(task: dict, store: TimerStore) -> None`  (async)
  - `reschedule_auto_response(store: TimerStore) -> None`
  - `refresh_auto_response(store: TimerStore) -> None`  (async)

- [ ] **Step 1: Add _random_response_trigger()**

Insert after line 96 (end of `_random_next_trigger`):

```python

def _random_response_trigger() -> float:
    """Generate a random trigger time in [now+1h, now+3h].

    No time-window restriction — auto_response runs 24h.
    Returns a Unix timestamp (float).
    """
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    delta_seconds = random.uniform(1 * 3600, 3 * 3600)
    t = now + timedelta(seconds=delta_seconds)
    return t.timestamp()
```

- [ ] **Step 2: Add _execute_auto_response(), reschedule_auto_response(), refresh_auto_response()**

Insert after the `reschedule_auto_create` function (after line 148, before `refresh_auto_create`):

```python

# ---------------------------------------------------------------------------
# Auto Response — execution and lifecycle
# ---------------------------------------------------------------------------

async def _execute_auto_response(task: dict, store: TimerStore) -> None:
    """Execute an auto_response timer: inject into graph, then reschedule.

    Mirror of _execute_auto_create — injects the prompt with user_id=0
    (no @-mention) and reschedules immediately (fire-and-forget).
    """
    from ..prompts import get_auto_response_prompt
    from ..graph.nodes.ai import inject_timer
    from ..config import AUTO_RESPONSE_GROUP_ID

    prompt = task.get("prompt") or get_auto_response_prompt()

    print("💬 [auto_response] Executing...")
    inject_timer(
        user_id=0,
        group_id=AUTO_RESPONSE_GROUP_ID,
        timer_prompt=prompt,
        start_conversation_cb=_timer_start_conv_cb,
        is_auto_create=False,
    )

    # Reschedule immediately — fire-and-forget pattern
    reschedule_auto_response(store)


def reschedule_auto_response(store: TimerStore) -> None:
    """Delete the old auto_response task and create a new one with a random
    trigger time in [now+1h, now+3h].

    Registers the new APScheduler job for the random trigger time.
    """
    next_trigger = _random_response_trigger()
    task_id = store.upsert_auto_response(next_trigger)

    triggers = store.get_triggers_for_task(task_id)
    for t in triggers:
        if not t["fired"]:
            register_job(t, store)

    run_dt = datetime.fromtimestamp(next_trigger, tz=timezone(timedelta(hours=8)))
    print(
        f"💬 [auto_response] Rescheduled: task={task_id} "
        f"next={run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    )


async def refresh_auto_response(store: TimerStore) -> None:
    """Called on startup: ensure one auto_response task exists with a registered job.

    If a pending auto_response task already exists (not yet triggered), re-register
    its APScheduler job without changing the trigger time.
    Otherwise, create a fresh one via reschedule_auto_response.
    """
    import time as time_mod

    now = time_mod.time()

    # Check for existing pending auto_response trigger
    pending = store.list_auto_response_triggers()
    future_pending = [t for t in pending if t["trigger_at"] > now]

    if future_pending:
        # Re-register jobs for existing pending triggers (lost on restart)
        for t in future_pending:
            register_job(t, store)
        run_dt = datetime.fromtimestamp(
            future_pending[0]["trigger_at"], tz=timezone(timedelta(hours=8))
        )
        print(
            f"💬 [auto_response] Startup: existing task retained, "
            f"next={run_dt.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        # No pending trigger — create fresh one
        store._conn.execute(
            "DELETE FROM timer_tasks WHERE task_type = 'auto_response'"
        )
        store._conn.commit()
        reschedule_auto_response(store)
        print("💬 [auto_response] Startup refresh complete (new task created)")
```

- [ ] **Step 3: Route auto_response in _execute_timer()**

In `_execute_timer()`, after the `auto_create` routing block (line 252-255), add:

```python
    # Auto-response tasks take a separate execution path
    if task.get("task_type") == "auto_response":
        # Mark fired before executing (fire-and-forget)
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_response(task, store)
        return
```

Edit: replace the existing auto_create routing block to add the new block right after it.

The existing block at lines 251-255:
```python
    # Auto-create tasks take a separate execution path
    if task.get("task_type") == "auto_create":
        # Mark fired before executing (fire-and-forget)
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_create(task, store)
        return
```

Replace with:
```python
    # Auto-create tasks take a separate execution path
    if task.get("task_type") == "auto_create":
        # Mark fired before executing (fire-and-forget)
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_create(task, store)
        return

    # Auto-response tasks take a separate execution path
    if task.get("task_type") == "auto_response":
        # Mark fired before executing (fire-and-forget)
        store.mark_trigger_fired(trigger_id)
        await _execute_auto_response(task, store)
        return
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/timer/executor.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/timer/executor.py
git commit -m "feat: add auto_response executor (trigger, execute, reschedule, refresh)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Scheduler init

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/__init__.py:38-39`

**Interfaces:**
- Consumes: `refresh_auto_response` from executor

- [ ] **Step 1: Add refresh_auto_response() call in init_scheduler()**

In `init_scheduler()`, add the auto_response refresh call after the auto_create refresh (commented-out) block.

Edit: replace:
```python
    # Refresh auto-create: delete old, create new for tomorrow
    # await refresh_auto_create(store)

    print("⏰ [timer] Scheduler recovery complete")
```

With:
```python
    # Refresh auto-create: delete old, create new for tomorrow
    # await refresh_auto_create(store)

    # Refresh auto-response: re-register pending or create fresh
    from .executor import refresh_auto_response
    await refresh_auto_response(store)

    print("⏰ [timer] Scheduler recovery complete")
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/timer/__init__.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/timer/__init__.py
git commit -m "feat: call refresh_auto_response() on scheduler startup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Debug command handler

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/commands.py:374` (after `handle_autocreate`)

**Interfaces:**
- Consumes: `inject_timer` from graph.nodes.ai, `get_auto_response_prompt` from prompts, `AUTO_RESPONSE_GROUP_ID` from config
- Produces: `handle_autoresponse(bot, event, matcher, args) -> None` (async)

- [ ] **Step 1: Add handle_autoresponse() function**

Insert after line 373 (end of `handle_autocreate`):

```python

async def handle_autoresponse(bot, event, matcher, args: Message) -> None:
    """Immediately trigger an auto-response execution (debug command).

    Injects the auto-response prompt into the graph targeting the group
    where the command was sent.
    If args is non-empty, use it as the prompt instead of the default.
    Does NOT modify the database — no task created, no reschedule.
    """
    from ..graph.nodes.ai import inject_timer
    from ..prompts import get_auto_response_prompt
    from ..config import AUTO_RESPONSE_GROUP_ID

    custom_prompt = args.extract_plain_text().strip()
    group_id = event.group_id
    if args.extract_plain_text().strip() == "prod":
        prompt = get_auto_response_prompt()
        group_id = AUTO_RESPONSE_GROUP_ID
    else:
        prompt = custom_prompt if custom_prompt else get_auto_response_prompt()

    inject_timer(
        user_id=0,
        group_id=group_id,
        timer_prompt=prompt,
        start_conversation_cb=None,
    )
    await matcher.finish(f"💬 Auto Response Mode ON\n\n {prompt}")
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/handlers/commands.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/handlers/commands.py
git commit -m "feat: add handle_autoresponse debug command handler

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Matcher registration

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py:15,100,179-181`

**Interfaces:**
- Consumes: `handle_autoresponse` from handlers.commands

- [ ] **Step 1: Import handle_autoresponse**

Edit line 15, add `handle_autoresponse` to the import:

Replace:
```python
from .handlers.commands import handle_shell, handle_generate_video, handle_timer, handle_list_skills, handle_membersearch, handle_resetsandbox, handle_clear, handle_agents, handle_autocreate
```

With:
```python
from .handlers.commands import handle_shell, handle_generate_video, handle_timer, handle_list_skills, handle_membersearch, handle_resetsandbox, handle_clear, handle_agents, handle_autocreate, handle_autoresponse
```

- [ ] **Step 2: Register matcher**

Add after line 100 (the `autocreate_cmd` matcher):

```python
autoresponse_cmd = on_command("autoresponse", rule=lambda event: str(event.get_user_id()) == ADMIN_QQ_ID, priority=10, block=True)
```

- [ ] **Step 3: Add handler**

Add after line 181 (the autocreate handler):

```python

@autoresponse_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_autoresponse(bot, event, autoresponse_cmd, args)
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/__init__.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/__init__.py
git commit -m "feat: register /autoresponse admin debug command

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Tests

**Files:**
- Create: `tests/test_auto_response.py`

**Interfaces:**
- Consumes: `_random_response_trigger`, `_execute_auto_response`, `reschedule_auto_response`, store methods from timer module

- [ ] **Step 1: Write the test file**

Create `tests/test_auto_response.py`:

```python
"""Tests for auto-response timer: random trigger generation and execution."""

from __future__ import annotations

import importlib.util
import sys
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

# Stub utils.py before executor tries to import it
_utils_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.utils")
_utils_mod.get_group_member_name = lambda bot, group_id, user_id: f"user_{user_id}"
sys.modules["hatsume.plugins.hatsume-plugin.utils"] = _utils_mod

# Stub nonebot before loading executor (which imports get_bot, require at module level)
_nonebot_mod = types.ModuleType("nonebot")
_nonebot_mod.get_bot = lambda: None
_nonebot_mod.get_driver = lambda: None
_nonebot_mod.require = lambda name: sys.modules.get(name, types.ModuleType(name))
sys.modules["nonebot"] = _nonebot_mod

# Stub nonebot_plugin_apscheduler (imported by executor with require())
_apscheduler_mod = types.ModuleType("nonebot_plugin_apscheduler")
_apscheduler_mod.scheduler = type("Scheduler", (), {"add_job": lambda *a, **kw: None, "remove_job": lambda *a, **kw: None})()
sys.modules["nonebot_plugin_apscheduler"] = _apscheduler_mod

# Stub apscheduler.triggers.date (imported by executor)
_date_trigger_mod = types.ModuleType("apscheduler.triggers.date")
_date_trigger_mod.DateTrigger = type("DateTrigger", (), {})
_apscheduler_mod_pkg = types.ModuleType("apscheduler")
_apscheduler_mod_pkg.triggers = types.ModuleType("apscheduler.triggers")
_apscheduler_mod_pkg.triggers.date = _date_trigger_mod
sys.modules["apscheduler"] = _apscheduler_mod_pkg
sys.modules["apscheduler.triggers"] = _apscheduler_mod_pkg.triggers
sys.modules["apscheduler.triggers.date"] = _date_trigger_mod

_cfg = _load_module("config")
_timer_init = _load_submodule("timer", "timer.__init__")
_timer_store = _load_submodule("timer", "timer.store")
sys.modules["hatsume.plugins.hatsume-plugin.timer.store"] = _timer_store
_timer_executor = _load_submodule("timer", "timer.executor")

_random_response_trigger = _timer_executor._random_response_trigger


class TestRandomResponseTrigger:
    """Random trigger time generation for auto_response."""

    def test_returns_within_valid_horizon(self):
        """_random_response_trigger returns a timestamp at least ~50min in the
        future and at most ~3.5h."""
        now = datetime.now(timezone(timedelta(hours=8)))
        result_ts = _random_response_trigger()
        result_dt = datetime.fromtimestamp(result_ts, tz=timezone(timedelta(hours=8)))

        # Must be at least ~50min in the future (allowing for test execution time)
        min_expected = now + timedelta(minutes=50)
        assert result_dt > min_expected, (
            f"Expected > {min_expected.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"got {result_dt.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # Must not exceed 3.5h (allowing small margin beyond the 3h max)
        max_expected = now + timedelta(hours=3.5)
        assert result_dt < max_expected, (
            f"Expected < {max_expected.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"got {result_dt.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def test_random_distribution(self):
        """100 samples all fall within [now+1h, now+3h]."""
        now = datetime.now(timezone(timedelta(hours=8)))
        for _ in range(100):
            result_ts = _random_response_trigger()
            result_dt = datetime.fromtimestamp(
                result_ts, tz=timezone(timedelta(hours=8))
            )
            min_expected = now + timedelta(minutes=50)
            max_expected = now + timedelta(hours=3.5)
            assert result_dt > min_expected, (
                f"Hour {result_dt.hour} too early: "
                f"{result_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            assert result_dt < max_expected, (
                f"Hour {result_dt.hour} too late: "
                f"{result_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            )

    def test_no_time_window_restriction(self):
        """Unlike auto_create, auto_response has no hour-of-day restriction.
        Verify that samples can land in any hour (0-23)."""
        hours_seen = set()
        for _ in range(500):
            result_ts = _random_response_trigger()
            result_dt = datetime.fromtimestamp(
                result_ts, tz=timezone(timedelta(hours=8))
            )
            hours_seen.add(result_dt.hour)
        # With 500 samples over 1-3h windows, we should see at least 3 distinct hours
        assert len(hours_seen) >= 3, (
            f"Expected at least 3 distinct hours, got {len(hours_seen)}: {sorted(hours_seen)}"
        )


class TestAutoResponseStore:
    """Store CRUD for auto_response tasks."""

    def test_upsert_creates_single_task(self):
        """upsert_auto_response creates exactly one task with one trigger."""
        store = _timer_store.TimerStore(":memory:")
        store.init_db()

        now = datetime.now(timezone(timedelta(hours=8)))
        trigger_at = (now + timedelta(hours=2)).timestamp()

        task_id = store.upsert_auto_response(trigger_at)
        assert task_id is not None
        assert task_id > 0

        task = store.get_auto_response()
        assert task is not None
        assert task["task_type"] == "auto_response"
        assert task["user_id"] == 0
        assert task["group_id"] == 0

        triggers = store.get_triggers_for_task(task_id)
        assert len(triggers) == 1
        assert not triggers[0]["fired"]

    def test_upsert_replaces_old_task(self):
        """A second upsert deletes the old task and creates a new one."""
        store = _timer_store.TimerStore(":memory:")
        store.init_db()

        now = datetime.now(timezone(timedelta(hours=8)))
        t1 = (now + timedelta(hours=1)).timestamp()
        t2 = (now + timedelta(hours=2)).timestamp()

        id1 = store.upsert_auto_response(t1)
        id2 = store.upsert_auto_response(t2)

        assert id2 != id1

        # Old task should be gone
        assert store.get_task(id1) is None

        # New task should exist
        task = store.get_auto_response()
        assert task is not None
        assert task["id"] == id2

    def test_get_auto_response_returns_none_when_empty(self):
        """get_auto_response returns None when no auto_response task exists."""
        store = _timer_store.TimerStore(":memory:")
        store.init_db()

        result = store.get_auto_response()
        assert result is None

    def test_list_auto_response_triggers(self):
        """list_auto_response_triggers returns unfired triggers."""
        store = _timer_store.TimerStore(":memory:")
        store.init_db()

        now = datetime.now(timezone(timedelta(hours=8)))
        trigger_at = (now + timedelta(hours=2)).timestamp()
        store.upsert_auto_response(trigger_at)

        triggers = store.list_auto_response_triggers()
        assert len(triggers) == 1
        assert not triggers[0]["fired"]

        # Mark fired, should no longer appear
        store.mark_trigger_fired(triggers[0]["id"])
        triggers = store.list_auto_response_triggers()
        assert len(triggers) == 0
```

- [ ] **Step 2: Run tests to verify they fail (store/trigger functions exist)**

Run: `python -m pytest tests/test_auto_response.py -xvs`
Expected: All tests pass (the functions exist from Tasks 3-4)

- [ ] **Step 3: Commit**

```bash
git add tests/test_auto_response.py
git commit -m "test: add auto_response timer tests (trigger, store CRUD)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
