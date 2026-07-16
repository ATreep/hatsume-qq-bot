# Research: Memory System SQLite Refactor

## Decision 1: SQLite as Storage Backend

**Decision**: Use Python stdlib `sqlite3` with WAL mode.

**Rationale**: SQLite is zero-dependency (stdlib), supports concurrent reads with WAL mode, and handles the single-process bot workload. JSON→SQLite migration is trivial via Python. BLOB storage for numpy embedding vectors is native via `.tobytes()`/`frombuffer()`.

**Alternatives considered**:
- **PostgreSQL**: Overkill for single-process bot; adds deployment complexity.
- **Continue with JSON**: Requires full rebuild on startup; doesn't support per-column queries for user/time filtering.
- **DuckDB**: Powerful but adds dependency; not in stdlib.

## Decision 2: Inline Memory Recording via Regex Parsing

**Decision**: Parse `[memoryrecord: {"content": "...", "people": [...]}]` from chat_agent output using `re.finditer()` with a non-greedy JSON pattern, then strip tags from visible output.

**Rationale**: Avoids a separate LLM call (cost savings), uses existing output parsing infrastructure (already strips `[hatsumeface:...]` tags the same way), and JSON provides structured data for people attribution without needing the `active_memory_sources` indirection.

**Alternatives considered**:
- **Separate tool call**: LLM would call `write_memory` tool during conversation — but this consumes tool-calling budget and adds latency.
- **XML tags**: `<memoryrecord>...</memoryrecord>` — harder to parse structured data (people arrays).
- **Post-processing LLM**: Current approach (mem_record_agent) — expensive and slow.

## Decision 3: Two-Phase Retrieval with SQL Filtering

**Decision**: Phase 1 queries SQLite for user-matching memories within 6-hour window, scores via BM25+embedding. Phase 2 fills remaining slots from all memories (no time/user filter).

**Rationale**: SQLite's `json_each()` allows filtering by user IDs in the `people` JSON column without loading all memories. The 6-hour window reflects recent conversation relevance while preventing irrelevant old memories from crowding out recent ones.

**Alternatives considered**:
- **Score-then-filter**: Load all memories, score, then partition by user/time — O(N) scoring for every retrieval, wasteful when most memories don't match current users.
- **Weighted scoring**: Assign user-matching a score multiplier instead of partitioning — less predictable ordering.
- **BM25-only for Phase 2**: Skip embedding similarity for supplemental — would miss semantically relevant memories with different keywords.

## Decision 4: Per-Row Embedding BLOB Storage

**Decision**: Store each memory's embedding vector as a BLOB in its row (not a separate table or file). Load and `np.stack()` on startup.

**Rationale**: Atomic per-row storage means insert and delete don't require index reconstruction. BLOBs are native to SQLite and efficient for binary data. The 1024-dimensional float32 vectors are 4KB each — well within SQLite's limits.

**Alternatives considered**:
- **Separate embeddings file (.npy)**: Faster to load but requires index synchronization with SQLite rows.
- **JSON array in SQLite**: Much larger storage (text representation of floats), slower to parse.
- **Separate embeddings table**: Normalized but adds JOIN complexity for no benefit in this single-entity case.

## Decision 5: In-Memory Indices Maintained Alongside SQLite

**Decision**: Keep `all_mem_list`, `tokenized_corpus`, `tokenized_corpus_pos`, BM25 index, and `embedding_vectors` numpy array in memory. SQLite is authoritative for persistence; in-memory structures are a performance cache loaded at startup.

**Rationale**: BM25 (rank_bm25 library) requires an in-memory tokenized corpus. Embedding similarity uses numpy operations on the full matrix. Both are faster in-memory than querying per-row from SQLite. The design compromise is acceptable because the memory store is bounded (~1000 memories).

**Alternatives considered**:
- **Pure SQLite retrieval**: BM25 would need reimplementation; embedding similarity would load vectors row-by-row — impractical.
- **Redis/vector DB**: Overkill for this scale; adds infrastructure dependency.
