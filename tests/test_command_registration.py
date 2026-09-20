"""Static checks for the plugin's slash-command registration surface."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_INIT = ROOT / "hatsume/plugins/hatsume-plugin/__init__.py"


def _registered_commands() -> set[str]:
    tree = ast.parse(PLUGIN_INIT.read_text(encoding="utf-8"))
    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "on_command" or not node.args:
            continue
        command = node.args[0]
        if isinstance(command, ast.Constant) and isinstance(command.value, str):
            commands.add(command.value)
    return commands


def test_removed_and_group_selectable_commands():
    commands = _registered_commands()

    assert "clear" not in commands
    assert "video" not in commands
    assert {"agents", "skills", "likerank", "resetsandbox"} <= commands
