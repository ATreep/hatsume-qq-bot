# Secret Key Hiding Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `mask_secret_keys()` utility that detects and masks API keys (sk-*, ghp-*, ark-*, etc.) in outbound messages across all 4 send paths, preventing accidental key leakage into QQ chat.

**Architecture:** A single pure function in `utils.py` with a list of regex patterns. Called from `handle_ai_message()` (Path 1) and each `_send_to_group` closure (Paths 2-4) before the message hits the wire. Preserves key prefix, replaces body with `xxx...xxx`. Silent fallback on error.

**Tech Stack:** Python 3.12+ stdlib `re`, pytest

## Global Constraints

- Python 3.12+ with `from __future__ import annotations`
- Follow existing project conventions: `snake_case`, `UPPER_CASE` for module-level constants
- Use `print()` for debug logging (consistent with existing codebase)
- Never block message delivery — all errors silently return original text
- Preserve key prefix; mask only the secret body

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `hatsume/plugins/hatsume-plugin/utils.py` | Modify | Add `mask_secret_keys()` and `_SECRET_KEY_PATTERNS` |
| `hatsume/plugins/hatsume-plugin/handlers/chat.py` | Modify | 3 integration points (handle_ai_message + 2 _send_to_group closures) |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Modify | 1 integration point (_start_direct_conv _send_to_group) |
| `tests/test_secret_gate.py` | Create | Unit tests for mask_secret_keys() |

---

### Task 1: Core function + unit tests

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/utils.py` (append at end)
- Create: `tests/test_secret_gate.py`

**Interfaces:**
- Produces: `mask_secret_keys(text: str) -> str` — pure function, takes string, returns masked string
- Produces: `_SECRET_KEY_PATTERNS: list[tuple[str, str]]` — module-level constant, list of (regex, label) pairs

- [ ] **Step 1: Write the failing tests**

Create `tests/test_secret_gate.py`:

```python
"""Tests for secret key masking gate."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTILS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/utils.py"

# Import mask_secret_keys via importlib to avoid package dependency issues
import importlib.util
spec = importlib.util.spec_from_file_location("utils", UTILS_PATH)
utils = importlib.util.module_from_spec(spec)
sys.modules["utils"] = utils
spec.loader.exec_module(utils)
mask_secret_keys = utils.mask_secret_keys


class TestMaskSecretKeys:
    """Tests for mask_secret_keys function."""

    # ---- OpenAI / Anthropic keys ----

    def test_masks_sk_ant_key(self):
        result = mask_secret_keys("My key is sk-ant-api03-abc123def456ghi789jkl012")
        assert "sk-ant-api03-xxx...xxx" in result
        assert "abc123def456ghi789jkl012" not in result

    def test_masks_sk_basic_key(self):
        result = mask_secret_keys("Use sk-abcdefghijklmnopqrstuvwxyz123456 for auth")
        assert "sk-xxx...xxx" in result
        assert "abcdefghijklmnopqrstuvwxyz123456" not in result

    # ---- GitHub tokens ----

    def test_masks_ghp_key(self):
        result = mask_secret_keys("token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890")
        assert "ghp_xxx...xxx" in result
        assert "aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in result

    def test_masks_gho_key(self):
        result = mask_secret_keys("oauth: gho_1234567890abcdefghijklmnopqrstuv")
        assert "gho_xxx...xxx" in result

    def test_masks_ghu_key(self):
        result = mask_secret_keys("user: ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
        assert "ghu_xxx...xxx" in result

    def test_masks_github_pat_key(self):
        result = mask_secret_keys("pat: github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")
        assert "github_pat_xxx...xxx" in result

    # ---- Volcengine Ark ----

    def test_masks_ark_key(self):
        result = mask_secret_keys("secret: ark-abc123def456ghi789jkl012mno345pqr678")
        assert "ark-xxx...xxx" in result
        assert "abc123def456ghi789jkl012mno345pqr678" not in result

    # ---- Generic access key ----

    def test_masks_ak_key(self):
        result = mask_secret_keys("access: ak-1234567890abcdefghijklmnopqrstuv")
        assert "ak-xxx...xxx" in result

    # ---- Multiple keys in one message ----

    def test_masks_multiple_keys(self):
        result = mask_secret_keys(
            "Keys: sk-ant-api03-aaa111bbb222ccc333ddd444eee555 "
            "and ghp_XXX111YYY222ZZZ333WWW444VVV555UUU666"
        )
        assert "sk-ant-api03-xxx...xxx" in result
        assert "ghp_xxx...xxx" in result
        assert "aaa111bbb222ccc333ddd444eee555" not in result
        assert "XXX111YYY222ZZZ333WWW444VVV555UUU666" not in result

    # ---- No false positives ----

    def test_no_mask_on_normal_text(self):
        text = "Hello! How are you today? Let's discuss the project."
        assert mask_secret_keys(text) == text

    def test_no_mask_on_short_prefix_match(self):
        """Keys shorter than 20 body chars should not be masked (too short to be real keys)."""
        text = "the sk- short one"  # "short" is only 5 chars after sk-
        assert mask_secret_keys(text) == text

    def test_no_mask_on_sk_without_enough_chars(self):
        text = "sk-tooshort"  # only 8 chars after sk-
        assert mask_secret_keys(text) == text

    # ---- Edge cases ----

    def test_empty_string(self):
        assert mask_secret_keys("") == ""

    def test_key_at_start_of_string(self):
        result = mask_secret_keys("sk-ant-api03-abc123def456ghi789jkl012mno345 is my key")
        assert result.startswith("sk-ant-api03-xxx...xxx")

    def test_key_at_end_of_string(self):
        result = mask_secret_keys("My key is ark-abc123def456ghi789jkl012mno345")
        assert result.endswith("ark-xxx...xxx")

    def test_key_with_hyphens_in_body(self):
        """Keys with hyphens in the body (like Anthropic keys)."""
        result = mask_secret_keys("sk-ant-api03-abc-def-ghi-jkl-mno-pqr-stu-vwx-yz0")
        assert "sk-ant-api03-xxx...xxx" in result

    def test_key_with_underscores_in_body(self):
        """GitHub tokens have underscores as prefix separator."""
        result = mask_secret_keys("ghp_abc123def456ghi789jkl012mno345pqr678stu")
        assert "ghp_xxx...xxx" in result

    def test_mixed_content_with_code_blocks(self):
        text = """Here is a config:
        API_KEY=sk-ant-api03-abc123def456ghi789jkl
        export GITHUB_TOKEN=ghp_secret1234567890abcdefgh
        """
        result = mask_secret_keys(text)
        assert "sk-ant-api03-xxx...xxx" in result
        assert "ghp_xxx...xxx" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/hatsume && python -m pytest tests/test_secret_gate.py -v
```

Expected: All tests FAIL with `AttributeError: module 'utils' has no attribute 'mask_secret_keys'`

- [ ] **Step 3: Implement `mask_secret_keys()` in utils.py**

Append this code to the end of `hatsume/plugins/hatsume-plugin/utils.py` (after the existing code, before any trailing blank lines):

```python

# ---------------------------------------------------------------------------
# Secret key masking gate
# ---------------------------------------------------------------------------
import re as _re

_SECRET_KEY_PATTERNS: list[tuple[str, str]] = [
    # (regex pattern, label for debug logging)
    # Pattern captures the prefix in group 1; body is matched but not captured
    (r'(sk-(?:ant(?:-api\d{2})?-)?)[A-Za-z0-9_\-]{20,}', "sk-*"),
    (r'(gh[opu]_|github_pat_)[A-Za-z0-9_]{20,}', "gh*_*"),
    (r'(ark-)[A-Za-z0-9_\-]{20,}', "ark-*"),
    (r'(ak-)[A-Za-z0-9_\-]{20,}', "ak-*"),
]


def mask_secret_keys(text: str) -> str:
    """Detect and mask API keys in text. Preserves key prefix, masks secret body.

    Returns the masked string, or the original string if no keys are detected
    or if an error occurs during processing (never raises).
    """
    try:
        for pattern, label in _SECRET_KEY_PATTERNS:
            compiled = _re.compile(pattern)
            if compiled.search(text):
                text = compiled.sub(r"\1xxx...xxx", text)
                print(f"🔑 [secret-gate] masked potential key matching {label}")
        return text
    except Exception:
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /path/to/hatsume && python -m pytest tests/test_secret_gate.py -v
```

Expected: All 18 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /path/to/hatsume
git add hatsume/plugins/hatsume-plugin/utils.py tests/test_secret_gate.py
git commit -m "feat: add secret key masking gate utility

Add mask_secret_keys() to utils.py with regex patterns for
OpenAI/Anthropic, GitHub, Volcengine Ark, and generic access keys.
Preserves key prefix, masks body with xxx...xxx.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Integrate into handle_ai_message (Path 1)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py:193-224`

**Interfaces:**
- Consumes: `mask_secret_keys(text: str) -> str` from `..utils`

- [ ] **Step 1: Add import**

At the top of `chat.py` (line 24), add `mask_secret_keys` to the utils import. The current import at line 24 is:

```python
from .pipeline import get_human_message
```

Add a new import line for `mask_secret_keys` alongside the existing `..utils` usages. Since `utils` functions are currently imported inline (e.g., `from ..utils import get_group_member_name` inside `pipeline.py`), add this import inside `handle_ai_message` or at the top. Check: `chat.py` does NOT currently import from `..utils` at module level. The cleanest approach is to add the import at the top:

After line 24 (`from .pipeline import get_human_message`), insert:

```python
from ..utils import mask_secret_keys
```

- [ ] **Step 2: Add mask call in handle_ai_message**

In `handle_ai_message()` at line 212, the condition `if not (isinstance(msg, str) and msg.strip() == ""):` guards the send block. Insert the mask call immediately after this condition check, before the send attempt:

Current code (lines 212-217):
```python
    if not (isinstance(msg, str) and msg.strip() == ""):
        try:
            if at_id:
                await matcher.send(MessageSegment.at(at_id) + " " + msg)
            else:
                await matcher.send(msg)
```

Replace with:
```python
    if not (isinstance(msg, str) and msg.strip() == ""):
        if isinstance(msg, str):
            msg = mask_secret_keys(msg)
        try:
            if at_id:
                await matcher.send(MessageSegment.at(at_id) + " " + msg)
            else:
                await matcher.send(msg)
```

- [ ] **Step 3: Verify existing tests still pass**

```bash
cd /path/to/hatsume && python -m pytest tests/test_chat_send.py tests/test_secret_gate.py -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume
git add hatsume/plugins/hatsume-plugin/handlers/chat.py
git commit -m "feat: integrate secret key gate into handle_ai_message

Apply mask_secret_keys() to string messages before sending in the
normal user chat path (Path 1).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Integrate into _start_conv_for_agent _send_to_group (Path 2)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py:46-56`

**Interfaces:**
- Consumes: `mask_secret_keys(text: str) -> str` from `..utils` (already imported in Task 2)

- [ ] **Step 1: Add mask call in agent _send_to_group**

In `_start_conv_for_agent`, the `_send_to_group` closure at lines 46-56. Current code:

```python
    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = str(msg)
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")
```

Replace with:

```python
    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = mask_secret_keys(str(msg))
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
cd /path/to/hatsume && python -m pytest tests/test_secret_gate.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume
git add hatsume/plugins/hatsume-plugin/handlers/chat.py
git commit -m "feat: integrate secret key gate into agent _send_to_group

Apply mask_secret_keys() in the agent notification send path (Path 2).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Integrate into _start_conv_for_timer _send_to_group (Path 3)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/chat.py:87-97`

- [ ] **Step 1: Add mask call in timer _send_to_group**

Same change as Task 3. Current code at lines 87-97:

```python
    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = str(msg)
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")
```

Replace with:

```python
    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = mask_secret_keys(str(msg))
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
cd /path/to/hatsume && python -m pytest tests/test_secret_gate.py -v
```

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd /path/to/hatsume
git add hatsume/plugins/hatsume-plugin/handlers/chat.py
git commit -m "feat: integrate secret key gate into timer _send_to_group

Apply mask_secret_keys() in the timer notification send path (Path 3).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Integrate into _start_direct_conv _send_to_group (Path 4)

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py:214-224`

**Interfaces:**
- Consumes: `mask_secret_keys(text: str) -> str` — import from `..utils` equivalent. Since this file is at `graph/nodes/ai.py`, the relative import is `from ...utils import mask_secret_keys`. However, this file also imports from `...handlers.chat` at line 209 (`from ...handlers.chat import conv_state, start_new_conversation`). We can either add the `mask_secret_keys` import alongside that, or import at the top of the file.

- [ ] **Step 1: Add import to ai.py**

Check if `ai.py` already has a top-level import section. If it imports from `..utils` elsewhere, add there. Otherwise, add the import inside `_start_direct_conv` alongside the existing lazy import at line 209:

Current line 209:
```python
    from ...handlers.chat import conv_state, start_new_conversation
```

Replace with:
```python
    from ...handlers.chat import conv_state, start_new_conversation
    from ...utils import mask_secret_keys
```

- [ ] **Step 2: Add mask call in direct conv _send_to_group**

Current code at lines 214-224:

```python
    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = str(msg)
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")
```

Replace with:

```python
    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = mask_secret_keys(str(msg))
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")
```

- [ ] **Step 3: Verify all tests pass**

```bash
cd /path/to/hatsume && python -m pytest tests/test_secret_gate.py -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd /path/to/hatsume
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: integrate secret key gate into direct conv _send_to_group

Apply mask_secret_keys() in the direct conversation send path (Path 4).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /path/to/hatsume && python -m pytest tests/test_secret_gate.py tests/test_chat_send.py tests/test_graph_nodes.py -v
```

Expected: All tests PASS, no regressions

- [ ] **Step 2: Run ruff lint check**

```bash
cd /path/to/hatsume && ruff check hatsume/plugins/hatsume-plugin/utils.py hatsume/plugins/hatsume-plugin/handlers/chat.py hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
```

Expected: No lint errors

- [ ] **Step 3: Manual smoke test verification**

Run the bot and send a test message containing a fake key:
```
My API key is sk-ant-api03-abc123def456ghi789jkl012mno345pqr678stu
```

Expected: The message appears in QQ with the key masked as `sk-ant-api03-xxx...xxx`

- [ ] **Step 4: Commit any final changes**

```bash
cd /path/to/hatsume
git add -A
git commit -m "chore: final verification of secret key hiding gate

All tests pass, lint clean.

Co-Authored-By: Claude <noreply@anthropic.com>"
```
