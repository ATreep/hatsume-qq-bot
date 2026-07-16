# Quickstart: Auto-Stop Docker Container

**Feature**: 023-auto-stop-container

## How It Works

1. Every `run_cmd()` or `start_background_cmd()` call increments a refcount.
2. Every `run_cmd()` return or `kill_background_cmd()` call decrements it.
3. When refcount hits 0, a 5-minute timer starts.
4. If no new subprocess starts during those 5 minutes, the container is stopped.
5. If a new subprocess starts, the timer is cancelled and refcount goes back up.

## Testing

```bash
# Run all container lifecycle tests
python -m pytest tests/test_container_lifecycle.py -v

# Run existing tests to verify no regressions
python -m pytest tests/test_background_shell_infra.py tests/test_background_shell_agent.py -v
```

## Configuration

The grace period is defined as a module-level constant in `infra.py`:

```python
_STOP_GRACE_SECONDS: float = 300.0  # 5 minutes
```

Change this value to adjust the idle timeout. No other configuration needed.

## Manual Override

The existing `/resetsandbox` command still works — it cancels any pending timer and immediately removes the container.
