"""Small immutable-ish models used by the MCP manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    description: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    autoload: bool = False
    default_allowed: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, filename: str) -> "MCPServerConfig":
        name = str(value.get("name") or filename.rsplit(".", 1)[0]).strip()
        description = str(value.get("description", "")).strip()
        if not name or not description:
            raise ValueError("name and description are required")
        transport = str(value.get("transport", "stdio")).strip().lower()
        if transport not in {"stdio", "sse", "streamable-http"}:
            raise ValueError(f"unsupported transport: {transport}")
        if transport == "stdio" and not value.get("command"):
            raise ValueError("stdio MCP server requires command")
        if transport in {"sse", "streamable-http"} and not value.get("url"):
            raise ValueError(f"{transport} MCP server requires url")
        return cls(
            name=name,
            description=description,
            transport=transport,
            command=str(value["command"]) if value.get("command") else None,
            args=[str(item) for item in value.get("args", [])],
            url=str(value["url"]) if value.get("url") else None,
            env={str(k): str(v) for k, v in dict(value.get("env", {})).items()},
            headers={str(k): str(v) for k, v in dict(value.get("headers", {})).items()},
            enabled=bool(value.get("enabled", True)),
            autoload=bool(value.get("autoload", False)),
            default_allowed=bool(value.get("default_allowed", False)),
        )


@dataclass(slots=True, frozen=True)
class MCPToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
