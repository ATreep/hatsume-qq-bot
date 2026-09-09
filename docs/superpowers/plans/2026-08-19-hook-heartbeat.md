# Per-Group Hook Heartbeat Implementation Plan

> **For agentic workers:** Execute this plan task-by-task in the current session. Repository policy forbids commits unless the user explicitly requests them, so commit steps are intentionally omitted.

**Goal:** Add persistent, per-group, AI-authored Hook scripts whose heartbeats trigger the existing chat graph through a dedicated Hook injection.

**Architecture:** A new `hooks` package owns SQLite records and APScheduler/subprocess lifecycle. Chat tools manage only the bound group, `inject_hook` queues a marked system trigger, and a source-owned read-only Skill teaches the AI to write incremental scripts using exit codes 0 and 10.

**Tech Stack:** Python 3.12+, SQLite, asyncio subprocesses, APScheduler, NoneBot2, LangChain tools, pytest, Ruff, Pyright.

---

### Task 1: Hook persistence

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/hooks/store.py`
- Create: `tests/test_hook_store.py`

- [ ] Add failing tests for idempotent schema setup, group-filtered CRUD, unique names, positive ownership, bounds (`interval >= 300`, `1 <= timeout <= 60`), and the transactional maximum of five enabled Hooks.
- [ ] Run `docker exec hatsume-containerization python -m pytest tests/test_hook_store.py -q` and confirm the missing module/tests fail.
- [ ] Implement `HookStore`, constants, serialized SQLite access, explicit transactions, row-to-dict conversion, create/update/delete/list/get methods, run-state updates, and `close()`.
- [ ] Re-run the focused store tests and confirm they pass without warnings.

Core API:

```python
class HookStore:
    def init_db(self) -> None: ...
    def create_hook(self, *, group_id: int, name: str, script_path: str,
                    prompt: str, interval_seconds: int,
                    timeout_seconds: int, created_by: int) -> dict[str, Any]: ...
    def get_hook(self, hook_id: int) -> dict[str, Any] | None: ...
    def get_hook_by_name(self, group_id: int, name: str) -> dict[str, Any] | None: ...
    def list_hooks(self, group_id: int) -> list[dict[str, Any]]: ...
    def list_enabled_hooks(self, group_ids: Iterable[int] | None = None) -> list[dict[str, Any]]: ...
    def update_hook(self, group_id: int, name: str, **changes: Any) -> dict[str, Any]: ...
    def delete_hook(self, group_id: int, name: str) -> dict[str, Any] | None: ...
    def record_success(self, hook_id: int, exit_code: int, run_at: float) -> None: ...
    def record_failure(self, hook_id: int, exit_code: int | None,
                       error: str, run_at: float) -> None: ...
```

### Task 2: Script validation and execution

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/hooks/executor.py`
- Create: `tests/test_hook_executor.py`

- [ ] Add failing tests for group-root path validation, path traversal, symlink escape, executable/shebang enforcement, exit 0, exit 10, empty exit 10, invalid exit, validation environment, 60-second program bounds, timeout cleanup, output bounds, and same-Hook non-reentrancy.
- [ ] Run the executor test module in the container and verify it fails before implementation.
- [ ] Implement canonical path checks and direct `asyncio.create_subprocess_exec` execution with `/work` cwd, `/root` home, optional `HATSUME_HOOK_VALIDATION=1`, bounded stdout/stderr pumps, timeout termination, process-group kill escalation, and credential-redacted errors.
- [ ] Implement heartbeat execution that re-reads enabled/routable state, persists result state, calls `inject_hook` only for exit 10 with non-empty stdout, and suppresses stale deleted/disabled records.
- [ ] Re-run executor tests and confirm cleanup leaves no child tasks or resource warnings.

Core protocol:

```python
@dataclass(frozen=True)
class HookScriptResult:
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None

async def run_hook_script(script_path: Path, *, timeout_seconds: int,
                          validation: bool = False,
                          workdir: Path = Path("/work")) -> HookScriptResult: ...
```

### Task 3: Scheduling, recovery, and lifecycle

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/hooks/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/hooks/executor.py`
- Modify: `hatsume/plugins/hatsume-plugin/__init__.py`
- Modify: `hatsume/plugins/hatsume-plugin/config.py`
- Modify: `hatsume/plugins/hatsume-plugin/group_runtime.py`
- Extend: `tests/test_hook_executor.py`
- Modify: `tests/test_config.py`

- [ ] Add failing tests for stable job IDs, one job per enabled/routable Hook, first-run delay, one overdue recovery run, disconnect pause without deletion, reconnect restore, update/delete cancellation, and shutdown process cleanup.
- [ ] Add configuration tests for `HOOKS_DIR`, minimum interval, maximum active count, default interval, default timeout, and maximum timeout.
- [ ] Implement the HookStore singleton and public lifecycle functions `init_hook_system`, `restore_hooks`, `pause_hooks_for_groups`, and `shutdown_hooks`.
- [ ] Register interval jobs with `max_instances=1`, `coalesce=True`, and `replace_existing=True`; calculate the recovery start time from `last_run_at` without replaying multiple missed checks.
- [ ] Wire Bot connect after route discovery, Bot disconnect after route removal, and shutdown cleanup without changing Timer semantics.
- [ ] Run Hook executor and config tests.

### Task 4: Dedicated Hook injection

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes.py`
- Modify: `hatsume/plugins/hatsume-plugin/handlers/dialogue.py`
- Modify: `tests/test_timer_injection.py`

- [ ] Add failing tests showing active conversations receive a `hook`-marked queue entry, inactive conversations use `trigger_type="hook"`, Hook payload structure includes stored instructions and stdout, and groups remain isolated.
- [ ] Implement `inject_hook(group_id, hook_name, prompt, event_text, start_conversation_cb=None)` as a distinct injection function.
- [ ] Extend `_start_direct_conv` and `_start_conv_for_trigger` to preserve the explicit trigger type and treat user ID 0 as no notified user for Hook startup.
- [ ] Run injection-focused tests.

Expected queued shape:

```python
{
    "type": "text",
    "text": "(SYSTEM) Hook 'mailbox' detected a new event.\n...",
    SYSTEM_TRIGGER_KEY: "hook",
}
```

### Task 5: Hook chat tools

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`
- Create: `tests/test_hook_tools.py`

- [ ] Add failing tests for `create_hook`, `list_hooks`, `update_hook`, and `delete_hook`; task-local group ownership; requester identity; default 900-second interval and 15-second timeout; validation with no injection; active limit; rollback on schedule failure; and registry inclusion.
- [ ] Implement strict annotated integer types and the four decorated tools with no `group_id` argument.
- [ ] Put semantic refusal/admin-override guidance in `create_hook`'s docstring while enforcing interval, timeout, path, count, and process bounds for everyone.
- [ ] Coordinate validation, persistence, and scheduling so failed validation leaves no row and failed scheduling compensates persisted changes.
- [ ] Run Hook tool tests and existing `tests/test_tools.py` focused registry cases.

### Task 6: Default Hook-authoring Skill

**Files:**
- Create: `data/hatsume-plugin/skills/hook-authoring.md`

- [ ] Add the `hook-authoring` Markdown Skill with frontmatter and the exact exit-code, cursor, validation, credential, interval, timeout, refusal, and registration instructions from the design.

### Task 7: Documentation and runtime exclusions

**Files:**
- Modify: `README.md`
- Modify: `docs/arch.md`
- Modify: `AGENTS.md`
- Modify: `hatsume/plugins/hatsume-plugin/AGENTS.md`
- Modify: `tests/AGENTS.md`

- [ ] Document the Hook capability, package ownership, SQLite/script paths, tools, lifecycle, protocol, injection marker, limits, and runtime artifact exclusions.
- [ ] Preserve all unrelated existing edits while inserting Hook information into the current documents.
- [ ] Run `git diff --check` on all touched files.

### Task 8: Verification, synchronization, and restart

**Files:**
- Synchronize allowed changed files to `/Users/treep/Dev/qqbot/hatsume`, excluding `.container` and root `AGENTS.md`.

- [ ] Run Hook test modules in parallel container processes, not the full test suite.
- [ ] Run relevant existing regression modules in parallel: injection, tools, Skill manager, config, command registration, container lifecycle, and self-evolution runtime.
- [ ] Run `docker exec hatsume-containerization ruff check hatsume/plugins/hatsume-plugin tests/test_hook_store.py tests/test_hook_executor.py tests/test_hook_tools.py`.
- [ ] Run `docker exec hatsume-containerization npx --no-install pyright` and report any unrelated baseline failures separately.
- [ ] Inspect the full source worktree and independent `data/hatsume-plugin` worktree without staging or committing either.
- [ ] Query unfinished runtime Agent state using the repository-supported command. If none are active, run `docker exec hatsume-containerization hatsume-restart`; otherwise create/reuse the single restart-waiting Todo and wait for completion before restarting.
- [ ] Verify the container remains running and its post-restart logs show successful Hook database initialization and scheduler recovery.
