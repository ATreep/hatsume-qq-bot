# Feature Specification: Memory System SQLite Refactor

**Feature Branch**: `027-memory-sqlite-refactor`

**Created**: 2026-07-05

**Status**: Draft

**Input**: User description: "Refactor the memory writing and retrieving mechanism. 1. Remove the additional memory recording LLM invoking. 2. chat_agent should output [memoryrecord: xxx] in the end of its response when a significant event happens. 3. Automatically retrieve memories relative to the current chatting users (ordered by sentence relevance, and do not exceed MAX_MEMORY_LIMIT=50), which are recorded in the past 6 hours. 4. If the number of retrieved memories is less than MAX_MEMORY_LIMIT, supply other sentence-relative memories. 5. Use SQLite database instead of JSON to store memories, also save the tokenized corpus and embedding vector of each memory into the database."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Efficient Memory Recording During Conversation (Priority: P1)

The bot (初芽) engages in conversation with group members. During its response, it identifies significant events — user interests, personality traits, important experiences, opinions, relationships, key events, or explicit "remember this" requests — and records them inline as part of its reply, without needing a separate post-conversation analysis pass. This eliminates the cost and latency of an additional LLM call dedicated solely to memory extraction.

**Why this priority**: This is the core behavioral change — replacing a costly separate LLM invocation with inline recording. It directly reduces API costs (one fewer advance-model LLM call per conversation) and simplifies the conversation lifecycle.

**Independent Test**: Can be fully tested by triggering a conversation where a user shares a memorable fact (e.g., "I just started learning piano") and verifying the bot's response contains a `[memoryrecord: ...]` tag, and that the memory is persisted to storage.

**Acceptance Scenarios**:

1. **Given** a user tells the bot "我最近开始学钢琴了", **When** the bot generates its reply, **Then** the reply ends with `[memoryrecord: {"content": "\"小明\" 最近开始学习钢琴。", "people": [{"user_id": 123, "user_name": "小明"}]}]` and the memory is stored.
2. **Given** a conversation contains only casual greetings ("你好", "今天天气不错"), **When** the bot generates its reply, **Then** no `[memoryrecord: ...]` tag is included (no significant event to record).
3. **Given** historical chat messages ("## 历史聊天记录") contain a significant event about a user, **When** the bot responds to current messages, **Then** it can also record memories from the historical context.
4. **Given** the bot's reply contains multiple significant events, **When** the reply is generated, **Then** multiple `[memoryrecord: ...]` tags can appear, one per event.

---

### User Story 2 - Contextual Memory Retrieval (Priority: P1)

When a user sends a message, the bot automatically retrieves relevant memories. Memories involving the current chatting users from the past 6 hours are prioritized first. If fewer than 50 relevant memories are found, additional sentence-relevant memories (not restricted by user or time) supplement the results. This ensures the bot always has rich context while prioritizing recent, personally relevant information.

**Why this priority**: Memory retrieval quality directly impacts conversation quality. The two-phase approach ensures the bot remembers what users recently said about themselves while still having access to broader context.

**Independent Test**: Can be tested by creating test memories with varying user associations and timestamps, then triggering a query from a specific user and verifying the retrieval order and count.

**Acceptance Scenarios**:

1. **Given** user A (QQ 123) and user B (QQ 456) are chatting, and user A has 3 memories from the past hour and 40 older memories, **When** the bot retrieves memories, **Then** the 3 recent user-A memories appear first, followed by the most relevant remaining memories, up to 50 total.
2. **Given** the current chatting users have only 5 memories from the past 6 hours, **When** the bot retrieves memories, **Then** those 5 appear first, and up to 45 additional sentence-relevant memories (from any user, any time) fill the remaining slots.
3. **Given** the current chatting users have zero memories from the past 6 hours, **When** the bot retrieves memories, **Then** up to 50 sentence-relevant memories from the full memory store are returned.
4. **Given** the memory store has fewer than 50 total memories, **When** the bot retrieves memories, **Then** all available memories are returned, ordered by relevance.

---

### User Story 3 - Persistent Storage with Fast Startup (Priority: P2)

The system stores all memories in a structured database that persists tokenization results and semantic embedding vectors alongside each memory entry. On startup, the system loads all memories directly without re-tokenizing or re-computing embeddings, enabling fast initialization even with large memory stores.

**Why this priority**: This is an infrastructure improvement. While important for scalability and maintenance, the bot can function without it using the existing JSON-based approach. It becomes critical as the memory store grows.

**Independent Test**: Can be tested by starting the bot, verifying that memories load without re-tokenization or re-embedding API calls, and confirming that new memories are correctly persisted with their tokens and vectors.

**Acceptance Scenarios**:

1. **Given** the bot has 100 stored memories, **When** the bot starts up, **Then** all memories are loaded into memory without any embedding API calls (vectors read from storage).
2. **Given** the bot records a new memory, **When** the memory is saved, **Then** its tokenized form and embedding vector are persisted atomically with the content.
3. **Given** an existing `memory.json` file from the previous system version, **When** the bot starts for the first time after upgrade, **Then** all existing memories are migrated to the new storage format and the JSON file is retained as backup.

---

### User Story 4 - Expired Memory Cleanup (Priority: P3)

Memories older than the configured retention period (150 days) are periodically removed to prevent unbounded storage growth. The cleanup happens during the daily maintenance window without disrupting active conversations.

**Why this priority**: Storage maintenance is important for long-term operation but has no immediate user-facing impact. The existing system already performs this function; this story ensures the new storage backend supports it equivalently.

**Independent Test**: Can be tested by creating memories with old timestamps, triggering the daily maintenance job, and verifying only expired memories are removed.

**Acceptance Scenarios**:

1. **Given** memories exist with timestamps older than 150 days, **When** the daily maintenance job runs, **Then** those memories are permanently deleted from storage.
2. **Given** the daily maintenance completes, **When** the bot continues operation, **Then** the in-memory indices reflect only the non-expired memories.

---

### Edge Cases

- What happens when the `[memoryrecord: ...]` JSON is malformed (e.g., missing closing brace, invalid JSON)? → The malformed tag is silently skipped; the rest of the reply is sent normally.
- What happens when the database file is corrupted or unreadable? → The system logs an error and initializes with an empty memory store; existing conversation continues.
- What happens when two conversations record memories simultaneously? → The storage layer handles concurrent writes safely through write-ahead logging.
- What happens when the embedding API is unavailable during memory recording? → The memory is stored without an embedding vector; it will still be retrievable via keyword search.
- What happens when the JSON-to-database migration encounters corrupted entries? → Corrupted entries are skipped; valid entries are migrated; a count of migrated vs. skipped is logged.
- What happens with memories that have empty associated people? → They are stored and retrieved normally; they simply won't match any user-specific query but can appear in supplemental results.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The bot MUST record significant events from conversations using inline `[memoryrecord: ...]` JSON tags in its response, without requiring a separate post-conversation LLM call.
- **FR-002**: The bot MUST NOT include `[memoryrecord: ...]` tags for insignificant interactions (greetings, casual small talk, transient topics).
- **FR-003**: The bot MUST be able to record memories based on events described in both current messages and the historical chat context.
- **FR-004**: The system MUST strip `[memoryrecord: ...]` tags from the visible message text before sending to users.
- **FR-005**: The system MUST automatically retrieve relevant memories when generating a response, without requiring explicit user request.
- **FR-006**: Retrieved memories MUST be ordered with user-specific memories (matching current chatting users, from the past 6 hours) first, followed by sentence-relevant supplemental memories.
- **FR-007**: The total number of retrieved memories MUST NOT exceed 50.
- **FR-008**: The system MUST store memories in a structured database, including the memory content, timestamp, associated people, tokenized form, and embedding vector.
- **FR-009**: The system MUST load all memories on startup without re-tokenizing content or re-computing embedding vectors.
- **FR-010**: The system MUST support a one-time migration from the existing JSON-based memory file to the new database format on first startup after upgrade.
- **FR-011**: The system MUST automatically delete memories older than the configured retention period (150 days) during daily maintenance.
- **FR-012**: The `find_memory` on-demand search capability MUST remain available for the bot during conversations.
- **FR-013**: When fewer user-specific memories exist than the retrieval limit, the system MUST supplement results with sentence-relevant memories regardless of associated users or timestamp.

### Key Entities *(include if feature involves data)*

- **Memory**: A recorded observation about a user or event. Contains: descriptive content, timestamp of the event, associated people (user IDs and names), tokenized text for keyword search, and a semantic embedding vector for similarity search.
- **Person Reference**: A user mentioned in or associated with a memory. Contains: user ID (QQ number) and display name.
- **Memory Store**: The collection of all memories, indexed by time and searchable by keyword relevance and semantic similarity.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Memory recording no longer requires a separate LLM API call per conversation — recording happens inline during the bot's normal response generation.
- **SC-002**: Bot startup completes memory loading without any embedding API calls, regardless of the number of stored memories.
- **SC-003**: Memory retrieval returns results ordered with user-specific recent memories (past 6 hours) before any supplemental results.
- **SC-004**: The maximum number of memories injected into a conversation context never exceeds 50.
- **SC-005**: All existing memories from the legacy JSON file are successfully migrated to the new database on first upgrade.
- **SC-006**: Malformed `[memoryrecord: ...]` tags in bot output do not cause message delivery failures or system errors.
- **SC-007**: Daily maintenance removes all expired memories (older than 150 days) without affecting active conversations.

## Assumptions

- The embedding model remains available and produces fixed-dimensional vectors suitable for binary storage.
- The existing Chinese text tokenization library continues to be used; its output format is compatible with JSON serialization.
- The database engine is available in the standard library and requires no additional dependencies.
- The QQ bot operates on a single process, so concurrent write contention is minimal and write-ahead logging is sufficient.
- The `memory.json` file from the previous system version is located at the standard plugin data path and is readable during migration.
- The bot operator does not need to manually trigger migration or configure the new storage backend.
- The 6-hour window for user-specific retrieval is a fixed constant in the configuration, not user-configurable at runtime.
