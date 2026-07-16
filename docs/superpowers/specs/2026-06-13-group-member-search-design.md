# Group Member Search — Design Spec

**Date:** 2026-06-13
**Status:** Approved

## Overview

Add a fuzzy group member search capability. The chat agent (LLM) can invoke a tool to search for group members by partial/fuzzy nickname, and users can trigger the same search via the `/membersearch <query>` slash command. Core logic is shared — no duplicate implementation.

## Architecture

```
utils.py                              ← search_group_members() — core search function

graph/tools.py                        ← membersearch @tool — LLM-facing wrapper
                                      reads _current_group_id, calls search_group_members

handlers/commands.py                  ← handle_membersearch() — command handler
                                      reads event.group_id, calls search_group_members

__init__.py                           ← on_command("membersearch") — command registration
```

## Components

### 1. Core Search — `utils.py::search_group_members`

```python
async def search_group_members(
    bot: Bot, group_id: int, query: str, max_results: int = 5
) -> list[dict[str, str]]:
```

**Input:** NoneBot Bot instance, group ID, search query string, max results (default 5).

**Output:** List of dicts sorted by relevance:
```python
[{"username": "菠萝面包", "id": "123456", "level": "活跃LV6"}, ...]
```

**Algorithm:**
1. Fetch all group members via `bot.get_group_member_list(group_id=group_id)`
2. For each member, extract `username = card if card.strip() else nickname`
3. **Pass 1 — Substring match:** Case-insensitive substring of username. These go to the front of results.
4. **Pass 2 — Character-overlap match:** For remaining members, count overlapping characters between query and username. Rank by overlap ratio, append behind substring results.
5. Truncate to `max_results` (5).
6. For each final result, fetch `level` via `bot.get_group_member_info(group_id, user_id).info.get("level", "未知")`. On API failure, default to `"未知"`.
7. Return the list.

**Caching:** A module-level TTL cache stores the member list per group_id for 300 seconds, avoiding redundant `get_group_member_list` API calls within a single conversation or rapid retriggers. Only caches the member list (user_id, nickname, card) — level is fetched fresh per match since it's only called for max 5 users.

### 2. LLM Tool — `graph/tools.py::membersearch`

```python
@tool
async def membersearch(query: str) -> str:
```

- Reads `_current_group_id` (set before each conversation turn — follows existing tool pattern)
- Returns JSON string of results or an error/empty message
- Tool description instructs the LLM: max 5 results, front-of-list = most accurate, use when trying to identify a user by vague/partial nickname

### 3. Slash Command — `handlers/commands.py::handle_membersearch`

```python
async def handle_membersearch(bot: Bot, event: GroupMessageEvent, matcher, args: Message) -> None:
```

- Extracts query from `args.extract_plain_text().strip()`
- Empty query → help/usage message
- Calls `search_group_members(bot, event.group_id, query)`
- Formats results as readable text and calls `matcher.finish(...)`
- No results → "未找到匹配的群成员"

### 4. Command Registration — `__init__.py`

```python
membersearch_cmd = on_command("membersearch", priority=10, block=True)

@membersearch_cmd.handle()
async def _(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    await handle_membersearch(bot, event, membersearch_cmd, args)
```

## Data Flow

```
LLM path:     LLM → membersearch tool → search_group_members() → JSON string → LLM parses → responds
Command path: User → /membersearch 菠萝 → handle_membersearch() → search_group_members() → formatted text → User
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Empty/whitespace query | Return usage help message |
| `get_group_member_list` API fails | Return error message, log traceback |
| No matches found | Return "未找到匹配的群成员" |
| `get_group_member_info` fails for level | Default `level` to `"未知"` |
| Tool called without group context (`_current_group_id` is None) | Return error: "无法确定当前群聊 ID" |

## Testing Strategy

- Unit test `search_group_members` with mocked `get_group_member_list` and `get_group_member_info`
- Test substring matches appear before character-overlap matches
- Test result truncation at 5 (and configurable `max_results`)
- Test empty query, no matches, API failure cases
- Test level defaults to "未知" on API failure
- Test command handler formatting output

## Files

| File | Action |
|------|--------|
| `hatsume/plugins/hatsume-plugin/utils.py` | Add `search_group_members()` |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Add `membersearch` @tool |
| `hatsume/plugins/hatsume-plugin/handlers/commands.py` | Add `handle_membersearch()` |
| `hatsume/plugins/hatsume-plugin/__init__.py` | Add `on_command("membersearch")` matcher + handler |
| `tests/test_membersearch.py` | New test file |
