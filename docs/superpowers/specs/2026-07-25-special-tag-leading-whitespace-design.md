# Special Tag Leading Whitespace Design

## Goal

Allow Hatsume to recognize supported output directives when horizontal
whitespace appears between the opening bracket and the directive name. For
example, `[ hatsumeface:害羞]` must behave the same as
`[hatsumeface:害羞]`.

## Scope

The compatibility change applies to these existing directives:

- `[memoryrecord: ...]`
- `[memorykeyman: ...]`
- `[hatsumeface: ...]`
- `[reply: ...]`
- `[CQ:at,qq=...]`

Only spaces and tabs immediately after `[` are accepted. Newlines are not
accepted because a directive must remain a single bracketed control token.
Existing syntax without whitespace remains unchanged.

## Design

Update the existing compiled regular expressions to accept `[ \t]*` after the
opening bracket. Keep parsing at the current ownership boundaries:

- `graph/nodes.py` continues to own face, memory, and reply parsing.
- `utils/__init__.py` continues to own the shared CQ-at pattern used by ID
  extraction, display rendering, and OneBot message segment generation.

Do not normalize or rewrite the complete model response before parsing. Each
parser removes only the directive it already owns, preserving the current
LangGraph history and user-visible text behavior.

## Data Flow

1. The model produces a response containing an existing directive, with or
   without spaces or tabs after the opening bracket.
2. The directive's existing parser recognizes and removes it from user-visible
   text.
3. Face, memory, reply, or CQ-at behavior proceeds through its existing path.
4. Malformed directives and directives split across lines remain ordinary text.

## Testing

Add focused regression coverage proving that spaced variants:

- extract memory content and associated QQ numbers;
- validate and remove a leading reply directive;
- trigger face handling without exposing the tag to the user;
- extract and convert CQ-at placeholders through the shared pattern.

Run the focused graph-node and utility tests first, followed by the repository's
required Ruff, Pyright, and full pytest checks.

## Non-Goals

- Introducing a generic directive parser or changing directive ownership.
- Accepting newlines between `[` and a directive name.
- Relaxing directive contents, placement, duplication, or reply target
  validation rules.
- Changing prompts to emit spaced directives.
