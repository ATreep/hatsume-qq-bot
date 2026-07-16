# Face Emoji Injection + Auto-Create 24h — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Replace the separate `face_choice_agent` LLM call with inline prompt injection into `chat_agent`. (2) Remove auto-create time window so it can trigger at any hour.

**Architecture:** Program-side gate conditions (cooling + random + no image tools used) are checked before `create_agent`. When the gate passes, the `# 表情发送` section (with dynamically-read emotion list from `data/hatsume-plugin/faces/`) is appended to `chat_agent`'s system prompt. The LLM appends `<hatsumeface>emotion</hatsumeface>` at the end of its reply when it wants to send a face. After `ainvoke`, regex extracts the tag; clean text (tag stripped) is sent to users via `ai_answer`; original text (with tag) goes into `AIMessage` for graph state. Face image is then read from disk and sent inline.

**Tech Stack:** Python 3.12+, NoneBot2, LangGraph, LangChain, `re` (stdlib)

## Global Constraints

- Do NOT change the gate conditions (face_cooling_count, random, image-tool flags)
- Do NOT change the face file reading/sending logic (base64 + MessageSegment.image)
- Remove `_maybe_send_face()` entirely — no separate function, logic is inline in `ai_node`
- Remove `FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX`, `FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX`, `build_face_emotion_classifier_prompt()` from prompts.py
- `ai_answer` callback receives clean text (tag stripped); `AIMessage` receives original text (tag preserved)
- Remove `AUTO_CREATE_TIME_START` and `AUTO_CREATE_TIME_END` from config.py
- Simplify `_random_next_trigger()` — just return `now + random(4h, 6h)`, no hour clamping

---

### Task 1: prompts.py — replace face classifier with injection prompt builder

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py:160-180`

**Interfaces:**
- Removes: `FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX`, `FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX`, `build_face_emotion_classifier_prompt(emotions: list[str]) -> str`
- Produces: `build_face_injection_prompt(emotions: list[str]) -> str` — returns empty string if `emotions` is empty, otherwise returns the `# 表情发送` markdown section

- [ ] **Step 1: Remove old face classifier code**

In `hatsume/plugins/hatsume-plugin/prompts.py`, delete lines 160-180:
```python
FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX = (
    "## Role: Classify the emotion of the speaker of the input text. \n"
    "## Output Form: ONLY output between: "
)

FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX = (
    " \n"
    "## Rules: \n"
    "- Output the most relative emotion. \n"
    "- If just no emotion relative, output `general`. Do not guess. \n"
    "- Do not output any other things. "
)


def build_face_emotion_classifier_prompt(emotions: list[str]) -> str:
    """Build the face emotion classifier system prompt with the given emotion list."""
    return (
        FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX
        + ", ".join(emotions + ["general"])
        + FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX
    )
```

- [ ] **Step 2: Add `build_face_injection_prompt` function**

Insert after the `AUXILIARY_COMPACTION_PROMPT` block (after line 158):

```python
def build_face_injection_prompt(emotions: list[str]) -> str:
    """Build the face injection prompt section for chat_agent system prompt.

    Returns empty string if no emotions are available (no face files found).
    Otherwise returns a '# 表情发送' markdown section listing available emotions
    and instructing the LLM to use <hatsumeface>emotion</hatsumeface> tags.
    """
    if not emotions:
        return ""

    emotions_str = "、".join(emotions)
    return (
        "\n\n"
        "# 表情发送\n\n"
        "当前你可以发送一张表情图片来表达情绪。"
        "在回复的最后，插入以下格式的标记来发送表情：\n"
        "<hatsumeface>情绪名</hatsumeface>\n\n"
        f"可选的情绪：{emotions_str}\n\n"
        "只在自然适合的情况下使用。如果不想发送表情，不插入标记即可。"
    )
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "from hatsume.plugins.hatsume_plugin.prompts import build_face_injection_prompt; print(repr(build_face_injection_prompt(['开心','生气'])))"`
Expected: prints the injection prompt string containing `开心、生气`
Run: `python -c "from hatsume.plugins.hatsume_plugin.prompts import build_face_injection_prompt; print(repr(build_face_injection_prompt([])))"`
Expected: prints `''`

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py
git commit -m "feat: replace face emotion classifier prompt with face injection prompt builder

- Remove FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX/SUFFIX and
  build_face_emotion_classifier_prompt()
- Add build_face_injection_prompt(emotions) that builds the # 表情发送 section
- Returns empty string when no emotions available (no face files)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: ai.py — restructure face sending mechanism

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

**Interfaces:**
- Consumes: `build_face_injection_prompt(emotions: list[str]) -> str` from Task 1
- Removes: `_maybe_send_face()` function (lines 433-472)
- Produces: inline face injection + tag extraction + face sending in `ai_node`

- [ ] **Step 1: Update imports (lines 1-26)**

Add `import re` after `import traceback` (line 9):
```python
import re
```

Replace `build_face_emotion_classifier_prompt` with `build_face_injection_prompt` in the prompts import block (line 22):
```python
from ...prompts import (
    AUXILIARY_COMPACTION_PROMPT,
    build_face_injection_prompt,
    build_memory_context_prompt,
    build_skill_prompt,
    role_sys_prompt,
)
```

- [ ] **Step 2: Add FACE_TAG_PATTERN constant (after TIMER_MARK, line 54)**

```python
FACE_TAG_PATTERN = re.compile(r"<hatsumeface>(.*?)</hatsumeface>")
```

- [ ] **Step 3: Move gate check before create_agent, add face injection**

Replace the `create_agent` call block (lines 356-364) and the old gate block (lines 417-426) with the new gate + injection logic that runs BEFORE `create_agent`.

Specifically: After the skill injection block (line 354 `print(f"[skills] ...")`), insert the face injection gate, then `create_agent`:

```python
    # Inject available skills into system prompt
    skill_mgr = get_skill_manager()
    skill_list = skill_mgr.list_skills()
    skill_prompt = build_skill_prompt(skill_list)
    if skill_prompt:
        sys_prompt += skill_prompt
        print(f"[skills] Injected {len(skill_list)} skill(s) into system prompt")

    # ── Face injection gate ──
    from ..tools import _capture_html_shot_used as _cap_used, _generate_image_used as _gen_used

    global _face_cooling_count
    _face_cooling_count += 1
    _face_allowed = (
        not _cap_used
        and not _gen_used
        and random.randint(0, 1) == 0
        and _face_cooling_count >= 1
    )
    _face_dict: dict[str, list[str]] = {}
    if _face_allowed:
        face_list = [
            f.name
            for f in store.get_plugin_data_file("faces").iterdir()
            if f.is_file() and f.name.lower().endswith((".png", ".jpg", ".jpeg"))
        ]
        if face_list:
            for fname in face_list:
                emotion = fname.split("_")[0]
                _face_dict.setdefault(emotion, []).append(fname)
            emotions = list(_face_dict.keys())
            face_prompt = build_face_injection_prompt(emotions)
            if face_prompt:
                sys_prompt += face_prompt
                print(f"[face] Injected face prompt with {len(emotions)} emotions")
        _face_cooling_count = 0

    chat_agent = create_agent(
        model_chosen,
        [search_web, shell_executor, find_memory, capture_html_shot,
         generate_image, send_image, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch,
         agent_allocate, check_agent, respond_to_shell_prompt],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 4: Add tag extraction after ai_text, send clean text to user**

Replace the sending block (lines 399-413) with tag-aware logic that sends `ai_text_clean` and preserves `ai_text` in transcript:

```python
    # ── Extract face tag from ai_text ──
    face_emotion: str | None = None
    ai_text_clean = ai_text
    match = FACE_TAG_PATTERN.search(ai_text)
    if match:
        face_emotion = match.group(1).strip()
        ai_text_clean = FACE_TAG_PATTERN.sub("", ai_text).strip()
        print(f"[face] Detected face tag: {face_emotion}")

    ai_msg = MessageSegment.text(ai_text_clean)
    if notified_uid is not None and notified_uid != 0:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, notified_uid)
            print(f"🧩 [ai_node] Sent agent result via ai_answer_with_at to user {notified_uid}")
    elif timer_uid is not None:
        at_callback = _state.ai_answer_with_at if _state else None
        if at_callback:
            await at_callback(ai_msg, timer_uid)
            print(f"⏰ [ai_node] Sent timer result via ai_answer_with_at to user {timer_uid}")
    else:
        _ai_answer = _get_ai_answer()
        if _ai_answer:
            await _ai_answer(ai_msg)

    _memory_record_transcript.append({"type": "text", "text": "你: " + ai_text})
```

- [ ] **Step 5: Replace old gate block with inline face sending**

Replace lines 417-426 (the old `_face_cooling_count += 1` / gate / `_maybe_send_face` block) with face sending that uses the already-extracted `face_emotion` and `_face_dict`:

```python
    from ..tools import _last_capture_html_demand
    if _cap_used and _last_capture_html_demand:
        _memory_record_transcript.append(
            {"type": "text", "text": "你发送了一张关于以下内容的富文本渲染图片:\n" + _last_capture_html_demand}
        )

    # ── Send face image if tag matched a valid emotion ──
    _ai_answer_cb = _get_ai_answer()
    if face_emotion and _face_dict.get(face_emotion) and _ai_answer_cb:
        face_filename = random.choice(_face_dict[face_emotion])
        print(f"[face] Send face: {face_filename}")
        face_path = str(store.get_plugin_data_file("faces").absolute()) + "/" + face_filename
        with open(face_path, "rb") as f:
            base64_str = base64.b64encode(f.read()).decode("utf-8")
        face_msg = MessageSegment.image("base64://" + base64_str, cache=False)
        await _ai_answer_cb(face_msg)
```

Note: The lazy import now only needs `_last_capture_html_demand` since `_cap_used` and `_gen_used` were already imported in Step 3.

- [ ] **Step 6: Remove `_maybe_send_face` function**

Delete the entire `_maybe_send_face` function (lines 433-472):
```python
async def _maybe_send_face(ai_text: str) -> None:
    ...
```

- [ ] **Step 7: Verify the return statement**

The return at the end of `ai_node` should remain:
```python
    return {"messages": [AIMessage(ai_text)]}
```
This uses the original `ai_text` (with tag preserved) — no change needed.

- [ ] **Step 8: Verify syntax**

Run: `python -c "from hatsume.plugins.hatsume_plugin.graph.nodes import ai"`
Expected: no ImportError or SyntaxError

- [ ] **Step 9: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: inline face injection into chat_agent, remove separate face_choice_agent

- Gate conditions checked before create_agent; face prompt injected into sys_prompt
- Regex extracts <hatsumeface>emotion</hatsumeface> from ai_text
- Clean text (tag stripped) sent to user via ai_answer
- Original ai_text (with tag) preserved in AIMessage for graph state
- Remove _maybe_send_face() — face sending logic now inline in ai_node

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Update tests for new face mechanism

**Files:**
- Modify: `tests/test_graph_nodes.py:246,895-1006`

**Interfaces:**
- Consumes: `build_face_injection_prompt` from Task 1, new `ai_node` logic from Task 2

- [ ] **Step 1: Update mock for new prompt function (line 246)**

Replace:
```python
    prompts_pkg.build_face_emotion_classifier_prompt = lambda emotions: f"Classify emotion from: {emotions}"
```
with:
```python
    prompts_pkg.build_face_injection_prompt = lambda emotions: (
        "\n\n# 表情发送\n\n可选的情绪：" + "、".join(emotions)
        if emotions else ""
    )
```

- [ ] **Step 2: Replace `test_generate_image_used_skips_maybe_send_face` with `test_generate_image_used_skips_face_injection`**

Delete lines 895-951 and replace with:

```python
# -----------------------------------------------------------------------
# Feature: generate_image_used flag skips face injection
# -----------------------------------------------------------------------


def test_generate_image_used_skips_face_injection():
    """When _generate_image_used is True, face injection prompt should NOT be
    added to chat_agent's system_prompt."""
    nodes = _load_nodes_module()

    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod._generate_image_used = True
    tools_mod._capture_html_shot_used = False
    tools_mod._last_capture_html = ""

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    # Track the system_prompt passed to create_agent
    sys_prompts: list[str] = []

    class _FakeAgent:
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="hello", type="ai")]}

    original_create_agent = nodes._ai.create_agent
    def _tracking_create_agent(model, tools, system_prompt=None, **kw):
        sys_prompts.append(system_prompt or "")
        return _FakeAgent()
    nodes._ai.create_agent = _tracking_create_agent

    # Force random to return 0 (so face WOULD be injected if not for the flag)
    original_randint = random.randint
    random.randint = lambda a, b: 0

    # Set _face_cooling_count high enough to pass the >= 1 check
    nodes._ai._face_cooling_count = 2

    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )
        assert len(sys_prompts) == 1, "create_agent should be called exactly once"
        assert "# 表情发送" not in sys_prompts[0], (
            "face injection should NOT be in sys_prompt when _generate_image_used is True"
        )
    finally:
        nodes._ai.create_agent = original_create_agent
        random.randint = original_randint
        tools_mod._generate_image_used = False
```

- [ ] **Step 3: Replace `test_face_can_be_called_when_both_flags_false` with `test_face_injection_when_flags_false`**

Delete lines 954-1006 and replace with:

```python
def test_face_injection_when_flags_false():
    """When both _generate_image_used and _capture_html_shot_used are False,
    face injection prompt should be added to chat_agent's system_prompt."""
    import tempfile

    nodes = _load_nodes_module()

    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod._generate_image_used = False
    tools_mod._capture_html_shot_used = False
    tools_mod._last_capture_html = ""

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=None,
    )
    nodes.bind_state(mock_state)

    # Create temp dir with fake face files so the gate proceeds to injection
    tmpdir = tempfile.TemporaryDirectory()
    face_dir = Path(tmpdir.name)
    (face_dir / "开心_0.png").touch()
    (face_dir / "生气_0.png").touch()

    # Replace localstore mock to return our temp dir
    original_get_data = nodes._ai.store.get_plugin_data_file
    def _mock_get_data(name):
        return types.SimpleNamespace(
            iterdir=lambda: list(face_dir.iterdir()),
            absolute=lambda: face_dir,
        )
    nodes._ai.store.get_plugin_data_file = _mock_get_data

    # Track the system_prompt passed to create_agent
    sys_prompts: list[str] = []

    class _FakeAgent:
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content="hello", type="ai")]}

    original_create_agent = nodes._ai.create_agent
    def _tracking_create_agent(model, tools, system_prompt=None, **kw):
        sys_prompts.append(system_prompt or "")
        return _FakeAgent()
    nodes._ai.create_agent = _tracking_create_agent

    # Force random to return 0 (so face WILL be injected)
    original_randint = random.randint
    random.randint = lambda a, b: 0

    # Set _face_cooling_count high enough to pass the >= 1 check
    nodes._ai._face_cooling_count = 2

    try:
        asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )
        assert len(sys_prompts) == 1, "create_agent should be called exactly once"
        assert "# 表情发送" in sys_prompts[0], (
            "face injection should be in sys_prompt when both flags are False"
        )
        assert "开心" in sys_prompts[0], (
            "face injection should list available emotions"
        )
    finally:
        nodes._ai.create_agent = original_create_agent
        random.randint = original_randint
        nodes._ai.store.get_plugin_data_file = original_get_data
        tmpdir.cleanup()
```

- [ ] **Step 4: Add test for face tag extraction — clean text to user, tag preserved in AIMessage**

Insert after the test from Step 3:

```python
def test_face_tag_stripped_from_user_text_preserved_in_aimessage():
    """<hatsumeface> tag should be stripped from user-facing text but preserved
    in AIMessage for graph state history."""
    nodes = _load_nodes_module()

    tools_mod = sys.modules["hatsume.plugins.hatsume-plugin.graph.tools"]
    tools_mod._generate_image_used = False
    tools_mod._capture_html_shot_used = False
    tools_mod._last_capture_html = ""

    sent_messages: list = []

    async def _mock_send(msg):
        sent_messages.append(msg)

    mock_state = types.SimpleNamespace(
        human_queue=[],
        human_source_queue=[],
        is_graph_running=True,
        current_query_user_id=None,
        ai_answer=_mock_send,
        ai_answer_with_at=None,
    )
    nodes.bind_state(mock_state)

    # AI response includes a face tag
    ai_response = "今天天气真好呀，心情不错呢<hatsumeface>开心</hatsumeface>"

    class _FakeAgent:
        async def ainvoke(self, *a, **kw):
            return {"messages": [types.SimpleNamespace(content=ai_response, type="ai")]}

    original_create_agent = nodes._ai.create_agent
    nodes._ai.create_agent = lambda *a, **kw: _FakeAgent()

    # Force random to return 0
    original_randint = random.randint
    random.randint = lambda a, b: 0

    # Set cooling count high enough
    nodes._ai._face_cooling_count = 2

    try:
        result = asyncio.run(
            nodes.ai_node(
                {"messages": [types.SimpleNamespace(content="hello", type="human")]}
            )
        )

        # AIMessage should preserve the face tag
        aimessage = result["messages"][0]
        assert "<hatsumeface>开心</hatsumeface>" in aimessage.content, (
            "AIMessage should preserve the face tag for graph state history"
        )

        # User-facing text should NOT contain the face tag
        assert len(sent_messages) >= 1, "at least the text message should be sent"
        text_msg = sent_messages[0]
        assert text_msg.type == "text"
        assert "<hatsumeface>" not in text_msg.data["text"], (
            "Sent text should not contain face tag"
        )
        assert "今天天气真好呀" in text_msg.data["text"], (
            "Sent text should contain the message content without the tag"
        )
    finally:
        nodes._ai.create_agent = original_create_agent
        random.randint = original_randint
```

- [ ] **Step 5: Run all face-related tests**

Run: `pytest tests/test_graph_nodes.py -k "face" -xvs`
Expected: all 3 face tests PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -xvs`
Expected: all tests PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add tests/test_graph_nodes.py
git commit -m "test: update face tests for inline injection mechanism

- Replace build_face_emotion_classifier_prompt mock with build_face_injection_prompt
- test_generate_image_used_skips_face_injection: verify no face prompt in sys_prompt
- test_face_injection_when_flags_false: verify face prompt IS in sys_prompt
- test_face_tag_stripped_from_user_text_preserved_in_aimessage: verify tag extraction

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Remove auto-create time window

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/config.py:116-118`
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py:15-17,93-138`

**Interfaces:**
- Removes: `AUTO_CREATE_TIME_START`, `AUTO_CREATE_TIME_END` from config
- Simplifies: `_random_next_trigger()` — just returns `now + random(4h, 6h)` timestamp, no hour clamping

- [ ] **Step 1: Remove time constants from config.py**

In `hatsume/plugins/hatsume-plugin/config.py`, delete lines 117-118:
```python
AUTO_CREATE_TIME_START: int = 7    
AUTO_CREATE_TIME_END: int = 22    
```

- [ ] **Step 2: Remove imports of time constants in executor.py**

In `hatsume/plugins/hatsume-plugin/timer/executor.py`, remove `AUTO_CREATE_TIME_START` and `AUTO_CREATE_TIME_END` from the config import block (lines 15-17).

Before:
```python
from ..config import (
    AUTO_CREATE_GROUP_ID,
    AUTO_CREATE_TIME_START,
    AUTO_CREATE_TIME_END,
)
```

After:
```python
from ..config import AUTO_CREATE_GROUP_ID
```

- [ ] **Step 3: Simplify `_random_next_trigger()`**

Replace the entire `_random_next_trigger()` function (lines 93-138) with:

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

- [ ] **Step 4: Update docstring in `reschedule_auto_create`**

In `reschedule_auto_create()` (line 170-172), update docstring from `[now+4h, now+8h] clamped to the valid daily window` to `[now+4h, now+6h]`.

- [ ] **Step 5: Verify syntax**

Run: `python -c "from hatsume.plugins.hatsume_plugin.timer.executor import _random_next_trigger; print(_random_next_trigger())"`
Expected: prints a future Unix timestamp (no error)

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/ -xvs`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/config.py hatsume/plugins/hatsume-plugin/timer/executor.py
git commit -m "feat: remove auto-create time window, allow triggering at any hour

- Remove AUTO_CREATE_TIME_START and AUTO_CREATE_TIME_END from config
- Simplify _random_next_trigger() to just return now + random(4h, 6h)
- No more hour clamping / next-day wrapping

Co-Authored-By: Claude <noreply@anthropic.com>"
```
