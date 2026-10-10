"""Slash command operations independent of NoneBot and secret-bearing messages."""

from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any

from .model_config import ModelConfigError, ModelConfigStore

MODEL_HELP = """/model 或 /model list — 查看所有模型角色
/model <model> — 切换高级模型（使用当前供应商/API）
/model use <role> <provider> <model> [--api <api>]
/model options <role> <key> <value> — null 删除该选项
/model check <role> — 发送一条短请求检查聊天模型
角色：advance, lite, mini, coding, vision, systemone, embedding,
image_sensenova"""
PROVIDER_HELP = """/provider list
/provider show <id>
/provider add <id> --base-url <完整URL> --api <api[,api]>
/provider update <id> [--base-url <完整URL>] [--api <api[,api]>]
/provider remove <id>
API Key 只直接写入 providers.yml，请勿通过聊天发送。
聊天 API：openai_chat_completions, openai_responses, google_genai"""


def _parts(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        raise ModelConfigError("命令引号未闭合。") from None


def _flags(parts: list[str], allowed: set[str]) -> tuple[list[str], dict[str, str]]:
    args: list[str] = []
    flags: dict[str, str] = {}
    index = 0
    while index < len(parts):
        value = parts[index]
        if value.startswith("--"):
            if (
                value not in allowed
                or value in flags
                or index + 1 == len(parts)
                or parts[index + 1].startswith("--")
            ):
                raise ModelConfigError("命令参数无效；使用 help 查看格式。")
            flags[value] = parts[index + 1]
            index += 2
        else:
            args.append(value)
            index += 1
    return args, flags


def _display_roles(store: ModelConfigStore) -> str:
    _, roles = store.snapshot()
    if not roles:
        return "尚未配置模型。\n" + MODEL_HELP
    lines = []
    for name, item in roles.items():
        options = json.dumps(item["options"], ensure_ascii=False, sort_keys=True)
        lines.append(
            f"{name}: {item['provider']} / {item['model']} [{item['api']}] {options}"
        )
    return "\n".join(lines)


async def model_command(store: ModelConfigStore, text: str) -> str:
    parts = _parts(text)
    if parts == ["help"]:
        return MODEL_HELP
    if not parts or parts == ["list"]:
        return _display_roles(store)
    if len(parts) == 1 and parts[0] not in ("use", "options", "check"):
        _, roles = store.snapshot()
        if "advance" not in roles:
            raise ModelConfigError(
                "请先用 /model use advance <provider> <model> 配置高级模型。"
            )
        current = roles["advance"]
        store.use_model("advance", current["provider"], parts[0], current["api"])
        return "✅ 高级模型已保存。\n" + _display_roles(store)
    if parts[0] == "use":
        args, flags = _flags(parts[1:], {"--api"})
        if len(args) != 3:
            raise ModelConfigError(MODEL_HELP)
        store.use_model(*args, api=flags.get("--api"))
        return "✅ 模型配置已保存，下一次调用生效。\n" + _display_roles(store)
    if parts[0] == "options" and len(parts) == 4:
        raw = parts[3]
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        store.set_option(parts[1], parts[2], value)
        return "✅ 模型选项已保存。\n" + _display_roles(store)
    if parts[0] == "check" and len(parts) == 2:
        from .model_factory import create_chat_model

        settings = store.resolve(parts[1])
        try:
            model = create_chat_model(settings)
            # The caller explicitly requested one small paid API request.
            await asyncio.wait_for(model.ainvoke("Reply with OK."), timeout=30)
        except Exception as exc:
            # SDK errors can contain the request, URL, or credentials. Report
            # only the status/type and never the raw exception or model reply.
            status = getattr(exc, "status_code", None)
            suffix = f"HTTP {status}" if isinstance(status, int) else type(exc).__name__
            return f"❌ 模型检查失败：{suffix}。"
        return f"✅ {parts[1]} 检查成功：{settings['provider']} / {settings['model']} [{settings['api']}]"
    raise ModelConfigError(MODEL_HELP)


def provider_command(store: ModelConfigStore, text: str) -> str:
    parts = _parts(text)
    if parts == ["help"]:
        return PROVIDER_HELP
    if not parts or parts == ["list"]:
        providers, _ = store.snapshot()
        return (
            "\n".join(
                f"{name}: {', '.join(item['supported_apis']) or '本轮不支持'}；Key {'已配置' if item['key_configured'] else '未配置'}"
                for name, item in providers.items()
            )
            or "尚未配置供应商。\n" + PROVIDER_HELP
        )
    if parts[0] == "show" and len(parts) == 2:
        providers, _ = store.snapshot()
        item = providers.get(parts[1])
        if item is None:
            raise ModelConfigError("Unknown provider.")
        return json.dumps({parts[1]: item}, ensure_ascii=False, indent=2)
    if parts[0] in ("add", "update"):
        args, flags = _flags(parts[1:], {"--base-url", "--api"})
        if (
            len(args) != 1
            or not flags
            or (parts[0] == "add" and set(flags) != {"--base-url", "--api"})
        ):
            raise ModelConfigError(PROVIDER_HELP)
        store.save_provider(
            args[0],
            base_url=flags.get("--base-url"),
            supported_apis=flags["--api"].split(",") if "--api" in flags else None,
            create=parts[0] == "add",
        )
        return "✅ 供应商配置已保存。"
    if parts[0] == "remove" and len(parts) == 2:
        store.remove_provider(parts[1])
        return "✅ 供应商已移除。"
    raise ModelConfigError(PROVIDER_HELP)
