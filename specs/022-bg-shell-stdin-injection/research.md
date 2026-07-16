# Research: Background Shell Stdin Injection

**Date**: 2026-06-30

## Research Tasks

No NEEDS CLARIFICATION markers in Technical Context. All technology choices are dictated by the existing project stack. Research focused on validating approach against existing codebase patterns.

## Decisions

### D1: asyncio.Queue for Chat↔Agent Bridge

**Decision**: Use `asyncio.Queue[str | None]` to bridge the synchronous boundary between the chat agent's tool call (running in LangGraph's event loop) and the background shell agent's poll loop (asyncio task).

**Rationale**: 
- Both the chat agent and bg shell agent run in the same asyncio event loop
- `asyncio.Queue` provides native `await queue.get(timeout=N)` matching the "configurable timeout" requirement
- No locking needed — single consumer (bg shell agent poll loop), single producer (chat agent tool)
- `None` sentinel value cleanly signals timeout/cancellation

**Alternatives considered**:
- `asyncio.Event` + shared variable: No built-in timeout support, requires polling
- File FIFO (mkfifo): Disk I/O overhead, cleanup complexity, no request_id matching
- ConversationState field: Couples agents.py to graph state, requires synchronization

### D2: Code Model as Stdin Mediator

**Decision**: The code model (doubao-seed-2-0-code) serves as the final decision point for what text gets written to process stdin, mediating between the chat agent's raw text and process-appropriate input.

**Rationale**:
- Chat agent provides high-level context ("password is abc123")
- Process expects formatted input ("abc123\n" at password prompt)
- Code model understands shell context and prompt patterns
- Same model already used for command parsing and decision-making in the poll loop

**Alternatives considered**:
- Direct pass-through (chat text → stdin): Risk of format mismatch (missing newline, wrong case for y/N)
- Rule-based transform: Brittle, hard to maintain prompt pattern list

### D3: INPUT_NEEDED Decision in Existing Poll Loop

**Decision**: Extend the existing `BACKGROUND_SHELL_DECISION_PROMPT` with an `INPUT_NEEDED:<timeout>:<description>` decision type rather than creating a separate detection mechanism.

**Rationale**:
- Leverages existing poll loop infrastructure (output reading, code model invocation, decision parsing)
- Code model already analyzes process output for DONE/KILL/CONTINUE/NOTIFY decisions
- Adding INPUT_NEEDED to the same decision prompt lets the model use the same context
- Consistent with established pattern — each decision type maps to a handler branch

**Alternatives considered**:
- Separate stdin detection thread: Duplicates poll logic, adds synchronization complexity
- Timeout-only detection: Would miss prompt patterns the LLM can recognize

### D4: Unique request_id Namespace

**Decision**: Each stdin request gets a unique `request_id` in format `stdin_<proc_id>_<seq>` where `proc_id` is the process identifier and `seq` is a monotonically increasing counter.

**Rationale**:
- Prevents stdin cross-talk between different agent invocations
- Seq counter supports multiple sequential stdin requests per process
- Request ID is short and parseable
- Queue is popped on first `put()` preventing double-reply

**Alternatives considered**:
- UUID-based IDs: Overkill, harder to trace in logs
- Single global queue: No way to match response to request
