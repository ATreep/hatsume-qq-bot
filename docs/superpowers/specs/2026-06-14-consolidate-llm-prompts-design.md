# Consolidate All LLM Prompts into `prompts.py`

**Date:** 2026-06-14
**Status:** Design Approved

## Motivation

LLM prompts are currently scattered across 8 files. Consolidating them into `prompts.py` provides a single source of truth, makes prompts easier to find, review, and maintain, and reduces duplication risk.

## Design

### Organization

Prompts are grouped into 5 sections, all appended after the existing `build_skill_prompt()` in `prompts.py`:

```
prompts.py
├── [EXISTING] role_sys_prompt          — Main character role (~110 lines)
├── [EXISTING] build_skill_prompt()     — Skill list injection
│
├── NEW: Graph Node Prompts
│   ├── AUXILIARY_COMPACTION_PROMPT       — Auxiliary message compaction (from ai.py)
│   ├── FACE_EMOTION_CLASSIFIER_PROMPT     — Face image emotion classifier (from ai.py)
│   ├── CHAT_END_DETECT_PROMPT             — Conversation end detection (from detect.py)
│   ├── MEMORY_RECORDING_PROMPT            — Long-term memory recording (from finish.py)
│   └── build_memory_context_prompt()      — Memory context injection (from ai.py)
│
├── NEW: Tool Prompts
│   ├── WEB_BROWSER_AGENT_PROMPT           — Web browser agent (from tools.py)
│   ├── HTML_GENERATION_PROMPT             — HTML generation (from tools.py)
│   ├── build_web_result_rephrase_prompt() — Web result rephrasing (from tools.py)
│   ├── build_video_failure_prompt()       — Video generation failure (from tools.py)
│   └── build_video_success_prompt()       — Video generation success (from tools.py)
│
├── NEW: Feature Prompts
│   ├── NIGHT_COMIC_STORY_PROMPT           — Night comic story generation
│   ├── build_night_comic_image_prompt()   — Night comic image prompt
│   ├── build_like_failure_prompt()        — Like failure message
│   └── build_like_success_prompt()        — Like success message
│
└── NEW: Timer Prompts
    ├── build_timer_system_prompt()        — Timer task wrapper
    ├── build_timer_context_prompt()       — Timer context injection
    └── build_timer_task_prompt()          — Timer task instruction
```

### Naming Convention

| Type | Convention | Example |
|------|-----------|---------|
| Pure string constant | `UPPER_CASE` | `CHAT_END_DETECT_PROMPT` |
| Parameterized builder | `build_xxx_prompt()` returning `str` | `build_memory_context_prompt(summary)` |

Follows the existing pattern: `build_skill_prompt()` is already in this style.

### Files Changed

| File | Change |
|------|--------|
| `prompts.py` | Add ~15 prompt definitions (~120 lines) |
| `graph/nodes/ai.py` | Replace 3 inline prompts with imports |
| `graph/nodes/detect.py` | Replace 1 inline prompt with import |
| `graph/nodes/finish.py` | Replace 1 inline prompt with import |
| `graph/tools.py` | Replace 5 inline prompts with imports |
| `handlers/night_comic.py` | Replace 2 inline prompts with imports |
| `handlers/likes.py` | Replace 2 inline prompts with imports |
| `timer/executor.py` | Replace 3 inline prompts with imports |

### Consumer Pattern

Each consumer file changes from defining prompts inline to importing them:

```python
# Before (detect.py):
SystemMessage(content="""## 任务：判断\n- 对话是否已经自然结束\n...""")

# After (detect.py):
from ...prompts import CHAT_END_DETECT_PROMPT
SystemMessage(content=CHAT_END_DETECT_PROMPT)
```

No behavioral changes — purely relocation.

### Exclusions

| Content | Reason |
|---------|--------|
| `data/.../skills/*.md` | Dynamically loaded external resources, not code-level prompts |
| `"__end__"` / `"[CONVERSATION END]"` | Internal control signals, not LLM instructions |
| `"## 历史聊天记录："` / `"## 当前聊天记录："` | Structural labels in HumanMessage, not prompts |

## Implementation Notes

- Each prompt string is copied verbatim — no rewording, no refactoring
- Parameterized prompts become simple functions returning formatted strings
- `build_timer_system_prompt()` imports `role_sys_prompt` from the same file (no circular dependency)
- All existing tests should continue to pass without modification (prompts are not mocked in tests)
