# Sandbox Computer Use with Jev Routing

## Problem

`sandbox_computer_use` currently exposes the complete desktop and Chrome tool
set to one general LLM agent. The model must repeatedly inspect the desktop,
choose a window, inspect controls, choose an operation, and decide when to
report completion. This makes inspection and routing expensive, and it mixes
semantic decisions with low-level execution.

The redesign makes Jev the typed router for the recurring inspection choices.
The existing LLM remains responsible for bounded operations that require
vision, natural-language argument extraction, or opening a new application or
webpage. Existing AT-SPI and Chrome CDP tools remain the only execution layer.

## Goals

- Run a fixed inspect -> Jev choice -> inspect selected target -> Jev choice ->
  execute loop for the lifetime of one sandbox task.
- Give Jev the current task and all currently displayed windows on every
  top-level iteration.
- Support existing native windows, existing Chrome windows, opening an
  application, opening a Chrome webpage, and ending with an LLM-generated
  report.
- Use Jev to choose native and Chrome elements and their next operation.
- Preserve the current singleton `sandbox_computer_use` dispatch contract.
- Keep low-level action execution deterministic and preserve stale-reference
  checks in `gui_automation.py`.

## Non-goals

- Changing AT-SPI or Chrome CDP behavior.
- Exposing GUI tools to the main chat agent.
- Passing raw screenshots to Jev. Jev receives text and structured JSON only;
  the existing vision path handles images.
- Replacing the existing general LLM for bounded vision or argument tasks.

## Architecture

### Coordinator

Add `graph/sandbox_computer_use.py` with a coordinator used by
`_run_sandbox_computer_use`. The coordinator receives the task, the user ID,
the current group runtime, and injected callables for Jev and GUI operations.
The injected boundary keeps the loop testable without starting a container or
calling a remote model.

The coordinator owns iteration state:

```text
task
iteration
recent_action
last_window_state
last_target_state
```

The coordinator does not retain element IDs across a fresh inspection. Any
stale-element response causes a new top-level inspection.

### Shared System One helper

Move the dependency-light request construction and answer extraction currently
local to `graph/nodes.py` into a shared helper module. The helper will preserve
the current `/systemone` request body and model configuration, so the existing
chat-intent judge and the new coordinator use the same TypeSafe-compatible
contract. The helper exposes:

- `post_systemone(model, state, questions)`
- `get_choice_answer(response, question_id)`
- `build_systemone_body(model_name, state, questions)`

The Jev model remains `get_intent_model()` / `get_jev_model()` and is configured
by the existing TypeSafe environment variables.

### Existing tools

The coordinator invokes the existing structured tools rather than duplicating
their shell bridge:

- Native desktop: `gui_inspect`, `gui_click`, `gui_focus`, `gui_set_text`,
  `gui_key`, `gui_type`, `gui_screenshot`, `gui_click_coordinates`.
- Chrome: `chrome_inspect`, `chrome_click`, `chrome_focus`,
  `chrome_set_text`.
- Bounded LLM support: `gui_launch`, `chrome_open`, `view_image`.

## Jev state and questions

Every Jev request uses one structured state object:

```json
{
  "task": "the complete sandbox task",
  "windows": [
    {
      "id": "window-1",
      "application": "Firefox",
      "kind": "native",
      "summary": "visible window and relevant controls"
    }
  ],
  "selected_window": null,
  "inspection": null,
  "recent_action": null,
  "step3_decision": null,
  "step3_llm_result": null,
  "step3_history": []
}
```

All dynamic criteria include an explicit no-match outcome. Jev responses are
accepted only when the selected key is present in the criteria and confidence
is at least `SANDBOX_COMPUTER_USE_JEV_MIN_CONFIDENCE` (default `0.55`). A
missing, malformed, or low-confidence answer routes to the bounded LLM
inspection path and does not execute a guessed action.

### Window choice

After `gui_inspect`, ask one `Choice` named `window_action` with dynamic choices:

- one choice for each visible window;
- `open_application`;
- `open_webpage`;
- `finish_report`.

The selected window choice includes the normalized application name and kind in
the coordinator state. The LLM handles the two open branches, then the loop
restarts at `gui_inspect`.

### Native window choices

For a selected native application, call `gui_inspect(application=...)`, then
ask Jev for `element_action` with one choice for each inspected element and
these control choices:

- `screenshot_coordinate_click`;
- `finish_report`.

For a selected element, ask `native_operation` with:

- `click`;
- `set_text`;
- `focus_key`;
- `focus_type`.

Element metadata includes only the current inspect output: ID, role, name,
description, actions, bounds, enabled state, focus state, and text where
available.

### Chrome window choices

For a selected Chrome window, call `chrome_inspect`, then ask Jev for
`chrome_element_action` with one choice per current CDP element plus
`screenshot_coordinate_click` and `finish_report`. For an element, ask
`chrome_operation` with `chrome_click`, `chrome_focus`, or
`chrome_set_text`.

## Bounded LLM branches

The general model is created as a short-lived bounded agent for each branch.
Each branch has a narrow tool list and a single-purpose prompt:

- Open application: `gui_launch`, optional `gui_inspect` for confirmation.
- Open webpage: `chrome_open`, optional `chrome_inspect` for confirmation.
- Native text/key/type argument: exactly one selected low-level operation and
  the task/element metadata needed to derive its argument.
- Chrome text argument: exactly one `chrome_set_text` call.
- Screenshot coordinate click: `gui_screenshot`, `view_image`, and
  `gui_click_coordinates` only. The vision response must identify integer
  coordinates in the original screenshot dimensions; invalid coordinates end
  the iteration with a report rather than retrying an arbitrary click.
- Finish report: `gui_screenshot` followed by `view_image`, returning the
  vision model's concise report directly.

After a successful open or action branch, the coordinator records
`recent_action` and restarts at the top-level inspection. The latest Step 3
Jev element/operation decision is also retained as `step3_decision` for the
next Step 3 choice. Completed Step 3 iterations are retained in
`step3_history`, capped at the latest three iterations. When an operation is
`chrome_set_text`, its bounded LLM result is stored on that history entry and
retained as `step3_llm_result`. `finish_report` returns immediately.

## Loop and failure behavior

- Default maximum iterations: `30`, configurable through
  `SANDBOX_COMPUTER_USE_MAX_ITERATIONS`.
- A tool error, container startup error, or stale reference is recorded in
  `recent_action`; stale references restart inspection once, while repeated
  errors are included in the final report.
- A Jev transport or parsing error uses the bounded LLM inspection branch for
  the current state. It does not silently execute a default click.
- The iteration limit returns a report stating the completed actions and the
  last observed state.
- Task cancellation propagates and preserves the existing agent cancellation
  state handling.
- The existing global singleton check remains in `agent_dispatch`.

## Integration changes

- Replace the current general-agent implementation in
  `_run_sandbox_computer_use` with the coordinator entry point.
- Keep `_get_sandbox_computer_use_tools` for bounded LLM agents, but do not
  expose the entire list to one unconstrained loop.
- Update `SANDBOX_COMPUTER_USE_PROMPT` to describe the bounded branch contracts
  and the Jev-controlled loop.
- Add the confidence and iteration settings to configuration with safe defaults.
- Preserve current user-facing completion notifications and result text.

## Testing

Use focused local unit tests only; do not inspect or execute `.venv` and do not
run full-volume tests.

Add coordinator tests with fake Jev and GUI callables covering:

1. top-level inspect and dynamic window criteria;
2. native element selection and each native operation;
3. Chrome element selection and each Chrome operation;
4. open-application and open-webpage branches restarting inspection;
5. screenshot coordinate click and report termination;
6. malformed or low-confidence Jev answers using bounded fallback;
7. stale references, tool errors, and iteration limits;
8. cancellation propagation.

Retain and run the existing GUI tool schema tests and sandbox singleton tests.
Run the focused test modules in parallel with the local Python interpreter.

## Rollout and observability

Log one compact record per iteration containing the iteration number, selected
window/action key, confidence, and execution result class. Do not log task
secrets, text-entry values, screenshots, or API credentials. The final report
contains user-relevant outcomes only.
