# Research: Face Emoji Injection + Auto-Create 24h

**Date**: 2026-07-02

## Decisions

### 1. Face tag format: `<hatsumeface>emotion</hatsumeface>`

- **Decision**: Use XML-like tag format embedded in LLM text output
- **Rationale**: Simple to regex-parse, unlikely to appear in natural conversation, follows existing pattern of Mark-based signaling (NOTIFY_MARK, TIMER_MARK)
- **Alternatives considered**: JSON block (` ```json {"face": "开心"} ``` `) — more complex to parse, more tokens. Special prefix (`__face__:开心`) — could collide with other mark prefixes.

### 2. Regex pattern: non-greedy match `<hatsumeface>(.*?)</hatsumeface>`

- **Decision**: Single non-greedy regex, first match only
- **Rationale**: Handles malformed input gracefully (no match → no face), handles multiple tags by taking first only
- **Alternatives considered**: Greedy match — would capture across multiple tags incorrectly. Full XML parser — overkill for fixed-format tag.

### 3. Gate timing: inject prompt BEFORE create_agent

- **Decision**: Check gate conditions, then inject face prompt into sys_prompt before creating the agent
- **Rationale**: The LLM needs the face prompt at inference time to know it can use the tag. Checking after would mean the LLM doesn't know about faces.
- **Alternatives considered**: Inject as separate system message after main reply — would require second LLM call, defeating the purpose.

### 4. AIMessage preservation: keep tag in graph state

- **Decision**: Store original `ai_text` (with tag) in `AIMessage`, send stripped `ai_text_clean` to user
- **Rationale**: The LLM benefits from seeing its past face choices in conversation history. Users should never see the raw tag.
- **Alternatives considered**: Strip from both — loses conversation context. Add as separate metadata — more complex, LangChain messages don't easily support custom metadata.

### 5. Auto-create 24h: remove hour clamping entirely

- **Decision**: Simplify `_random_next_trigger()` to `now + random(4h, 6h)` with no window logic
- **Rationale**: The 07:00–22:00 window was an arbitrary restriction. Removing it is the simplest change — just delete the clamping code.
- **Alternatives considered**: Extend window to e.g. 00:00–23:59 — almost the same as removing it, more code. Make window configurable — unnecessary complexity for a feature that should just work 24/7.
