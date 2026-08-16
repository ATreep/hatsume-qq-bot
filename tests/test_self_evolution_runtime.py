"""Operational tests for the containerized self-evolution runtime."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER_DIR = ROOT / ".container"
SKILL_PATH = ROOT / "data/hatsume-plugin/skills/self-evolution.md"
PUBLIC_RESTART_HELPER = Path("/usr/local/bin/hatsume-restart")


def _load_skill_manager_class():
    path = ROOT / "hatsume/plugins/hatsume-plugin/skills/manager.py"
    spec = importlib.util.spec_from_file_location("self_evolution_skill_manager", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SkillManager


def test_supervisor_runs_nonebot_directly_and_supports_requested_restart():
    script = (CONTAINER_DIR / "supervise.sh").read_text(encoding="utf-8")

    assert "/work/hatsume/.venv/bin/python" in script
    assert "/work/hatsume/.container/run_bot.py" in script
    assert "RUNTIME_DIR=/run/hatsume" in script
    assert 'PID_FILE="${RUNTIME_DIR}/bot.pid"' in script
    assert 'RESTART_FILE="${RUNTIME_DIR}/restart.request"' in script
    assert "ENVIRONMENT=prod" in script
    assert 'export PATH="/work/hatsume/.container:' in script


def test_direct_runner_binds_nonebot_for_docker_networking():
    runner = (CONTAINER_DIR / "run_bot.py").read_text(encoding="utf-8")

    assert 'sys.path.insert(0, "/work/hatsume")' in runner
    assert "ONEBOT_V11Adapter" in runner
    assert 'host="0.0.0.0"' in runner
    assert "port=6999" in runner
    assert 'nonebot.load_from_toml("pyproject.toml")' in runner


def test_restart_helper_targets_recorded_bot_pid_after_a_delay():
    script = (CONTAINER_DIR / "hatsume-restart").read_text(encoding="utf-8")

    assert "RUNTIME_DIR=/run/hatsume" in script
    assert 'PID_FILE="${RUNTIME_DIR}/bot.pid"' in script
    assert 'RESTART_FILE="${RUNTIME_DIR}/restart.request"' in script
    assert "kill -TERM" in script
    assert "sleep" in script


def test_public_restart_command_targets_relocated_helper():
    assert PUBLIC_RESTART_HELPER.resolve() == CONTAINER_DIR / "hatsume-restart"


def test_self_evolution_skill_is_discoverable_and_contains_safety_contract():
    manager_class = _load_skill_manager_class()
    manager = manager_class(SKILL_PATH.parent, create_dir=False)

    listed = {item["name"]: item["description"] for item in manager.list_skills()}
    content = manager.load_skill("self-evolution")

    assert "self-evolution" in listed
    assert "/work/hatsume" in content
    assert "hatsume-restart" in content
    assert "AGENTS.md" in content
    assert "git status --short" in content
    assert "data/hatsume-plugin" in content
    assert "macOS" in content


def test_self_evolution_skill_restarts_directly_after_user_request_and_focused_tests():
    """When the user explicitly requested the change and the functional
    modification plus focused tests are complete, the skill restarts directly
    without asking for a second confirmation; check failures are no longer a
    hard gate, so the skill must not contain a "do not restart" rule."""
    manager_class = _load_skill_manager_class()
    manager = manager_class(SKILL_PATH.parent, create_dir=False)
    content = manager.load_skill("self-evolution")

    assert "user explicitly requested" in content
    assert "hatsume-restart" in content
    assert "focused tests" in content
    assert "do not restart" not in content
    assert "确认重启" not in content
    assert "回复确认" not in content


def test_self_evolution_skill_never_auto_approves_restart():
    """Restart is gated on the user explicitly requesting the change and all
    checks passing; default, timeout, or silence-based approval patterns are
    forbidden."""
    manager_class = _load_skill_manager_class()
    manager = manager_class(SKILL_PATH.parent, create_dir=False)
    content = manager.load_skill("self-evolution")

    for auto_approval in (
        "默认确认",
        "默认同意",
        "超时自动同意",
        "未收到回复视为同意",
        "自动确认",
        "视为同意",
        "auto-confirm",
        "auto-approve",
    ):
        assert auto_approval not in content


def test_self_evolution_skill_reports_checks_failures_without_hard_blocking_restart():
    """When checks fail, the skill reports the exact failure and evaluates
    whether it is related to this task; pre-existing baseline failures
    unrelated to this task do not automatically block the restart."""
    manager_class = _load_skill_manager_class()
    manager = manager_class(SKILL_PATH.parent, create_dir=False)
    content = manager.load_skill("self-evolution")

    assert "checks fail" in content
    assert "Report the exact failure" in content
    assert "related to this task" in content
    assert "baseline" in content
    assert "do not restart" not in content


def test_self_evolution_skill_waits_for_unfinished_agents_via_todo():
    """After finishing the modification, unfinished Agents gate the restart
    behind a Todo ('all Agents finished -> automatically restart'); with no
    unfinished Agent the bot restarts directly."""
    manager_class = _load_skill_manager_class()
    manager = manager_class(SKILL_PATH.parent, create_dir=False)
    content = manager.load_skill("self-evolution")

    assert "unfinished Agent" in content
    assert "Todo" in content
    assert "all Agents" in content
    assert "automatically restart" in content
    assert "restart directly" in content


def test_self_modification_restart_rule_documented_in_agents_files():
    """The unfinished-Agent -> Todo -> restart rule is part of the repository
    instruction contract for every self-modifying Agent."""
    root_agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    plugin_agents = (
        ROOT / "hatsume/plugins/hatsume-plugin/AGENTS.md"
    ).read_text(encoding="utf-8")

    assert "未完成的 Agent" in root_agents
    assert "Todo" in root_agents
    assert "自动重启" in root_agents
    assert "unfinished Agent" in plugin_agents
    assert "Todo" in plugin_agents
    assert "automatically restart" in plugin_agents
