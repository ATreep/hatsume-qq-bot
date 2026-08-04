# Activated Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `AUTO_RESPONSE_GROUP_ID` with a memory-owned activated-group registry that gates new-member welcomes and synchronizes per-group autoresponse timers.

**Architecture:** `memory/engine.py` owns a lock-protected RAM set whose source of truth is the current-schema `memories.group_id` column. Startup loads a snapshot, successful memory writes notify one `(group_id, active=True)` callback, and daily expiry notifies deactivations. The plugin connects that callback to Timer synchronization and handlers query the snapshot without touching SQLite.

**Tech Stack:** Python 3.12, SQLite, NoneBot2, APScheduler, pytest.

**Repository constraint:** Do not create commits unless the user explicitly requests one. Preserve the existing Docker/image-pack and runtime-data worktree changes.

---

### Task 1: Activated-Group Registry and Timer Synchronization

**Files:**
- Modify: `tests/test_memory_db.py`
- Modify: `tests/test_memory_utils.py`
- Modify: `tests/test_auto_response.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/timer/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py`
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py`

- [ ] **Step 1: Write failing memory registry tests**

Add tests proving that startup exposes distinct memory-owning groups, a successful `add_mem()` activates its group and emits `(group_id, True)`, and daily expiry emits `(group_id, False)` only when the last memory disappears.

```python
memory.configure_activated_group_callback(updates.append)
memory.add_mem("new", group_id=GROUP_ID)
assert memory.get_activated_group_ids() == (GROUP_ID,)
assert updates == [(GROUP_ID, True)]
```

- [ ] **Step 2: Run the registry tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_memory_db.py tests/test_memory_utils.py -q -k activated`

Expected: FAIL because the activated-group APIs do not exist.

- [ ] **Step 3: Implement the registry and merged callback**

Add a lock-protected set, snapshot query, membership check, callback configuration, and update helpers. Call the startup refresh from `init_memory_system()`, the active update after SQLite insert, and the deactivation refresh after expiry.

```python
_activated_group_ids: set[int] = set()
_activated_group_lock = threading.RLock()
_activated_group_callback: Callable[[int, bool], None] | None = None

def get_activated_group_ids() -> tuple[int, ...]:
    with _activated_group_lock:
        return tuple(sorted(_activated_group_ids))
```

- [ ] **Step 4: Write and run failing Timer synchronization tests**

Test that active groups retain/create their future point, inactive groups cancel/delete it, and blacklisted groups remain without a point.

Run: `.venv/bin/python -m pytest tests/test_auto_response.py -q -k sync_auto_response`

Expected: FAIL because the unified synchronization function does not exist.

- [ ] **Step 5: Implement Timer synchronization and startup wiring**

Expose `sync_auto_response_for_group(group_id, active)` from `timer/__init__.py`, use it as the memory callback, and feed `get_activated_group_ids()` into `init_scheduler()` after Bot routing discovery.

- [ ] **Step 6: Run Task 1 tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_memory_db.py tests/test_memory_utils.py tests/test_auto_response.py tests/test_timer_startup.py -q`

Expected: PASS.

### Task 2: Activated-Group New-Member Welcomes

**Files:**
- Modify: `tests/test_conversation.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`

- [ ] **Step 1: Write failing welcome tests**

Replace fixed-group setup with an `is_group_activated()` stub. Prove two different activated groups can enter the welcome flow, inactive groups return before runtime binding, and the Bot itself is ignored.

```python
dialogue.is_group_activated = MagicMock(side_effect=lambda group_id: group_id in {100, 101})
asyncio.run(dialogue.handle_group_increase(bot, _make_group_increase_event(group_id=101)))
assert dialogue._start_conv_for_trigger.call_args.args[1] == 101
```

- [ ] **Step 2: Run welcome tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_conversation.py -q -k group_increase`

Expected: FAIL because the handler still compares one configured group ID.

- [ ] **Step 3: Gate welcomes through the memory registry**

Import `is_group_activated` from `memory` and replace the fixed-ID comparison. Keep the self-join check before member lookup, runtime binding, or graph injection.

- [ ] **Step 4: Run welcome tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_conversation.py -q -k group_increase`

Expected: PASS.

### Task 3: Remove Fixed-Group Command and Legacy Compatibility

**Files:**
- Modify: `.env.prod`
- Modify: `hatsume/plugins/hatsume-plugin/config.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/tools.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/social.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/vector_store.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`
- Modify: `scripts/migrate_memory_vectors.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_social.py`
- Modify: `tests/test_memory_db.py`
- Modify: `tests/test_memory_vector_store.py`

- [ ] **Step 1: Write failing removal-contract tests**

Prove `/autoresponse prod` no longer changes target group, flat likes are rejected without rewriting, unscoped memory schemas are rejected rather than migrated, and vector reconciliation requires current `group_id` ownership.

- [ ] **Step 2: Run removal tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_tools.py tests/test_social.py tests/test_memory_db.py tests/test_memory_vector_store.py -q`

Expected: FAIL on the old command routing and compatibility behavior.

- [ ] **Step 3: Remove compatibility code and configuration**

Delete the `AUTO_RESPONSE_GROUP_ID` source constant and `.env.prod` entry, the `prod` branch, flat-like migration, unscoped memory schema migration, `memory.json` migration, and unscoped vector fallback. Preserve current-schema SQLite-to-Milvus reconciliation using each row's explicit `group_id`.

- [ ] **Step 4: Run removal tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_tools.py tests/test_social.py tests/test_memory_db.py tests/test_memory_vector_store.py -q`

Expected: PASS.

### Task 4: Current Documentation and Full Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/arch.md`

- [ ] **Step 1: Update current documentation**

Document activated-group ownership, startup/write/expiry transitions, welcome gating, callback-based Timer synchronization, strict current schemas, and `/autoresponse [prompt]`. Remove current references to `AUTO_RESPONSE_GROUP_ID` and legacy ownership migration while leaving historical specs unchanged.

- [ ] **Step 2: Scan for stale current references**

Run: `rg -n "AUTO_RESPONSE_GROUP_ID|autoresponse.*prod|legacy_group_id|migrate_from_json" hatsume tests scripts AGENTS.md README.md docs/arch.md`

Expected: no matches.

- [ ] **Step 3: Run required verification**

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Expected: Ruff and Pyright clean; tests pass except for any explicitly reported failure caused by preserved unrelated user changes.
