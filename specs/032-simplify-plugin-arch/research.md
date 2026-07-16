# Research: Simplify Plugin Architecture

**Feature**: 032-simplify-plugin-arch
**Date**: 2026-07-15

## Research Questions

### Q1: Can modules be merged without breaking Python's import system?

**Decision**: Yes — all merges are code-level consolidations within existing packages. No `sys.path` or `importlib` changes are needed. The merged modules remain in the same package directories with the same package-level visibility.

**Rationale**: The refactor only changes which file contains which code. All public exports remain importable from the package namespace. Internal cross-imports that previously went between files (e.g., `from .pipeline import get_human_message`) become same-file references after the merge.

**Alternatives considered**:
- `importlib` redirections via `sys.meta_path` — overly complex for a static refactor; unnecessary since we control all import sites.
- Shim modules (keep old files as one-line re-exports) — rejected per user's choice of "full rename" approach.

### Q2: Will the circular import in memory/ be resolved?

**Decision**: Yes. The current circular dependency chain is: `store.py` → `db.py` (static import), `db.py` → `store.py` (lazy import inside `migrate_from_json()`), and `retrieval.py` imports both. Merging all three into `engine.py` eliminates all intra-file imports — the lazy import of `normalize_memory_object` from `store` becomes a same-file function call.

**Rationale**: Python's circular import issue only arises at the module granularity. When all code lives in one file, function definition ordering resolves the dependency (as long as functions are defined before their call sites, which the section ordering ensures).

### Q3: What test stub strategy preserves test isolation?

**Decision**: Global string replacement of `sys.modules["..."]` paths in test files. The `sed` command-based approach is the safest because:
1. Test stubs reference modules by fully-qualified Python path strings (not Python expressions)
2. The replacement is purely mechanical (old name → new name)
3. No test logic, mock setup, or assertion needs to change

**Alternatives considered**:
- Dynamic module aliasing via `sys.modules` entries — would preserve old names but leaves a compat shim that contradicts the "full rename" approach.
- Rewriting tests to use a fixture-based import system — good long-term but out of scope for this refactor.

### Q4: Are there any import-order pitfalls in the merged files?

**Decision**: The section ordering in merged files (determined during the design audit) ensures all dependencies are defined before their consumers:
- `dialogue.py`: forward → pipeline → chat (pipeline uses forward, chat uses both)
- `engine.py`: db → store → retrieval (store uses db, retrieval uses both)
- `tools.py`: poke → commands (commands uses nothing from poke; poke is a leaf)

Module-level code (imports, class/function definitions) is order-independent within a single file as long as forward references aren't resolved at import time. The only tricky case is the `_wire_conv_state(conv_state)` call in chat.py — this is a module-level function call that runs at import time. The `_wire_conv_state` function is defined in tools.py, which is imported by dialogue.py via `from .tools import _wire_conv_state` — this import is already at the top of chat.py (after the merge, at the top of dialogue.py). Python resolves module-level imports before executing module-level code in the importing file, so `_wire_conv_state` is available when `conv_state = ConversationState()` followed by `_wire_conv_state(conv_state)` runs. No ordering issue.
