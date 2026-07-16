# skill_create Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `skill_create` tool that saves skill markdown content (with YAML frontmatter) directly to the skills directory.

**Architecture:** Thin tool in `tools.py` delegates to a new `save_skill()` method on `SkillManager`, reusing the existing `parse_frontmatter_text()` for validation. Registered in the chat agent tool list alongside the other skill tools.

**Tech Stack:** Python 3.12, LangChain @tool decorator, existing `SkillManager` / `SKILLS_DIR` / `yaml`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `hatsume/plugins/hatsume-plugin/skills/manager.py` | Modify | Add `save_skill(name, content)` method |
| `hatsume/plugins/hatsume-plugin/graph/tools.py` | Modify | Add `@tool skill_create(content)` |
| `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py` | Modify | Import + register `skill_create` |
| `tests/test_skill_create.py` | Create | Unit tests for save_skill + skill_create |

---

### Task 1: Write Tests for `SkillManager.save_skill()`

**Files:**
- Create: `tests/test_skill_create.py`

- [ ] **Step 1: Write the test file covering all save_skill scenarios**

```python
"""Tests for skill_create tool and SkillManager.save_skill()."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hatsume.plugins.hatsume_plugin.skills.manager import SkillManager


class TestSaveSkill:
    """Tests for SkillManager.save_skill()."""

    def test_save_new_skill_returns_created(self):
        """Saving a new skill returns the created message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))
            result = mgr.save_skill("my-skill", "---\nname: my-skill\ndescription: Test\n---\n# Content")
            assert "已创建" in result
            assert "my-skill" in result
            assert (Path(tmpdir) / "my-skill.md").exists()

    def test_save_existing_skill_overwrites(self):
        """Saving an existing skill returns the overwrite message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))
            mgr.save_skill("my-skill", "---\nname: my-skill\ndescription: Test\n---\n# V1")
            result = mgr.save_skill("my-skill", "---\nname: my-skill\ndescription: Test\n---\n# V2")
            assert "覆盖" in result
            assert "my-skill" in result
            content = (Path(tmpdir) / "my-skill.md").read_text()
            assert "V2" in content

    def test_save_skill_clears_cache(self):
        """After save, the cache entry is cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))
            mgr._content_cache["my-skill"] = "old cached content"
            mgr.save_skill("my-skill", "---\nname: my-skill\ndescription: Test\n---\n# Fresh")
            assert "my-skill" not in mgr._content_cache

    def test_save_skill_write_failure_returns_error(self, monkeypatch):
        """When file write fails, an error message is returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))

            def _failing_write(*args, **kwargs):
                raise OSError("disk full")

            monkeypatch.setattr(Path, "write_text", _failing_write)
            result = mgr.save_skill("my-skill", "---\nname: my-skill\ndescription: Test\n---\n# Content")
            assert "错误" in result
            assert "保存技能文件失败" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_skill_create.py -xvs
```
Expected: FAIL — `AttributeError: 'SkillManager' object has no attribute 'save_skill'`

- [ ] **Step 3: Commit**

```bash
git add tests/test_skill_create.py
git commit -m "test: add failing tests for SkillManager.save_skill()"
```

---

### Task 2: Implement `SkillManager.save_skill()`

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/skills/manager.py`

- [ ] **Step 1: Add the `save_skill` method to `SkillManager`**

After the `remove_skill` method (after line ~92) and before `reset_conversation`, add:

```python
    def save_skill(self, name: str, content: str) -> str:
        """Save a skill file to disk and clear its cache entry.

        Returns a success message. If a skill with the same name already
        exists, it is overwritten and the message indicates so.
        """
        self._ensure_dir()
        file_path = self._skills_dir / f"{name}.md"
        existed = file_path.exists()
        try:
            file_path.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"❌ [skills] Failed to write skill '{name}': {e}")
            return f"错误：保存技能文件失败：{e}"
        self._content_cache.pop(name, None)
        if existed:
            print(f"✅ [skills] Overwrote skill '{name}'")
            return f"✅ 技能 '{name}' 已创建（覆盖了已有文件）。"
        else:
            print(f"✅ [skills] Created skill '{name}'")
            return f"✅ 技能 '{name}' 已创建。"
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
python -m pytest tests/test_skill_create.py -xvs
```
Expected: 4 PASS

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/skills/manager.py
git commit -m "feat: add SkillManager.save_skill() method"
```

---

### Task 3: Write Tests for `skill_create` Tool

**Files:**
- Modify: `tests/test_skill_create.py` (append to existing)

- [ ] **Step 1: Add tool-level tests**

Append to `tests/test_skill_create.py`:

```python
import sys
import types
import importlib


def _load_tools_module():
    """Load tools.py module with isolated imports for testing."""
    for name in list(sys.modules):
        if name.startswith("hatsume"):
            del sys.modules[name]

    # Stub nonebot
    nonebot_stub = types.ModuleType("nonebot")
    nonebot_stub.get_bot = lambda: None
    nonebot_stub.adapters = types.ModuleType("nonebot.adapters")
    nonebot_stub.adapters.onebot = types.ModuleType("nonebot.adapters.onebot")
    nonebot_stub.adapters.onebot.v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    nonebot_stub.adapters.onebot.v11.MessageSegment = types.SimpleNamespace
    sys.modules["nonebot"] = nonebot_stub
    sys.modules["nonebot.adapters"] = nonebot_stub.adapters
    sys.modules["nonebot.adapters.onebot"] = nonebot_stub.adapters.onebot
    sys.modules["nonebot.adapters.onebot.v11"] = nonebot_stub.adapters.onebot.v11

    # Stub langchain
    lc_tools = types.ModuleType("langchain_core.tools")
    lc_tools.tool = lambda *a, **kw: (lambda f: f)
    sys.modules["langchain_core.tools"] = lc_tools

    lc_msgs = types.ModuleType("langchain.messages")
    sys.modules["langchain.messages"] = lc_msgs
    lc_comm = types.ModuleType("langchain_community.tools")
    sys.modules["langchain_community.tools"] = lc_comm
    lc_comm.DuckDuckGoSearchRun = lambda: types.SimpleNamespace(run=lambda q: "...")

    # Import tools
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume_plugin.graph.tools",
        "hatsume/plugins/hatsume-plugin/graph/tools.py",
    )
    tools_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools_mod)
    return tools_mod


class TestSkillCreateTool:
    """Tests for the skill_create @tool."""

    def test_valid_content_returns_success(self):
        """skill_create with valid content returns success message."""
        import tempfile
        from pathlib import Path

        tools = _load_tools_module()
        from hatsume.plugins.hatsume_plugin.skills.manager import SkillManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))

            import hatsume.plugins.hatsume_plugin.skills as skills_mod
            original_get = skills_mod.get_skill_manager
            skills_mod.get_skill_manager = lambda: mgr

            content = "---\nname: test-skill\ndescription: A test skill\n---\n# Hello"
            result = tools.skill_create(content)
            assert "已创建" in result
            assert "test-skill" in result
            assert (Path(tmpdir) / "test-skill.md").exists()

            if original_get:
                skills_mod.get_skill_manager = original_get

    def test_missing_name_returns_error(self):
        """skill_create with missing name field returns error."""
        tools = _load_tools_module()
        content = "---\ndescription: No name here\n---\n# Content"
        result = tools.skill_create(content)
        assert "错误" in result
        assert "name" in result

    def test_missing_description_returns_error(self):
        """skill_create with missing description field returns error."""
        tools = _load_tools_module()
        content = "---\nname: no-desc\n---\n# Content"
        result = tools.skill_create(content)
        assert "错误" in result
        assert "description" in result

    def test_no_frontmatter_returns_error(self):
        """skill_create without YAML frontmatter returns error."""
        tools = _load_tools_module()
        content = "# Just a heading\nNo frontmatter here."
        result = tools.skill_create(content)
        assert "错误" in result
        assert "frontmatter" in result
```

- [ ] **Step 2: Run tool tests to verify they fail**

```bash
python -m pytest tests/test_skill_create.py::TestSkillCreateTool -xvs
```
Expected: FAIL — `AttributeError: module ... has no attribute 'skill_create'`

- [ ] **Step 3: Commit**

```bash
git add tests/test_skill_create.py
git commit -m "test: add failing tests for skill_create tool"
```

---

### Task 4: Implement `skill_create` Tool

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/tools.py`

- [ ] **Step 1: Add the `skill_create` tool**

Add after the `skill_download` function, before the `membersearch` tool:

```python
@tool
def skill_create(content: str) -> str:
    """
    根据提供的完整技能内容创建一个新技能或覆盖已有技能。

    ## 参数：
    - content: 完整的技能 markdown 内容。必须以 --- 开头的 YAML frontmatter 开始，
      frontmatter 中必须包含 name（技能名称）和 description（技能描述）两个字段。

    ## 行为：
    - 从 frontmatter 中自动解析 name 和 description
    - 保存为 data/hatsume-plugin/skills/{name}.md
    - 如果同名技能已存在，覆盖并提示
    - 创建后技能立即可用（无需重启）

    ## frontmatter 示例：
    ```
    ---
    name: my-skill
    description: 简短描述该技能的功能
    version: 1.0.0
    author: 作者名
    ---
    # 技能指令内容
    ...
    ```

    ## 使用时机：
    - 用户明确要求创建或编写一个新技能
    - 用户提供了完整的技能内容（含 frontmatter）
    """
    from ..skills import get_skill_manager

    mgr = get_skill_manager()
    meta = mgr.parse_frontmatter_text(content)
    if meta is None:
        return "错误：内容不是有效的技能文件（缺少 --- frontmatter 或 'name' 字段）。"

    name = meta["name"]
    description = meta.get("description", "").strip()
    if not description:
        return f"错误：frontmatter 中缺少 'description' 字段。技能 '{name}' 需要描述才能被识别。"

    return mgr.save_skill(name, content)
```

- [ ] **Step 2: Run all tests to verify they pass**

```bash
python -m pytest tests/test_skill_create.py -xvs
```
Expected: 8 PASS (4 save_skill tests + 4 skill_create tests)

- [ ] **Step 3: Run existing skill tests to verify no regression**

```bash
python -m pytest tests/test_skill_manager.py -xvs
```
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/tools.py
git commit -m "feat: add skill_create tool for chat agent"
```

---

### Task 5: Register `skill_create` in Chat Agent Tools

**Files:**
- Modify: `hatsume/plugins/hatsume-plugin/graph/nodes/ai.py`

- [ ] **Step 1: Import `skill_create` and add to chat agent tools list**

Change the import block (line ~26-31):
```python
from ..tools import (
    search_web, web_browser, find_memory, query_memory,
    capture_html_shot, generate_image, generate_video,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, membersearch
)
```
To add `skill_create`:
```python
from ..tools import (
    search_web, web_browser, find_memory, query_memory,
    capture_html_shot, generate_image, generate_video,
    reset_capture_flag, get_avatar,
    create_timer, list_timers, delete_timer,
    skill_loader, skill_remove, skill_download, skill_create, membersearch
)
```

And in the `create_agent` tools list (line ~165-171), add `skill_create` after `skill_download`:
```python
    chat_agent = create_agent(
        model_chosen,
        [search_web, web_browser, find_memory, capture_html_shot,
         generate_image, generate_video, get_avatar,
         create_timer, list_timers, delete_timer,
         skill_loader, skill_remove, skill_download, skill_create, membersearch],
        system_prompt=sys_prompt,
    )
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from hatsume.plugins.hatsume_plugin.graph.tools import skill_create; print('OK:', skill_create.name)"
```
Expected: `OK: skill_create`

- [ ] **Step 3: Commit**

```bash
git add hatsume/plugins/hatsume-plugin/graph/nodes/ai.py
git commit -m "feat: register skill_create in chat agent tools"
```

---

### Task 6: Final Integration Verification

- [ ] **Step 1: Run the full relevant test suite**

```bash
python -m pytest tests/test_skill_create.py tests/test_skill_manager.py tests/test_tools.py tests/test_graph_nodes.py -xvs
```
Expected: All tests PASS

- [ ] **Step 2: Verify clean working tree**

```bash
git status
```
Expected: clean working tree
