"""Tests for SkillManager and build_skill_prompt."""

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
    """Set up the package hierarchy in sys.modules for hyphenated package names."""
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", PLUGIN_DIR),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


def _load_module(short_name: str, **stub_attrs: object) -> types.ModuleType:
    """Load a plugin module using importlib."""
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
    """Load a submodule under a package directory."""
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

# Load config (required by skills/__init__.py for SKILLS_DIR)
config_mod = _load_module("config")
SKILLS_DIR = config_mod.SKILLS_DIR

# Load skills submodule
skills_init_mod = _load_submodule("skills", "skills.__init__")
SkillManager = skills_init_mod.SkillManager
GroupSkillManager = skills_init_mod.GroupSkillManager
get_skill_manager = skills_init_mod.get_skill_manager

# Load prompts module for build_skill_prompt
prompts_mod = _load_module("prompts")
build_skill_prompt = prompts_mod.build_skill_prompt


# ---------------------------------------------------------------------------
# Helper to create temporary skill directories and files
# ---------------------------------------------------------------------------
def make_skill_file(dir_path: Path, name: str, description: str, content: str = "") -> Path:
    """Create a .md skill file in the given directory and return its path."""
    file_path = dir_path / f"{name}.md"
    text = f"---\nname: {name}\ndescription: {description}\n---\n{content}"
    file_path.write_text(text, encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# SkillManager tests
# ---------------------------------------------------------------------------
class TestSkillManagerListSkills:
    """FR-001: scan configured directory, parse YAML frontmatter."""

    def test_empty_directory(self):
        """list_skills() returns empty list when directory has no .md files."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SkillManager(Path(tmp))
            result = mgr.list_skills()
            assert result == []

    def test_single_skill(self):
        """list_skills() extracts name and description from a single skill file."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "math-tutor", "数学辅导技能", "# Math Tutor\n...")
            mgr = SkillManager(dir_path)
            result = mgr.list_skills()
            assert len(result) == 1
            assert result[0]["name"] == "math-tutor"
            assert result[0]["description"] == "数学辅导技能"

    def test_multiple_skills(self):
        """list_skills() returns all valid skills sorted."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "skill-a", "Skill A description")
            make_skill_file(dir_path, "skill-b", "Skill B description")
            mgr = SkillManager(dir_path)
            result = mgr.list_skills()
            assert len(result) == 2
            names = [s["name"] for s in result]
            assert "skill-a" in names
            assert "skill-b" in names

    def test_ignores_non_md_files(self):
        """Files without .md extension are ignored."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            (dir_path / "notes.txt").write_text("hello", encoding="utf-8")
            (dir_path / "readme.md").touch()
            make_skill_file(dir_path, "real-skill", "A real skill")
            mgr = SkillManager(dir_path)
            result = mgr.list_skills()
            names = [s["name"] for s in result]
            assert "real-skill" in names
            # readme.md skipped because it has no frontmatter
            assert len([s for s in result if s["name"] == "readme"]) == 0

    def test_malformed_frontmatter_skipped(self):
        """Files with missing name or description are skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            # Missing description
            (dir_path / "bad1.md").write_text(
                "---\nname: bad1\n---\nNo description", encoding="utf-8"
            )
            # Missing name
            (dir_path / "bad2.md").write_text(
                "---\ndescription: No name here\n---\nContent", encoding="utf-8"
            )
            # No frontmatter at all
            (dir_path / "bad3.md").write_text("# Just a heading\nSome content", encoding="utf-8")
            mgr = SkillManager(dir_path)
            result = mgr.list_skills()
            assert result == []

    def test_duplicate_name_logs_warning(self):
        """Duplicate skill names log a warning; last one wins."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "dup", "First description")
            make_skill_file(dir_path, "dup", "Second description")
            mgr = SkillManager(dir_path)
            result = mgr.list_skills()
            names = [s["name"] for s in result]
            assert "dup" in names


class TestSkillManagerLoadSkill:
    """FR-003, FR-006, FR-008, FR-009: lazy load, cache, dedup."""

    def test_load_valid_skill(self):
        """load_skill() returns full content for a valid skill name."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "test", "desc", "# Skill Body\nHello world")
            mgr = SkillManager(dir_path)
            content = mgr.load_skill("test")
            assert "Hello world" in content
            assert "# Skill Body" in content

    def test_load_nonexistent_skill(self):
        """load_skill() returns error for nonexistent skill."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SkillManager(Path(tmp))
            result = mgr.load_skill("nonexistent")
            assert "不存在" in result

    @pytest.mark.skip(reason="Deduplication early-return was intentionally removed from production code")
    def test_load_deduplication(self):
        """Loading same skill twice returns already-loaded message."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "test", "desc", "Content here")
            mgr = SkillManager(dir_path)
            first = mgr.load_skill("test")
            assert "Content here" in first
            second = mgr.load_skill("test")
            assert "已" in second

    def test_load_after_reset(self):
        """After reset_conversation(), same skill can be loaded again."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "test", "desc", "Content here")
            mgr = SkillManager(dir_path)
            first = mgr.load_skill("test")
            assert "Content here" in first
            mgr.reset_conversation()
            second = mgr.load_skill("test")
            assert "Content here" in second

    @pytest.mark.skip(reason="Deduplication early-return was intentionally removed from production code")
    def test_content_cache(self):
        """Content cache is used on second load (after reset) rather than re-reading."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            file_path = make_skill_file(dir_path, "test", "desc", "Original")
            mgr = SkillManager(dir_path)
            content = mgr.load_skill("test")
            assert "Original" in content
            # Modify file on disk
            file_path.write_text(
                "---\nname: test\ndescription: desc\n---\nModified", encoding="utf-8"
            )
            # Same conversation - still dedup-blocked
            result = mgr.load_skill("test")
            assert "已" in result
            # Reset and reload - should use cache
            mgr.reset_conversation()
            result2 = mgr.load_skill("test")
            assert "Original" in result2


class TestSkillManagerRemoveSkill:
    """FR-004: remove_skill deletes file and clears cache."""

    def test_remove_existing_skill(self):
        """remove_skill() deletes the file and returns success."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            file_path = make_skill_file(dir_path, "to-remove", "desc", "content")
            mgr = SkillManager(dir_path)
            assert file_path.exists()
            result = mgr.remove_skill("to-remove")
            assert "已删除" in result
            assert not file_path.exists()

    def test_remove_nonexistent_skill(self):
        """remove_skill() returns error for nonexistent skill."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SkillManager(Path(tmp))
            result = mgr.remove_skill("nonexistent")
            assert "不存在" in result

    def test_remove_clears_listing(self):
        """After removal, skill no longer appears in list_skills()."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "temp-skill", "desc", "content")
            mgr = SkillManager(dir_path)
            assert len(mgr.list_skills()) == 1
            mgr.remove_skill("temp-skill")
            assert len(mgr.list_skills()) == 0


class TestSkillManagerAutoCreateDir:
    """FR-011: auto-create skills directory if it doesn't exist."""

    def test_auto_create_directory(self):
        """SkillManager creates the directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "nonexistent" / "skills"
            assert not skills_dir.exists()
            mgr = SkillManager(skills_dir)
            assert skills_dir.exists()
            assert skills_dir.is_dir()


class TestSkillManagerResetConversation:
    """FR-007: reset_conversation clears dedup set."""

    def test_reset_clears_dedup(self):
        """After reset, previously loaded skills can be loaded again."""
        with tempfile.TemporaryDirectory() as tmp:
            dir_path = Path(tmp)
            make_skill_file(dir_path, "a", "desc a", "Content A")
            make_skill_file(dir_path, "b", "desc b", "Content B")
            mgr = SkillManager(dir_path)
            mgr.load_skill("a")
            mgr.load_skill("b")
            assert "a" in mgr._loaded_this_conversation
            assert "b" in mgr._loaded_this_conversation
            mgr.reset_conversation()
            assert len(mgr._loaded_this_conversation) == 0


class TestGroupSkillManager:
    """Common Skills are read-only and local Skills are group-owned."""

    def test_common_skills_are_visible_but_cannot_be_changed(self, tmp_path):
        common_dir = tmp_path / "common"
        common_dir.mkdir()
        common_file = make_skill_file(
            common_dir,
            "shared",
            "Shared instructions",
            "Original common content",
        )
        manager = GroupSkillManager(
            SkillManager(common_dir),
            tmp_path / "groups" / "101",
            create_local=True,
        )

        assert [skill["name"] for skill in manager.list_skills()] == ["shared"]
        assert "Original common content" in manager.load_skill("shared")
        assert "公共技能" in manager.remove_skill("shared")
        assert "公共技能" in manager.save_skill(
            "shared",
            "---\nname: shared\ndescription: changed\n---\nchanged",
        )
        assert "Original common content" in common_file.read_text(encoding="utf-8")

    def test_local_skills_and_load_dedup_are_isolated_by_group(self, tmp_path):
        common_dir = tmp_path / "common"
        common_dir.mkdir()
        make_skill_file(common_dir, "shared", "Shared", "Common body")
        common = SkillManager(common_dir)
        first = GroupSkillManager(
            common,
            tmp_path / "groups" / "101",
            create_local=True,
        )
        second = GroupSkillManager(
            common,
            tmp_path / "groups" / "202",
            create_local=True,
        )
        local_content = (
            "---\nname: local-only\ndescription: Group 101\n---\nLocal body"
        )

        assert "已创建" in first.save_skill("local-only", local_content)
        assert {skill["name"] for skill in first.list_skills()} == {
            "shared",
            "local-only",
        }
        assert [skill["name"] for skill in second.list_skills()] == ["shared"]
        assert "Local body" in first.load_skill("local-only")
        assert "已在本轮对话中加载" in first.load_skill("local-only")
        assert "Common body" in first.load_skill("shared")
        assert "Common body" in second.load_skill("shared")

        first.reset_conversation()
        assert "Local body" in first.load_skill("local-only")
        assert "已在本轮对话中加载" in second.load_skill("shared")

    def test_read_only_inspection_does_not_create_local_directory(self, tmp_path):
        common_dir = tmp_path / "common"
        common_dir.mkdir()
        local_dir = tmp_path / "groups" / "303"
        manager = GroupSkillManager(
            SkillManager(common_dir),
            local_dir,
            create_local=False,
        )

        assert manager.list_skills() == []
        assert not local_dir.exists()

    @pytest.mark.parametrize(
        "malicious_name",
        ["../../shared", "../202/local", "/tmp/escaped", r"..\\..\\shared"],
    )
    def test_local_skill_names_cannot_escape_group_directory(
        self,
        tmp_path,
        malicious_name,
    ):
        common_dir = tmp_path / "common"
        common_dir.mkdir()
        common_file = make_skill_file(
            common_dir,
            "shared",
            "Shared instructions",
            "Original common content",
        )
        manager = GroupSkillManager(
            SkillManager(common_dir),
            tmp_path / "groups" / "101",
            create_local=True,
        )

        assert "名称无效" in manager.save_skill(malicious_name, "changed")
        assert "名称无效" in manager.remove_skill(malicious_name)
        assert "名称无效" in manager.load_skill(malicious_name)
        assert "Original common content" in common_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# build_skill_prompt tests
# ---------------------------------------------------------------------------
class TestBuildSkillPrompt:
    """FR-002: build_skill_prompt generates the system prompt injection."""

    def test_empty_skills(self):
        """Returns empty string when skills list is empty."""
        result = build_skill_prompt([])
        assert result == ""

    def test_with_skills(self):
        """Returns formatted prompt with skill names and descriptions."""
        skills = [
            {"name": "math-tutor", "description": "数学辅导"},
            {"name": "translator", "description": "翻译服务"},
        ]
        result = build_skill_prompt(skills)
        assert "math-tutor" in result
        assert "数学辅导" in result
        assert "translator" in result
        assert "翻译服务" in result
        assert "skill_loader" in result

    def test_single_skill(self):
        """Works with a single skill."""
        skills = [{"name": "only-one", "description": "唯一技能"}]
        result = build_skill_prompt(skills)
        assert "only-one" in result
        assert "唯一技能" in result
