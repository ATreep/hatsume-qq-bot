# Sandbox Computer Use with Jev Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the sandbox computer-use loop through Jev typed choices while retaining bounded LLM execution for launch, vision, and natural-language action arguments.

**Architecture:** Add a dependency-light coordinator module that receives GUI/Jev/LLM callables and runs the inspect-select-execute loop. Extract the existing System One request helpers into a shared module, wire the existing sandbox handler to the coordinator, and keep the AT-SPI/CDP bridge as the execution boundary.

**Tech Stack:** Python 3, LangChain tools/agents, existing TypeSafe-compatible `/systemone` client, AT-SPI, Chrome CDP, unittest/pytest-compatible focused tests.

**Spec:** `docs/superpowers/specs/2026-10-05-sandbox-computer-use-jev-design.md`

## Global Constraints

- Do not modify or inspect `.venv`.
- Do not run full-volume tests; run focused unit tests in parallel.
- Do not expose GUI tools to the main chat agent.
- Jev receives structured JSON/text, never raw screenshots.
- Low-confidence or malformed Jev answers must not execute guessed actions.
- Preserve the singleton `sandbox_computer_use` dispatch contract.

### Task 1: Extract shared System One helpers

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/graph/systemone.py`
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes.py`
- Test: `tests/test_drex_systemone.py`

**Interfaces:**
- Produces `build_systemone_body(model_name, state, questions) -> dict`, `post_systemone(model, state, questions) -> Any`, and `get_choice_answer(response, question_id) -> Mapping[str, Any] | None`.
- Preserves the current request body and response compatibility used by `ai_node`.

- [x] **Step 1: Add shared helper contract tests**

Extend the existing dependency-light tests to import the new helper module and verify the exact body shape, one async POST, and extraction from mapping/model-dump answers.

- [x] **Step 2: Run focused tests and confirm the new import fails**

Run: `python -m pytest tests/test_drex_systemone.py -q`

Expected: the new helper import/tests fail before implementation.

- [x] **Step 3: Move the helper implementations**

Copy the current `_build_systemone_body`, `_post_systemone`, and `_jev_answer` behavior into `graph/systemone.py`, rename the public functions, and preserve the existing typing imports.

- [x] **Step 4: Update `nodes.py` to import the shared functions**

Replace local definitions/calls with imports and aliases only where needed, leaving chat-intent state and criteria unchanged.

- [x] **Step 5: Run the focused helper tests**

Run: `python -m pytest tests/test_drex_systemone.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the helper extraction**

```bash
git add hatsume/plugins/hatsume-plugin/graph/systemone.py hatsume/plugins/hatsume-plugin/graph/nodes.py tests/test_drex_systemone.py
git commit -m "refactor: share system one request helpers"
```

### Task 2: Implement the Jev-routed coordinator

**Files:**
- Create: `hatsume/plugins/hatsume-plugin/graph/sandbox_computer_use.py`
- Create: `tests/test_sandbox_computer_use_coordinator.py`

**Interfaces:**
- Produces `SandboxComputerUseCoordinator.run(task: str) -> str`.
- Constructor accepts `jev`, `llm_branch`, `gui`, `chrome`, `max_iterations`, and `min_confidence` callables/settings so tests can use fakes.
- Jev calls receive `{task, windows, selected_window, inspection, recent_action, step3_decision, step3_llm_result, step3_history}` and typed question mappings; `step3_history` preserves the latest three completed Step 3 iterations for routing context.

- [x] **Step 1: Write failing coordinator tests**

Cover top-level window criteria, native and Chrome operation criteria, launch-branch restart, screenshot/report termination, low-confidence fallback, and iteration limit. Assert call order and that no low-confidence action executes.

- [x] **Step 2: Run the coordinator tests to verify failure**

Run: `python -m pytest tests/test_sandbox_computer_use_coordinator.py -q`

Expected: FAIL because the coordinator module and class are absent.

- [x] **Step 3: Implement normalized state and Jev-choice validation**

Implement JSON parsing/normalization, dynamic criteria with `open_application`, `open_webpage`, and `finish_report`, confidence validation at `0.55`, and an explicit fallback result for malformed/low-confidence responses.

- [x] **Step 4: Implement native and Chrome target routing**

Implement selected-window inspection, element criteria, native operations (`click`, `set_text`, `focus_key`, `focus_type`), and Chrome operations (`chrome_click`, `chrome_focus`, `chrome_set_text`). Do not retain IDs after a fresh inspect.

- [x] **Step 5: Implement bounded branches and loop restart**

Call the injected bounded LLM branch for application/webpage opens, screenshot coordinate clicks, text/key/type argument extraction, and final screenshot reports. Record `recent_action`, restart after successful actions/opens, and return after reports.

- [x] **Step 6: Implement errors, cancellation, and iteration limits**

Record tool/stale-reference errors, propagate cancellation, and return a concise final report at `30` iterations unless configured otherwise.

- [x] **Step 7: Run coordinator tests**

Run: `python -m pytest tests/test_sandbox_computer_use_coordinator.py -q`

Expected: PASS.

- [ ] **Step 8: Commit the coordinator**

```bash
git add hatsume/plugins/hatsume-plugin/graph/sandbox_computer_use.py tests/test_sandbox_computer_use_coordinator.py
git commit -m "feat: add Jev-routed sandbox computer use coordinator"
```

### Task 3: Wire the sandbox agent and configuration

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/agents.py`
- Modify: `hatsume/plugins/hatsume-plugin/config.py`
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py`
- Modify: `tests/test_sandbox_computer_use.py`

**Interfaces:**
- `_run_sandbox_computer_use` delegates to `SandboxComputerUseCoordinator`.
- Configuration exposes `SANDBOX_COMPUTER_USE_MAX_ITERATIONS=30` and `SANDBOX_COMPUTER_USE_JEV_MIN_CONFIDENCE=0.55`.
- Existing tool registration and singleton dispatch behavior remain intact.

- [x] **Step 1: Update agent integration tests**

Change the AST contract test to assert the handler imports/constructs the coordinator and does not create one unconstrained full-tool agent for the main loop.

- [x] **Step 2: Run the focused sandbox tests to capture the expected failure**

Run: `python -m pytest tests/test_sandbox_computer_use.py -q`

Expected: the updated integration assertion fails until wiring is implemented.

- [x] **Step 3: Add configuration defaults**

Read the two environment values with numeric validation and safe defaults; do not print secrets or modify `.venv`.

- [x] **Step 4: Replace `_run_sandbox_computer_use`**

Construct the Jev model, bounded branch runner, existing GUI tool wrappers, and coordinator. Preserve runtime binding, shell limits, retry behavior where it remains appropriate, result extraction, and existing notification flow.

- [x] **Step 5: Update the sandbox prompt**

Describe Jev-controlled inspection, bounded LLM branches, screenshot/report behavior, and the requirement to restart at top-level inspection after opens/actions.

- [x] **Step 6: Run focused integration/tool tests**

Run in parallel:

```bash
python -m pytest tests/test_sandbox_computer_use.py -q
python -m pytest tests/test_gui_tools.py -q
python -m pytest tests/test_drex_systemone.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit integration changes**

```bash
git add hatsume/plugins/hatsume-plugin/graph/agents.py hatsume/plugins/hatsume-plugin/config.py hatsume/plugins/hatsume-plugin/prompts.py tests/test_sandbox_computer_use.py
git commit -m "feat: route sandbox computer use through Jev"
```

### Task 4: Final verification

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-sandbox-computer-use-jev.md`

- [x] **Step 1: Run all focused tests in parallel**

Run:

```bash
python -m pytest tests/test_sandbox_computer_use.py tests/test_sandbox_computer_use_coordinator.py tests/test_gui_tools.py tests/test_drex_systemone.py -q
```

Expected: PASS with no `.venv` access.

- [x] **Step 2: Run syntax and diff checks**

Run: `python -m compileall -q hatsume/plugins/hatsume-plugin/graph hatsume/plugins/hatsume-plugin` and `git diff --check HEAD~3..HEAD`

Expected: zero syntax or whitespace errors.

- [x] **Step 3: Record completed plan items and residual risks**

Mark completed steps in this plan and report that live GUI/CDP execution was not run unless a sandbox container is available; unit fakes cover routing behavior.
