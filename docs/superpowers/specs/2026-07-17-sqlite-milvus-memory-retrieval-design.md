# SQLite and Milvus Lite Memory Retrieval Design

**Date:** 2026-07-17
**Status:** Approved for implementation
**Scope:** Long-term memory retrieval, resident memory removal, and a reversible SQLite-to-Milvus vector migration

## 1. Goals

1. Treat a tool query as whitespace-separated keywords and guarantee retrieval of every qualifying exact match.
2. Match memory content and the raw `people` JSON text with parameterized SQLite `LIKE`; do not use SQLite JSON functions for retrieval.
3. Match a numeric keyword only against an exact associated QQ user ID encoded in the raw `people` text.
4. Rank exact matches by the number of distinct query keywords they match, then by memory time.
5. Supplement exact matches with bounded BM25 results and Milvus cosine-similarity results.
6. Remove the process-resident full memory list, full token corpus, BM25 index, and vector matrix.
7. Store and search vectors with Milvus Lite at `data/hatsume-plugin/memory_vectors.db`.
8. Copy existing SQLite vectors to Milvus without deleting, updating, or changing the schema of the existing `memory.db` in this phase.

## 2. Non-Goals

- Do not drop the SQLite `embedding` column in this phase.
- Do not rewrite existing SQLite rows during vector migration.
- Do not use SQLite vectors as a runtime search fallback after the Milvus path is enabled.
- Do not add an external Milvus server. The deployment remains a local Milvus Lite file.
- Do not introduce a separate memory service or background task manager.

## 3. Persistence Boundaries

SQLite remains authoritative for memory identity and metadata:

- `id`
- `content`
- `time`
- raw `people` JSON text
- persisted `tokens` JSON text, retained for compatibility in this phase
- the existing `embedding` BLOB, retained only as migration and rollback source

Milvus Lite is authoritative for runtime vector search:

- collection: `memory_embeddings`
- primary key: `memory_id`, an `INT64` equal to `memories.id`
- vector field: `embedding`, a 1024-dimensional float vector
- metric: cosine similarity
- database path: `data/hatsume-plugin/memory_vectors.db` (Milvus Lite 3 stores its files below this directory)

The SQLite ID is the cross-store identity. Retrieval never joins by content because duplicate memory content is valid.

## 4. Components

### 4.1 `memory/vector_store.py`

This module owns the `pymilvus` boundary and exposes a small synchronous API:

- open or create the local Milvus collection;
- upsert vectors by SQLite memory ID;
- search by query vector;
- delete vectors by memory ID;
- check which IDs are present;
- close the client for tests and shutdown.

The module must not import graph or handler code. Tests use a temporary Milvus Lite file.
Each operation closes the PyMilvus client and releases the embedded Milvus Lite server before returning, because the Bot later forks Shell and Docker subprocesses.

### 4.2 `memory/engine.py`

The engine continues to own SQLite, tokenization, embedding-model access, memory creation, expiry, migration orchestration, and result fusion. It no longer owns full process-resident memory or vector indexes.

Remove these globals and their rebuild helpers:

- `all_mem_list`
- `tokenized_corpus`
- `tokenized_corpus_pos`
- `bm25`
- `bm25_dirty`
- `embedding_vectors`

Startup initializes SQLite, performs the existing JSON migration when applicable, and opens Milvus Lite. It does not select all SQLite memories into Python collections.

### 4.3 `graph/tools.py`

`query_memory()` calls `query_mems()` directly. It no longer calls `get_mem_list()` merely to test whether any memories exist. Existing conversation-level content deduplication and output formatting remain unchanged.

## 5. Exact Keyword Retrieval

### 5.1 Query parsing

Split on all whitespace, trim empty values, and deduplicate keywords with case-insensitive comparison while retaining first occurrence order.

A non-numeric keyword is eligible when its weighted length is at least 5:

- each CJK unified ideograph counts as 2;
- each ASCII English letter counts as 1;
- digits, whitespace, and punctuation count as 0.

This preserves the requested boundaries: three Chinese characters qualify and five English letters qualify. Mixed Chinese-English keywords use the same calculation.

A keyword containing only ASCII digits is always eligible and bypasses the weighted-length rule.

### 5.2 Parameterized `LIKE`

Escape `\\`, `%`, and `_` before constructing `LIKE` parameters and use `ESCAPE '\\'`.

For every eligible text keyword, add a score term that is true when either condition is true:

- `content LIKE '%keyword%'`
- `people LIKE '%keyword%'`

The `people` column is treated as plain text. Retrieval must not call `json_each`, `json_extract`, or `json.loads` to decide a match.

For a numeric keyword, match the canonical JSON fragment for an integer user ID, including its following delimiter, so `123` does not match `1234`. The stored normalization order is `user_id` followed by `user_name`, making the comma after the number the equality boundary.

The SQL computes `keyword_hits` as the number of distinct eligible keywords matched by each row. It filters on at least one match and orders by:

1. `keyword_hits DESC`
2. `time DESC`
3. `id DESC`

Exact matches are not truncated by `max_limit`.

## 6. Supplemental Retrieval

If exact matches contain fewer than `max_limit` unique memory IDs, retrieve supplemental results.

### 6.1 BM25

Fetch a bounded SQLite candidate set using the existing two-phase intent:

1. memories linked to current users within the configured time window;
2. recent global memories not already selected, up to three times the remaining result count.

User linkage uses raw `people LIKE` ID fragments, not SQLite JSON functions. Tokenize candidate content for this query and build a temporary `BM25Okapi` instance. Do not load or parse the persisted `tokens` JSON for retrieval.

### 6.2 Milvus

Embed the full query once and search `memory_embeddings` with cosine similarity. Request three times the remaining result count to allow for deduplication and stale IDs. Fetch returned memory IDs from SQLite in one parameterized query. Missing SQLite IDs are ignored and may be removed from Milvus during normal maintenance.

Runtime vector search must never read the SQLite `embedding` column. If Milvus is unavailable, exact and BM25 retrieval continue and the error is logged; SQLite vector fallback is forbidden.

### 6.3 Fusion

Normalize eligible BM25 and Milvus scores with the existing thresholds and `EMBEDDING_WEIGHT`. Merge by SQLite memory ID, exclude IDs already returned as exact matches, sort by fused score and then recency, and append only enough results to reach `max_limit`.

If exact matches already meet or exceed `max_limit`, return all exact matches and skip supplemental retrieval.

## 7. Write and Cleanup Flows

### 7.1 New memory

1. Normalize people and tokenize content.
2. Insert the SQLite row without writing an embedding BLOB; the retained legacy column receives `NULL` for new rows.
3. Generate the vector.
4. Upsert the vector into Milvus with the returned SQLite ID.

If vector generation or Milvus upsert fails, keep the SQLite memory. Keyword and BM25 retrieval remain available. Rerunning the explicit migration/reconciliation command detects the missing Milvus ID and generates its vector from SQLite content.

### 7.2 Expiry

Before deleting expired SQLite rows, select their IDs. Delete the SQLite rows with the existing retention transaction, then best-effort delete those IDs from Milvus. Failure to delete Milvus records must not restore expired SQLite memories; orphan Milvus IDs are harmless because final content is always fetched from SQLite.

### 7.3 Character proxy

`get_recent_user_memories()` queries SQLite directly using the canonical raw JSON user-ID fragment, orders by time descending, and applies its existing limit. It returns only fields required by the profile prompt and does not depend on a process memory mirror.

## 8. Reversible Vector Migration

Migration is an explicit operation performed only after the new read path and tests pass.

1. Open the real `memory.db` through a SQLite read-only URI.
2. Open `memory_vectors.db` and ensure the collection schema.
3. Stream `id`, `content`, and `embedding` from SQLite in batches of 100 rows.
4. Decode valid float32 BLOBs and upsert them unchanged into Milvus.
5. For rows whose BLOB is null or invalid, generate a vector from the first 300 content characters and upsert it. This reads content but does not modify SQLite.
6. Verify that every SQLite memory ID has a 1024-dimensional Milvus vector.
7. Report copied, generated, invalid, failed, and verified counts.

The migration must be idempotent: rerunning it verifies existing Milvus IDs, upserts legacy SQLite vectors when needed, and generates vectors for IDs absent from Milvus. It must not execute `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `VACUUM`, writable PRAGMAs, or schema creation against `memory.db`.

The real migration creates or updates only the independent `data/hatsume-plugin/memory_vectors.db` runtime artifact. The existing `memory.db`, WAL, and SHM files are not staged or committed.

## 9. Failure Handling

- Milvus open failure: log the error; exact and BM25 retrieval remain functional.
- Milvus query failure: omit vector supplements; never read SQLite embeddings as fallback.
- Embedding API failure during a new write: retain the SQLite row and report the missing vector.
- Migration batch failure: stop with a nonzero result after reporting the last completed batch; rerun is safe.
- Invalid or wrong-dimensional legacy BLOB: count it as invalid and regenerate from content. If the regenerated vector still has the wrong dimension, count the row as failed, do not upsert it, and do not alter SQLite.
- Duplicate memory content: keep distinct SQLite/Milvus IDs throughout retrieval and scoring.

## 10. Tests and Verification

Focused tests must cover:

- weighted keyword eligibility for Chinese, English, mixed, short, punctuation, and numeric input;
- raw `people LIKE` username matching and exact numeric ID boundaries;
- `%`, `_`, and backslash escaping;
- union matching, distinct-keyword hit counts, ordering, and unlimited exact results;
- bounded BM25 supplement and temporary corpus lifecycle;
- Milvus search supplement, score fusion, deduplication, and missing SQLite IDs;
- proof that runtime retrieval does not select SQLite `embedding` values;
- startup without any full-memory globals or full-table load;
- new writes using Milvus while leaving the SQLite legacy embedding null;
- read-only, idempotent migration from existing BLOBs;
- generated vectors for null legacy BLOBs;
- migration dimension validation and partial failure recovery;
- SQLite-backed recent-user memories and coordinated expiry cleanup.

After focused tests, run the repository-required checks:

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Only after those checks pass may the real read-only SQLite-to-Milvus migration run. After migration, compare the SQLite ID count with verified Milvus IDs and inspect `git status --short` in both the main repository and `data/hatsume-plugin` without committing either repository.
