# Memory-Group Auto Response and Poke Whitelist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every group represented in `memory.db` an independent recurring auto-response timer, add timers when a group receives its first new memory, and silence poke notices outside the configured whitelist.

**Architecture:** SQLite memory metadata remains the source of eligible group IDs. The plugin entry point passes those IDs into timer startup, while the memory engine emits a post-insert callback that the plugin wires to an idempotent timer ensure operation. Timer rows retain their existing schema but store the owning positive group ID, so each group can be refreshed, executed, and rescheduled independently.

**Tech Stack:** Python 3.12, NoneBot2, APScheduler, SQLite, pytest

---

### Task 1: Persist one auto-response task per memory-owning group

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/store.py`
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py`
- Test: `tests/test_timer_store.py`
- Test: `tests/test_auto_response.py`

- [x] **Step 1: Write failing store and executor tests**

Cover two groups retaining separate rows, replacement affecting only one group, refresh creating one future point per eligible group, stale group cleanup, and execution rescheduling the fired task's own group.

```python
first = store.upsert_auto_response(101, first_at)
other = store.upsert_auto_response(202, other_at)
replacement = store.upsert_auto_response(101, replacement_at)
assert store.get_task(first) is None
assert store.get_auto_response_point(101)["task_id"] == replacement
assert store.get_auto_response_point(202)["task_id"] == other
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_timer_store.py tests/test_auto_response.py -q`

Expected: failures because auto-response store and executor APIs still represent one global task.

- [x] **Step 3: Implement group-owned timer persistence and scheduling**

Change the store and executor APIs to require a positive `group_id`:

```python
def upsert_auto_response(
    self, group_id: int, trigger_at: float, prompt: str | None = None
) -> int: ...

def get_auto_response_point(self, group_id: int) -> dict | None: ...

def ensure_auto_response_for_group(store: TimerStore, group_id: int) -> None: ...

async def refresh_auto_responses(
    store: TimerStore, group_ids: Iterable[int]
) -> None: ...
```

The refresh operation deletes tasks for groups absent from the eligible set, retains valid future points, and creates missing or expired points. `_execute_auto_response()` reads `task["group_id"]` and reschedules only that group in `finally`.

- [x] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_timer_store.py tests/test_auto_response.py -q`

Expected: all selected tests pass without warnings.

### Task 2: Make memory ownership drive timer lifecycle

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/timer/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py`
- Test: `tests/test_memory_db.py`
- Test: `tests/test_timer_startup.py`

- [x] **Step 1: Write failing memory and startup tests**

```python
assert memory.list_memory_group_ids(conn) == (101, 202)

ensured = []
memory.configure_auto_response_timer_callback(ensured.append)
memory.add_mem("new", group_id=202)
assert ensured == [202]
```

Also verify `init_scheduler((101, 202))` passes both IDs to `refresh_auto_responses` after normal timer recovery.

- [x] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_memory_db.py tests/test_timer_startup.py -q`

Expected: failures because memory group enumeration and post-insert timer notification do not exist.

- [x] **Step 3: Implement memory-driven orchestration**

Add a bounded distinct-group query and a callback invoked only after SQLite insertion succeeds:

```python
def list_memory_group_ids(conn: sqlite3.Connection | None = None) -> tuple[int, ...]: ...

def configure_auto_response_timer_callback(
    callback: Callable[[int], None] | None,
) -> None: ...
```

At plugin initialization, wire the callback to the timer package's ensure function. On bot connection, discover delivery routes first and call `init_scheduler(list_memory_group_ids())`.

- [x] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_memory_db.py tests/test_timer_startup.py -q`

Expected: all selected tests pass without warnings.

### Task 3: Enforce the poke group whitelist

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/tools.py`
- Create: `tests/test_poke_whitelist.py`

- [x] **Step 1: Write failing handler tests**

Verify a poke outside the whitelist does not export a photo, bind a runtime, or send a message, while the currently allowed group reaches the export path.

```python
await tools.handle_poke(bot, SimpleNamespace(group_id=999))
export.assert_not_awaited()
bot.send.assert_not_awaited()
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_poke_whitelist.py -q`

Expected: the outside-group test fails because the current handler exports for every positive group.

- [x] **Step 3: Add the whitelist and early return**

Define `POKE_GROUP_WHITELIST` in `config.py` with the requested initial group and check membership immediately after validating `event.group_id`, before importing photo tools or binding group state.

- [x] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_poke_whitelist.py -q`

Expected: both whitelist tests pass.

### Task 4: Document, verify, and start the bot

**Files:**
- Modify: `docs/arch.md`
- Modify: `README.md` only if its existing configuration or capability summary requires correction

- [x] **Step 1: Update architecture documentation**

Document memory-backed group eligibility, positive group ownership for internal timer rows, per-group refresh/reschedule behavior, the memory-insert ensure hook, and poke whitelist behavior without recording real configuration values.

- [x] **Step 2: Run focused and full checks**

```bash
.venv/bin/python -m pytest tests/test_auto_response.py tests/test_timer_store.py tests/test_timer_startup.py tests/test_memory_db.py tests/test_poke_whitelist.py -q
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Expected: all commands exit zero with no collection errors, resource warnings, or type errors.

- [x] **Step 3: Review the final worktree**

Run: `git status --short` and focused `git diff` commands.

Expected: unrelated user changes remain intact; only the planned files contain new task edits.

- [x] **Step 4: Start the production bot**

Run: `./run_nb.sh`, then inspect the `nb-hatsume` tmux session output.

Expected: the script recreates the tmux session and NoneBot reaches normal startup without a traceback.
