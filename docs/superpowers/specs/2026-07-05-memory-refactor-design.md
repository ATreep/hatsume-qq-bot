# Memory System Refactor — Design Document

**Date:** 2026-07-05
**Branch:** main
**Status:** Design Approved

## Overview

Refactor the hatsume memory writing and retrieving mechanism to:
1. Eliminate the separate LLM call for memory recording (finance_conversation_node's mem_record_agent)
2. Have `chat_agent` output `[memoryrecord: {...}]` inline JSON tags for significant events
3. Auto-retrieve memories by current chatting users with a 6-hour window, up to MAX_MEMORY_LIMIT=50
4. Fall back to sentence-relevant supplemental memories if user-specific count < MAX_MEMORY_LIMIT
5. Migrate from JSON file to SQLite with tokenized corpus + embedding vectors persisted

---

## 1. SQLite Storage (`memory/db.py` — NEW)

### Schema

```sql
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT NOT NULL,
    time        INTEGER NOT NULL,
    people      TEXT NOT NULL DEFAULT '[]',
    tokens      TEXT NOT NULL DEFAULT '[]',
    embedding   BLOB,
    created_at  INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_time ON memories(time);
```

### Column Details

| Column | Type | Content |
|--------|------|---------|
| `content` | TEXT | Memory description string (e.g., `"小明" 喜欢吃芒果。`) |
| `time` | INTEGER | Unix timestamp of when the event occurred |
| `people` | TEXT | JSON array: `[{"user_id": 123, "user_name": "小明"}]` |
| `tokens` | TEXT | JSON array of `[word, pos_tag]` pairs from jieba tokenization |
| `embedding` | BLOB | float32 numpy array serialized via `.tobytes()` |
| `created_at` | INTEGER | Unix timestamp of when the row was inserted |

### Key Operations

```python
def init_db() -> None
    # CREATE TABLE IF NOT EXISTS, enable WAL mode

def insert_memory(content, time, people, tokens, embedding) -> int
    # INSERT and return row id

def delete_expired_memories(retention_seconds: int) -> int
    # DELETE FROM memories WHERE time < ?

def load_all_memories() -> tuple[list[dict], list[list[str]], 
                                   list[list[tuple[str, str]]], np.ndarray | None]
    # SELECT all rows, reconstruct in-memory structures
    # tokens: deserialize JSON → list[tuple[str, str]]
    # embedding: deserialize BLOB → np.ndarray via np.frombuffer() + reshape

def query_by_user_ids(user_ids: list[int], since_time: float | None,
                      exclude_ids: list[int]) -> list[dict]
    # SELECT where people JSON contains any user_id
    # Filter by time if since_time provided (6h window)
    # Exclude already-retrieved memory IDs

def query_all_except(exclude_ids: list[int], limit: int) -> list[dict]
    # SELECT rows not in exclude_ids, ordered by time DESC
```

### One-Time Migration

```python
def migrate_from_json() -> int
    # If memory.json exists and SQLite is empty:
    #   1. Load from JSON
    #   2. Re-tokenize each entry (no tokens stored in JSON)
    #   3. Re-embed each entry (no embeddings stored in JSON)
    #   4. INSERT all into SQLite
    #   5. Rename memory.json → memory.json.bak
    # Returns count of migrated memories
```

### Connection Lifecycle

- Single shared `sqlite3.Connection` in WAL mode
- Opened on plugin init, closed on plugin shutdown
- Path: `data/hatsume-plugin/memory.db` (alongside existing `memory.json`)

---

## 2. Recording Mechanism

### Inline Recording in `ai_node` (`graph/nodes/ai.py`)

After chat_agent generates `ai_text`, parse `[memoryrecord: {...}]` tags:

```python
MEMORY_RECORD_PATTERN = re.compile(r"\[memoryrecord:\s*(\{.*?\})\]")

# Parse memory records from AI response
mem_records: list[dict] = []
for match in MEMORY_RECORD_PATTERN.finditer(ai_text):
    try:
        record = json.loads(match.group(1))
        if "content" in record and record["content"].strip():
            mem_records.append(record)
    except json.JSONDecodeError:
        pass

# Strip memoryrecord tags from output text
ai_text_clean = MEMORY_RECORD_PATTERN.sub("", ai_text_clean).strip()

# After sending reply, save each record
for record in mem_records:
    add_mem(
        value=record["content"].strip(),
        people=record.get("people", [])
    )
```

### Record Format

```json
{"content": "简要描述（50字内），用户名用引号包围", "people": [{"user_id": QQ号, "user_name": "昵称"}]}
```

### System Prompt Addition

Added to the chat_agent system prompt (in `prompts.py`):

```
# 记忆记录
当对话中出现值得长期记住的重要事件时（用户兴趣爱好、性格特点、重要经历、
观点偏好、人际关系、关键事件、用户明确要求记住的内容），在回复的最后添加：

[memoryrecord: {"content": "简要描述（50字内），用户名用引号包围", "people": [{"user_id": QQ号, "user_name": "昵称"}]}]

可以记录多条，每条一个 [memoryrecord: ...]。
不记录问候告别、无实质闲聊、日常寒暄。
历史聊天记录中的事件也可以记录。
```

### Removed Components

| Component | Location | Reason |
|-----------|----------|--------|
| `mem_record_agent` creation | `finish.py` | No separate LLM needed |
| `MEMORY_RECORDING_PROMPT` | `prompts.py` | No separate recording prompt needed |
| `write_memory` tool | `tools.py` | Not called; chat_agent outputs inline tags |
| `active_memory_sources` / `set_active_memory_sources` / `clear_active_memory_sources` / `resolve_active_memory_people` | `store.py` | chat_agent provides `people` directly in JSON |
| `_memory_record_transcript` / `_memory_record_source_map` / `append_memory_record_sources` / `reset_memory_record_context` | `ai.py` | No finish-time recording pass needed |
| `save_mem_list()` | `store.py` | No JSON file to persist |

### Modified `finish_conversation_node`

Simplifies to:
- Clear queues and keys
- Send `[CONVERSATION END]`
- Reset skill dedup
- **No memory recording logic**

---

## 3. Retrieval Mechanism

### New Constant in `config.py`

```python
MAX_MEMORY_LIMIT: int = 50  # Maximum memories to retrieve per turn
```

Existing constants retained: `MEMORY_TOP_K` removed (replaced by MAX_MEMORY_LIMIT), others kept for scoring.

### Updated `query_mems()` in `retrieval.py`

```python
def query_mems(
    user_ids: list[int],
    query_text: str,
    max_limit: int = MAX_MEMORY_LIMIT,
    six_hour_window: int = 6 * 3600,
) -> list[tuple[str, int]]:
```

**Two-Phase Algorithm:**

**Phase 1 — User-Specific (6-hour window):**
1. `since_time = now() - 6 * 3600`
2. Query SQLite: rows where `time > since_time` AND `people` JSON contains any `user_id` from `user_ids`
3. Score all matching rows via hybrid BM25 + embedding against `query_text`
4. Sort by relevance descending
5. Take up to `max_limit`

**Phase 2 — Supplemental (no time filter):**
1. If `len(phase1_results) < max_limit`:
   - Query all memories not already in results (no time filter)
   - Score via hybrid BM25 + embedding
   - Sort by relevance descending
   - Fill up to `max_limit` total

### User ID Extraction from `last_human_content`

```python
def extract_user_ids(content: Any) -> list[int]:
    """Walk message content structure to find user IDs from type:message entries."""
    # Parse the JSON message format (type: 'message' → user.id)
    # Return unique list of user IDs
```

### What `query_memory()` in `tools.py` does

- Now passes `user_ids` from current chatting context
- Calls updated `query_mems()` with the two-phase algorithm
- Still formats results as timestamped lines

### `find_memory` Tool

- **Unchanged interface** — still available to chat_agent for keyword-based memory search
- Calls `query_memory()` which now uses the new two-phase logic
- The tool's `query` parameter overrides the auto-retrieved context for relevance scoring

---

## 4. Lifecycle & Migration

### Startup (plugin init)

```
init_db()                            # Ensure table + WAL mode
if memory.json exists and db empty:
    migrate_from_json()              # One-time JSON → SQLite conversion
mem_data = load_all_memories()       # Load into in-memory structures
rebuild_bm25(index_b=0.3)            # Initial BM25 from tokenized corpus
```

### Add Memory (runtime)

```
tokens = tokenize_with_pos(content)
embedding = embedding_model.embed(content)
row_id = insert_memory(content, now(), people, tokens, embedding)
append to all_mem_list, tokenized_corpus, tokenized_corpus_pos
append to embedding_vectors (or rebuild if mismatch)
set bm25_dirty = True
```

### Daily Maintenance (4:30 AM scheduler job)

```
deleted = delete_expired_memories(MEMORY_EXPIRY_DAYS * 86400)
if deleted > 0:
    reload all in-memory structures from SQLite   # SQL rows are authoritative
    rebuild_bm25()
```

---

## 5. Files Changed Summary

| File | Action | Detail |
|------|--------|--------|
| `memory/db.py` | **NEW** | SQLite CRUD, schema, migration |
| `memory/store.py` | MODIFY | Remove JSON I/O, remove active_memory_sources; delegate to db.py; keep in-memory lists |
| `memory/retrieval.py` | MODIFY | New `query_mems()` signature, two-phase algorithm, `extract_user_ids()` |
| `config.py` | MODIFY | Add `MAX_MEMORY_LIMIT=50`, remove `MEMORY_TOP_K` |
| `prompts.py` | MODIFY | Add `# 记忆记录` section to role_sys_prompt; remove `MEMORY_RECORDING_PROMPT` |
| `graph/nodes/ai.py` | MODIFY | Parse `[memoryrecord:...]`, call `add_mem()` inline; remove recording transcript vars |
| `graph/nodes/finish.py` | MODIFY | Remove `mem_record_agent` and memory recording logic |
| `graph/tools.py` | MODIFY | Remove `write_memory`; update `query_memory()` to pass user_ids |
| `memory/__init__.py` | MODIFY | Re-export from db.py if needed |
| `data/.../memory.json` | OBSOLETE | Migrated to `memory.db`, kept as `.bak` |

---

## 6. Error Handling

| Scenario | Handling |
|----------|----------|
| `[memoryrecord: ...]` JSON parse error | Skip malformed record, continue sending reply |
| DB connection lost | Reconnect on next operation (lazy) |
| Migration from JSON fails | Log error, continue with empty DB |
| Embedding API fails during add | Skip embedding update, set `bm25_dirty=True` |
| Invalid `people` in record | `normalize_people()` sanitizes, empty list is valid |
| DB file corrupted | Delete + re-init (memories lost but bot continues) |

---

## 7. Testing Strategy

| Test Area | Approach |
|-----------|----------|
| `db.py` CRUD | Unit tests with in-memory `:memory:` SQLite |
| Regex parsing | Test `[memoryrecord: {...}]` extraction with valid/invalid/multiple records |
| Two-phase retrieval | Mock DB rows, verify user-specific vs supplemental ordering |
| Migration | Test JSON → SQLite conversion with sample `memory.json` |
| `finish.py` simplification | Verify no memory logic remains |
| `ai_node` integration | Verify records parsed and saved in response flow |
