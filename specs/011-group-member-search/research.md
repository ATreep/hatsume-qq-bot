# Research: Group Member Fuzzy Search

**Feature**: 011-group-member-search | **Date**: 2026-06-13

## Decision 1: Fuzzy Matching Algorithm

**Decision**: Two-pass matching — substring first, character-overlap fallback.

**Rationale**:
- Substring matching is fast, predictable, and covers most real-world use cases (partial nicknames)
- Character-overlap fallback handles imprecise queries without adding complexity of full edit-distance algorithms
- Ordering substring results first gives users intuitive relevance ranking

**Alternatives considered**:
- Jaro-Winkler / Levenshtein: More sophisticated but slower for large member lists; overkill for Chinese-character names where character-level overlap is more meaningful than edit distance
- Pure substring only: Would miss cases where user remembers characters but not order

## Decision 2: Member List Caching

**Decision**: Module-level dict cache with 300-second TTL per group_id.

**Rationale**:
- `get_group_member_list` is a heavy API call; group membership rarely changes within 5 minutes
- 300s TTL matches the spec requirement (consecutive searches within 5 minutes = cache hit)
- No persistent storage needed — cache lives as long as the bot process

**Alternatives considered**:
- Per-request cache (fetch once per conversation): Too short-lived for slash command usage
- No cache: Wastes API calls on repeated searches

## Decision 3: username Priority (card > nickname)

**Decision**: Use `card` if non-empty, fall back to `nickname`.

**Rationale**:
- Group cards are set specifically for that group context — more recognizable
- Follows existing pattern in `utils.py::get_group_member_name()`
- Consistent with how QQ displays names in group settings

## Decision 4: Architecture — Core in utils.py

**Decision**: Place `search_group_members()` in `utils.py`, with thin wrappers in `graph/tools.py` (tool) and `handlers/commands.py` (command).

**Rationale**:
- Follows existing project pattern: `utils.py` holds shared QQ utility functions
- Avoids duplicated implementation between tool and command
- Easy to test — core function takes stubbable dependencies (bot, group_id, query)

**Alternatives considered**:
- New module `handlers/membersearch.py`: More self-contained but introduces unnecessary new file for single function + two thin wrappers
- Inline logic in both tool and command: Violates "no duplicated implementation" requirement
