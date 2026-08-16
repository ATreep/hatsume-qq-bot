# URL Paren Boundary Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix URL/link extraction so a trailing right paren `)` is kept only when it closes a balanced `(` inside the URL (e.g. Wikipedia URLs), and stripped together with adjacent sentence punctuation (`.,;:!?`) when it is Markdown/prose wrapping.

**Architecture:** The extraction lives in `_extract_links` in `hatsume/plugins/hatsume-plugin/utils/md_to_image.py`. It first rewrites `[label](url)` into the bare URL, then greedily matches `https?://` plus the RFC 3986 ASCII set (which includes `()`). A small post-processing trim step added in `_extract_links` strips trailing unbalanced `)` and sentence punctuation, preserving balanced parens. No regex rewrite of `_LINK_PATTERN` is needed.

**Tech Stack:** Python 3.12+, regex, pytest.

**Spec:** Task prompt "链接提取修复" — trailing `)` boundary handling. Requirements: (1) balanced trailing `)` kept, unbalanced stripped; (2) Markdown `[text](url)` closing `)` not part of URL; (3) internal balanced parens preserved; (4) `)` followed by `,`/`.` boundary correct.

## Global Constraints

- Only modify `hatsume/plugins/hatsume-plugin/utils/md_to_image.py` (production) and `tests/test_md_to_image.py` (tests). New files only for tests if needed (not needed here).
- Preserve all existing uncommitted working-tree changes; do not `git add`/`commit`/`push`.
- TDD: write failing tests first, verify RED, then implement, verify GREEN.
- Run `.venv/bin/ruff check hatsume/plugins/hatsume-plugin`, `npx --no-install pyright`, and `.venv/bin/python -m pytest tests -q`.

---

### Task 1: Add regression tests for trailing-paren URL boundaries

**Files:**
- Modify: `tests/test_md_to_image.py` (add tests in the `_extract_links` section)

**Interfaces:**
- Consumes: `_extract_links(text: str) -> list[str]` (already exported in the test module as `_extract_links`)
- Produces: no new production interface

- [ ] **Step 1: Add the regression tests after `test_extract_links_urls_in_code_blocks`.**

```python
def test_extract_links_strips_wrapping_paren():
    """A sentence-wrapping right paren with no matching open paren is stripped."""
    result = _extract_links("(https://example.com)")
    assert result == ["https://example.com"]


def test_extract_links_strips_paren_and_sentence_punctuation():
    """Trailing ')' plus a period or comma are both treated as wrapping."""
    assert _extract_links("https://example.com/path).") == [
        "https://example.com/path"
    ]
    assert _extract_links("(https://example.com),") == ["https://example.com"]


def test_extract_links_keeps_balanced_parens():
    """A trailing ')' that closes a '(' inside the URL is part of the URL."""
    result = _extract_links(
        "https://en.wikipedia.org/wiki/Disambiguation_(disambiguation)"
    )
    assert result == [
        "https://en.wikipedia.org/wiki/Disambiguation_(disambiguation)"
    ]


def test_extract_links_keeps_internal_balanced_parens():
    """Balanced parens in the middle of a URL are preserved."""
    result = _extract_links("https://example.com/foo(bar)")
    assert result == ["https://example.com/foo(bar)"]


def test_extract_links_balanced_paren_followed_by_punctuation():
    """Punctuation after a balanced ')' is stripped; the ')' is kept."""
    result = _extract_links(
        "https://en.wikipedia.org/wiki/Disambiguation_(disambiguation),"
    )
    assert result == [
        "https://en.wikipedia.org/wiki/Disambiguation_(disambiguation)"
    ]


def test_extract_links_markdown_link_with_balanced_paren_url():
    """Markdown [text](url) keeps a balanced trailing ')' and strips nothing extra."""
    result = _extract_links(
        "[text](https://en.wikipedia.org/wiki/Disambiguation_(disambiguation))"
    )
    assert result == [
        "https://en.wikipedia.org/wiki/Disambiguation_(disambiguation)"
    ]
```

- [ ] **Step 2: Run the new tests to verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_md_to_image.py -q`
Expected: the six new tests FAIL (extraction currently returns `https://example.com)`, `https://example.com/path).`, `…(disambiguation),` for the failing cases); the balanced-paren cases already pass.

---

### Task 2: Implement the trailing-paren trim in `_extract_links`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/utils/md_to_image.py` (`_extract_links` + new `_trim_url_tail` helper)

**Interfaces:**
- Consumes: `_LINK_PATTERN` (unchanged), the existing Markdown-link `re.sub` step
- Produces: `_trim_url_tail(url: str) -> str` — strips trailing sentence punctuation and unmatched `)`, keeps a balanced trailing `)`.

- [ ] **Step 1: Add the helper next to `_LINK_PATTERN` and apply it in `_extract_links`.**

```python
# Sentence punctuation that may wrap a URL in prose; stripped from the tail.
# A closing paren ``)`` is handled separately because it is also a legal URL
# character when it closes an opening paren inside the URL.
_URL_TAIL_PUNCTUATION = set(".,;:!?")


def _trim_url_tail(url: str) -> str:
    """Strip Markdown/prose wrapping from a URL tail, keeping balanced parens.

    A trailing ``)`` belongs to the URL only when it closes a ``(`` opened
    inside the URL — e.g. ``…/Disambiguation_(disambiguation)``.  An unmatched
    ``)`` plus adjacent sentence punctuation (``.,;:!?``) is wrapping and is
    removed.
    """
    while url:
        if url[-1] == ")":
            # Balanced means every ``)`` has an opening ``(`` inside the URL.
            if url.count("(") >= url.count(")"):
                break
        elif url[-1] not in _URL_TAIL_PUNCTUATION:
            break
        url = url[:-1]
    return url


def _extract_links(text: str) -> list[str]:
    """Extract all URLs from *text*.

    Matches both raw URLs (``https?://...``) and Markdown link targets
    (``[label](url)``). URL characters are limited to the RFC 3986 ASCII set,
    excluding adjacent angle brackets, Unicode prose, and fullwidth punctuation.
    A trailing ``)`` is kept only when it closes a ``(`` inside the URL;
    otherwise it and adjacent sentence punctuation are stripped as wrapping.
    Returns a deduplicated, order-preserving list, or an empty list if none exist.

    First replaces each ``[label](url)`` with the bare URL, then extracts
    all ``https?://`` URLs in a single pass — preserving original order.
    """
    # Replace Markdown links [label](url) → url so both are found in one pass
    unified = re.sub(
        r"\[([^\]]*)\]\(((?:https?://)[^\)]+)\)",
        r"\2",
        text,
    )
    # Extract all URLs in order of appearance, trim wrapping, deduplicate
    return list(
        dict.fromkeys(_trim_url_tail(u) for u in _LINK_PATTERN.findall(unified))
    )
```

- [ ] **Step 2: Run the full md_to_image tests.**

Run: `.venv/bin/python -m pytest tests/test_md_to_image.py -q`
Expected: all PASS (the six new tests plus the existing `_extract_links`/`_format_links`/`auto_convert_text` tests).

---

### Task 3: Run repository checks and verify no new failures

**Files:**
- No file changes.

- [ ] **Step 1: Run the required checks.**

Run:
```bash
cd /work/hatsume && .venv/bin/ruff check hatsume/plugins/hatsume-plugin
cd /work/hatsume && npx --no-install pyright
cd /work/hatsume && .venv/bin/python -m pytest tests -q
```

Expected: Ruff and Pyright clean for the changed files. Pytest full suite may show pre-existing, unrelated baseline failures (these are reported, not fixed).

- [ ] **Step 2: Confirm `git status` preserves all unrelated working-tree changes; do not stage, commit, or push.**

Run: `git status --short`
Expected: all pre-existing modified/untracked files remain, plus the new plan file.
