"""Filesystem-backed, group-isolated MCP configuration store."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..config import MCP_DIR, MCP_GROUPS_DIR
from ..group_runtime import validate_group_id
from .models import MCPServerConfig


class MCPConfigStore:
    def __init__(self, root: Path = MCP_GROUPS_DIR, global_root: Path | None = None) -> None:
        """Store MCP JSON files with separate global and per-group scopes.

        ``root`` points at the isolated ``mcp/groups`` directory. Global
        server files live directly under ``mcp`` and are visible to every
        group. The optional ``global_root`` mainly makes the layout explicit
        and keeps temporary stores easy to test.
        """
        self.root = Path(root)
        self.global_root = Path(global_root) if global_root is not None else (
            MCP_DIR if self.root == MCP_GROUPS_DIR else self.root.parent
        )

    def group_dir(self, group_id: int) -> Path:
        return self.root / str(validate_group_id(group_id))

    def _list_directory(self, directory: Path) -> list[MCPServerConfig]:
        if not directory.exists():
            return []
        result: list[MCPServerConfig] = []
        for path in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("root must be an object")
                result.append(MCPServerConfig.from_dict(raw, filename=path.name))
            except Exception as exc:
                print(f"⚠️ [mcp] Ignoring invalid config {path}: {exc}")
        return result

    def list_global_servers(self) -> list[MCPServerConfig]:
        """Return MCP servers configured directly under the global MCP dir."""
        return self._list_directory(self.global_root)

    def list_group_servers(self, group_id: int) -> list[MCPServerConfig]:
        """Return only the MCP servers stored in one group's directory."""
        return self._list_directory(self.group_dir(group_id))

    def list_servers(self, group_id: int) -> list[MCPServerConfig]:
        """Return global servers merged with group-local overrides.

        A group-local file with the same server name takes precedence over the
        global file, allowing one group to customize or disable a shared
        server without changing the global configuration.
        """
        merged = {item.name: item for item in self.list_global_servers()}
        merged.update({item.name: item for item in self.list_group_servers(group_id)})
        return [merged[name] for name in sorted(merged)]

    def get_server(self, group_id: int, name: str) -> MCPServerConfig | None:
        normalized = self.validate_name(name)
        for server in self.list_servers(group_id):
            if server.name == normalized:
                return server
        return None

    def get_group_server(self, group_id: int, name: str) -> MCPServerConfig | None:
        normalized = self.validate_name(name)
        for server in self.list_group_servers(group_id):
            if server.name == normalized:
                return server
        return None

    def save_server(self, group_id: int, config: MCPServerConfig) -> None:
        directory = self.group_dir(group_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.validate_name(config.name)}.json"
        payload: dict[str, Any] = {
            "name": config.name,
            "description": config.description,
            "transport": config.transport,
            "enabled": config.enabled,
            "autoload": config.autoload,
            "default_allowed": config.default_allowed,
        }
        for key in ("command", "url"):
            value = getattr(config, key)
            if value is not None:
                payload[key] = value
        for key in ("args", "env", "headers"):
            value = getattr(config, key)
            if value:
                payload[key] = value
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)

    def remove_server(self, group_id: int, name: str) -> bool:
        path = self.group_dir(group_id) / f"{self.validate_name(name)}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def validate_name(name: str) -> str:
        value = str(name).strip()
        if not value or value in {".", ".."} or any(char in value for char in "/\\\0"):
            raise ValueError("invalid MCP server name")
        return value
