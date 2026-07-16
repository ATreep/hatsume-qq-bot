# Test Suite Guide

Tests are offline and deterministic. They must not require QQ, live model APIs,
Docker, Apple Photos, or network access.

## Isolation

- Prefer importing pure modules normally.
- When loading plugin files with `importlib`, give stubs complete interfaces and
  remove or restore modified `sys.modules` entries. Module-level stubs affect test
  collection, so avoid them when a fixture or subprocess can isolate the import.
- Use subprocess tests for global monkey patches (`models.py`) or modules that
  cannot safely coexist with other stubs.
- Close coroutines passed to mocked timeout functions and cancel/await background
  tasks during teardown. A passing suite with resource warnings is not clean.

## Coverage Expectations

- Message parsing: use official protocol-shaped payloads plus documented vendor
  variants, malformed responses, timeouts, media, and nesting boundaries.
- Graph logic: test routing marks, queue ownership, cleanup, and the exact tool
  registry passed to `create_agent`.
- Persistence: use temporary SQLite databases; cover migrations and repeated init.
- Agent/process logic: cover success, timeout, cancellation, stdin, and cleanup.

## Commands

```bash
.venv/bin/python -m pytest tests/test_forward.py -q
.venv/bin/python -m pytest tests/test_graph_nodes.py -q
.venv/bin/python -m pytest tests -q
```

Do not update a test to match changed behavior until the intended contract is
verified in source specifications or current product requirements.
