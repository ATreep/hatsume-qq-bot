# Quickstart: Agent Allocate Deduplication Guard

## Verification

1. Run the test suite:
   ```bash
   cd /path/to/hatsume
   python -m pytest tests/test_agent_allocate.py -xvs
   ```

2. Confirm the three new dedup guard tests pass:
   - `test_refuses_when_agent_running_and_not_checked`
   - `test_allows_when_agent_running_and_check_agent_was_called`
   - `test_allows_when_agent_not_running`

3. Confirm no regression in existing tests:
   ```bash
   python -m pytest tests/ -xvs
   ```
