# Feature Specification: Extract Links from Markdown-to-Image Messages

**Feature Branch**: `029-extract-links-md-to-image`

**Created**: 2026-07-08

**Status**: Draft

**Input**: User description: "Update md_to_image.py: When auto_convert_text sends an image, use regex to extract all links (Markdown links and raw URLs) from the message. After sending the image, also send all links as a single formatted text message with LINKS header and numbered list."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Links Preserved in Image-Rendered Messages (Priority: P1)

A QQ group member receives a long or Markdown-rich bot reply that is rendered as an image. The image contains embedded URLs that are now unclickable pixels. The bot appends a separate text message with all extracted links in a numbered list, so the user can tap or copy them without manually retyping.

**Why this priority**: This is the core feature — without it, every image-rendered message with links silently loses clickable URLs. This affects all users who receive image-formatted bot replies.

**Independent Test**: Send a bot message containing Markdown links and raw URLs that exceeds the image threshold. Verify the bot sends an image followed by a text message listing all links. Verify clicking/tapping the links works as expected in the QQ client.

**Acceptance Scenarios**:

1. **Given** the bot produces a long message (over threshold) containing `[GitHub](https://github.com)` and a raw `https://example.com`, **When** the message is rendered as an image, **Then** the bot sends the image AND a separate text message: "LINKS\n\n1. https://github.com\n2. https://example.com"
2. **Given** the bot produces a message with code blocks and no URLs, **When** the message is rendered as an image, **Then** only the image is sent (no LINKS message appended)
3. **Given** the bot produces a message with the same URL appearing twice, **When** the message is rendered as an image, **Then** each link appears only once in the LINKS message (deduplicated)

---

### User Story 2 - Short Messages With Markdown Features (Priority: P2)

A short message containing rich Markdown formatting (code blocks, headers, LaTeX) is rendered as an image even though it's under the length threshold. Links in this message are also extracted and sent as a follow-up.

**Why this priority**: The image rendering path is taken for both long messages AND short messages with Markdown features. Both paths should preserve links.

**Independent Test**: Send a short bot message (under threshold) with a fenced code block and a URL. Verify it renders as image + LINKS follow-up.

**Acceptance Scenarios**:

1. **Given** a message under the length threshold containing ``` ```python``` and a `https://docs.python.org` link, **When** the message is sent, **Then** it renders as an image followed by a LINKS text message with the URL.

---

### User Story 3 - Plain Text Messages Unchanged (Priority: P3)

Short plain-text messages without rich Markdown formatting are sent as-is (text, not image). The link extraction logic does not affect this path.

**Why this priority**: Regression prevention — ensures the normal text path is untouched by the new link extraction behavior.

**Independent Test**: Send a short plain-text message. Verify it arrives as plain text, not as an image, and no LINKS follow-up appears.

**Acceptance Scenarios**:

1. **Given** a short plain-text message ("Hello, how are you?") with no Markdown features, **When** the message is sent, **Then** it is delivered as a plain text MessageSegment, with no image rendering and no LINKS message.

---

### Edge Cases

- **Message with only a URL and no other content**: Should still render as image if URL length exceeds threshold, with the link extracted and sent as LINKS.
- **Invalid/partial URLs** (e.g., `htp://typo`, `www.example.com` without protocol): Only `https?://` prefixed URLs are matched. Non-matching text is ignored.
- **URLs inside Markdown code blocks/backticks**: Still extracted — the pixel problem applies to code blocks too, so links inside them should be clickable in the follow-up.
- **Emoji in message**: Already stripped before processing (existing behavior in `auto_convert_text`). No conflict with link extraction.
- **Empty links list**: If the message has no extractable URLs, no LINKS message is sent — the result is just `[image_segment]`.
- **Extremely long URLs**: Included as-is in the LINKS message. The QQ client handles URL display/wrapping.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST extract all Markdown-style links (`[label](url)`) and raw URLs (`https?://...`) from the message text when it decides to render an image.
- **FR-002**: The system MUST format extracted links as a numbered list under the header "LINKS": each link on its own line as `N. <url>`.
- **FR-003**: The system MUST deduplicate extracted links, preserving first-occurrence order.
- **FR-004**: The `auto_convert_text` function MUST return a list of `MessageSegment` objects instead of a single `MessageSegment`.
- **FR-005**: When no image rendering occurs (short plain text), the return value MUST be `[MessageSegment.text(text)]` — a single-element list.
- **FR-006**: When image rendering occurs and links are found, the return value MUST be `[MessageSegment.image(...), MessageSegment.text(formatted_links)]`.
- **FR-007**: When image rendering occurs but no links are found, the return value MUST be `[MessageSegment.image(...)]` — no follow-up text.
- **FR-008**: Both call sites (`graph/nodes/ai.py` and `handlers/chat.py`) MUST iterate the returned list and send each segment independently.

### Key Entities

- **MessageSegment**: An existing entity representing a sendable message part (text or image). The function now returns a list of them.
- **Extracted Link**: A URL string (`https?://...`) found in the source text, either as a raw URL or as the target of a Markdown link. Deduplicated by exact string match.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All URLs from an image-rendered message appear as clickable text in a follow-up message in 100% of cases.
- **SC-002**: Duplicate URLs never appear in the LINKS message.
- **SC-003**: Plain-text messages (no image rendering) are unaffected — zero regressions in the existing text delivery path.
- **SC-004**: The combined image + links delivery completes without errors or dropped messages.

## Assumptions

- URL matching is case-sensitive per RFC 3986 (scheme and host are case-insensitive, but we match the exact string found).
- MessageSegment concatenation (at + msg in chat.py) with a list is not supported — callers must iterate and send each segment individually.
- The existing `emoji_pattern.sub("", text)` call at the top of `auto_convert_text` runs before link extraction, so emoji-stripped text is what gets scanned for links.
- The QQ OneBot V11 adapter handles consecutive `MessageSegment.image` then `MessageSegment.text` sends without issues.
- `render_html` timeout/error fallback already returns `MessageSegment.text(text)` — this path naturally becomes `[MessageSegment.text(text)]`.
