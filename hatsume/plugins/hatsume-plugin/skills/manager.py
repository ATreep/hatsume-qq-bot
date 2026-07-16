"""SkillManager: scan, cache, load, and remove skill files."""

from __future__ import annotations

from pathlib import Path

import yaml


class SkillManager:
    """Manages skill files: scanning, lazy loading, caching, deduplication, removal."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        self._content_cache: dict[str, str] = {}
        self._loaded_this_conversation: set[str] = set()
        self._ensure_dir()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_skills(self) -> list[dict[str, str]]:
        """Scan the skills directory and return [{name, description}] for all valid skills.

        Only .md files with valid YAML frontmatter (name + description) are included.
        Files with duplicate names log a warning; last one wins.
        """
        self._ensure_dir()
        seen: dict[str, bool] = {}
        results: list[dict[str, str]] = []

        for file_path in sorted(self._skills_dir.iterdir()):
            if not file_path.suffix == ".md":
                continue
            meta = self._parse_frontmatter(file_path)
            if meta is None:
                continue

            name = meta["name"]
            if name in seen:
                print(f"⚠️ [skills] Duplicate skill name '{name}' — last file wins")
                results = [r for r in results if r["name"] != name]
            seen[name] = True
            results.append({"name": name, "description": meta["description"]})

        return results

    def load_skill(self, name: str) -> str:
        """Load a skill's full content by name.

        Returns the skill content on success, or an error message if not found.
        Deduplicates: returns an 'already loaded' message if called twice in
        the same conversation.
        """

        if name in self._content_cache:
            self._loaded_this_conversation.add(name)
            return self._content_cache[name]

        file_path = self._skills_dir / f"{name}.md"
        if not file_path.exists():
            print(f"⚠️ [skills] Skill '{name}' not found at expected path: {file_path}")
            return f"错误：技能 '{name}' 不存在。"

        try:
            content = file_path.read_text(encoding="utf-8")
            self._content_cache[name] = content
            self._loaded_this_conversation.add(name)
            print(f"✅ [skills] Loaded skill '{name}' successfully")
            return content
        except Exception as e:
            print(f"⚠️ [skills] Failed to read skill '{name}': {e}")
            return f"错误：无法读取技能 '{name}'：{e}"

    def remove_skill(self, name: str) -> str:
        """Remove a skill file from disk and clear its cache entry.

        Returns success message or error if the skill doesn't exist.
        """
        file_path = self._skills_dir / f"{name}.md"
        if not file_path.exists():
            return f"错误：技能 '{name}' 不存在。"

        try:
            file_path.unlink()
            self._content_cache.pop(name, None)
            return f"✅ 技能 '{name}' 已删除。"
        except Exception as e:
            return f"错误：删除技能 '{name}' 失败：{e}"

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

    def reset_conversation(self) -> None:
        """Clear the per-conversation deduplication set.

        Call this when a conversation ends so skills can be loaded again
        in the next conversation.
        """
        self._loaded_this_conversation.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_frontmatter(self, file_path: Path) -> dict[str, str] | None:
        """Parse YAML frontmatter from a .md file.

        Returns dict with 'name' and 'description' keys, or None if parsing fails
        or required fields are missing.
        """
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        yaml_text = parts[1].strip()
        if not yaml_text:
            return None

        try:
            meta = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict):
            return None

        name = str(meta.get("name", "")).strip()
        description = str(meta.get("description", "")).strip()

        if not name or not description:
            return None

        return {"name": name, "description": description}

    def parse_frontmatter_text(self, text: str) -> dict[str, str] | None:
        """Parse YAML frontmatter from raw text content.

        Returns dict with 'name' and 'description' keys, or None if parsing fails
        or required fields are missing. Only requires 'name' (description optional
        for download use case — caller can decide).
        """
        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        yaml_text = parts[1].strip()
        if not yaml_text:
            return None

        try:
            meta = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict):
            return None

        name = str(meta.get("name", "")).strip()
        description = str(meta.get("description", "")).strip()

        if not name:
            return None

        return {"name": name, "description": description}

    def _ensure_dir(self) -> None:
        """Create the skills directory if it doesn't exist."""
        self._skills_dir.mkdir(parents=True, exist_ok=True)
