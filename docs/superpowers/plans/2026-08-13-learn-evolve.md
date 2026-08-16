# 学习进化（learn-evolve）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "学习进化" (learning evolution) feature: read the most recent 24 hours of long-term memories (max 100 rows), inject them structurally into an evolution Agent that combines them with `web_search` to produce concrete "升级方向" (improvement directions), and hand those directions to the existing self-evolution flow (runtime Skill `self-evolution` + user-confirmed `hatsume-restart`) for execution — no new code-editing/restart pipeline. Triggered by an admin-only `/learn-evolve` slash command and a daily 03:00 (Asia/Shanghai) scheduler job. Safety: same-day dedup (idempotent re-trigger), non-blocking concurrency lock, bounded `recursion_limit` (no unbounded self-modification loops), and execution always stays behind the existing skill's explicit user confirmation.

**Architecture:** Pure extension of existing surfaces, no new dependencies, no schema changes.

- Memory: new bounded global read `query_recent_memories(conn, limit=100, since_time=...)` in `memory/engine.py` (cross-group bounded query, same precedent as daily maintenance in `init_tokenized_corpus`); exported through `memory/__init__.py`.
- Orchestration: new `evolution.py` module — `run_learn_evolve()` builds the structured prompt (new `build_learn_evolve_prompt()` in `prompts.py`) and runs a LangChain agent over `get_advance_model(thinking=True)` with the provider-native `{"type": "web_search"}` tool (same tool shape as `_get_coding_agent_tools`), bounded by `LEARN_EVOLVE_RECURSION_LIMIT`. Dedup + lock + last-run state are module-level in-memory (process-local, same precedent as `ADVANCE_MODEL_NAME`).
- Command: `handlers/tools.py::handle_learn_evolve` + `on_command("learn-evolve", rule=admin, priority=10, block=True)` in `__init__.py` (same pattern as `/autoresponse`).
- Daily job: `@scheduler.scheduled_job(CronTrigger(hour=3, minute=0, second=0, timezone="Asia/Shanghai"), id="daily_learn_evolve", ...)` decorator inside `evolution.py`, imported by `__init__.py` with a `# noqa: F401` comment (same pattern as `init_tokenized_corpus` in `memory/engine.py`). The daily run quietly refreshes the latest directions (in-memory `get_last_learn_evolve_directions()`), which the command surfaces; 03:00 is inside the auto-response quiet window, so no group injection happens at night.
- Execution hand-off: the evolution prompt instructs the agent to output only improvement directions and to state that implementation follows the existing self-evolution Skill (test first, then explicit user confirmation before `hatsume-restart`). The command reply is the hand-off into the group conversation, where the existing chat agent + `skill_loader` + self-evolution Skill execute with the user in the loop.

**Tech Stack:** Python 3.12, NoneBot2 (OneBot V11), APScheduler, LangChain, pytest.

---

### Task 1: Focused tests for learn-evolve (RED)

**Files:**
- Add: `tests/test_learn_evolve.py`
- Modify: `tests/test_command_registration.py` — add `"learn-evolve"` to the expected command set.

- [x] **Step 1: Write failing tests**

Cover, using the importlib stub conventions of `tests/test_memory_db.py` / `tests/test_dsbalance_command.py` (temporary SQLite DBs, mocked model/agent, `MockFinished` for `matcher.finish`):

1. `query_recent_memories` — temp DB with rows across groups/times: returns only rows with `time > since_time`, newest first, `group_id` present, `limit` respected (and no limit truncation when fewer).
2. `build_learn_evolve_prompt` — structured output contains time/group/content fields, bounded count; empty memory fallback.
3. `run_learn_evolve` — with stubbed `query_recent_memories`/`create_agent`: passes `recursion_limit=LEARN_EVOLVE_RECURSION_LIMIT`; returns agent text; second same-day call is deduped (no second agent invocation); `force=True` bypasses dedup; concurrent run (lock held) returns "进行中" without invoking the agent; no-memory run still completes and marks the window.
4. `handle_learn_evolve` — admin command handler finishes with the directions text; `run_learn_evolve` failure produces a friendly message.
5. `daily_learn_evolve` — decorated with the 03:00 Asia/Shanghai CronTrigger under id `daily_learn_evolve` (stub scheduler records the registration).
6. `tests/test_command_registration.py` — `"learn-evolve" in commands`.

- [x] **Step 2: Run focused test and record RED output**

Run: `.venv/bin/python -m pytest tests/test_learn_evolve.py tests/test_command_registration.py -q`

Expected: collection succeeds; all new tests fail because `query_recent_memories`, `build_learn_evolve_prompt`, `evolution.py`, and `handle_learn_evolve` do not exist yet; the registration test fails because `learn-evolve` is not registered. Observed: 18 failed — AttributeError (`query_recent_memories` missing), FileNotFoundError (`evolution.py` missing), command registration assertion.

### Task 2: Memory read — `query_recent_memories` (GREEN)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`

- [x] **Step 1: Implement the bounded global recent-memories query**

`query_recent_memories(conn, limit=100, since_time=None)` — parameterized SQL over `memories` (`time > ?` when given, `ORDER BY time DESC, id DESC LIMIT ?`), rows include `id`, `group_id`, `content`, `time`. Bounded by `min(limit, 100)`. Also added the public `get_db()` accessor (process-lazy singleton connection) and exported both from `memory/__init__.py`.

- [x] **Step 2: Run focused test and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_learn_evolve.py -q`

### Task 3: Evolution module, prompt, command, and daily job (GREEN)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py` — `LEARN_EVOLVE_MEMORY_LIMIT = 100`, `LEARN_EVOLVE_WINDOW_HOURS = 24`, `LEARN_EVOLVE_RECURSION_LIMIT = 20` (documented names only; dedup is a fixed Shanghai-calendar-day rule, no separate constant).
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py` — `build_learn_evolve_prompt(memories)` + `LEARN_EVOLVE_TASK_INPUT`.
- Add: `hatsume/plugins/hatsume-plugin/evolution.py` — `run_learn_evolve(force=False)`, `get_last_learn_evolve_directions()`, `get_last_learn_evolve_run()`, `daily_learn_evolve` (03:00 job), module-level non-blocking `asyncio.Lock` + Shanghai-date dedup key.
- Modify: `hatsume/plugins/hatsume-plugin/handlers/tools.py` — `handle_learn_evolve(event, matcher, args)`.
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py` — `learn_evolve_cmd` matcher + handler + `daily_learn_evolve` import.

- [x] **Step 1: Run focused test and verify RED still holds**
- [x] **Step 2: Implement config constants and the prompt builder**
- [x] **Step 3: Implement `evolution.py`** — locked, deduped run; structured injection; bounded recursion; web_search tool; last-run state. (Fixed `global` declarations for the module-level run state.)
- [x] **Step 4: Implement the command handler and matcher registration**
- [x] **Step 5: Run focused test and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_learn_evolve.py tests/test_command_registration.py -q` — 18 passed.

### Task 4: Documentation

**Files:**
- Modify: `docs/arch.md` — add `evolution.py` to the runtime module table, `/learn-evolve` to the command list, the 03:00 learn-evolve job and the bounded global memory read to the corresponding sections, and the test module to the test index. Preserve all unrelated uncommitted edits.

- [x] **Step 1: Update `docs/arch.md`**

### Task 5: Full verification

- [x] **Step 1: Run focused tests**
- [x] **Step 2: Run ruff**

Run: `.venv/bin/ruff check hatsume/plugins/hatsume-plugin`

- [x] **Step 3: Run pyright**

Run: `npx --no-install pyright`

- [x] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests -q`

- [x] **Step 5: Final review** — `git diff`/`git status` limited to learn-evolve files plus preserved unrelated changes; write the task report. No commit, no push, no `hatsume-restart`.
