"""Skill management sub-package.

Provides SkillManager for scanning, loading, caching, and removing skill files.
"""

from __future__ import annotations

from .manager import GroupSkillManager, SkillManager

__all__ = ["GroupSkillManager", "SkillManager", "get_skill_manager"]


# ---------------------------------------------------------------------------
# Singleton accessor (matching timer.get_store() pattern)
# ---------------------------------------------------------------------------
_common_skill_manager: SkillManager | None = None


def get_skill_manager(
    group_id: int | None = None,
    *,
    create_local: bool = True,
) -> GroupSkillManager:
    """Return the common-plus-local Skill view for one group."""
    from ..config import COMMON_SKILLS_DIR, GROUP_SKILLS_DIR
    from ..group_runtime import (
        get_current_group_runtime,
        group_runtime_registry,
        validate_group_id,
    )

    global _common_skill_manager
    if _common_skill_manager is None:
        _common_skill_manager = SkillManager(COMMON_SKILLS_DIR)

    runtime = None
    if group_id is None:
        runtime = get_current_group_runtime()
        assert runtime is not None
        resolved_group_id = runtime.group_id
    else:
        resolved_group_id = validate_group_id(group_id)
        runtime = group_runtime_registry.get_existing(resolved_group_id)

    if runtime is not None and runtime.skill_manager is not None:
        return runtime.skill_manager

    manager = GroupSkillManager(
        _common_skill_manager,
        GROUP_SKILLS_DIR / str(resolved_group_id),
        create_local=create_local,
    )
    if runtime is not None:
        runtime.skill_manager = manager
    return manager
