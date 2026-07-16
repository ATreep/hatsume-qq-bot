# Data Model: Memory System SQLite Refactor

## Entity: Memory

The core entity representing a single remembered observation.

### SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,              -- Memory description (≤50 chars recommended)
    time        INTEGER NOT NULL,           -- Unix timestamp of the event
    people      TEXT NOT NULL DEFAULT '[]',  -- JSON: [{"user_id": int, "user_name": str}]
    tokens      TEXT NOT NULL DEFAULT '[]',  -- JSON: [["word", "POS"], ...]
    embedding   BLOB,                       -- float32 numpy array, 1024 dims (nullable)
    created_at  INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_time ON memories(time);
```

### Field Details

| Field | Python Type | SQL Type | Constraints | Notes |
|-------|------------|----------|-------------|-------|
| `id` | `int` | INTEGER PK | Auto-increment | Row identifier |
| `content` | `str` | TEXT | NOT NULL | Free-text memory description |
| `time` | `int` | INTEGER | NOT NULL | Unix timestamp (second precision) |
| `people` | `list[dict]` | TEXT (JSON) | Default `[]` | `[{"user_id": int, "user_name": str}]` |
| `tokens` | `list[tuple[str, str]]` | TEXT (JSON) | Default `[]` | jieba POS-tagged tokens |
| `embedding` | `np.ndarray \| None` | BLOB (nullable) | — | float32, shape `(1024,)` |
| `created_at` | `int` | INTEGER | Auto-set | When row was inserted |

### In-Memory Cache

For fast retrieval, a denormalized copy is maintained in memory:

| Variable | Python Type | Notes |
|----------|------------|-------|
| `all_mem_list` | `list[dict]` | `[{"content": str, "time": int, "people": list[dict]}]` |
| `tokenized_corpus` | `list[list[str]]` | Word-only tokens for BM25 |
| `tokenized_corpus_pos` | `list[list[tuple[str, str]]]` | POS-tagged tokens |
| `embedding_vectors` | `np.ndarray \| None` | Shape `(N, 1024)`, float32 |

### State Transitions

```
┌──────────┐  add_mem()   ┌──────────┐  daily job   ┌───────────┐
│  (new)   │ ────────────→ │  active  │ ────────────→ │  expired  │
└──────────┘               └──────────┘               └───────────┘
                                │                          │
                                │ find_memory /            │ DELETE FROM
                                │ auto-retrieval           │ memories
                                ▼                          ▼
                           returned in                  permanently
                           query results                  removed
```

### Validation Rules

- `content`: Must be non-empty string (validated in `normalize_memory_object`)
- `time`: Must be valid integer (Unix timestamp)
- `people`: Each entry must have `user_id` (int) and `user_name` (str); duplicate `user_id` entries are deduplicated in `normalize_people`
- `tokens`: Each token is a `[word, pos_tag]` pair; filtered by POS relevance in `tokenize_with_pos`
- `embedding`: May be NULL (if embedding API was unavailable during recording); memories without embeddings are still keyword-searchable

### Relationships

- **Memory → Person Reference**: One memory can reference zero or more people (stored as JSON array in `people` column)
- **Memory → Memory Store**: All memories belong to one flat collection; no categories or hierarchies
- **No foreign keys**: People are referenced by user_id only; users are external entities managed by the QQ platform
