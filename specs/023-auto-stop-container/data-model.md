# Data Model: Auto-Stop Docker Container

**Feature**: 023-auto-stop-container | **Date**: 2026-07-01

## Entities

### Subprocess Reference Counter

| Attribute | Type | Description |
|-----------|------|-------------|
| `_subprocess_refcount` | `int` | Number of currently-active Docker subprocesses. Range: [0, ∞). Initial: 0. |
| `_subprocess_refcount_lock` | `threading.Lock` | Mutex protecting all refcount mutations and timer lifecycle transitions. |

**Lifecycle**:
```
0 ──acquire──▶ 1 ──acquire──▶ 2 ──acquire──▶ 3 ...
                   ◀──release──   ◀──release──   ◀──release──
                                       
0 ──release──▶ 0 (clamped, no-op)
```

**State transitions**:
- `_acquire_subprocess()`: `n → n+1`, cancels pending timer if exists
- `_release_subprocess()`: `n → max(0, n-1)`, starts timer if result is 0

### Grace Timer

| Attribute | Type | Description |
|-----------|------|-------------|
| `_stop_timer_task` | `asyncio.Task \| None` | The pending auto-stop task. At most one exists. |
| `_STOP_GRACE_SECONDS` | `float` | Grace period duration. Constant: 300.0 (5 minutes). |

**Lifecycle**:
```
None ──release(refcount→0)──▶ Task("sleep 300 → check → stop")
                                   │
          ◀──acquire (cancel)──────┘
          ◀──cleanup (cancel)──────┘
          ◀──expiry (sets None)────┘
```

**State transitions**:
- Created: `_release_subprocess()` when refcount reaches 0
- Cancelled: `_acquire_subprocess()` when refcount rises from 0, or `cleanup_persistent_container()`
- Completed: After `asyncio.sleep(300)`, if refcount still 0: `stop_container()` → `_container_active = False` → `_stop_timer_task = None`

### Container Active Flag (Existing)

| Attribute | Type | Description |
|-----------|------|-------------|
| `_container_active` | `bool` | Whether the Docker container is believed to be running. |

**Modified state transitions**:
- Set `True`: `ensure_container_running()` (unchanged)
- Set `False`: `cleanup_persistent_container()` (unchanged) **+** `_delayed_stop_container()` (new)

## Relationships

```
_container_active ◀── reads/writes ──▶ ensure_container_running()
                                     ▶ cleanup_persistent_container()
                                     ▶ _delayed_stop_container() [NEW]

_subprocess_refcount ◀── mutates ──▶ _acquire_subprocess() [NEW]
                                    ▶ _release_subprocess() [NEW]

_stop_timer_task ◀── mutates ──▶ _acquire_subprocess() [NEW]
                                ▶ _release_subprocess() [NEW]
                                ▶ cleanup_persistent_container()
                                ▶ _delayed_stop_container() [NEW]

run_cmd() ──calls──▶ _acquire_subprocess() + [body] + _release_subprocess() [finally]
start_background_cmd() ──calls──▶ _acquire_subprocess()
kill_background_cmd() ──calls──▶ _release_subprocess()
```

## Validation Rules

1. `_subprocess_refcount` must never go below 0 (clamped in `_release_subprocess`)
2. `_stop_timer_task` must be cancelled before being replaced (handled in `_acquire_subprocess` and `cleanup_persistent_container`)
3. `_delayed_stop_container` must re-check `_subprocess_refcount == 0` under lock before calling `stop_container()`
4. All mutations to `_subprocess_refcount` and `_stop_timer_task` must be under `_subprocess_refcount_lock`
