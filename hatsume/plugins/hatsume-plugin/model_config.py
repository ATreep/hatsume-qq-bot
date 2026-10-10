"""Validated provider connections and model roles persisted in two YAML files.

No SDK or bot-framework imports: command handlers, migration tools and model
factories share this store without booting NoneBot. Credentials belong only in
providers.yml; a resolved role is an independent snapshot for one invocation.
"""

from __future__ import annotations

import copy
import math
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

CHAT_APIS = frozenset({"openai_chat_completions", "openai_responses", "google_genai"})
ROLE_APIS = {
    **{name: CHAT_APIS for name in ("advance", "lite", "mini", "coding", "vision")},
    "systemone": frozenset({"systemone"}),
    "embedding": frozenset({"openai_embeddings"}),
    "image_sensenova": frozenset({"sensenova_images"}),
}
ALL_APIS = frozenset().union(*ROLE_APIS.values())
REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
OPTION_KEYS = {
    "openai_chat_completions": frozenset(
        {"reasoning_effort", "temperature", "max_tokens"}
    ),
    "openai_responses": frozenset({"reasoning_effort", "temperature", "max_tokens"}),
    "google_genai": frozenset(
        {"thinking_budget", "thinking_level", "temperature", "max_tokens"}
    ),
    "openai_embeddings": frozenset({"chunk_size", "dimensions"}),
}
DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "data" / "hatsume-plugin"


class ModelConfigError(ValueError):
    """Actionable validation error which never includes a credential value."""


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ModelConfigError(
            "Provider IDs must contain only letters, digits, _ or -."
        )
    return value


def validate_options(api: str, options: Any) -> dict[str, Any]:
    if not isinstance(options, dict) or any(not isinstance(k, str) for k in options):
        raise ModelConfigError("Model options must be a mapping with string keys.")
    if set(options) - OPTION_KEYS.get(api, frozenset()):
        raise ModelConfigError(f"Unsupported model option for API {api}.")
    for key, value in options.items():
        if key == "reasoning_effort":
            if not isinstance(value, str) or value not in REASONING_EFFORTS:
                raise ModelConfigError("Invalid reasoning_effort.")
        elif key == "thinking_level":
            if value not in ("minimal", "low", "medium", "high"):
                raise ModelConfigError("Invalid thinking_level.")
        elif key == "temperature":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 2
            ):
                raise ModelConfigError(
                    "temperature must be a finite number between 0 and 2."
                )
        else:
            minimum = -1 if key == "thinking_budget" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ModelConfigError(f"{key} must be an integer >= {minimum}.")
    if "thinking_budget" in options and "thinking_level" in options:
        raise ModelConfigError("Choose thinking_budget or thinking_level, not both.")
    return copy.deepcopy(options)


def _validate(providers: Any, roles: Any) -> None:
    if not isinstance(providers, dict) or not isinstance(roles, dict):
        raise ModelConfigError("providers and roles must be mappings.")
    for name, item in providers.items():
        _identifier(name)
        if not isinstance(item, dict) or set(item) != {
            "base_url",
            "api_key",
            "supported_apis",
        }:
            raise ModelConfigError(
                f"Provider {name} requires base_url, api_key and supported_apis."
            )
        url = item["base_url"]
        if not isinstance(url, str):
            raise ModelConfigError(f"Provider {name} needs an HTTP(S) base URL.")
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme in ("http", "https")
                and parsed.hostname
                and not (
                    parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                )
            )
        except ValueError:
            valid = False
        if not valid:
            raise ModelConfigError(
                f"Provider {name} needs an HTTP(S) base URL without credentials, query or fragment."
            )
        if not isinstance(item["api_key"], str):
            raise ModelConfigError(f"Provider {name} api_key must be a string.")
        apis = item["supported_apis"]
        if (
            not isinstance(apis, list)
            or any(not isinstance(api, str) or api not in ALL_APIS for api in apis)
            or len(set(apis)) != len(apis)
        ):
            raise ModelConfigError(f"Provider {name} has invalid supported_apis.")
    for role, item in roles.items():
        if role not in ROLE_APIS:
            raise ModelConfigError("Unknown model role.")
        if not isinstance(item, dict) or set(item) != {
            "provider",
            "api",
            "model",
            "options",
        }:
            raise ModelConfigError(
                f"Role {role} requires provider, api, model and options."
            )
        provider, api, model = item["provider"], item["api"], item["model"]
        if not isinstance(provider, str) or provider not in providers:
            raise ModelConfigError(f"Role {role} references an unknown provider.")
        if (
            not isinstance(api, str)
            or api not in ROLE_APIS[role]
            or api not in providers[provider]["supported_apis"]
        ):
            raise ModelConfigError(
                f"Role {role} uses an API unsupported by the role or provider."
            )
        if (
            not isinstance(model, str)
            or not model.strip()
            or model != model.strip()
            or any(char.isspace() for char in model)
        ):
            raise ModelConfigError(f"Role {role} needs a model ID without whitespace.")
        validate_options(api, item["options"])


class ModelConfigStore:
    def __init__(self, root: Path = DEFAULT_ROOT):
        self.root = Path(root)
        self.providers_path = self.root / "providers.yml"
        self.models_path = self.root / "models.yml"
        self._lock = threading.RLock()

    @staticmethod
    def _read(path: Path, key: str) -> dict:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # YAML diagnostics can contain the failing line and therefore a key.
            raise ModelConfigError(
                f"Cannot read {path.name}; check its YAML syntax and permissions."
            ) from None
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema_version", key}
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] != 1
        ):
            raise ModelConfigError(f"{path.name} requires schema_version: 1 and {key}.")
        return raw[key]

    @staticmethod
    def _write(path: Path, key: str, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                yaml.safe_dump(
                    {"schema_version": 1, key: value},
                    stream,
                    allow_unicode=True,
                    sort_keys=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load(self) -> tuple[dict, dict]:
        # Empty first-run stores allow administrators to configure via commands.
        # Never reset one missing file while the other still exists.
        exists = (self.providers_path.exists(), self.models_path.exists())
        if exists == (False, False):
            self._write(self.providers_path, "providers", {})
            self._write(self.models_path, "roles", {})
        elif not all(exists):
            raise ModelConfigError(
                "Both providers.yml and models.yml are required; restore the missing file."
            )
        providers = self._read(self.providers_path, "providers")
        roles = self._read(self.models_path, "roles")
        _validate(providers, roles)
        return providers, roles

    def snapshot(self, *, include_keys: bool = False) -> tuple[dict, dict]:
        with self._lock:
            providers, roles = self._load()
            if not include_keys:
                providers = {
                    name: {
                        key: value for key, value in item.items() if key != "api_key"
                    }
                    | {"key_configured": bool(item["api_key"])}
                    for name, item in providers.items()
                }
            return copy.deepcopy(providers), copy.deepcopy(roles)

    def resolve(self, role: str, *, require_key: bool = True) -> dict:
        with self._lock:
            providers, roles = self._load()
            if role not in roles:
                raise ModelConfigError(
                    f"Role {role} is not configured. Use /model use {role} <provider> <model>."
                )
            result = copy.deepcopy(roles[role])
            connection = providers[result["provider"]]
            if require_key and not connection["api_key"].strip():
                raise ModelConfigError(
                    f"Provider {result['provider']} has no API key; set it directly in providers.yml."
                )
            return result | {
                "base_url": connection["base_url"],
                "api_key": connection["api_key"],
            }

    def provider_connection(self, name: str) -> dict:
        with self._lock:
            providers, _ = self._load()
            if name not in providers:
                raise ModelConfigError("Unknown provider.")
            return copy.deepcopy(providers[name])

    def save_provider(
        self,
        name: str,
        *,
        base_url: str | None = None,
        supported_apis: list[str] | None = None,
        api_key: str | None = None,
        create: bool = False,
    ) -> None:
        _identifier(name)
        with self._lock:
            providers, roles = self._load()
            if create == (name in providers):
                raise ModelConfigError(
                    "Provider already exists." if create else "Unknown provider."
                )
            item = copy.deepcopy(
                providers.get(
                    name, {"base_url": "", "api_key": "", "supported_apis": []}
                )
            )
            if base_url is not None:
                item["base_url"] = base_url.rstrip("/")
            if supported_apis is not None:
                item["supported_apis"] = list(supported_apis)
            if api_key is not None:
                item["api_key"] = api_key.strip()
            providers[name] = item
            _validate(providers, roles)
            self._write(self.providers_path, "providers", providers)

    def remove_provider(self, name: str) -> None:
        with self._lock:
            providers, roles = self._load()
            if name not in providers:
                raise ModelConfigError("Unknown provider.")
            used = [role for role, item in roles.items() if item["provider"] == name]
            if used:
                raise ModelConfigError(
                    "Provider is still used by roles: " + ", ".join(used)
                )
            del providers[name]
            self._write(self.providers_path, "providers", providers)

    def use_model(
        self, role: str, provider: str, model: str, api: str | None = None
    ) -> None:
        with self._lock:
            providers, roles = self._load()
            if role not in ROLE_APIS or provider not in providers:
                raise ModelConfigError("Unknown model role or provider.")
            available = ROLE_APIS[role].intersection(
                providers[provider]["supported_apis"]
            )
            previous = roles.get(role)
            if api is None:
                if (
                    previous
                    and previous["provider"] == provider
                    and previous["api"] in available
                ):
                    api = previous["api"]
                elif len(available) == 1:
                    api = next(iter(available))
                else:
                    raise ModelConfigError(
                        "Specify --api; the provider has multiple or no compatible APIs."
                    )
            # Model/API switches reset options: settings for the previous model
            # (e.g. reasoning support) must not silently leak into a new model.
            unchanged = previous and (
                previous["provider"],
                previous["api"],
                previous["model"],
            ) == (provider, api, model)
            options = previous["options"] if unchanged else {}
            roles[role] = {
                "provider": provider,
                "api": api,
                "model": model,
                "options": options,
            }
            _validate(providers, roles)
            self._write(self.models_path, "roles", roles)

    def set_option(self, role: str, key: str, value: Any) -> None:
        with self._lock:
            providers, roles = self._load()
            if role not in roles:
                raise ModelConfigError("Model role is not configured.")
            options = roles[role]["options"]
            if value is None:
                options.pop(key, None)
            else:
                options[key] = value
            _validate(providers, roles)
            self._write(self.models_path, "roles", roles)


_store = ModelConfigStore()


def get_model_config_store() -> ModelConfigStore:
    return _store
