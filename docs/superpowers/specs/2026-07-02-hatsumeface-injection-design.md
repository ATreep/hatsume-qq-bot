# Face Emoji Injection + Auto-Create 24h — Design Spec

**Date**: 2026-07-02
**Status**: approved

---

## Feature 1: Face Emoji Injection

### Motivation

Current face-sending mechanism invokes a separate `face_choice_agent` (advance model, no thinking) to classify the emotion of the AI's reply text, then randomly picks a matching face image to send. This costs an extra LLM round-trip per face send.

The new approach injects a face-selection prompt into `chat_agent`'s system prompt when conditions allow, so the LLM selects the emotion inline with its reply — no second model invocation.

### Flow

```
ai_node
  ├─ query memory                    (unchanged)
  ├─ build sys_prompt                (unchanged)
  ├─ [gate] conditions met?
  │     ├─ yes → sys_prompt += build_face_injection_prompt(available_emotions)
  │     └─ no  → skip
  ├─ create_agent(model, tools, system_prompt=sys_prompt)
  ├─ chat_agent.ainvoke(...) → ai_text
  ├─ regex extract <hatsumeface>emotion</hatsumeface>
  │     └─ ai_text_clean = strip tag
  ├─ ai_answer(ai_text_clean)        ← user sees clean text
  ├─ return AIMessage(ai_text)       ← graph state keeps the tag (LLM sees history with tags)
  └─ [if valid emotion] → random pick face → ai_answer(face image)
```

### Gate conditions (unchanged from current behavior)

```python
_face_cooling_count += 1
face_allowed = (
    not _cap_used
    and not _gen_used
    and random.randint(0, 1) == 0
    and _face_cooling_count >= 1
)
if face_allowed:
    # inject face prompt before create_agent
    _face_cooling_count = 0
```

### Face injection prompt

Dynamically built from scanned face files. Appended as a `# 表情发送` section at the end of system prompt:

```markdown
# 表情发送

当前你可以发送一张表情图片来表达情绪。在回复的最后，插入以下格式的标记来发送表情：
<hatsumeface>情绪名</hatsumeface>

可选的情绪：开心、生气、害羞、伤心、惊讶、喜欢、疑惑、无语、无聊

只在自然适合的情况下使用。如果不想发送表情，不插入标记即可。
```

The emotion list is dynamically generated from files in `data/hatsume-plugin/faces/` (split by first `_`).

### Tag extraction

```python
import re
FACE_TAG_PATTERN = re.compile(r"<hatsumeface>(.*?)</hatsumeface>")

match = FACE_TAG_PATTERN.search(ai_text)
if match:
    emotion = match.group(1).strip()
    ai_text_clean = FACE_TAG_PATTERN.sub("", ai_text).strip()
else:
    emotion = None
    ai_text_clean = ai_text
```

### Face image selection and sending (logic preserved from `_maybe_send_face`)

1. Look up `face_dict[emotion]` — if exists, `random.choice()` one file
2. Read file, base64-encode, send via `MessageSegment.image("base64://...")`
3. If emotion not found in dict → silent skip

## Files changed

### `prompts.py`

| Change | Detail |
|--------|--------|
| **Remove** | `FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX`, `FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX`, `build_face_emotion_classifier_prompt()` |
| **Add** | `build_face_injection_prompt(emotions: list[str]) -> str` — builds the `# 表情发送` section |

### `graph/nodes/ai.py`

| Change | Detail |
|--------|--------|
| **Remove** | `_maybe_send_face()` entire function |
| **Add import** | `build_face_injection_prompt` from prompts |
| **Add import** | `re` (standard library) |
| **Add constant** | `FACE_TAG_PATTERN` regex |
| **Modify** | `ai_node`: gate check before `create_agent`, tag extraction after `ainvoke`, face send inline |
| **Modify** | `ai_node` return: use `ai_text` (with tag) for `AIMessage`, but `ai_text_clean` for `ai_answer` callback |

### No changes

- `config.py` — no face-related constants
- `state.py` — no changes needed (`face_cooling_count` read from global, not state field)
- `graph/tools.py` — no face-related code
- `handlers/chat.py` — no changes (uses same `ai_answer` callback)
- `handlers/commands.py` — no changes

## Edge cases

| Case | Behavior |
|------|----------|
| No face files in directory | `face_allowed` gate stays False (emotion list empty → no injection) |
| LLM outputs unknown emotion | Tag extracted but `face_dict` lookup fails → silent skip, text already sent clean |
| LLM outputs multiple tags | Only first match used; all tags stripped from user-facing text |
| LLM outputs no tag | `ai_text_clean == ai_text`, no face sent — normal behavior |
| Tag malformed (e.g. unclosed) | Regex won't match → treated as no tag → normal text sent |
| Conditions not met | No injection, no tag expected, no face sent — identical to current behavior |

---

## Feature 2: Remove Auto-Create Time Window

### Motivation

`_random_next_trigger()` currently clamps the random trigger time to the `AUTO_CREATE_TIME_START`(7) – `AUTO_CREATE_TIME_END`(22) window (UTC+8). Times outside this window wrap to the next day. This prevents auto-create from firing during nighttime hours.

Remove this restriction so auto-create can trigger at any hour of the day.

### Changes

#### `config.py`

| Change | Detail |
|--------|--------|
| **Remove** | `AUTO_CREATE_TIME_START: int = 7` |
| **Remove** | `AUTO_CREATE_TIME_END: int = 22` |

#### `timer/executor.py`

| Change | Detail |
|--------|--------|
| **Remove import** | `AUTO_CREATE_TIME_START`, `AUTO_CREATE_TIME_END` |
| **Simplify** | `_random_next_trigger()` — remove hour-clamping logic, return random `now+4h..+6h` directly |

### Simplified `_random_next_trigger()`

```python
def _random_next_trigger() -> float:
    """Generate a random trigger time in [now+4h, now+6h].

    Returns a Unix timestamp (float).
    """
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    delta_seconds = random.uniform(4 * 3600, 6 * 3600)
    t = now + timedelta(seconds=delta_seconds)
    return t.timestamp()
```

### No changes

- `timer/store.py` — `upsert_auto_create` / `get_auto_create` unaffected
- `timer/__init__.py` — `refresh_auto_create()` unaffected
- `handlers/commands.py` — `/timer autocreate` and `handle_autocreate` unaffected
- `handlers/commands.py` — `display_next_autocreate` reads trigger time from DB, unaffected
