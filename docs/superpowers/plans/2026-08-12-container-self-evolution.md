# Container Self-Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the copied Hatsume bot entirely inside `hatsume-space`, execute its tools against `/work/hatsume`, and let it safely edit and restart that isolated copy.

**Architecture:** The macOS repository is copied into the container writable layer with no bind mount. `infra.py` keeps group ownership and process lifecycle tracking, but foreground commands, background commands, and file copies target the local `/work/hatsume` repository instead of per-group Docker containers. A PID 1 supervisor relaunches NoneBot when `hatsume-restart` records a restart request and terminates the current bot process.

**Tech Stack:** Docker, Bash, Python 3.12+, NoneBot2, pytest, Ruff, Pyright.

---

### Task 1: Prove local execution behavior

**Files:**
- Create: `tests/test_local_execution.py`

- [ ] **Step 1: Write tests for the local workspace contract**

```python
async def test_run_cmd_executes_in_local_workspace():
    result = await infra.run_cmd("pwd", group_id=101)
    assert result.strip() == "/work/hatsume"

async def test_copy_host_file_to_sandbox_is_a_local_copy():
    await infra.copy_host_file_to_sandbox(source, destination, group_id=101)
    assert destination.read_text() == source.read_text()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_local_execution.py -q`

Expected: failures because the copied implementation still invokes `virtual/launch_image.sh` and Docker.

### Task 2: Route shell and container abstractions locally

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/infra.py`
- Test: `tests/test_local_execution.py`

- [ ] **Step 1: Add explicit local workspace constants**

```python
LOCAL_EXECUTION = True
LOCAL_WORKSPACE_PATH = Path("/work/hatsume")
```

- [ ] **Step 2: Make lifecycle startup and cleanup local**

`ensure_container_running()` marks the per-group logical runtime active without launching Docker. Reset and shutdown cancel only locally owned foreground/background processes and never delete the bot container.

- [ ] **Step 3: Execute foreground and background Bash locally**

Use `bash` with `cwd=LOCAL_WORKSPACE_PATH`, retain the existing timeout, cancellation, output, stdin, and group-ownership behavior, and do not invoke `docker exec`.

- [ ] **Step 4: Copy generated files locally**

Use a local `cp -- SOURCE DESTINATION` subprocess after validating the source and absolute destination. Preserve timeout and cancellation handling.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_local_execution.py tests/test_background_shell_infra.py -q`

Expected: all tests pass with no warnings.

### Task 3: Add supervised restart and runtime skill

**Files:**
- Create: `.container/supervise.sh`
- Create: `.container/hatsume-restart`
- Create: `data/hatsume-plugin/skills/self-evolution.md`
- Test: `tests/test_self_evolution_runtime.py`

- [ ] **Step 1: Test the operational artifacts**

Verify the supervisor launches the bot from `/work/hatsume`, records its child PID, distinguishes restart requests from terminal exits, and that the Skill has valid frontmatter plus exact `/work/hatsume` and `hatsume-restart` instructions.

- [ ] **Step 2: Implement the PID 1 supervisor**

The supervisor forwards TERM/INT, removes stale restart requests, launches the bot, and loops only when `/run/hatsume/restart.request` exists.

- [ ] **Step 3: Implement `hatsume-restart`**

The command validates the recorded bot PID, creates the restart request, and schedules a short delayed TERM so the invoking QQ tool can return first.

- [ ] **Step 4: Add the self-evolution Skill**

Teach Hatsume to inspect repository instructions, edit only `/work/hatsume`, use tests before restart, preserve unrelated changes/runtime data, and call `hatsume-restart` only after verification.

- [ ] **Step 5: Run artifact tests**

Run: `.venv/bin/python -m pytest tests/test_self_evolution_runtime.py tests/test_skill_manager.py -q`

Expected: all tests pass.

### Task 4: Install and verify the isolated runtime

**Files:**
- Modify only the container filesystem and dependency environments.

- [ ] **Step 1: Recreate Linux dependencies**

Run: `python3 -m venv --clear .venv && .venv/bin/pip install -e '.[dev]' && npm ci`

Expected: Linux Python and Node dependencies install successfully.

- [ ] **Step 2: Run required checks**

Run: `.venv/bin/ruff check hatsume/plugins/hatsume-plugin`

Run: `npx --no-install pyright`

Run: `.venv/bin/python -m pytest tests -q`

Expected: zero errors, zero test failures, and no resource warnings.

### Task 5: Start and verify live Docker networking

**Files:**
- Update NapCat's existing OneBot JSON through a backup-preserving structured JSON operation.

- [ ] **Step 1: Recreate `hatsume-space` from the verified state**

Snapshot the prepared container, then create `hatsume-space` on `shared-net` with `/work/hatsume/.container/supervise.sh` as PID 1 and no mounts or Docker socket.

- [ ] **Step 2: Point NapCat at Docker DNS**

Change the enabled reverse WebSocket client URL from `ws://host.docker.internal:6999/onebot/v11/ws` to `ws://hatsume-space:6999/onebot/v11/ws`, connect NapCat to `shared-net`, and restart NapCat.

- [ ] **Step 3: Verify bot health and restart behavior**

Confirm `hatsume-space` listens on `0.0.0.0:6999`, NapCat resolves and connects to `hatsume-space`, OneBot reports a connected bot, `hatsume-restart` changes the child PID without stopping the container, and no source mount exists.

- [ ] **Step 4: Verify host isolation**

Run host `git status --short` and compare the host HEAD/tree to the pre-change state. Expected: the macOS repository remains clean and unchanged.
