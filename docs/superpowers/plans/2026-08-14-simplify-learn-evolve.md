# Simplify Learn Evolve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce learning evolution to 24-hour memory retrieval, one focused self-evolution prompt, and chat-agent injection, with automatic execution every day at Shanghai midnight and optional `/learn-evolve <group_id>` memory filtering.

**Architecture:** `evolution.py` owns only orchestration and the APScheduler midnight job. Optional memory filtering remains in `memory/engine.py`, prompt text remains in `prompts.py`, and the command handler keeps the no-argument global memory behavior while accepting a positive group ID as a memory-source filter. The runtime `self-evolution` Skill remains the sole owner of source editing, verification, Agent waiting, and supervised restart behavior.

**Tech Stack:** Python 3.12+, NoneBot2, APScheduler, SQLite, pytest.

---

### Task 1: Define the simplified behavior with focused tests

**Files:**
- Modify: `tests/test_learn_evolve.py`
- Modify: `tests/test_self_evolution_runtime.py`
- Delete: `tests/test_self_evolution_auto_restart.py`

- [x] **Step 1: Replace obsolete dedup/restart tests with group-filter, single-direction prompt, midnight scheduling, and command-target tests.**
- [x] **Step 2: Run `.venv/bin/python -m pytest tests/test_learn_evolve.py -q` in the bot container.**

Expected: FAIL because group filtering, midnight registration, and command targeting are not implemented yet.

### Task 2: Implement the minimal learning-evolution chain

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/evolution.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/tools.py`
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/config.py`

- [x] **Step 1: Add optional positive `group_id` filtering to `query_recent_memories`.**
- [x] **Step 2: Rewrite the learning-evolution prompt to require exactly one memory-backed direction and loading/following `self-evolution`.**
- [x] **Step 3: Reduce `evolution.py` to query, prompt, injection, error reporting, and a Shanghai-midnight job over routed activated groups.**
- [x] **Step 4: Parse `/learn-evolve [group_id]`, preserve global reads without an argument, and use an explicit group only as the memory source.**
- [x] **Step 5: Remove the obsolete restart-complete callback from plugin startup.**
- [x] **Step 6: Run `.venv/bin/python -m pytest tests/test_learn_evolve.py tests/test_self_evolution_runtime.py -q`.**

Expected: PASS.

### Task 3: Align repository documentation and verify

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/arch.md`
- Modify: `hatsume/plugins/hatsume-plugin/AGENTS.md`
- Modify: `tests/AGENTS.md`

- [x] **Step 1: Document the daily 00:00 group-scoped run and `/learn-evolve [group_id]`.**
- [x] **Step 2: Remove references to deleted programmatic restart orchestration while preserving the runtime Skill restart contract.**
- [x] **Step 3: Run focused tests, Ruff, Pyright, and the full test suite; report unrelated baseline failures separately.**
- [x] **Step 4: Inspect `git diff` and `git status`, check unfinished Agents, then request the supervised Hatsume restart.**
