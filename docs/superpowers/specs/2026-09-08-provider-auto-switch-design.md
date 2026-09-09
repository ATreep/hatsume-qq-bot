# Provider Auto-Switching Design

## Goal

Automatically switch the LLM provider used by `chat_agent` when the provider
becomes slow. The trigger is the monotonic duration of a `chat_agent` invocation:
if it exceeds 100 seconds, the bot switches the advance model's provider to the
next healthy candidate. The candidate auto-switching list is `ruoli` and `waw`.

## Product Requirements

- Only the advance model used by `chat_agent` (`get_advance_model`) switches
  providers. All other models (intent, mini, lite, vision, embedding, …) keep
  their fixed providers.
- The switching trigger is a completed `chat_agent` invocation whose elapsed
  time (the existing `t_invocation_start` → `t_invocation_end` window in
  `ai_node`) exceeds 100 seconds. Errors and exceptions never trigger a
  switch; only latency does.
- A provider marked slow stays "slow" for a 12-hour cooldown. A switch only
  moves to a candidate that is not currently in its cooldown window.
- If every candidate is in cooldown, the bot stays on the current provider
  and logs a warning — no flip-flopping between two slow providers.
- A fast invocation (≤ 100s) clears the current provider's slow mark
  (recovery signal).
- Provider state is in-memory only. A bot restart resets the selection to the
  static `config.PROVIDER` default (currently `waw`).

## Architecture

### New module: `hatsume/plugins/hatsume-plugin/provider_switch.py`

A dependency-light module owning all switching logic:

- `CANDIDATE_PROVIDERS = ("ruoli", "waw")` — the candidate auto-switching list.
- `SLOW_THRESHOLD_SECONDS = 100.0` — the latency trigger.
- `SLOW_COOLDOWN_SECONDS = 12 * 60 * 60` — how long a slow mark lasts.
- `ProviderSwitcher` class:
  - Holds `current` provider and a `slow_until: dict[str, float]` map.
  - Serializes state transitions with a lock because multiple graph loops may
    report completed invocations concurrently.
  - `record_elapsed(elapsed_seconds, provider=None, now=None, started_at=None) -> str | None`:
    - `elapsed > SLOW_THRESHOLD_SECONDS`: mark `provider` slow for the
      cooldown window, then switch to the next candidate not in cooldown.
      If all candidates are slow, stay and return `None`.
    - `elapsed <= threshold`: clear the provider's slow mark only when this
      invocation started after the newest slow invocation for that provider.
      This prevents an older fast completion from clearing a newer slow mark.
    - Returns the new provider name when a switch happened, else `None`.
  - `now` and the monotonic `started_at` token are injectable for deterministic
    tests. The invocation duration itself uses `time.monotonic()`.
- Module-level singleton plus two helpers:
  - `get_chat_provider() -> str` — the provider the advance model should use.
  - `report_chat_elapsed(elapsed_seconds) -> str | None` — convenience that
    records on the current provider and returns the switched-to provider.

### `models.py` changes

- `get_google_api_model(model_name, reasoning_effort="low", provider=None)`
  and `get_standard_api_model(..., provider=None)` gain an optional provider
  parameter. When omitted they fall back to the static `config.PROVIDER`, so
  every existing caller keeps its current behavior.
- `get_advance_model(..., provider=None)` accepts an optional provider. When
  omitted it reads `get_chat_provider()`; `ai_node` captures one provider
  snapshot and passes it into model construction so the model used and the
  provider reported on completion cannot diverge.

### `graph/nodes.py` changes (`ai_node`)

- After the existing elapsed-time print of the `chat_agent` invocation, call
  `report_chat_elapsed(t_invocation_end - t_invocation_start, provider=..., started_at=...)`.
- When a switch is returned, print
  `[provider-switch] chat_agent took Xs (> 100s); provider 'waw' -> 'ruoli'`
  so operators can observe the behavior in logs.

## Error Handling

- `report_chat_elapsed` is pure bookkeeping and cannot raise in practice.
- Latency is only measured on the success path; the `llm_error_type` branches
  (rate limit / auth / other) never report elapsed time and never switch.
- If both providers are slow the system degrades gracefully: it keeps using
  the current provider and logs a single warning per trigger.

## Testing

`tests/test_provider_switch.py`, offline and deterministic per the test
suite guide, following the established importlib-loading pattern:

- Slow invocation on `waw` switches to `ruoli`.
- A second slow invocation on `ruoli` within 12h does not switch back (both
  candidates in cooldown → stay).
- After the cooldown expires (injected `now`), a slow invocation switches
  again.
- A fast invocation clears the current provider's slow mark.
- The initial current provider equals the static `config.PROVIDER` default.
