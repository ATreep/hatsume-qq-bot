# Quickstart: Memory System SQLite Refactor

## For Developers

### Running Tests

```bash
# All memory-related tests
python -m pytest tests/test_memory_db.py tests/test_memory_utils.py -xvs

# Graph node tests (finish, ai nodes)
python -m pytest tests/test_graph_nodes.py -xvs

# Tool tests (query_memory)
python -m pytest tests/test_tools.py -xvs -k "memory"
```

### Key Files

| File | Purpose |
|------|---------|
| `memory/db.py` | SQLite schema, CRUD, JSON migration |
| `memory/store.py` | In-memory indices, `add_mem()`, daily maintenance |
| `memory/retrieval.py` | Two-phase `query_mems()` (BM25 + embedding) |
| `graph/nodes/ai.py` | Parses `[memoryrecord:...]` from chat_agent output |
| `graph/nodes/finish.py` | Cleanup only (no more mem_record_agent) |
| `graph/tools.py` | `query_memory()`, `find_memory` tool |

### Configuration

```python
# In config.py
MAX_MEMORY_LIMIT: int = 50           # Max memories per retrieval
MEMORY_SIX_HOUR_WINDOW: int = 21600   # User-specific window (seconds)
MEMORY_EXPIRY_DAYS: int = 150         # Auto-delete threshold
SCORE_THRESHOLD: float = 0.1          # BM25 score floor
EMBEDDING_WEIGHT: float = 0.5         # Embedding vs BM25 weight
```

### Memory Record Format

Chat agent outputs at end of reply:
```
[memoryrecord: {"content": "\"小明\" 喜欢芒果。", "people": [{"user_id": 123, "user_name": "小明"}]}]
```

### Migration

On first startup after deploy:
1. Bot detects `memory.json` exists and `memory.db` is empty
2. Reads all entries from JSON, re-tokenizes and re-embeds
3. Inserts into SQLite
4. Renames `memory.json` → `memory.json.bak`

### Troubleshooting

- **DB corrupted**: Delete `memory.db`, restart — bot starts with empty store (memories lost but service continues)
- **Migration failed**: Check logs for `Migrating memory.json → SQLite...` message; JSON file remains as `.bak`
- **Embeds missing**: Memories stored without embedding are still retrievable via BM25 keyword search
