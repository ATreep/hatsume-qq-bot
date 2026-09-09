# Per-Group Hook Heartbeat Design

## Goal

Add persistent, per-group Hooks that let Hatsume monitor external changes with
AI-authored scripts. A heartbeat runs each enabled script on its configured
interval. When a script reports an event, Hatsume injects the event into the
target group's existing chat graph in the same queue-oriented manner as Agent
and Timer notifications.

The motivating example is a mailbox watcher: the AI writes an incremental
inbox-checking script, registers it as a Hook, and a newly received message
causes `chat_agent` to handle an event in the owning QQ group.

## Product Requirements

- Hooks are persisted and restored after a bot restart.
- Every Hook belongs to exactly one positive QQ `group_id`.
- A group may have at most five enabled Hooks. Disabled Hooks do not consume
  this limit.
- A group can have multiple Hooks with unique names.
- All Hook intervals are at least 300 seconds. There is no administrator
  exception.
- `timeout_seconds` must be between 1 and 60 seconds. The default is 15
  seconds, and there is no administrator exception.
- The LLM chooses an appropriate interval when authoring a Hook. It should use
  a longer interval unless the monitored source genuinely needs five-minute
  polling.
- The bot normally refuses meaningless Hook requests, requests better served
  by an existing Timer, and scripts that cannot be implemented as a short
  incremental check. An administrator may explicitly override this semantic
  refusal, but the program-enforced interval and timeout limits still apply.
- Triggered events join the target group's existing `human_queue`. A Hook must
  never start a second graph for a group that already has an active graph.
- Hook scripts and their state live under the shared
  `data/hatsume-plugin/hooks/` directory; per-group ownership remains in the
  Hook metadata rather than in the filesystem layout.

## Architecture

Create a dedicated `hooks/` package beside `timer/`, `memory/`, and `skills/`.
It owns Hook persistence, validation, scheduling, execution, and lifecycle.
Hook behavior remains separate from the Timer schema because it has distinct
script, exit-code, timeout, failure, and enablement semantics.

```text
chat_agent
    |
    | create/list/update/delete Hook tools
    v
HookStore (SQLite) <----> data/hatsume-plugin/hooks/hooks.db
    |
    v
APScheduler heartbeat job (one per enabled, routable Hook)
    |
    v
bounded local subprocess
    |
    | exit 10 + stdout
    v
inject_hook()
    |
    +-- active group graph -> append marked entry to human_queue
    |
    +-- inactive group graph -> existing direct-conversation startup path
```

The package should expose a small public API from `hooks/__init__.py`, while
keeping SQLite operations in `hooks/store.py` and APScheduler/subprocess work in
`hooks/executor.py`. It reuses the configured `nonebot_plugin_apscheduler`
scheduler but does not add a new scheduler instance.

## Storage Model

`nonebot_plugin_localstore` locates `hooks/hooks.db`, which resolves to
`data/hatsume-plugin/hooks/hooks.db` when localstore uses the repository data
directory. The database uses WAL, foreign-key enforcement, parameterized SQL,
explicit commits, and a reentrant operation lock following the TimerStore
cross-thread pattern.

The initial schema contains one table:

```sql
CREATE TABLE hooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL CHECK (group_id > 0),
    name TEXT NOT NULL,
    script_path TEXT NOT NULL,
    prompt TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds >= 300),
    timeout_seconds INTEGER NOT NULL CHECK (
        timeout_seconds >= 1 AND timeout_seconds <= 60
    ),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_by INTEGER NOT NULL CHECK (created_by > 0),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_run_at REAL,
    last_exit_code INTEGER,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    UNIQUE (group_id, name)
);
```

The store checks the enabled-Hook count inside the same serialized transaction
that creates or enables a Hook. This prevents concurrent requests from
exceeding five enabled Hooks for one group. Names are trimmed, non-empty, and
limited to 64 characters. Prompts are trimmed, non-empty, and limited to 2,000
characters. Persisted `last_error` text is credential-redacted and limited to
2,000 characters.

The stable APScheduler job ID is derived from the database ID, for example
`hook_heartbeat_<id>`. Next-run time is scheduler state rather than persisted
domain state; `last_run_at` is used to compute recovery behavior.

## Script Ownership And Validation

All groups share one canonical script root:

```text
data/hatsume-plugin/hooks/
```

`create_hook` and script-changing `update_hook` only accept an existing regular
file below the shared canonical root. Validation resolves the candidate and
root paths, rejects path traversal and paths outside the shared root, and
rejects symlinks whose resolved target escapes it. The stored path is the
normalized canonical path.

Scripts are written before registration, normally by `coding_agent` after it
loads the built-in Hook-authoring Skill. A registered script must be directly
executable and have a shebang. The executor launches it with
`asyncio.create_subprocess_exec()` rather than interpolating it into a shell
command. It runs inside the current Hatsume container, uses `/work` as its
working directory and `/root` as `HOME`, and does not invoke Docker or create a
nested container.

The script owns source-specific cursor state beneath its group directory. It
must use incremental identifiers, timestamps, UIDs, or another durable cursor
so unchanged data does not trigger repeatedly. Credentials come from the
environment or an explicitly provisioned permission-restricted configuration;
they are never embedded in the script or injected event text.

## Exit-Code Protocol

The protocol is intentionally small:

- Exit `0`: no new event. stdout should be empty. No chat injection occurs.
- Exit `10`: one or more new events are available. Trimmed stdout is the event
  payload delivered to `chat_agent`.
- Any other exit code: execution failure. No chat injection occurs.

Exit `10` with empty stdout is a protocol failure. Output is decoded as UTF-8
with replacement for invalid bytes. stdout and stderr collection is bounded;
stdout beyond 8 KiB is a failure instead of silently injecting a truncated
event. stderr is retained only as bounded diagnostic state and is never sent
directly to the group.

Registration performs one validation run under the requested timeout with
`HATSUME_HOOK_VALIDATION=1`. A conforming script must not advance, create, or
replace its durable event cursor in validation mode. Exit `0` and exit `10` both
prove that the script follows the executable protocol, but a validation-time
exit `10` is not injected. Other exits, timeout, oversized output, or an empty
exit-10 payload prevent registration or script replacement. Validation runs do
not update `last_run_at`, `last_exit_code`, `last_error`, or failure counters.

## Scheduling And Recovery

Every enabled Hook with an explicit Bot route has one APScheduler heartbeat job.
The job uses `max_instances=1` and coalescing, and the executor also holds a
per-Hook execution lock covering validation and normal runs. The same Hook
therefore cannot overlap with itself or build a backlog. Different Hooks,
including Hooks in different groups, may run concurrently.

After a normal heartbeat finishes, the interval schedule continues regardless
of whether the result was no change, a trigger, or a failure. Failures never
cause a rapid retry loop.

On startup and Bot connect:

1. Discover and bind group-to-Bot routes first.
2. Restore enabled Hook jobs only for explicitly routable groups.
3. If `last_run_at` is null, schedule the first heartbeat one full interval
   after restoration. If `last_run_at + interval_seconds` is in the future,
   schedule from that point. If it is overdue, run once promptly and then
   continue at the normal interval. Do not replay multiple missed heartbeats.

On Bot disconnect, cancel jobs for routes owned by that Bot but keep Hook rows
and scripts. Reconnection restores them. Plugin shutdown cancels heartbeat jobs,
terminates and awaits running Hook subprocesses, then allows existing group
runtime cleanup to proceed. A failure in one Hook cleanup must not prevent
other groups from being cleaned up.

## Execution State And Failure Handling

Before launch, the executor re-reads the Hook row and confirms that it remains
enabled and its group remains routable. It tracks the running subprocess by
Hook ID so update, delete, shutdown, and tests can cancel it deterministically.
Update, disable, and delete first cancel and reap an active process for that
Hook before replacing scheduling or persistence.

Each completed run updates `last_run_at` and `last_exit_code`. Exit `0` and a
successfully injected exit `10` clear `last_error` and reset
`consecutive_failures`. Protocol errors, non-protocol exit codes, launch errors,
timeouts, oversized output, and injection failures store a redacted bounded
error and increment `consecutive_failures`. Hooks are not automatically deleted
or disabled on repeated failure; their status remains visible through
`list_hooks` and normal-interval retries continue.

Timeout cancellation terminates the child process and escalates to kill after a
short grace period. Cancellation must reap the process and close its streams.
Logs and persisted errors pass through the existing credential-redaction helper.

## Dedicated Chat Injection

Add `inject_hook()` to `graph/nodes.py`. It may share small internal helpers with
Agent and Timer injection, but it remains a distinct public injection function
and does not masquerade as either trigger type.

The injected model message has a stable structure:

```text
(SYSTEM) Hook '<name>' detected a new event.

## Hook instructions
<stored prompt>

## Hook event
<script stdout>
```

The queue entry uses `make_system_trigger_message(message, "hook")`. The
`hook` marker bypasses end detection exactly like Agent and Timer markers and is
removed before the model sees user-origin metadata. When the group is already
chatting, `inject_hook()` appends to that group's `human_queue`. Otherwise it
uses the existing group graph-start lock and direct-conversation helper with
`trigger_type="hook"`. Bot routing always comes from
`GroupRuntimeRegistry.get_bot(group_id)`; no global or most-recent Bot fallback
is allowed.

If the Hook row is deleted after its script exits but before injection, the
executor suppresses the stale event. Multiple exit-10 runs may enqueue multiple
events, while deduplicating external events remains the script's cursor-based
responsibility.

## Chat Tools

Add four tools to `graph/tools.py` and register them once in `CHAT_TOOLS`:

### `create_hook`

Inputs are `name`, `script_path`, `prompt`, optional `interval_seconds`, and
optional `timeout_seconds`. It derives `group_id` and requester identity from
the current task-local runtime. The tool validates limits, path ownership,
enabled count, uniqueness, and the validation run before committing the row and
registering the job. The LLM should normally provide the interval it selected;
if omitted, the tool uses a conservative documented default of 900 seconds.

### `list_hooks`

Lists only the current group's Hooks with name, enabled state, interval,
timeout, script path, next heartbeat, last run, last exit code, bounded latest
error, and consecutive failure count. It does not create a group directory as a
side effect.

### `update_hook`

Updates one current-group Hook by name. Optional fields may replace its script,
prompt, interval, timeout, or enabled state. Script changes require a validation
run. Enabling rechecks the five-active limit transactionally. Scheduling is
replaced only after validation succeeds; on scheduler registration failure the
database update is rolled back or compensated so persisted and runtime state do
not silently diverge.

### `delete_hook`

Cancels and removes one current-group Hook by name. It does not delete the
script or adjacent cursor/configuration files because those may be shared or
valuable for recovery. Script cleanup remains an explicit filesystem action.

The tools accept no arbitrary `group_id`, so an LLM cannot use them to inspect
or mutate another group's Hooks. Tool docstrings and the role prompt state that
Hook creation is for meaningful, quick change detection. The semantic
administrator override is determined from the current query user's QQ ID and
`ADMIN_QQ_ID`; it never alters runtime validation. Meaningfulness is a prompt
and Skill policy rather than a heuristic database check; interval, timeout,
path, count, and process constraints are always enforced by the program.

## Default Hook-Authoring Skill

Store the read-only `hook-authoring` Skill with all other default Skills at
`data/hatsume-plugin/skills/hook-authoring.md`. It is part of the existing
public runtime Skill layer and is overlaid only by current-group local Skills.
Public names are reserved: group-local Skills cannot overwrite or delete them.
The Skill remains discoverable through the existing Skill list and is loaded
through the existing `skill_read` flow.

The Skill instructs the AI to:

- decide whether the request is change detection rather than a Timer or a
  one-shot task;
- refuse meaningless or inherently long-running designs unless the requester
  is the administrator and explicitly insists;
- still restructure every accepted script into a run lasting at most 60
  seconds and use an interval of at least 300 seconds;
- choose a conservative interval based on source cost and freshness needs;
- store scripts and state only under the shared Hook directory, using stable
  names to avoid collisions;
- use an incremental durable cursor and atomic cursor writes;
- honor `HATSUME_HOOK_VALIDATION=1` by checking the source without mutating the
  durable cursor or other externally visible state;
- emit no stdout and exit `0` when unchanged;
- emit concise, non-secret event context and exit `10` when changed;
- send diagnostics to stderr and use other exit codes for failure;
- avoid interactive input, daemonization, background children, and overlapping
  work;
- obtain credentials from the environment or protected configuration;
- manually run the script at least twice in validation mode, including an
  unchanged pass, before calling `create_hook`.

## Lifecycle Integration

Plugin initialization creates/opens the Hook store without running jobs. Bot
connect first discovers group routes, then initializes Timer and Hook jobs for
the routed group set. Bot disconnect tells the Hook executor to cancel jobs for
the affected groups while retaining persistence. Shutdown calls Hook cleanup as
a separate stage so Agent and container cleanup still run if it fails.

No Hook state is added to `ConversationState`; persistent metadata belongs to
HookStore, running subprocess ownership belongs to the Hook executor, and chat
delivery continues through the target `GroupRuntime`.

## Security And Operational Boundaries

- Hook scripts are arbitrary local programs and therefore are only authored
  through the existing trusted AI/Shell workflow; the feature does not accept
  script text from untrusted protocol payloads.
- Direct subprocess execution avoids shell interpolation of stored paths.
- Canonical path enforcement prevents reads outside the shared Hook directory
  through the Hook tools.
- Hook output and errors are bounded and credential-redacted before storage or
  logging.
- The runtime never invokes Docker or stops the Hatsume container.
- `data/hatsume-plugin/hooks/` is runtime data and must be added to repository
  documentation and ignore/exclusion rules; scripts, cursors, and `hooks.db*`
  are not committed to the Hatsume source repository.

## Testing Strategy

Tests are offline, focused, and parallelizable. They use temporary directories,
temporary SQLite databases, fake schedulers, stub Bot routes, and short local
scripts. No live QQ, mail server, model API, network, or Docker dependency is
allowed.

Coverage includes:

- idempotent schema initialization and reopening an existing database;
- positive group ownership, name uniqueness, and group-filtered CRUD;
- transactional five-enabled-Hook limit under concurrent create/enable calls;
- 300-second minimum interval and 1-to-60-second timeout enforcement for every
  requester, including administrators;
- canonical-path acceptance, traversal rejection, cross-group rejection,
  symlink escape rejection, missing/non-regular file rejection, and executable
  validation;
- validation runs for exit `0`, valid exit `10`, empty exit `10`, invalid exit,
  timeout, and oversized output, with no validation-time injection;
- heartbeat success, trigger, error state, credential redaction, timeout child
  cleanup, bounded output, and same-Hook non-reentrancy;
- independent parallel execution for different Hooks and groups;
- route-aware startup recovery, one overdue recovery run, future scheduling,
  disconnect cancellation, reconnect restoration, update replacement, delete
  cancellation, and shutdown cleanup;
- `inject_hook()` active-conversation queuing, inactive-conversation graph
  startup, group isolation, dedicated `hook` source marking, and end-detection
  bypass;
- tool registry presence, task-local group binding, requester/admin semantic
  guidance, omitted-interval default, update rollback/compensation, and list
  output;
- source built-in Skill discovery, precedence, read-only behavior, and required
  authoring contract text.

Run Hook/store/executor/injection/tool/Skill-focused tests first. Per repository
instruction, do not run the full-volume test suite for this feature. Run relevant
unit modules in parallel where isolation permits, followed by Ruff and Pyright
checks scoped according to repository requirements.

## Documentation Impact

Implementation updates must document the new `hooks/` package, persistence,
script protocol, queue injection, startup/disconnect/shutdown flow, tool list,
built-in Skill layer, and runtime artifact exclusion in `docs/arch.md`,
`README.md`, root `AGENTS.md`, and the plugin/test-specific `AGENTS.md` files as
appropriate. The separate `/Users/treep/Dev/qqbot/hatsume` synchronization must
exclude `.container` and root `AGENTS.md` as required by repository policy.

## Out Of Scope

- Push/webhook HTTP endpoints.
- Sub-five-minute polling.
- More than five enabled Hooks per group.
- Cross-group Hook management tools.
- Automatic deletion of scripts or cursor files.
- Automatic disabling after repeated failures.
- A second chat graph or Hook-specific LLM agent.
- Exactly-once delivery guarantees from external services.
