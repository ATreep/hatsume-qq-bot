# Data Model: Consolidate LLM Prompts

**Date**: 2026-06-14
**Feature**: [spec.md](./spec.md)

## Overview

This is a pure refactoring — no new data entities, no schema changes, no state transitions. The "data model" consists of the prompt artifacts being relocated.

## Prompt Artifacts

### Prompt Constants (8)

| Name | Type | Section |
|------|------|---------|
| `AUXILIARY_COMPACTION_PROMPT` | `str` | Graph Node |
| `CHAT_END_DETECT_PROMPT` | `str` | Graph Node |
| `MEMORY_RECORDING_PROMPT` | `str` | Graph Node |
| `WEB_BROWSER_AGENT_PROMPT` | `str` | Tool |
| `HTML_GENERATION_PROMPT` | `str` | Tool |
| `NIGHT_COMIC_STORY_PROMPT` | `str` | Feature |
| `FACE_EMOTION_CLASSIFIER_PROMPT_PREFIX` | `str` | Graph Node |
| `FACE_EMOTION_CLASSIFIER_PROMPT_SUFFIX` | `str` | Graph Node |

### Prompt Builder Functions (11)

| Name | Parameters | Returns | Section |
|------|-----------|---------|---------|
| `build_face_emotion_classifier_prompt` | `emotions: list[str]` | `str` | Graph Node |
| `build_memory_context_prompt` | `memory_summary: str` | `str` | Graph Node |
| `build_web_result_rephrase_prompt` | `demand: str` | `str` | Tool |
| `build_video_failure_prompt` | `prompt: str` | `str` | Tool |
| `build_video_success_prompt` | `prompt: str, audio_note: str = ""` | `str` | Tool |
| `build_night_comic_image_prompt` | `story: str, user1_name: str, user2_name: str, img_style: str` | `str` | Feature |
| `build_like_failure_prompt` | `user_name: str` | `str` | Feature |
| `build_like_success_prompt` | `user_name: str, like_time: int, total_likes: int` | `str` | Feature |
| `build_timer_system_prompt` | `creator_info: str, group_id: int, task_content: str` | `str` | Timer |
| `build_timer_context_prompt` | `ctx_text: str` | `str` | Timer |
| `build_timer_task_prompt` | `task_prompt: str` | `str` | Timer |

### Unchanged (2)

| Name | Type | Notes |
|------|------|-------|
| `role_sys_prompt` | `str` | Already in `prompts.py` |
| `build_skill_prompt` | `(skills: list[dict]) -> str` | Already in `prompts.py` |

## Validation Rules

- **FR-005**: All relocated prompts MUST produce character-for-character identical output to the original inline versions.
- **FR-004**: Consumer files MUST NOT contain inline prompt definitions after relocation.
