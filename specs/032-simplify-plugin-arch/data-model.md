# Data Model: Simplify Plugin Architecture

**Feature**: 032-simplify-plugin-arch
**Date**: 2026-07-15

## Overview

This feature is a structural refactor — it does not introduce new data entities, new storage schemas, or new API contracts. The "data model" is the mapping of which code lives in which module.

## Module Mapping

### handlers/ (7 → 4 files)

| Before | After | Content |
|--------|-------|---------|
| `handlers/chat.py` | `handlers/dialogue.py` | Conversation orchestration, debouncing, graph coordination |
| `handlers/pipeline.py` | `handlers/dialogue.py` (section 2) | Message parsing, content assembly, image processing |
| `handlers/forward.py` | `handlers/dialogue.py` (section 1) | Forward message parsing |
| `handlers/commands.py` | `handlers/tools.py` | Shell, video, timer, skills, membersearch, agents, autocreate, autoresponse |
| `handlers/poke.py` | `handlers/tools.py` (section 1) | Poke notice → ACG photo |
| `handlers/likes.py` | `handlers/social.py` | QQ profile likes, likerank |
| `handlers/__init__.py` | `handlers/__init__.py` | Thin re-export facade |

### memory/ (5 → 3 files)

| Before | After | Content |
|--------|-------|---------|
| `memory/db.py` | `memory/engine.py` (section 1) | SQLite DDL, CRUD, embedding vector persistence |
| `memory/store.py` | `memory/engine.py` (section 2) | BM25 index, scheduler hooks, memory lifecycle |
| `memory/retrieval.py` | `memory/engine.py` (section 3) | Hybrid BM25 + embedding vector retrieval |
| `memory/tokenizer.py` | `memory/tokenizer.py` | jieba posseg tokenizer (unchanged) |
| `memory/__init__.py` | `memory/__init__.py` | Thin re-export facade |

## Public Export Contract

All public functions exported from the affected packages preserve their signatures. The only change is which module file they live in.

### dialogue.py exports

```text
start_chat(matcher, event) → None
user_chat_handle(bot, event, matcher) → None
start_new_conversation(conv_state, ai_callback, configure_tools_fn, *, user_id, messages) → None
conv_state: ConversationState  # module-level singleton
get_human_message(bot, event) → Awaitable[dict|None]
get_current_query_user_id() → int|None
append_auxiliary_message(msg) → None
```

### tools.py exports

```text
handle_shell(matcher, args) → None
handle_generate_video(matcher, args) → None
handle_timer(bot, event, matcher, args) → None
handle_list_skills(matcher, args) → None
handle_membersearch(bot, event, matcher, args) → None
handle_resetsandbox(matcher) → None
handle_clear(matcher) → None
handle_agents(matcher) → None
handle_autocreate(bot, event, matcher, args) → None
handle_autoresponse(bot, event, matcher, args) → None
handle_poke(bot, event) → None
_wire_conv_state(state: ConversationState) → None
```

### social.py exports

```text
handle_like(bot, event, matcher) → None
handle_likerank(bot, event, matcher) → None
```

### engine.py exports

```text
# From db section
init_db() → None
insert_memory(content, time, people, embedding) → None
delete_expired_memories() → None
load_all_memories() → list[dict]
query_by_user_ids(user_ids) → list[dict]
query_all_except(user_ids) → list[dict]
migrate_from_json() → None

# From store section
get_mem_list() → list[dict]
add_mem(...) → None
init_tokenized_corpus() → None
init_memory_system() → None
normalize_people(people) → list[dict]
normalize_memory_object(obj) → tuple[dict, bool]

# From retrieval section
query_mems(query, query_user_id, retrieved_keys) → tuple[list[dict], str]
ensure_embedding_model() → None
rebuild_bm25() → None
rebuild_embedding_vectors() → None
```

## Dead Code Removed

See the companion plan (`docs/superpowers/plans/2026-07-15-merge-handlers-memory.md`) for the complete list of 46 dead items removed. All are confirmed to have zero callers in the codebase.
