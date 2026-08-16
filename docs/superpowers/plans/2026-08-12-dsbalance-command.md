# /dsbalance Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/dsbalance` OneBot slash command that queries the DeepSeek balance API (`https://api.deepseek.com/user/balance`) with the existing `DS_API_KEY` config, shows the balance (converting 分 to 元 for display) and availability, and returns concise, secret-free error messages on any failure.

**Architecture:** Pure extension of the existing command surface. The matcher is registered in the plugin `__init__.py` (`on_command("dsbalance", priority=10, block=True)`), the handler lives in `handlers/tools.py` alongside the other command handlers, and the network call reuses the repository's `requests` + `asyncio.to_thread` pattern from `graph/tools.py::_fetch_pexels_search` (`timeout=10`, `raise_for_status()`, per-exception friendly messages). No config changes: `DS_API_KEY` (config.py:37) and `DS_BASE_URL` (config.py:54) already exist. No new dependencies.

**Tech Stack:** Python 3.12, NoneBot2 (OneBot V11), requests, pytest

---

### Task 1: Focused tests for /dsbalance (RED)

**Files:**
- Add: `tests/test_dsbalance_command.py` (modeled on `tests/test_agents_command.py` stub conventions; network mocked via `monkeypatch.setattr(cmd.requests, "get", ...)`)

- [x] **Step 1: Write failing handler tests**

Cover, with `matcher.finish` mocked to raise `MockFinished`:

1. Success: `balance_infos` with integer 分 values (`total_balance: "11000"`) renders `¥110.00`, `is_available: true` shows 可用; request URL is `{DS_BASE_URL}/user/balance`, header `Authorization: Bearer <key>`, `timeout=10`.
2. Success with already-yuan decimal strings (`"110.00"`) renders `¥110.00` unchanged.
3. Missing key: no network call, friendly "未配置" message.
4. HTTP 401/403 → "无效" message; HTTP 429 → rate-limit message; HTTP 500 → `HTTP 500` message.
5. Timeout / ConnectionError / InvalidJSONError / malformed payload (missing `balance_infos`) → friendly messages.
6. Every message must not contain the API key.

- [x] **Step 2: Run focused test and record RED output**

Run: `.venv/bin/python -m pytest tests/test_dsbalance_command.py -q`

Expected: collection succeeds, all tests fail because `handle_dsbalance` does not exist.

### Task 2: Implement /dsbalance (GREEN)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/tools.py` — add `_fetch_deepseek_balance()` (sync, `requests.get` + `raise_for_status()` + `.json()`), `_format_balance_amount()` (分→元), and `handle_dsbalance(event, matcher, args)` with per-exception `matcher.finish()` messages.
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py` — import `handle_dsbalance`, register `dsbalance_cmd = on_command("dsbalance", priority=10, block=True)`, add `@dsbalance_cmd.handle()` wrapper.

- [x] **Step 1: Run focused test and verify RED still holds**
- [x] **Step 2: Implement handler and matcher**
- [x] **Step 3: Run focused test and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_dsbalance_command.py -q`

### Task 3: Full verification

- [x] **Step 1: Run focused test**
- [x] **Step 2: Run ruff**

Run: `.venv/bin/ruff check hatsume/plugins/hatsume-plugin`

- [x] **Step 3: Run pyright**

Run: `npx --no-install pyright`

- [x] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest tests -q`

- [x] **Step 5: Final review of the /dsbalance diff (secret-free, convention-conformant) and write the task report**
