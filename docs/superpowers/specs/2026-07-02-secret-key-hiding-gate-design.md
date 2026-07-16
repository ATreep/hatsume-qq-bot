# Secret Key Hiding Gate — Design Spec

**Date:** 2026-07-02
**Status:** Approved

## Overview

Add a secret key detection/masking gate that intercepts all outbound messages and replaces API keys (sk-*, ghp-*, ark-*, etc.) with masked variants before they reach QQ chat or logs.

## Motivation

- Prevent accidental API key leakage in LLM-generated responses
- Cover all 4 message send paths (chat, agent notification, timer notification, direct conversation)
- Non-blocking: must never prevent message delivery, even on error

## Design

### Architecture

```
utils.py                              chat.py
+---------------------------+         +----------------------------------+
| mask_secret_keys(text)    |<--------| handle_ai_message()              |
|                           |<--------| _send_to_group (agent notify)    |
| _SECRET_KEY_PATTERNS      |<--------| _send_to_group (timer notify)    |
| _mask_match() [implicit]  |<--------| _send_to_group (direct conv)     |
+---------------------------+         +----------------------------------+
```

A single utility function `mask_secret_keys()` in `utils.py`, called from all 4 outbound send sites.

### Components

#### 1. `utils.py` — `mask_secret_keys(text: str) -> str`

Pure function: takes a string, returns the masked string. Uses compiled regex patterns to detect well-known API key prefixes and replaces the key body with `xxx...xxx` while preserving the prefix.

**Detection patterns** (extensible list):

| Pattern | Matches | Masked Example |
|---------|---------|----------------|
| `sk-(?:ant(?:-api\d{2})?-)?` | OpenAI / Anthropic keys | `sk-ant-api03-xxx...xxx` |
| `gh[opu]_|github_pat_` | GitHub classic & fine-grained tokens | `ghp_xxx...xxx` |
| `ark-` | Volcengine Ark keys | `ark-xxx...xxx` |
| `ak-` | Generic access keys | `ak-xxx...xxx` |

**Masking rule**: `re.sub(pattern, r'\1xxx...xxx', text)` — capture group 1 is the prefix, body replaced with literal `xxx...xxx`.

**Error handling**: try/except with silent fallback — returns original text on any exception. Uses `print()` for debug logging (not a logging framework, consistent with project conventions).

#### 2. Integration Points (4 sites in `chat.py`)

| # | File | Location | Change |
|---|------|----------|--------|
| 1 | `chat.py` | `handle_ai_message()` L212 | Wrap `msg` string with `mask_secret_keys()` before send |
| 2 | `chat.py` | `_start_conv_for_agent` `_send_to_group` L51 | Add `text = mask_secret_keys(str(msg))` |
| 3 | `chat.py` | `_start_conv_for_timer` `_send_to_group` L91 | Add `text = mask_secret_keys(str(msg))` |
| 4 | `ai.py` | `_start_direct_conv` `_send_to_group` L214 | Add `text = mask_secret_keys(str(msg))` |

### Data Flow

```
LLM response text
    |
    v
ai_node() extracts ai_text from response
    |
    +---> [Path 1] ai_cb(ai_msg) --> handle_ai_message()
    |         mask_secret_keys() applied BEFORE matcher.send()
    |
    +---> [Path 2/3/4] _send_to_group(msg)
              mask_secret_keys() applied BEFORE bot.send_group_msg()
```

### Error Handling

- Regex compilation/execution failure → return original text unchanged
- Never raises; never blocks message delivery
- `print()` debug line on each masked match for audit trail

### Testing Strategy

**Unit tests** (`tests/test_secret_gate.py`):
- Each pattern matches its intended key format
- Prefix is preserved in output
- No false positives on normal text (no match)
- No match on keys shorter than minimum length
- Special characters in key body handled
- Empty string / None-like inputs handled
- Exception safety: malformed patterns don't crash

### Non-Goals

- No image/OCR-based key detection
- No configurable pattern list (hardcoded, extensible via code edits)
- No structured logging framework integration
- No rate limiting or alerting on repeated leaks

## Implementation Plan

See `writing-plans` output for detailed task breakdown. High-level steps:

1. Add `mask_secret_keys()` to `utils.py` with patterns and tests
2. Integrate into `handle_ai_message()` in `chat.py`
3. Integrate into all 3 `_send_to_group` closures
4. Write unit tests
5. Manual smoke test (send a fake key through the bot)
