# Data Model: Group Member Fuzzy Search

**Feature**: 011-group-member-search | **Date**: 2026-06-13

## Entities

### MemberSearchResult

The output of a fuzzy search — represents a matched group member.

| Field    | Type  | Description                                   | Validation                      |
|----------|-------|-----------------------------------------------|---------------------------------|
| username | str   | Display name (card preferred, nickname fallback) | Non-empty, from member list   |
| id       | str   | QQ user ID                                    | Numeric string, from member list |
| level    | str   | Activity level (e.g., "活跃LV6")              | From member info API; defaults to "未知" |

**Identity**: `id` uniquely identifies a member within a group.

**Lifecycle**: Transient — created on each search call, never persisted.

### MemberListCache

In-memory cache of the raw group member list to avoid redundant API calls.

| Field     | Type                     | Description                                  |
|-----------|--------------------------|----------------------------------------------|
| group_id  | int                      | Cache key — the QQ group number              |
| timestamp | float                    | Unix timestamp of cache insertion            |
| members   | list[dict]               | Raw member list from get_group_member_list() |

**TTL**: 300 seconds. Entries older than TTL are evicted on next access.

**Storage**: Module-level `dict[int, tuple[float, list[dict]]]` in `utils.py`.

### SearchQuery

The user-supplied search input.

| Aspect           | Detail                                               |
|------------------|------------------------------------------------------|
| Type             | str                                                  |
| Empty handling   | Empty/whitespace-only → return []                     |
| Case sensitivity | Case-insensitive for substring matching               |
| Character set    | Used as set of characters for overlap pass            |

## Relationships

```
SearchQuery ──(two-pass matching)──> [MemberSearchResult]
                                      ↑
MemberListCache ──(provides)──> get_group_member_list() output
                                      ↑
get_group_member_info() ──(level)──> MemberSearchResult.level
```
