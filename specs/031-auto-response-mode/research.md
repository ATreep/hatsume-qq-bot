# Research: Auto Response Mode

**Feature**: Auto Response Mode
**Date**: 2026-07-13

## Decision: Reuse auto_create architecture

- **Decision**: Mirror the existing auto_create timer architecture without modification
- **Rationale**: The auto_create pattern (self-renewing fire-and-forget timer using APScheduler + inject_timer) has proven reliable in production. The auto_response feature is structurally identical — only parameters differ (interval, prompt, time window, config constant).
- **Alternatives considered**:
  1. **New standalone scheduling mechanism** — rejected; introduces unnecessary divergence and maintenance burden
  2. **Extending auto_create to handle both modes** — rejected; would couple unrelated concerns and complicate the auto_create lifecycle
  3. **APScheduler interval trigger** — rejected; auto_create uses date triggers for random intervals; consistency is more valuable than a slightly different scheduling approach

## Decision: No schema migration needed

- **Decision**: Use existing `task_type` column with new value `'auto_response'`
- **Rationale**: The column was added during the auto_create implementation and supports arbitrary string values. No ALTER TABLE needed.
- **Alternatives considered**: None — this is the simplest path.

## Decision: Fixed prompt core with minor random variations

- **Decision**: 5 Chinese wording variations that all encode the same instruction
- **Rationale**: Prevents the bot's responses from feeling mechanically identical while keeping behavior predictable. The prompt variations differ only in phrasing, not in substance.
- **Alternatives considered**:
  1. **Single fixed prompt** — simpler but makes periodic responses feel robotic
  2. **Dynamic prompt generation via LLM** — overengineered; the prompt is meta-instruction, not end-user content
