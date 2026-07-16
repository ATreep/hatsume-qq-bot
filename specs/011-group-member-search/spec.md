# Feature Specification: Group Member Fuzzy Search

**Feature Branch**: `011-group-member-search`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Add a group user search tool. Chat agent can use fuzzy search to find a user name and its qq id in the group by an unclear nikename. Also make this function a slash command `/membersearch xxx`. Do not make duplicated implementation for the slash command and the tool."

## User Scenarios & Testing

### User Story 1 - LLM Agent Identifies User by Fuzzy Nickname (Priority: P1)

The chat agent (LLM) needs to determine which group member a user is referring to when given an incomplete or vague nickname. For example, a user mentions "那个叫什么菠萝的人" and the agent searches for "菠萝" to find matching members.

**Why this priority**: This is the primary use case — enabling the LLM to resolve ambiguous user references during conversations, a core capability for contextual responses.

**Independent Test**: Can be fully tested by having the LLM invoke the search tool with a partial nickname and verifying it returns correctly formatted member data with all three fields.

**Acceptance Scenarios**:

1. **Given** the bot is in a conversation with group_id set, **When** the LLM calls the search tool with query "菠萝", **Then** the tool returns a JSON array of matching members sorted by relevance (substring matches first), each containing `username`, `id`, and `level`, with at most 5 results.
2. **Given** group members "菠萝面包" (card) and "测试菠萝二号" (nickname) exist, **When** the LLM searches "菠萝", **Then** both appear in results with the exact match "菠萝" ranked before partial matches.
3. **Given** no member matches the query "zzzznobody", **When** the LLM searches, **Then** the tool returns a "未找到匹配的群成员" message.
4. **Given** the LLM is not in a group context (group_id not set), **When** the LLM calls the search tool, **Then** the tool returns an error indicating group context is unavailable.

---

### User Story 2 - Group Member Uses `/membersearch` Slash Command (Priority: P2)

A group member wants to look up another member's QQ ID or level by typing `/membersearch <partial-nickname>` in the chat.

**Why this priority**: Provides a direct user-facing command that mirrors the LLM tool functionality. Important for user convenience but secondary to the LLM's ability to use search contextually.

**Independent Test**: Can be fully tested by a user typing `/membersearch 菠萝` in a group chat and receiving formatted search results as a text message.

**Acceptance Scenarios**:

1. **Given** a group member types `/membersearch 菠萝`, **When** the command executes, **Then** the bot replies with a formatted list showing numbered results with username, QQ ID, and level.
2. **Given** a group member types `/membersearch` with no query, **When** the command executes, **Then** the bot replies with usage instructions showing the command format and an example.
3. **Given** a group member types `/membersearch zzzznobody`, **When** no members match, **Then** the bot replies with "未找到匹配 'zzzznobody' 的群成员。"

---

### User Story 3 - Character-Overlap Fallback for Imprecise Queries (Priority: P3)

When a substring match finds no results, the system falls back to character-overlap matching. For example, searching "菠蜜" (no member has this as substring) still finds members whose names contain individual characters like "菠" or "蜜".

**Why this priority**: Enhances the robustness of fuzzy search but is not critical for the core use case. Most queries will produce substring matches.

**Independent Test**: Can be tested by creating group members with names that share individual characters (but not substrings) with the query, and verifying matches are returned ranked by character overlap ratio.

**Acceptance Scenarios**:

1. **Given** members "菠萝包" and "水蜜桃" exist, **When** searching "菠蜜" (no substring match), **Then** both appear in results sorted by character overlap ratio descending.
2. **Given** a query with no character overlap at all, **When** searching, **Then** an empty result set is returned.

---

### Edge Cases

- What happens when the query is empty or only whitespace? → Return empty results (tool) or usage help (command).
- What happens when the member list API call fails? → Return an error message and log the traceback.
- What happens when the member info API fails for a matched member's level? → Default `level` to "未知".
- What happens when a member has both empty card and empty nickname? → Skip that member (no username to match against).
- What happens when the same group member list is fetched multiple times in quick succession? → A 300-second TTL cache prevents redundant API calls.
- What happens with case differences (e.g., query "boluo" vs. name "BoLuo")? → Substring matching is case-insensitive.
- What happens when the bot itself appears in the member list? → The bot is not filtered out; it can appear in results if its name matches.

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide a fuzzy search function that accepts a query string and returns matching group members with `username`, `id` (QQ number as string), and `level`.
- **FR-002**: System MUST perform substring matching first (case-insensitive), ranking those results at the front of the returned list.
- **FR-003**: System MUST fall back to character-overlap matching when no substring matches exist, ranking by overlap ratio.
- **FR-004**: System MUST limit search results to a maximum of 5 entries, with front-of-list indicating highest relevance.
- **FR-005**: System MUST expose the search as an LLM-callable tool that reads the current group context and returns results as a JSON string.
- **FR-006**: System MUST expose the search as a `/membersearch <query>` slash command that formats results as human-readable text.
- **FR-007**: The LLM tool and the slash command MUST share a single underlying search implementation — no duplicated logic.
- **FR-008**: System MUST cache the group member list per group_id with a 300-second TTL to avoid redundant API calls.
- **FR-009**: System MUST determine `username` by preferring the member's group card over their global nickname when the card is non-empty.
- **FR-010**: System MUST fetch each matched member's `level` via the group member info API, defaulting to "未知" on failure.
- **FR-011**: System MUST return an appropriate error when the LLM tool is invoked without a valid group context.
- **FR-012**: System MUST return usage instructions when the slash command is invoked without a query.

### Key Entities

- **MemberSearchResult**: Represents a matched group member. Key attributes: `username` (display name — group card preferred, nickname fallback), `id` (QQ number as string), `level` (activity level string, e.g., "活跃LV6").
- **MemberListCache**: Per-group cache of the raw member list. Key attributes: `group_id` (cache key), `timestamp` (cache insertion time), `members` (list of member entries with id, nickname, and card).
- **SearchQuery**: The user-supplied search string. Used for two-pass matching: first as a substring, then as a character set for overlap scoring.

## Success Criteria

### Measurable Outcomes

- **SC-001**: The LLM can successfully identify a group member by partial nickname in a single tool call, with substring-matched results appearing before character-overlap results.
- **SC-002**: A user typing `/membersearch <query>` receives formatted results (or an appropriate "not found" / help message) within 3 seconds under normal network conditions.
- **SC-003**: Consecutive searches within 5 minutes for the same group do not trigger redundant member list API calls (cache hit).
- **SC-004**: 100% of search results include all three fields (`username`, `id`, `level`) — no field is missing or null, with `level` defaulting to "未知" only when the API fails.

## Assumptions

- The NoneBot2 OneBot V11 adapter provides member list and member info APIs that return the expected fields (`user_id`, `nickname`, `card`, `level`).
- Group membership is relatively static within a 300-second window, making TTL caching safe.
- The bot's own member entry in the member list does not need special filtering — it is acceptable if the bot matches its own name.
- The `level` field in the member info response is a string like "活跃LV6" or may be absent (→ default "未知").
- The LLM tool is only invoked during active conversations where the group context has been set by the conversation graph layer.
