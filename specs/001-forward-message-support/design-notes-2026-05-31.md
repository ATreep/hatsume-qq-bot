# Design Notes: JSON Output Format & Forward Message Visibility Fixes

**Date**: 2026-05-31
**Spec**: [spec.md](./spec.md)

## Issue 1: LLM JSON Output Format

**Problem**: LLM outputs plain text instead of `{"message": "..."}` JSON despite prompt instructions in `role_sys_prompt`.

**Root Cause**: The `create_agent()` LangChain wrapper injects tool-calling system instructions that can conflict with custom output format instructions. Model compliance varies.

**Decision**: Move output format instruction from `prompts.py` (role system prompt) to `ai.py` (agent creation site). Append format instruction at end of system prompt for recency effect. Keep existing JSON parse + fallback in `ai.py` as safety net.

**Changes**:
1. `prompts.py`: Remove "## 你的输出格式" section (lines 114-120)
2. `ai.py`: Append `_OUTPUT_FORMAT_INSTRUCTION` to system prompt before `create_agent()` call

## Issue 2: Forward Message Visibility

**Problem**: Bot detects forward messages but forward content doesn't reach LLM context.

**Root Cause**: Likely silent failure in the detection→API→JSON pipeline at runtime. The `get_human_message()` segment loop doesn't handle `"forward"` type, so if `has_forward_segment()` misses the segment, forward content silently drops.

**Decision**: Add explicit `case "forward"` in segment loop + debug logging across the full forward-handling pipeline (detection → API → JSON build).

**Changes**:
1. `pipeline.py`: Add `case "forward"` in segment loop; add debug logs
2. `forward.py`: Add success-path debug logs around API call
