# Quickstart: Agent Allocate Tool Implementation

## Prerequisites

- Python 3.12+
- Project dependencies installed
- Existing project tests pass: `python -m pytest tests/ -xvs`

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| **CREATE** | `graph/agents.py` | Agent registry + handler implementations |
| **CREATE** | `tests/test_agent_allocate.py` | Unit tests |
| **MODIFY** | `graph/tools.py` | Add `agent_allocate` tool, callback wiring |
| **MODIFY** | `graph/nodes/ai.py` | NOTIFY_MARK detection, inject_agent_notification, tool registration |
| **MODIFY** | `graph/nodes/__init__.py` | Export new symbols |
| **MODIFY** | `handlers/chat.py` | Callback registration, matcher storage |

## Implementation Order

1. **Task 1**: `graph/agents.py` (registry infrastructure) — test → implement → commit
2. **Task 2**: Agent handlers (`_run_web_browser_agent`, `_run_video_agent`) — test → implement → commit
3. **Task 3**: `agent_allocate` tool in `tools.py` — test → implement → commit
4. **Task 4**: `NOTIFY_MARK` + `inject_agent_notification` in `nodes/ai.py` — test → implement → commit
5. **Task 5**: NOTIFY_MARK detection + @-routing in `ai_node` — test → implement → commit
6. **Task 6**: Tool registration in `ai_node` + `__init__.py` exports — implement → commit
7. **Task 7**: Callback wiring in `chat.py` — implement → commit
8. **Task 8**: Integration verification — full test suite + lint

## Run Tests

```bash
# Run all tests
python -m pytest tests/ -xvs

# Run specific test file
python -m pytest tests/test_agent_allocate.py -xvs

# Run with coverage
python -m pytest tests/test_agent_allocate.py --cov=hatsume.plugins.hatsume_plugin.graph -xvs
```

## Verification

```bash
# Check imports resolve
python -c "from hatsume.plugins.hatsume_plugin.graph.agents import AGENT_REGISTRY, get_agent_list; print(get_agent_list())"

python -c "from hatsume.plugins.hatsume_plugin.graph.tools import agent_allocate; print(agent_allocate.description)"

python -c "from hatsume.plugins.hatsume_plugin.graph.nodes.ai import NOTIFY_MARK, inject_agent_notification; print(NOTIFY_MARK)"

# Lint
python -m ruff check hatsume/plugins/hatsume-plugin/
```
