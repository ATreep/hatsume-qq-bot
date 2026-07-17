# SQLite and Milvus Lite Memory Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace full resident memory indexes with SQLite-on-demand lexical retrieval and Milvus Lite vector search, then copy existing SQLite vectors into a local Milvus database without modifying `memory.db`.

**Architecture:** SQLite remains authoritative for memory content, timestamps, people, and IDs. A focused Milvus adapter stores vectors under the same SQLite IDs, while `memory/engine.py` performs exact `LIKE` retrieval, bounded per-query BM25, result fusion, writes, expiry, and migration orchestration without loading the full memory table. A separate CLI opens the real SQLite database read-only for the reversible vector copy.

**Tech Stack:** Python 3.12, sqlite3, NumPy, rank-bm25, pymilvus 2.6.x, Milvus Lite, pytest

**Repository constraint:** Do not commit or stage changes. Preserve the existing dirty worktree and do not modify existing `data/hatsume-plugin/memory.db*` files.

---

## File Map

- Create `hatsume/plugins/hatsume-plugin/memory/vector_store.py`: isolated Milvus Lite client and migration primitives.
- Create `scripts/migrate_memory_vectors.py`: explicit read-only SQLite-to-Milvus migration entry point.
- Modify `hatsume/plugins/hatsume-plugin/memory/engine.py`: SQLite queries, bounded BM25, Milvus fusion, lifecycle, and migration API.
- Modify `hatsume/plugins/hatsume-plugin/memory/__init__.py`: export only supported memory APIs.
- Modify `hatsume/plugins/hatsume-plugin/graph/tools.py`: remove the `get_mem_list()` precondition.
- Modify `pyproject.toml` and `uv.lock`: add `pymilvus[milvus-lite]`.
- Modify `tests/test_memory_db.py`: SQLite schema, raw JSON `LIKE`, recent-user, lifecycle, and read-source tests.
- Modify `tests/test_memory_utils.py`: keyword parsing, exact ordering, BM25/Milvus fusion, and no-resident-index tests.
- Create `tests/test_memory_vector_store.py`: real temporary Milvus Lite adapter and migration tests.
- Modify affected test stubs in `tests/test_tools.py`, `tests/test_graph_nodes.py`, `tests/test_conversation.py`, `tests/test_membersearch.py`, and `tests/test_random_acg_photo.py`.
- Modify `docs/arch.md`, repository `AGENTS.md`, and plugin `AGENTS.md`: document SQLite/Milvus ownership and retrieval flow.

## Task 1: Add and Prove the Milvus Lite Adapter

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `hatsume/plugins/hatsume-plugin/memory/vector_store.py`
- Create: `tests/test_memory_vector_store.py`

- [ ] **Step 1: Add the dependency**

Add this project dependency and refresh the lock file:

```toml
"pymilvus[milvus-lite]>=2.6.17,<3",
```

Run:

```bash
uv lock
uv sync --extra dev
```

Expected: `pymilvus`, `milvus-lite`, and their resolved dependencies install into `.venv`.

- [ ] **Step 2: Write failing adapter tests**

Create tests that use a temporary `.db` file and assert this public contract:

```python
store = MilvusVectorStore(tmp_path / "vectors.db", dimension=3)
store.upsert([(7, [1.0, 0.0, 0.0]), (8, [0.0, 1.0, 0.0])])
assert store.existing_ids([7, 8, 9]) == {7, 8}
assert store.search([1.0, 0.0, 0.0], limit=2)[0].memory_id == 7
store.delete([7])
assert store.existing_ids([7, 8]) == {8}
store.close()
```

Also assert that a vector with the wrong dimension raises `ValueError` before any Milvus call.

- [ ] **Step 3: Run tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_memory_vector_store.py -q
```

Expected: collection fails because `vector_store.py` or `MilvusVectorStore` does not exist.

- [ ] **Step 4: Implement the minimal adapter**

Define immutable search results and the wrapper:

```python
@dataclass(frozen=True)
class VectorSearchResult:
    memory_id: int
    score: float

class MilvusVectorStore:
    def __init__(self, db_path: str | Path, *, dimension: int = 1024): ...
    def upsert(self, items: Iterable[tuple[int, Sequence[float]]]) -> None: ...
    def search(self, vector: Sequence[float], *, limit: int) -> list[VectorSearchResult]: ...
    def existing_ids(self, memory_ids: Sequence[int]) -> set[int]: ...
    def delete(self, memory_ids: Sequence[int]) -> None: ...
    def close(self) -> None: ...
```

Use collection `memory_embeddings`, primary field `memory_id`, vector field `embedding`, and `COSINE`. Create parent directories before opening `MilvusClient(uri=str(db_path))`.

- [ ] **Step 5: Verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_memory_vector_store.py -q
```

Expected: all adapter tests pass with no warnings.

## Task 2: Implement Raw SQLite Exact Matching

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `tests/test_memory_db.py`
- Modify: `tests/test_memory_utils.py`

- [ ] **Step 1: Write failing keyword parser tests**

Cover the weighted threshold and deduplication:

```python
assert _eligible_exact_keywords("苹果手机 abcde ABCDE 123 你好 ab_cd") == [
    ExactKeyword("苹果手机", False),
    ExactKeyword("abcde", False),
    ExactKeyword("123", True),
]
assert _eligible_exact_keywords("中文ab") == [ExactKeyword("中文ab", False)]
```

Here each CJK ideograph weighs 2, each ASCII letter weighs 1, numeric-only values bypass the threshold, and casefolded duplicates collapse.

- [ ] **Step 2: Write failing SQLite exact-query tests**

Insert memories that distinguish:

- content substring from username substring;
- ID `123` from `1234`;
- one-keyword from two-keyword matches;
- `%`, `_`, and backslash literals;
- more exact results than `max_limit`.

Assert `query_exact_memories()` returns row dictionaries with `id`, `content`, `time`, and `keyword_hits`, ordered by hit count, time, and ID. Trace executed SQL and assert it contains no `json_each` or `json_extract`.

- [ ] **Step 3: Run tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_memory_db.py tests/test_memory_utils.py -q
```

Expected: failures identify missing exact-keyword and raw-`LIKE` APIs.

- [ ] **Step 4: Implement parser and SQL builder**

Add:

```python
@dataclass(frozen=True)
class ExactKeyword:
    value: str
    numeric_user_id: bool

def _eligible_exact_keywords(query: str) -> list[ExactKeyword]: ...
def _escape_like(value: str) -> str: ...
def _user_id_json_fragment(user_id: int) -> str: ...
def query_exact_memories(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]: ...
```

Build one `CASE WHEN` score term per keyword with parameter placeholders. Numeric keywords only test the canonical raw `people` fragment. Text keywords test both `content` and raw `people`. Do not parse `people` in this path and do not apply a SQL limit.

- [ ] **Step 5: Verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_memory_db.py tests/test_memory_utils.py -q
```

Expected: exact-query tests pass.

## Task 3: Replace Resident Hybrid Retrieval

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `tests/test_memory_utils.py`

- [ ] **Step 1: Write failing bounded-retrieval tests**

Use an in-memory SQLite database and a fake vector store. Assert:

```python
results = query_mems("苹果手机 abcde", user_ids=[42], max_limit=5)
assert [content for content, _ in results[:2]] == exact_contents
assert len(results) == 5
assert fake_vectors.search_calls == [(query_vector, 9)]  # remaining 3 * 3
```

Add separate assertions that:

- exact results exceeding five all survive;
- exact results at the limit skip BM25 and Milvus;
- BM25 candidate count is at most three times the remaining slots per phase;
- duplicate IDs from exact, BM25, and Milvus appear once;
- Milvus failure still returns exact and BM25 results;
- missing SQLite rows returned by Milvus are ignored;
- no query selects the SQLite `embedding` column.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_memory_utils.py -q
```

Expected: current `all_mem_list`-based retrieval violates the new contract.

- [ ] **Step 3: Implement bounded candidates and fusion**

Introduce an internal ID-based result:

```python
@dataclass(frozen=True)
class ScoredMemory:
    memory_id: int
    content: str
    timestamp: int
    score: float
```

Implement:

```python
def _query_bm25_candidates(conn, query, user_ids, exclude_ids, remaining): ...
def _query_vector_candidates(conn, query, exclude_ids, remaining): ...
def _fetch_memories_by_ids(conn, ids): ...
def query_mems(user_query, user_ids=None, max_limit=None, time_window=24 * 3600): ...
```

Build `BM25Okapi` only from the bounded candidate contents. Query Milvus with `remaining * 3`, fetch content by ID, apply configured thresholds and weights, then append supplements only until total count reaches `max_limit`.

- [ ] **Step 4: Remove all resident index state**

Delete `load_all_memories()`, full-memory globals, rebuild/get/set helpers, and content-to-index mapping. Confirm source search is empty:

```bash
rg -n "all_mem_list|tokenized_corpus|tokenized_corpus_pos|embedding_vectors|bm25_dirty|rebuild_bm25|rebuild_embedding_vectors" hatsume/plugins/hatsume-plugin/memory
```

Expected: no matches.

- [ ] **Step 5: Verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_memory_utils.py -q
```

Expected: all retrieval tests pass without resource warnings.

## Task 4: Switch Lifecycle Writes and Recent-User Reads

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/engine.py`
- Modify: `hatsume/plugins/hatsume-plugin/memory/__init__.py`
- Modify: `tests/test_memory_db.py`
- Modify: `tests/test_character_proxy.py`

- [ ] **Step 1: Write failing lifecycle tests**

Assert:

- `init_memory_system()` opens SQLite and Milvus but never runs `SELECT ... FROM memories` without a limit;
- `insert_memory()` omits the `embedding` column and leaves it `NULL` on the legacy schema;
- `add_mem()` inserts SQLite first and upserts Milvus with the returned ID;
- a failed Milvus upsert preserves the SQLite row;
- `get_recent_user_memories()` uses raw `people LIKE`, returns newest first, and respects 0..100 bounds;
- expiry captures IDs, deletes SQLite rows, and requests deletion of the same Milvus IDs.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_memory_db.py tests/test_character_proxy.py -q
```

Expected: failures show the current in-memory and SQLite-embedding behavior.

- [ ] **Step 3: Implement SQLite-first/Milvus-second writes**

Change the insert signature to:

```python
def insert_memory(conn, content, mem_time, people, tokens) -> int: ...
```

Do not include `embedding` in the insert statement. In `add_mem()`, persist first, embed `_truncate_for_embedding(value)`, then `vector_store.upsert([(memory_id, vector)])`.

- [ ] **Step 4: Implement direct recent-user and expiry queries**

Use canonical raw ID fragments with parameterized `LIKE`. Keep `people` unparsed unless a returned caller contract explicitly needs it. Preserve explicit commits for SQLite deletions and best-effort Milvus cleanup.

- [ ] **Step 5: Simplify startup and exports**

`init_memory_system()` must initialize stores and existing JSON migration only. `init_tokenized_corpus()` becomes the daily expiry task without rebuilding state. Remove obsolete exports from `memory/__init__.py`.

- [ ] **Step 6: Verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_memory_db.py tests/test_character_proxy.py -q
```

Expected: lifecycle tests pass.

## Task 5: Update the Graph Boundary and Test Stubs

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_graph_nodes.py`
- Modify: `tests/test_conversation.py`
- Modify: `tests/test_membersearch.py`
- Modify: `tests/test_random_acg_photo.py`
- Modify: `tests/test_timer_injection.py`

- [ ] **Step 1: Write a failing graph-tool test**

Assert `query_memory()` calls `query_mems()` even when no `get_mem_list` stub exists, formats timestamps, and preserves content-level conversation deduplication.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/python -m pytest tests/test_tools.py -k query_memory -q
```

Expected: import or call failure references `get_mem_list`.

- [ ] **Step 3: Remove the obsolete precondition**

Delete the `get_mem_list` import and guard. Call `query_mems()` directly and keep result formatting unchanged.

- [ ] **Step 4: Update only obsolete memory stubs**

Remove `get_mem_list`, rebuild-helper, and vector-matrix stubs. Provide the new engine interfaces where module-isolation tests need them. Do not change unrelated character-proxy assertions already present in the dirty worktree.

- [ ] **Step 5: Verify the affected boundary tests**

```bash
.venv/bin/python -m pytest tests/test_tools.py tests/test_graph_nodes.py tests/test_conversation.py tests/test_membersearch.py tests/test_random_acg_photo.py tests/test_timer_injection.py -q
```

Expected: all selected tests pass without collection errors.

## Task 6: Implement the Read-Only Vector Migration

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/memory/vector_store.py`
- Create: `scripts/migrate_memory_vectors.py`
- Modify: `tests/test_memory_vector_store.py`

- [ ] **Step 1: Write failing migration tests**

Create a temporary legacy SQLite database containing:

- one valid 3-dimensional float32 BLOB;
- one `NULL` embedding requiring the fake embedder;
- one invalid BLOB;
- an SQLite authorizer or file hash proving no writes occurred.

Assert a first migration copies the valid BLOB and regenerates null or invalid BLOBs, a second migration is idempotent, a wrong-dimensional regenerated vector is reported as failed, and a batch exception exits nonzero without changing SQLite bytes.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest tests/test_memory_vector_store.py -q
```

Expected: migration API and CLI do not exist.

- [ ] **Step 3: Implement the reusable migration API**

Add:

```python
@dataclass(frozen=True)
class MigrationReport:
    total: int
    copied: int
    generated: int
    already_present: int
    invalid: int
    failed: int
    verified: int

def migrate_sqlite_vectors(
    sqlite_path: Path,
    vector_store: MilvusVectorStore,
    embed_documents: Callable[[list[str]], list[list[float]]],
    *,
    batch_size: int = 100,
) -> MigrationReport: ...
```

Open SQLite with `file:{quoted_path}?mode=ro` and `uri=True`. Read `id`, `content`, and `embedding` only. Never call `init_db()` from this function.

- [ ] **Step 4: Implement the CLI**

The script resolves repository paths, loads `.env.prod`, constructs the existing BGE-M3 embedding client, opens `memory_vectors.db`, runs the migration, prints the report, and returns nonzero when `failed > 0` or `verified != total`. A recovered invalid legacy BLOB remains visible in the report but does not make a fully verified migration fail.

Support explicit test paths:

```bash
.venv/bin/python scripts/migrate_memory_vectors.py \
  --sqlite data/hatsume-plugin/memory.db \
  --milvus data/hatsume-plugin/memory_vectors.db
```

- [ ] **Step 5: Verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_memory_vector_store.py -q
```

Expected: adapter and migration tests pass.

## Task 7: Synchronize Architecture Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `hatsume/plugins/hatsume-plugin/AGENTS.md`
- Modify: `docs/arch.md`

- [ ] **Step 1: Update ownership and invariants**

Document that SQLite is the metadata source, Milvus Lite is the vector source, SQLite IDs join the stores, runtime retrieval uses no full resident memory structures, and this transition retains but does not read or update the legacy SQLite vector column.

- [ ] **Step 2: Update retrieval and migration data flows**

Replace the full-memory/BM25-matrix flow with exact SQLite `LIKE`, bounded transient BM25, Milvus cosine search, ID-based fusion, and explicit read-only migration. Add `memory/vector_store.py`, the CLI, and their tests to module indexes.

- [ ] **Step 3: Check documentation consistency**

```bash
rg -n "all_mem_list|embedding_vectors|SQLite.*向量|Milvus|memory_vectors" AGENTS.md hatsume/plugins/hatsume-plugin/AGENTS.md docs/arch.md
```

Expected: historical descriptions are clearly labeled or replaced; current architecture has no contradictory source-of-truth statement.

## Task 8: Verification and Real Migration

**Files:**
- Runtime output only: `data/hatsume-plugin/memory_vectors.db*`
- Must remain unchanged: `data/hatsume-plugin/memory.db*`

- [ ] **Step 1: Run focused memory and graph tests**

```bash
.venv/bin/python -m pytest \
  tests/test_memory_db.py \
  tests/test_memory_utils.py \
  tests/test_memory_vector_store.py \
  tests/test_tools.py \
  tests/test_character_proxy.py -q
```

Expected: all pass with no warnings.

- [ ] **Step 2: Run required repository checks**

```bash
.venv/bin/ruff check hatsume/plugins/hatsume-plugin
npx --no-install pyright
.venv/bin/python -m pytest tests -q
```

Expected: exit code 0 for all three commands, no collection errors, resource warnings, or type errors.

- [ ] **Step 3: Record SQLite fingerprints before migration**

```bash
shasum -a 256 data/hatsume-plugin/memory.db data/hatsume-plugin/memory.db-wal data/hatsume-plugin/memory.db-shm 2>/dev/null || true
sqlite3 -readonly data/hatsume-plugin/memory.db \
  "SELECT COUNT(*), COUNT(embedding) FROM memories;"
```

Record every existing file hash and both counts.

- [ ] **Step 4: Run the explicit migration**

```bash
.venv/bin/python scripts/migrate_memory_vectors.py \
  --sqlite data/hatsume-plugin/memory.db \
  --milvus data/hatsume-plugin/memory_vectors.db
```

Expected: exit code 0 and `verified == total`.

- [ ] **Step 5: Prove SQLite was not modified**

Repeat the exact hash and count commands from Step 3. Expected: all pre-existing SQLite file hashes and both row counts are identical.

- [ ] **Step 6: Inspect both repositories**

```bash
git status --short
git -C data/hatsume-plugin status --short
```

Expected: source changes are limited to this feature plus the user's pre-existing work; the data repository shows only the new Milvus runtime database files. Do not stage or commit either repository.
