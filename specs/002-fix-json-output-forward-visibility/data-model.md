# Data Model: 修复 JSON 输出格式与合并转发消息可见性

**Date**: 2026-05-31
**Plan**: [plan.md](./plan.md)

## Overview

No new data entities. This feature modifies only:
1. A string constant (`_OUTPUT_FORMAT_INSTRUCTION` in `ai.py`)
2. Debug log output format (print statements in `pipeline.py` and `forward.py`)

## Changes to Existing Models

### role_sys_prompt (prompts.py)

**Before**: Contains `## 你的输出格式` section with JSON output instruction.

**After**: Section removed. Role prompt only contains character definition, rules, and reference material.

### chat_agent system prompt (ai.py)

**Before**: `sys_prompt = get_role_sys_prompt()` (single source)

**After**: `sys_prompt = get_role_sys_prompt() + _OUTPUT_FORMAT_INSTRUCTION` (concatenated)

### plain_message (pipeline.py)

**Before**: Built from text/at/image segments only.

**After**: Additionally appends `[合并转发消息 id={forward_id}]` for `"forward"` segments.
