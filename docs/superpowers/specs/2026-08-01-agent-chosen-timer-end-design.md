# Agent-Chosen Recurring Timer End Design

## Goal

Resolve GitHub issue #2 by allowing the chat agent to create a daily, weekly, or
monthly timer when the user has not supplied an end time. The agent chooses a
finite end time from the task content and conversation context instead of asking
the user solely for that value. After successful creation, the agent tells the
user the exact end time it chose.

## Confirmed Decisions

- The agent determines the appropriate end time semantically; there is no fixed
  duration or mode-specific fallback in Python code.
- When the user supplies an end time, the agent preserves that instruction.
- When the user omits it, the agent must choose a reasonable finite `end_at` and
  must not ask a follow-up question solely to obtain an end time.
- After successful creation, the agent's natural reply must state the exact end
  time passed to the tool.
- The selected implementation is limited to timer tool descriptions. It does not
  add a system-prompt rule, tool-result metadata, reply post-processing, or new
  conversation state.

## Scope

The change applies to these recurring timer tools in
`hatsume/plugins/hatsume-plugin/graph/tools.py`:

- `create_daily_timer`
- `create_weekly_timer`
- `create_monthly_timer`

`create_at_timer` is unchanged because its finite schedule is already expressed
by the explicit `trigger_times` list.

The recurring tools continue to require `end_at` in their callable schemas. The
agent therefore makes the semantic decision before invoking a tool, and the
existing schedule builders continue to receive an explicit timezone-bearing ISO
8601 boundary.

## Tool Description Contract

Each recurring timer docstring will state all of the following behavior:

1. If the user explicitly gives an end time, use it.
2. If the user does not give an end time, infer a suitable finite value from the
   task purpose and available conversation context.
3. Do not ask the user solely because the end time is missing, including when the
   task contains no obvious natural horizon.
4. After the tool successfully creates the timer, state the exact chosen end time
   in the natural-language reply to the user.

The existing descriptions of `user_id`, `prompt`, `start_at`, `time_points`,
`step`, limits, formats, and examples remain accurate. The examples may continue
to pass explicit end timestamps because `end_at` remains part of every recurring
tool call.

## Data Flow

1. The chat agent interprets the timer request.
2. It uses an explicit user end time when present; otherwise it selects a finite
   end time appropriate to the task.
3. It calls the applicable recurring timer tool with that `end_at` value.
4. Existing schedule validation, SQLite persistence, and APScheduler registration
   run without behavioral changes.
5. On success, the agent's final reply includes the exact selected end time.

No default is calculated inside `timer/schedule.py`, and no nullable boundary is
introduced into the user-facing recurring timer path.

## Validation And Errors

Existing validation remains authoritative: boundaries require timezone offsets,
the end cannot precede the start, and the range must contain at least one future
occurrence. If an agent-inferred boundary fails validation, the agent should
correct its choice and retry without asking solely for the omitted end time.

If the user explicitly supplied an invalid or contradictory boundary, normal
clarification remains allowed because the problem is no longer an omitted default.
Database and scheduler failures retain their current responses and do not trigger
a claim that the timer was created.

## Testing

Focused tests in `tests/test_tools.py` will verify that all three recurring tool
descriptions contain the inference, no-inquiry, and disclosure requirements. The
tests will also continue to verify that the recurring schemas require `end_at`,
preserving an explicit finite scheduling boundary.

No live-model test is added. Under the selected docstring-only approach, agent
compliance is a prompt contract rather than a deterministic output guarantee.
The existing timer tool and scheduler tests remain the regression suite for tool
creation, validation, persistence, and registration behavior.

## Documentation

`docs/arch.md` will describe the agent-chosen end-time behavior in the timer
creation capability entry and the three recurring tool summaries. No persistence
or scheduling data-flow documentation changes are required because those layers
are unchanged.

## Non-Goals

- Choosing a global default duration.
- Making `end_at` optional or nullable in recurring timer schemas.
- Changing exact-time timers.
- Changing the timer database schema, schedule calculations, recovery, cleanup,
  or APScheduler job registration.
- Adding enforcement that rewrites or appends to the model's final response.
- Closing GitHub issue #2 automatically as part of implementation.
