"""Skill management sub-package.

Provides SkillManager for scanning, loading, caching, and removing skill files.
"""

from __future__ import annotations

from .manager import SkillManager

__all__ = ["SkillManager", "get_skill_manager"]


# ---------------------------------------------------------------------------
# Singleton accessor (matching timer.get_store() pattern)
# ---------------------------------------------------------------------------
_skill_manager: SkillManager | None = None


def get_skill_manager() -> SkillManager:
    """Get or create the global SkillManager singleton."""
    global _skill_manager
    if _skill_manager is None:
        from ..config import SKILLS_DIR
        _skill_manager = SkillManager(SKILLS_DIR)
    return _skill_manager
