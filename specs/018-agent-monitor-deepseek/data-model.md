# Data Model: Agent Monitor & Deepseek Provider

## AgentState

In-memory dictionary keyed by agent name string.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `Literal["idle", "running", "done"]` | Current execution state |
| `task` | `str` | Task description provided at allocation |
| `user_id` | `int` | QQ ID of the user who requested the task |
| `started_at` | `float` | Unix timestamp when task began execution |
| `result` | `str \| None` | Final output (populated when done) |

### State Transitions

```
idle ──agent_allocate──▶ running ──handler completes──▶ done
  ▲                         │                             │
  └─────────────────────────┘                             │
     next agent_allocate                                  │
     (overwrites state)                                   │
```

### Validation Rules

- `status` MUST be one of: `"idle"`, `"running"`, `"done"`
- `agent_allocate` MUST reject when `status == "running"`
- `agent_allocate` MUST accept when `status in ("idle", "done", None)`
- `result` MUST be populated when transitioning to `"done"`

## DeepseekConfig

Configuration constants in `config.py`.

| Field | Value | Source |
|-------|-------|--------|
| `DEEPSEEK_BASE_URL` | `"https://api.deepseek.com/v1"` | Hardcoded constant |
| `DEEPSEEK_V4_PRO` | `"deepseek-chat"` | Hardcoded constant |
| `DEEPSEEK_API_KEY` | `os.environ.get("DEEPSEEK_API_KEY", "")` | `.env.prod` |
