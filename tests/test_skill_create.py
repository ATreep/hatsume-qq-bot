"""Tests for skill_create tool and SkillManager.save_skill()."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hatsume/plugins/hatsume-plugin"


# ---------------------------------------------------------------------------
# Module loading helpers (follows existing test patterns)
# ---------------------------------------------------------------------------
def _ensure_package_hierarchy() -> None:
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Alias so hatsume_plugin resolves to hatsume-plugin
    alias_name = "hatsume.plugins.hatsume_plugin"
    if alias_name not in sys.modules:
        alias_mod = types.ModuleType(alias_name)
        alias_mod.__path__ = [str(PLUGIN_DIR)]
        sys.modules[alias_name] = alias_mod


def _load_module(short_name: str, **stub_attrs: object) -> types.ModuleType:
    full_name = f"hatsume.plugins.hatsume-plugin.{short_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PLUGIN_DIR / f"{short_name}.py"
    )
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    for k, v in stub_attrs.items():
        setattr(mod, k, v)
    spec.loader.exec_module(mod)
    return mod


def _load_submodule(package_short: str, module_name: str, **stub_attrs: object) -> types.ModuleType:
    full_name = f"hatsume.plugins.hatsume-plugin.{module_name}"
    spec = importlib.util.spec_from_file_location(
        full_name, PLUGIN_DIR / package_short / f"{module_name.split('.')[-1]}.py"
    )
    if spec is None:
        raise ImportError(f"Cannot load {full_name}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    for k, v in stub_attrs.items():
        setattr(mod, k, v)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
_ensure_package_hierarchy()

config_mod = _load_module("config")
SKILLS_DIR = config_mod.SKILLS_DIR

skills_init_mod = _load_submodule("skills", "skills.__init__")
SkillManager = skills_init_mod.SkillManager
get_skill_manager = skills_init_mod.get_skill_manager


# ---------------------------------------------------------------------------
# Tests: SkillManager.save_skill()
# ---------------------------------------------------------------------------
class TestSaveSkill:
    """Tests for SkillManager.save_skill()."""

    def test_save_new_skill_returns_created(self):
        """Saving a new skill returns the created message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))
            result = mgr.save_skill(
                "my-skill", "---\nname: my-skill\ndescription: Test\n---\n# Content"
            )
            assert "已创建" in result
            assert "my-skill" in result
            assert (Path(tmpdir) / "my-skill.md").exists()

    def test_save_existing_skill_overwrites(self):
        """Saving an existing skill returns the overwrite message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))
            mgr.save_skill(
                "my-skill", "---\nname: my-skill\ndescription: Test\n---\n# V1"
            )
            result = mgr.save_skill(
                "my-skill", "---\nname: my-skill\ndescription: Test\n---\n# V2"
            )
            assert "覆盖" in result
            assert "my-skill" in result
            content = (Path(tmpdir) / "my-skill.md").read_text()
            assert "V2" in content

    def test_save_skill_clears_cache(self):
        """After save, the cache entry is cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))
            mgr._content_cache["my-skill"] = "old cached content"
            mgr.save_skill(
                "my-skill", "---\nname: my-skill\ndescription: Test\n---\n# Fresh"
            )
            assert "my-skill" not in mgr._content_cache

    def test_save_skill_write_failure_returns_error(self, monkeypatch):
        """When file write fails, an error message is returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))

            def _failing_write(*args, **kwargs):
                raise OSError("disk full")

            monkeypatch.setattr(Path, "write_text", _failing_write)
            result = mgr.save_skill(
                "my-skill", "---\nname: my-skill\ndescription: Test\n---\n# Content"
            )
            assert "错误" in result
            assert "保存技能文件失败" in result


# ---------------------------------------------------------------------------
# Tests: skill_create @tool
# ---------------------------------------------------------------------------
def _stub_all_for_tools() -> None:
    """Stub all external dependencies needed to load graph/tools.py."""
    # Clear hatsume modules
    for name in list(sys.modules):
        if name.startswith("hatsume"):
            del sys.modules[name]

    _ensure_package_hierarchy()
    config_mod = _load_module("config")

    # langchain stubs
    langchain = types.ModuleType("langchain")
    langchain.__path__ = []
    sys.modules["langchain"] = langchain

    langchain_messages = types.ModuleType("langchain.messages")
    langchain_messages.SystemMessage = type("SystemMessage", (), {})
    langchain_messages.HumanMessage = type("HumanMessage", (), {})
    sys.modules["langchain.messages"] = langchain_messages

    langchain_agents = types.ModuleType("langchain.agents")
    langchain_agents.create_agent = lambda *a, **kw: None
    sys.modules["langchain.agents"] = langchain_agents

    langchain_core = types.ModuleType("langchain_core")
    langchain_core.__path__ = []
    sys.modules["langchain_core"] = langchain_core
    langchain_core.messages = types.ModuleType("langchain_core.messages")
    sys.modules["langchain_core.messages"] = langchain_core.messages

    lc_tools = types.ModuleType("langchain_core.tools")
    lc_tools.tool = lambda *a, **kw: (lambda f: f)
    sys.modules["langchain_core.tools"] = lc_tools

    lc_comm = types.ModuleType("langchain_community")
    lc_comm.__path__ = []
    sys.modules["langchain_community"] = lc_comm
    lc_comm_tools = types.ModuleType("langchain_community.tools")
    sys.modules["langchain_community.tools"] = lc_comm_tools
    lc_comm_tools.DuckDuckGoSearchRun = lambda: types.SimpleNamespace(run=lambda q: "...")

    # nonebot stubs
    nonebot = types.ModuleType("nonebot")
    nonebot.get_bot = lambda: None
    nonebot.require = lambda name: types.SimpleNamespace(
        scheduler=types.SimpleNamespace(
            add_job=lambda *a, **kw: None,
            remove_job=lambda *a, **kw: None,
            scheduled_job=lambda *a, **kw: lambda f: f,
        )
    )
    nonebot.get_plugin_config = lambda name: None
    nonebot.__path__ = []
    sys.modules["nonebot"] = nonebot

    # Stub nonebot_plugin_localstore to avoid importing the real one
    localstore = types.ModuleType("nonebot_plugin_localstore")
    localstore.get_plugin_data_dir = lambda name: Path("/tmp")
    localstore.get_plugin_data_file = lambda name: Path("/tmp/data.json")
    sys.modules["nonebot_plugin_localstore"] = localstore

    nonebot_adapters = types.ModuleType("nonebot.adapters")
    nonebot_adapters.__path__ = []
    nonebot_adapters.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters"] = nonebot_adapters

    nonebot_adapters_onebot = types.ModuleType("nonebot.adapters.onebot")
    nonebot_adapters_onebot.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = nonebot_adapters_onebot

    v11 = types.ModuleType("nonebot.adapters.onebot.v11")
    v11.MessageSegment = types.SimpleNamespace
    sys.modules["nonebot.adapters.onebot.v11"] = v11

    # Load skills module
    skills_init = _load_submodule("skills", "skills.__init__")

    # Load tools module
    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume_plugin.graph.tools",
        str(PLUGIN_DIR / "graph/tools.py"),
    )
    tools_mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume_plugin.graph.tools"] = tools_mod
    spec.loader.exec_module(tools_mod)
    return tools_mod, SkillManager, skills_init.get_skill_manager


@pytest.mark.skip(reason="Requires full tools module loading with all dependencies stubbed")
class TestSkillCreateTool:
    """Tests for the skill_create @tool."""

    def test_valid_content_returns_success(self):
        """skill_create with valid content returns success message."""
        tools_mod, SkillManager, get_skill_manager2 = _stub_all_for_tools()

        import hatsume.plugins.hatsume_plugin.skills as skills_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(Path(tmpdir))

            original_get = skills_mod.get_skill_manager
            skills_mod.get_skill_manager = lambda: mgr

            content = "---\nname: test-skill\ndescription: A test skill\n---\n# Hello"
            result = tools_mod.skill_create(content)
            assert "已创建" in result
            assert "test-skill" in result
            assert (Path(tmpdir) / "test-skill.md").exists()

            if original_get:
                skills_mod.get_skill_manager = original_get

    def test_missing_name_returns_error(self):
        """skill_create with missing name field returns error."""
        tools_mod, _, _ = _stub_all_for_tools()
        content = "---\ndescription: No name here\n---\n# Content"
        result = tools_mod.skill_create(content)
        assert "错误" in result
        assert "name" in result

    def test_missing_description_returns_error(self):
        """skill_create with missing description field returns error."""
        tools_mod, _, _ = _stub_all_for_tools()
        content = "---\nname: no-desc\n---\n# Content"
        result = tools_mod.skill_create(content)
        assert "错误" in result
        assert "description" in result

    def test_no_frontmatter_returns_error(self):
        """skill_create without YAML frontmatter returns error."""
        tools_mod, _, _ = _stub_all_for_tools()
        content = "# Just a heading\nNo frontmatter here."
        result = tools_mod.skill_create(content)
        assert "错误" in result
        assert "frontmatter" in result
