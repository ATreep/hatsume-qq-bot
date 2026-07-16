# Consolidate All LLM Prompts into `prompts.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all 15 scattered LLM prompts from 7 files into `prompts.py` as constants and builder functions.

**Architecture:** Append 15 prompt definitions to `prompts.py` grouped in 5 sections (Graph Node, Tool, Feature, Timer). Each consumer file removes its inline prompt and imports the definition instead. Pure relocation — zero behavioral change.

**Tech Stack:** Python 3.12+, langchain_core.messages

---

### Task 1: Add all 15 prompts to `prompts.py`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/prompts.py` — append after `build_skill_prompt()`

- [ ] **Step 1: Append all prompt definitions**

Append the following to the end of `hatsume/plugins/hatsume-plugin/prompts.py`:

```python


# ---------------------------------------------------------------------------
# Graph node prompts
# ---------------------------------------------------------------------------
AUXILIARY_COMPACTION_PROMPT = (
    "总结输入的聊天记录信息。必须明确时间、人物、事件。"
    "总结时，需要使用完整的用户昵称（用户昵称应使用引号包围），"
    "但不要完整的复述说话内容。除了总结文字外，不要输出其他任何内容。"
)

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


CHAT_END_DETECT_PROMPT = (
    "## 任务：判断\n"
    " - 对话是否已经自然结束\n"
    " - 用户是否在说再见\n"
    " - 用户是否开始说与当前话题无关的内容\n"
    " - 用户是否开始与他人聊天，而不是与你或名为 `初芽` 的聊天机器人交流\n"
    " - 如果用户提到了 `初芽`，则必须输出 `no`"
    "## 规则：如果以上任意一个条件为真，只输出 'yes'；"
    "否则输出 'no'。不要输出任何其他文本。\n\n"
    "## 示例 1：\n"
    "### 用户输入：\n"
    "```"
    "`小张`: 你怎么看感恩节？\n"
    "你: 是的，我也很喜欢感恩节。\n"
    "`小张`: @壮壮，嘿，感恩节有什么安排？\n"
    "```"
    "### 你的输出：yes\n\n"
    "## 示例 2：\n"
    "### 用户输入：\n"
    "```"
    '`小强`: "电子游戏"是什么意思？\n'
    "你: 一种在电子屏幕上进行的游戏。\n"
    "`小强`: 汉堡。\n"
    "```"
    "### 你的输出：yes\n"
    "## 示例 3：\n"
    "### 用户输入：\n"
    "```"
    '`小王`: "电子阳痿" 是什么意思？\n'
    "你: 就是不知道玩什么游戏的意思哦。\n"
    "`小王`: 细说。\n"
    "```"
    "### 你的输出：no\n"
    "## 示例 4：\n"
    "### 用户输入：\n"
    "```"
    "`小李`: 我想去郊游\n"
    "你： 我也喜欢郊游\n"
    "`小李`: @初芽，我不吃牛肉。\n"
    "```"
    "### 你的输出：no\n"
)

MEMORY_RECORDING_PROMPT = (
    "你是机器人（AI）的长期记忆记录器。你的任务是从用户与机器人之间的对话中，"
    "提取有趣、有价值的用户信息并记忆。不是记流水账。\n"
    "\n"
    "规则：\n"
    "1. 使用 `write_memory` 工具记录记忆。\n"
    "2. 调用 `write_memory` 时，每条记忆必须同时提供 `content` 与 `source_ids`。\n"
    "3. `source_ids` 只能填写对话里方括号中的消息编号，例如 `m3`、`m8`。\n"
    "4. 若一条记忆来源于多条消息，必须列出多个 `source_ids`。\n"
    "5. 若没有值得记忆的内容，或无法确定一条记忆具体来自哪些消息，则不要调用任何工具。 \n"
    "6. 只记录用户相关的信息：用户的兴趣爱好、性格特点、重要经历、"
    "观点偏好、人际关系、生活中的关键事件，以及用户明确要求你记住的内容。\n"
    "7. 不记录流水账式的日常互动，例如：问候/告别（再见、晚安）、"
    "无实质内容的闲聊（哈哈、好的、嗯）、日常寒暄、临时的聊天话题等。\n"
    "\n"
    "目标：构建精准、有深度的用户画像，而非面面俱到的聊天日志。"
)


def build_memory_context_prompt(memory_summary: str) -> str:
    """Build the memory context injection prompt."""
    return (
        "## 你的部分记忆如下（通过 find_memory 搜索更多记忆；"
        "用户无法直接看到你的记忆）：\n\n"
        + memory_summary
    )


# ---------------------------------------------------------------------------
# Tool prompts
# ---------------------------------------------------------------------------
WEB_BROWSER_AGENT_PROMPT = """\
根据用户给定的网站与提供的需求，使用 shell_executor 工具浏览网站。
最后使用中文向用户输出详细的结果报告。
如果目标网站存在限制无法得到结果，你的报告中应至少给出一个与结果最相关的链接。

## 示例
用户输入：在网站 http://www.example.com/ 中查找求职招聘信息
最终输出：在网址 http://www.example.com/job 中找到了求职招聘信息如下：......\
"""

HTML_GENERATION_PROMPT = (
    "你是一个专业的 HTML 设计师。根据用户的需求，生成完整的 HTML 代码。\n"
    "要求：\n"
    "- 代码必须是完整的 HTML 文档，包含 <!DOCTYPE html>、<html>、<head>、<body> 标签\n"
    "- 所有样式必须使用内联 CSS（在 <style> 标签中）\n"
    "- 设计要美观、现代化，不要使用默认的浏览器样式\n"
    "- 图片使用 <img> 标签时，必须提供完整的 URL\n"
    "- 只输出 HTML 代码，不要输出任何其他文字说明"
)


def build_web_result_rephrase_prompt(demand: str) -> str:
    """Build the web browser result rephrasing prompt."""
    return (
        f"(SYSTEM) 用户发出的检索请求是： `{demand}`，"
        "以下是 web_browser 工具检索得到的报告，请向用户简单转述此报告，"
        "但必须包含所有的关键信息。"
    )


def build_video_failure_prompt(prompt: str) -> str:
    """Build the video generation failure notification prompt."""
    return (
        f"(SYSTEM) 用户请求生成视频「{prompt}」，但视频生成失败了。"
        "请用你的口吻简短地告知用户视频生成失败。"
    )


def build_video_success_prompt(prompt: str, audio_note: str = "") -> str:
    """Build the video generation success notification prompt."""
    return (
        f"(SYSTEM) 用户请求生成视频「{prompt}」，视频已生成完毕{audio_note}，已发送给用户。"
        "请用你的口吻简短地告知用户视频生成完成。"
    )


# ---------------------------------------------------------------------------
# Feature prompts
# ---------------------------------------------------------------------------
NIGHT_COMIC_STORY_PROMPT = (
    "参考给定的几段话作为人物背景，编写一个条理清晰、逻辑通顺的搞笑故事。"
    "人物刻画必须生动形象、个性明显，情节偏疯癫、搞笑、离奇。"
    "你的故事必须包含这几段话中的所有人物（昵称），你的故事大约80字左右。"
    "除了故事外，你的输出不要有任何无关内容。"
)


def build_night_comic_image_prompt(
    story: str,
    user1_name: str,
    user2_name: str,
    img_style: str,
) -> str:
    """Build the night comic image generation prompt."""
    return (
        f"请根据以下故事，作画，画面中的所有人物必须聚在一起，参考以下故事情节，让他们共同做一件事：\n"
        f"        ```\n"
        f"        {story}\n"
        f"        ```\n"
        f"        画面中其中几个主人公的角色形象为给定的图片（人物/动物/植物/物品），"
        f"人物形象必须与图片中的内容强相关，输入的图片顺序依次是故事中的主人公："
        f" `@{user1_name}` `@{user2_name}`。\n"
        f"        这几个主人公应该在合作完成一件事，或者在同一个场景中互动，画面要有趣、离奇、搞笑。\n"
        f"        主人公必须在画面中得到凸显，人物形象占据画面主要空间。\n"
        f"        画面背景不要用单调、纯色填充，使用某个地点场所作背景。\n"
        f"        纯画作，不要出现人物名字介绍。不要出现任何文字。\n"
        f"        作画风格必须为：{img_style}"
    )


def build_like_failure_prompt(user_name: str) -> str:
    """Build the like failure notification prompt."""
    return (
        f"你接下来需要用抱歉的语气且不超过 30 个字的简短语句告诉用户 "
        f"`{user_name}`（你需要用这个名字称呼对方），初芽已经无法对其名片点赞，"
        f"并说明原因是由于初芽对其的点赞数已经上限，可以明天再让初芽点赞。"
    )


def build_like_success_prompt(user_name: str, like_time: int, total_likes: int) -> str:
    """Build the like success notification prompt."""
    return (
        f"你接下来需要用祝贺的语气且不超过 30 个字的简短语句恭喜用户 "
        f"`{user_name}`（你需要用这个名字称呼对方），初芽刚才对其名片成功点赞了 "
        f"{like_time} 次。并使用类似的话术（不要使用给出的这个话术）告诉用户："
        f"根据记录，这些日子里，初芽总共已经为其点赞 "
        f"{total_likes} 次了！"
    )


# ---------------------------------------------------------------------------
# Timer prompts
# ---------------------------------------------------------------------------
def build_timer_system_prompt(
    creator_info: str,
    group_id: int,
    task_content: str,
) -> str:
    """Build the timer executor system prompt.

    Returns role_sys_prompt with timer-specific task instructions appended.
    """
    return (
        f"{role_sys_prompt}\n\n"
        f"## 定时任务\n"
        f"你现在正在执行用户 {creator_info} "
        f"在群 {group_id} 设置的定时任务。\n"
        f"任务内容：{task_content}\n\n"
        f"请在下方消息上下文的帮助下执行此任务。"
    )


def build_timer_context_prompt(ctx_text: str) -> str:
    """Build the timer recent chat context prompt."""
    return "## 最近群聊上下文\n\n" + ctx_text


def build_timer_task_prompt(task_prompt: str) -> str:
    """Build the timer task execution prompt."""
    return f"## 执行任务\n{task_prompt}"
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/prompts.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/prompts.py
git commit -m "feat: add all LLM prompts to prompts.py as constants and builders"
```

---

### Task 2: Update `graph/nodes/ai.py` — replace 3 inline prompts

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

- [ ] **Step 1: Update imports**

Change line 18 (the `from ...prompts import` line) from:
```python
from ...prompts import build_skill_prompt, role_sys_prompt
```
to:
```python
from ...prompts import (
    AUXILIARY_COMPACTION_PROMPT,
    build_face_emotion_classifier_prompt,
    build_memory_context_prompt,
    build_skill_prompt,
    role_sys_prompt,
)
```

- [ ] **Step 2: Replace auxiliary compaction prompt (lines 83-87)**

Replace:
```python
                SystemMessage(
                    "总结输入的聊天记录信息。必须明确时间、人物、事件。"
                    "总结时，需要使用完整的用户昵称（用户昵称应使用引号包围），"
                    "但不要完整的复述说话内容。除了总结文字外，不要输出其他任何内容。"
                ),
```
with:
```python
                SystemMessage(AUXILIARY_COMPACTION_PROMPT),
```

- [ ] **Step 3: Replace memory context injection (lines 178-182)**

Replace:
```python
                HumanMessage(
                    "## 你的部分记忆如下（通过 find_memory 搜索更多记忆；"
                    "用户无法直接看到你的记忆）：\n\n"
                    + memory_summary
                )
```
with:
```python
                HumanMessage(build_memory_context_prompt(memory_summary))
```

- [ ] **Step 4: Replace face emotion classifier prompt (lines 248-257)**

Replace:
```python
        system_prompt=(
            "## Role: Classify the emotion of the speaker of the input text. \n"
            "## Output Form: ONLY output between: "
            + ", ".join(list(face_dict.keys()) + ["general"])
            + ". \n"
            "## Rules: \n"
            "- Output the most relative emotion. \n"
            "- If just no emotion relative, output `general`. Do not guess. \n"
            "- Do not output any other things. "
        ),
```
with:
```python
        system_prompt=build_face_emotion_classifier_prompt(list(face_dict.keys())),
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/graph/nodes/ai.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "refactor: import ai node prompts from prompts.py"
```

---

### Task 3: Update `graph/nodes/detect.py` — replace 1 inline prompt

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/detect.py`

- [ ] **Step 1: Add import**

Add after the existing `from ...models import` line:
```python
from ...prompts import CHAT_END_DETECT_PROMPT
```

- [ ] **Step 2: Replace the inline SystemMessage (lines 51-92)**

Replace the entire `SystemMessage(...)` block (currently lines 51-92) with:
```python
                    SystemMessage(CHAT_END_DETECT_PROMPT)
```

After replacement, the `detect_model.invoke(...)` call should look like:
```python
            detect_result = detect_model.invoke(
                state["messages"][-6:]
                + [SystemMessage(CHAT_END_DETECT_PROMPT)],
                timeout=10,
            )
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/graph/nodes/detect.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/detect.py
git commit -m "refactor: import detect node prompt from prompts.py"
```

---

### Task 4: Update `graph/nodes/finish.py` — replace 1 inline prompt

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/finish.py`

- [ ] **Step 1: Add import**

Add after the existing `from ...models import` line:
```python
from ...prompts import MEMORY_RECORDING_PROMPT
```

- [ ] **Step 2: Replace inline system_prompt (lines 52-68)**

Replace:
```python
        system_prompt=(
            "你是机器人（AI）的长期记忆记录器。你的任务是从用户与机器人之间的对话中，"
            "提取有趣、有价值的用户信息并记忆。不是记流水账。\n"
            "\n"
            "规则：\n"
            "1. 使用 `write_memory` 工具记录记忆。\n"
            "2. 调用 `write_memory` 时，每条记忆必须同时提供 `content` 与 `source_ids`。\n"
            "3. `source_ids` 只能填写对话里方括号中的消息编号，例如 `m3`、`m8`。\n"
            "4. 若一条记忆来源于多条消息，必须列出多个 `source_ids`。\n"
            "5. 若没有值得记忆的内容，或无法确定一条记忆具体来自哪些消息，则不要调用任何工具。 \n"
            "6. 只记录用户相关的信息：用户的兴趣爱好、性格特点、重要经历、"
            "观点偏好、人际关系、生活中的关键事件，以及用户明确要求你记住的内容。\n"
            "7. 不记录流水账式的日常互动，例如：问候/告别（再见、晚安）、"
            "无实质内容的闲聊（哈哈、好的、嗯）、日常寒暄、临时的聊天话题等。\n"
            "\n"
            "目标：构建精准、有深度的用户画像，而非面面俱到的聊天日志。"
        ),
```
with:
```python
        system_prompt=MEMORY_RECORDING_PROMPT,
```

- [ ] **Step 3: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/graph/nodes/finish.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/finish.py
git commit -m "refactor: import finish node prompt from prompts.py"
```

---

### Task 5: Update `graph/tools.py` — replace 5 inline prompts

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

- [ ] **Step 1: Add module-level import**

Add after the last `from ..` import (after `from ..infra import`):
```python
from ..prompts import (
    HTML_GENERATION_PROMPT,
    WEB_BROWSER_AGENT_PROMPT,
    build_video_failure_prompt,
    build_video_success_prompt,
    build_web_result_rephrase_prompt,
)
```

- [ ] **Step 2: Replace video failure prompt (line 382)**

Replace:
```python
            result_text = f"(SYSTEM) 用户请求生成视频「{prompt}」，但视频生成失败了。请用你的口吻简短地告知用户视频生成失败。"
```
with:
```python
            result_text = build_video_failure_prompt(prompt)
```

- [ ] **Step 3: Replace video success prompt (lines 386-390)**

Replace:
```python
            audio_note = "（该模型不支持生成声音）" if model == "1.0" else ""
            result_text = (
                f"(SYSTEM) 用户请求生成视频「{prompt}」，视频已生成完毕{audio_note}，已发送给用户。"
                "请用你的口吻简短地告知用户视频生成完成。"
            )
```
with:
```python
            audio_note = "（该模型不支持生成声音）" if model == "1.0" else ""
            result_text = build_video_success_prompt(prompt, audio_note)
```

- [ ] **Step 4: Replace web browser agent system_prompt (lines 448-456)**

Replace:
```python
        system_prompt="""
根据用户给定的网站与提供的需求，使用 shell_executor 工具浏览网站。
最后使用中文向用户输出详细的结果报告。
如果目标网站存在限制无法得到结果，你的报告中应至少给出一个与结果最相关的链接。

## 示例
用户输入：在网站 http://www.example.com/ 中查找求职招聘信息
最终输出：在网址 http://www.example.com/job 中找到了求职招聘信息如下：......
""",
```
with:
```python
        system_prompt=WEB_BROWSER_AGENT_PROMPT,
```

- [ ] **Step 5: Replace web result rephrase prompt (lines 480-484)**

Replace:
```python
                HumanMessage(
                    f"(SYSTEM) 用户发出的检索请求是： `{demand}`，"
                    "以下是 web_browser 工具检索得到的报告，请向用户简单转述此报告，"
                    "但必须包含所有的关键信息。"
                ),
```
with:
```python
                HumanMessage(build_web_result_rephrase_prompt(demand)),
```

- [ ] **Step 6: Replace HTML generation prompt (lines 499-505)**

Delete the `_HTML_GENERATION_SYSTEM_PROMPT` variable definition (lines 499-505). Then find the usage in `capture_html_shot()` and replace `_HTML_GENERATION_SYSTEM_PROMPT` with `HTML_GENERATION_PROMPT`.

- [ ] **Step 7: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/graph/tools.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 8: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py
git commit -m "refactor: import tool prompts from prompts.py"
```

---

### Task 6: Update `handlers/night_comic.py` — replace 2 inline prompts

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/night_comic.py`

- [ ] **Step 1: Add import**

Add after the existing imports from `..`:
```python
from ..prompts import NIGHT_COMIC_STORY_PROMPT, build_night_comic_image_prompt
```

- [ ] **Step 2: Replace story generation SystemMessage (lines 114-119)**

Replace:
```python
            SystemMessage(
                "参考给定的几段话作为人物背景，编写一个条理清晰、逻辑通顺的搞笑故事。"
                "人物刻画必须生动形象、个性明显，情节偏疯癫、搞笑、离奇。"
                "你的故事必须包含这几段话中的所有人物（昵称），你的故事大约80字左右。"
                "除了故事外，你的输出不要有任何无关内容。"
            ),
```
with:
```python
            SystemMessage(NIGHT_COMIC_STORY_PROMPT),
```

- [ ] **Step 3: Replace image prompt (lines 133-142)**

Replace:
```python
    img_url = generate_image_for(
        f"""请根据以下故事，作画，画面中的所有人物必须聚在一起，参考以下故事情节，让他们共同做一件事：
        ```
        {story}
        ```
        画面中其中几个主人公的角色形象为给定的图片（人物/动物/植物/物品），人物形象必须与图片中的内容强相关，输入的图片顺序依次是故事中的主人公： `@{user_tuples[0][1]}` `@{user_tuples[1][1]}`。
        这几个主人公应该在合作完成一件事，或者在同一个场景中互动，画面要有趣、离奇、搞笑。
        主人公必须在画面中得到凸显，人物形象占据画面主要空间。
        画面背景不要用单调、纯色填充，使用某个地点场所作背景。
        纯画作，不要出现人物名字介绍。不要出现任何文字。
        作画风格必须为：{img_style}""",
```
with:
```python
    img_url = generate_image_for(
        build_night_comic_image_prompt(
            story,
            user_tuples[0][1],
            user_tuples[1][1],
            img_style,
        ),
```

- [ ] **Step 4: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/handlers/night_comic.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/handlers/night_comic.py
git commit -m "refactor: import night comic prompts from prompts.py"
```

---

### Task 7: Update `handlers/likes.py` — replace 2 inline prompts

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/handlers/likes.py`

- [ ] **Step 1: Update import**

Change line 13 from:
```python
from ..prompts import role_sys_prompt
```
to:
```python
from ..prompts import build_like_failure_prompt, build_like_success_prompt, role_sys_prompt
```

- [ ] **Step 2: Replace like failure HumanMessage (lines 85-89)**

Replace:
```python
                HumanMessage(
                    f"你接下来需要用抱歉的语气且不超过 30 个字的简短语句告诉用户 "
                    f"`{user_name}`（你需要用这个名字称呼对方），初芽已经无法对其名片点赞，"
                    f"并说明原因是由于初芽对其的点赞数已经上限，可以明天再让初芽点赞。"
                ),
```
with:
```python
                HumanMessage(build_like_failure_prompt(user_name)),
```

- [ ] **Step 3: Replace like success HumanMessage (lines 103-109)**

Replace:
```python
                HumanMessage(
                    f"你接下来需要用祝贺的语气且不超过 30 个字的简短语句恭喜用户 "
                    f"`{user_name}`（你需要用这个名字称呼对方），初芽刚才对其名片成功点赞了 "
                    f"{like_time} 次。并使用类似的话术（不要使用给出的这个话术）告诉用户："
                    f"根据记录，这些日子里，初芽总共已经为其点赞 "
                    f"{_get_like_times(event.get_user_id())} 次了！"
                ),
```
with:
```python
                HumanMessage(
                    build_like_success_prompt(
                        user_name, like_time, _get_like_times(event.get_user_id())
                    )
                ),
```

- [ ] **Step 4: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/handlers/likes.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/handlers/likes.py
git commit -m "refactor: import like prompts from prompts.py"
```

---

### Task 8: Update `timer/executor.py` — replace 3 inline prompts

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/timer/executor.py`

- [ ] **Step 1: Update import**

Change line 15 from:
```python
from ..prompts import role_sys_prompt
```
to:
```python
from ..prompts import (
    build_timer_context_prompt,
    build_timer_system_prompt,
    build_timer_task_prompt,
    role_sys_prompt,
)
```

- [ ] **Step 2: Replace timer system prompt builder (lines 168-174)**

Replace:
```python
    timer_sys_prompt = (
        f"{role_sys_prompt}\n\n"
        f"## 定时任务\n"
        f"你现在正在执行用户 {creator_info} "
        f"在群 {group_id} 设置的定时任务。\n"
        f"任务内容：{prompt}\n\n"
        f"请在下方消息上下文的帮助下执行此任务。"
    )
```
with:
```python
    timer_sys_prompt = build_timer_system_prompt(creator_info, group_id, prompt)
```

- [ ] **Step 3: Replace timer context prompt (lines 302-303)**

Replace:
```python
            messages.append(HumanMessage(
                "## 最近群聊上下文\n\n" + ctx_text
            ))
```
with:
```python
            messages.append(HumanMessage(build_timer_context_prompt(ctx_text)))
```

- [ ] **Step 4: Replace timer task prompt (line 305)**

Replace:
```python
        messages.append(HumanMessage(f"## 执行任务\n{task_prompt}"))
```
with:
```python
        messages.append(HumanMessage(build_timer_task_prompt(task_prompt)))
```

- [ ] **Step 5: Verify syntax**

```bash
python -c "import ast; ast.parse(open('hatsume/plugins/hatsume-plugin/timer/executor.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 6: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/timer/executor.py
git commit -m "refactor: import timer prompts from prompts.py"
```

---

### Task 9: Run all tests to verify no regressions

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -xvs
```

Expected: All tests pass (same as before — no behavioral changes).

- [ ] **Step 2: Run ruff lint**

```bash
ruff check hatsume/plugins/hatsume-plugin/
```

Expected: Clean (no new issues).

- [ ] **Step 3: Commit any final cleanup** (if needed)

```bash
git add -A
git commit -m "chore: final verification pass for prompt consolidation"
```
