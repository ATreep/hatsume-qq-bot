"""LangGraph nodes backed by the task-local per-group runtime.

Human, detect, AI, and finish nodes share the runtime selected by the current
graph invocation. Mutable queues, flags, callbacks, proxy state, and Skill state
belong to that runtime; only node definitions and immutable tool topology are
common across groups.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import inspect
import json
import random
import re
import time
import traceback
from collections.abc import Iterator, Mapping
from typing import Any

import nonebot_plugin_localstore as store
from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages import RemoveMessage
from langgraph.graph import MessagesState
from nonebot.adapters.onebot.v11 import MessageSegment
from pydantic import BaseModel

from ..config import ADMIN_QQ_ID, BOT_QQ_ID, CONTEXT_QUEUE_LEN, LIVELY_TONE_ENABLED
from ..errors import (
    LLMAuthError,
    LLMBaseError,
    LLMLimitExceededError,
)
from ..group_runtime import (
    get_current_group_runtime,
    group_runtime_registry,
)
from ..models import get_advance_model, get_intent_model, get_lite_model, get_mini_model
from ..provider_switch import (
    SLOW_THRESHOLD_SECONDS,
    get_model_provider,
    report_chat_elapsed,
)
from ..prompts import (
    AUXILIARY_COMPACTION_PROMPT,
    CHAT_END_DETECT_PROMPT,
    CHAT_INTENT_URGENCY_TYPES,
    build_admin_mode_prompt,
    build_agent_state_prompt,
    build_face_injection_prompt,
    build_lively_tone_prompt,
    build_mcp_server_prompt,
    build_memory_context_prompt,
    build_skill_prompt,
    role_sys_prompt,
)
from ..skills import get_skill_manager
from ..state import peer_session_id
from ..utils import (
    CQ_AT_PATTERN,
    get_date,
    get_group_member_name,
    message_to_json,
    strip_thinking_tags,
)
from .tools import (
    get_chat_tools,
    get_current_group_id,
    get_timer_overview,
    query_memory,
    reset_capture_flag,
    set_shell_executor_limit,
)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
FACE_TAG_PATTERN = re.compile(r"\[[ \t]*hatsumeface:(.*?)\]")
MEMORY_RECORD_PATTERN = re.compile(
    r"\[[ \t]*memory:[ \t]*(?P<content>.*?)"
    r"[ \t]*MEMORYCONTENTEND"
    r"(?:[ \t]*,[ \t]*keyman:[ \t]*(?P<keyman>[^\]\r\n]*))?"
    r"[ \t]*\]",
    re.DOTALL,
)
REPLY_DIRECTIVE_PATTERN = re.compile(r"\[[ \t]*reply:\s*([^\]\r\n]*)\]")
NON_TEXT_MARK_PATTERN = re.compile(
    r"\[[ \t]*[^\[\]:\r\n]+:[^\]\r\n]*\]"
)
JSON_CODE_FENCE_PATTERN = re.compile(
    r"^\s*```(?:json)?[ \t]*\r?\n(?P<json>.*?)\r?\n[ \t]*```\s*$",
    re.IGNORECASE | re.DOTALL,
)
SYSTEM_TRIGGER_KEY = "_hatsume_system_trigger"
ADMIN_MODE_KEYWORD = "BYPASS"

CHAT_INTENT_MAX_ATTEMPTS = 3


class ChatIntentJudgeResult(BaseModel):
    """Structured response decision returned by the intent model."""

    is_response: bool
    urgency_type: str = ""
    brief_reason: str = ""


def _prompt_module_attr(name: str, default: Any = "") -> Any:
    from .. import prompts as prompt_module

    return getattr(prompt_module, name, default)


def _get_soul_prompt() -> str:
    loader = _prompt_module_attr("get_soul_prompt")
    if callable(loader):
        try:
            return str(loader()).strip()
        except Exception:
            traceback.print_exc()
    return str(_prompt_module_attr("soul", "")).strip()


def _get_chat_intend_judge_prompt() -> str:
    return str(
        _prompt_module_attr(
            "CHAT_INTEND_JUDGE_PROMPT",
            "判断当前对话是否需要回复，只输出结构化 JSON 判断结果。",
        )
    ).strip()


def _normalize_chat_intend_judge_json(content: str) -> str:
    """Remove one optional Markdown JSON fence emitted by some providers."""
    content = strip_thinking_tags(content)
    match = JSON_CODE_FENCE_PATTERN.fullmatch(content)
    return match.group("json").strip() if match else content


def _parse_chat_intend_judge_result(result: Any) -> ChatIntentJudgeResult:
    """Parse the judge model's direct JSON text response."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            if isinstance(part, Mapping)
            else str(part)
            for part in content
        )
    if not isinstance(content, str):
        raise ValueError("chat_intend_judge returned non-text output")

    parsed = json.loads(_normalize_chat_intend_judge_json(content))
    if not isinstance(parsed, Mapping):
        raise ValueError("chat_intend_judge JSON output must be an object")
    return ChatIntentJudgeResult.model_validate(dict(parsed))


def _chat_intent_is_eligible(result: ChatIntentJudgeResult) -> bool:
    return bool(
        result.is_response
        and result.urgency_type in CHAT_INTENT_URGENCY_TYPES
        and result.urgency_type != "无需回复"
        and result.brief_reason.strip()
    )


def _message_contains_system_trigger(value: Any) -> bool:
    if isinstance(value, Mapping):
        if SYSTEM_TRIGGER_KEY in value:
            return True
        return any(_message_contains_system_trigger(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_message_contains_system_trigger(item) for item in value)
    return False


def _has_injected_human_message(state: MessagesState) -> bool:
    if _runtime().last_was_system_trigger:
        return True
    return any(
        _message_contains_system_trigger(getattr(message, "content", message))
        for message in state.get("messages", [])
        if getattr(message, "type", None) == "human"
    )


def _combined_system_prompt() -> str:
    role_prompt = get_role_sys_prompt()
    soul_prompt = _get_soul_prompt()
    if role_prompt and soul_prompt:
        return role_prompt + "\n\n" + soul_prompt
    return role_prompt or soul_prompt


def _result_reason(result: ChatIntentJudgeResult | None, error: Exception | None = None) -> str:
    if result is not None and result.brief_reason.strip():
        return result.brief_reason.strip()
    if error is not None:
        return f"chat_intend_judge 无法完成判断：{error}"
    return "chat_intend_judge 判断当前不需要回复。"


async def _invoke_model(model: Any, messages: list[Any]) -> Any:
    """Invoke a model directly without provider-specific structured output."""
    ainvoke = getattr(model, "ainvoke", None)
    if callable(ainvoke):
        result = ainvoke(messages)
        if inspect.isawaitable(result):
            return await result
        return result

    invoke = getattr(model, "invoke", None)
    if not callable(invoke):
        raise TypeError("chat_intend_judge model does not support invoke")
    return invoke(messages)


async def chat_intend_judge(
    model: Any,
    messages: list[Any],
) -> ChatIntentJudgeResult:
    """Judge whether the current human turn warrants a visible response.

    Tracks consecutive rate-limit / quota errors and fails fast after three
    back-to-back hits so that retries don't just burn API quota on a hard
    limit.
    """
    judge_messages = [
        SystemMessage(_get_chat_intend_judge_prompt()),
        *_without_image_url_parts(messages),
    ]
    consecutive_limit_errors = 0
    for attempt in range(1, CHAT_INTENT_MAX_ATTEMPTS + 1):
        try:
            result = await _invoke_model(model, judge_messages)
            consecutive_limit_errors = 0  # Reset on success
            try:
                return _parse_chat_intend_judge_result(result)
            except Exception:
                raw_response = getattr(result, "content", result)
                print(
                    "[chat_intend_judge] original llm response: "
                    f"{raw_response!r}"
                )
                raise
        except LLMLimitExceededError:
            consecutive_limit_errors += 1
            print(
                f"[chat_intend_judge] rate limit hit (attempt {attempt}/"
                f"{CHAT_INTENT_MAX_ATTEMPTS}), consecutive={consecutive_limit_errors}"
            )
            if consecutive_limit_errors >= 3 or attempt == CHAT_INTENT_MAX_ATTEMPTS:
                raise LLMLimitExceededError(
                    "模型请求过于频繁或配额已用完，请稍后再试。"
                )
        except LLMBaseError:
            if attempt == CHAT_INTENT_MAX_ATTEMPTS:
                raise
            print(f"[chat_intend_judge] attempt {attempt}/{CHAT_INTENT_MAX_ATTEMPTS} failed; retrying")
        except Exception:
            if attempt == CHAT_INTENT_MAX_ATTEMPTS:
                raise
            print(f"[chat_intend_judge] attempt {attempt}/{CHAT_INTENT_MAX_ATTEMPTS} failed; retrying")

    raise RuntimeError("chat_intend_judge exhausted retry attempts")

def _runtime():
    return get_current_group_runtime()


def _conversation_state():
    return _runtime().conversation


def bind_state(conversation_state: Any) -> None:
    """Compatibility hook that binds a group-owned ConversationState."""
    runtime = group_runtime_registry.get_or_create(int(conversation_state.group_id))
    if runtime.conversation is not conversation_state:
        runtime.conversation = conversation_state
        runtime.reset_tool_callbacks()



# ---------------------------------------------------------------------------
# Memory record extraction
# ---------------------------------------------------------------------------
def _extract_memory_records(text: str) -> tuple[list[dict], str]:
    """Extract all sentinel-delimited memory cards and remove them from text."""
    records: list[dict] = []

    def _collect(match: re.Match[str]) -> str:
        content = match.group("content").strip()
        qq_numbers: list[int] = []
        for part in (match.group("keyman") or "").split(","):
            try:
                qq_number = int(part.strip())
            except ValueError:
                continue
            if qq_number not in qq_numbers:
                qq_numbers.append(qq_number)
        if content:
            records.append({"content": content, "qq_numbers": qq_numbers})
        return ""

    cleaned = MEMORY_RECORD_PATTERN.sub(_collect, text)
    return records, cleaned.strip()


# ---------------------------------------------------------------------------
# User-id extraction from message content
# ---------------------------------------------------------------------------
def extract_user_ids_from_content(content: Any) -> list[int]:
    """Extract user IDs from message content structure."""
    user_ids: list[int] = []
    seen: set[int] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "user" in obj and isinstance(obj["user"], dict):
                uid = obj["user"].get("id")
                if uid is not None:
                    try:
                        uid_int = int(uid)
                        if uid_int not in seen and uid_int != 0:
                            seen.add(uid_int)
                            user_ids.append(uid_int)
                    except (TypeError, ValueError):
                        pass
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(content)
    return user_ids


def is_admin_mode_message(content: Any, admin_qq_id: int | str) -> bool:
    """Return whether this round contains an authenticated ADMIN MODE message."""
    configured_admin_id = str(admin_qq_id).strip()
    if not configured_admin_id:
        return False

    parts = content if isinstance(content, list) else [content]
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            raw_text = part.get("text")
        elif isinstance(part, str):
            raw_text = part
        else:
            continue

        if not isinstance(raw_text, str):
            continue
        try:
            normalized = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(normalized, dict) or normalized.get("type") != "message":
            continue

        sender = normalized.get("user")
        if not isinstance(sender, dict):
            continue
        if str(sender.get("id")) != configured_admin_id:
            continue

        direct_content = normalized.get("content")
        if isinstance(direct_content, str) and ADMIN_MODE_KEYWORD in direct_content:
            return True

    return False


def _without_image_url_parts(messages: list[Any]) -> list[Any]:
    """Copy messages as needed while removing model image URL content parts."""
    filtered_messages: list[Any] = []
    for message in messages:
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", None)
        )
        if not isinstance(content, list):
            filtered_messages.append(message)
            continue

        filtered_content = [
            part
            for part in content
            if not (
                isinstance(part, dict)
                and part.get("type") in {"image_url", "img_url"}
            )
        ]
        if len(filtered_content) == len(content):
            filtered_messages.append(message)
        elif isinstance(message, dict):
            filtered_messages.append({**message, "content": filtered_content})
        elif callable(getattr(message, "model_copy", None)):
            filtered_messages.append(
                message.model_copy(update={"content": filtered_content})
            )
        else:
            filtered_message = copy.copy(message)
            filtered_message.content = filtered_content
            filtered_messages.append(filtered_message)

    return filtered_messages


def _without_bootstrap_role_prompt(messages: list[Any]) -> list[Any]:
    """Remove the graph bootstrap role prompt already owned by chat_agent."""
    if not messages:
        return messages

    first_message = messages[0]
    if (
        getattr(first_message, "type", None) == "system"
        and getattr(first_message, "content", None) == get_role_sys_prompt()
    ):
        return messages[1:]
    return messages


def _normalized_message_sender_id(normalized: Mapping[str, Any]) -> int | None:
    """Return the sender QQ of one normalized top-level message when usable."""
    user = normalized.get("user")
    if not isinstance(user, Mapping):
        return None
    raw_id = user.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
        return None
    return raw_id


def _iter_replyable_top_level_messages(
    messages: list[Any],
) -> Iterator[tuple[int, int | None]]:
    """Yield ``(message_id, sender_qq_id)`` for each replyable top-level JSON.

    Only ``HumanMessage`` content is inspected, and only text parts whose
    complete text parses as one normalized JSON object. Nested objects such as
    ``reply_to`` and forward children are never recursed into, so a user cannot
    smuggle a foreign ID through embedded JSON.
    """
    for message in messages:
        if getattr(message, "type", None) != "human":
            continue

        content = getattr(message, "content", "")
        text_parts: list[str] = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                elif isinstance(part, str):
                    text_parts.append(part)

        for text in text_parts:
            try:
                normalized = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(normalized, dict):
                continue
            if normalized.get("type") not in {"message", "forward"}:
                continue
            message_id = normalized.get("message_id")
            if not isinstance(message_id, int) or isinstance(message_id, bool):
                continue
            yield message_id, _normalized_message_sender_id(normalized)


def _extract_replyable_message_ids(messages: list[Any]) -> set[int]:
    """Collect top-level OneBot message IDs from human JSON shown to chat_agent."""
    return {
        message_id
        for message_id, _sender_id in _iter_replyable_top_level_messages(messages)
    }


def _extract_replyable_senders(messages: list[Any]) -> dict[int, int]:
    """Map each replyable top-level message ID to its sender QQ.

    IDs without a usable sender are omitted: they stay replyable but cannot
    promote anyone into ``chat_peers``.
    """
    senders: dict[int, int] = {}
    for message_id, sender_id in _iter_replyable_top_level_messages(messages):
        if sender_id is not None:
            senders.setdefault(message_id, sender_id)
    return senders


def _register_chat_peer(conversation_state: Any, user_id: int) -> str | None:
    """Add one group member to the owning conversation's chat peers.

    Returns the session id when the member is a valid peer, or ``None`` when the
    id is unusable or belongs to the bot itself.
    """
    group_id = getattr(conversation_state, "group_id", None)
    if (
        isinstance(group_id, bool)
        or not isinstance(group_id, int)
        or group_id <= 0
        or isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
        or user_id == BOT_QQ_ID
    ):
        return None

    session_id = peer_session_id(group_id, user_id)
    peers = conversation_state.chat_peers
    if session_id not in peers:
        peers.add(session_id)
        print(f"[chat_agent] Registered chat peer: {session_id}")
    return session_id


def _register_addressed_chat_peers(
    conversation_state: Any,
    *,
    reply_to_message_id: int | None,
    replyable_senders: Mapping[int, int],
    visible_text: str,
) -> None:
    """Register everyone this Agent response addresses as a chat peer.

    A native reply or an ``@`` mention means the Agent is talking to that
    member, so their later messages belong to the active conversation instead of
    the auxiliary context. Registration happens as soon as the directive and the
    visible text are known, so a failed or suppressed send cannot silently drop
    the relationship.
    """
    if reply_to_message_id is not None:
        sender_id = replyable_senders.get(reply_to_message_id)
        if sender_id is not None:
            _register_chat_peer(conversation_state, sender_id)

    for match in CQ_AT_PATTERN.finditer(visible_text):
        _register_chat_peer(conversation_state, int(match.group(1)))


def _parse_reply_directive(
    text: str,
    replyable_ids: set[int],
) -> tuple[str, int | None]:
    """Strip reply tags and return one valid leading target when available."""
    matches = list(REPLY_DIRECTIVE_PATTERN.finditer(text))
    cleaned = REPLY_DIRECTIVE_PATTERN.sub("", text).strip()
    if len(matches) != 1:
        return cleaned, None

    match = matches[0]
    if text[: match.start()].strip():
        return cleaned, None

    try:
        target = int(match.group(1).strip())
    except ValueError:
        return cleaned, None
    if target not in replyable_ids:
        return cleaned, None
    return cleaned, target


def _message_text(message: Any) -> str:
    """Return user-facing text from an AI message, ignoring tool messages.

    Thinking/reasoning blocks (``<think>...</think>`` and variants) are
    stripped so they never reach the user; the same content stays in the
    graph-state AIMessage for later model turns.
    """
    if getattr(message, "type", None) != "ai":
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return strip_thinking_tags(
            "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        )
    return strip_thinking_tags(str(content or ""))


def _has_visible_text(text: str) -> bool:
    """Return whether text contains more than model control marks."""
    without_thinking = strip_thinking_tags(text)
    without_memory = MEMORY_RECORD_PATTERN.sub("", without_thinking)
    without_known_marks = FACE_TAG_PATTERN.sub("", without_memory)
    without_known_marks = REPLY_DIRECTIVE_PATTERN.sub("", without_known_marks)
    return bool(NON_TEXT_MARK_PATTERN.sub("", without_known_marks).strip())


def _new_agent_messages(
    invocation_messages: list[Any], response_messages: list[Any]
) -> list[Any]:
    """Return messages appended by one agent invocation."""
    input_count = len(invocation_messages)
    if (
        len(response_messages) >= input_count
        and response_messages[:input_count] == invocation_messages
    ):
        return response_messages[input_count:]
    return response_messages


def _contains_tool_calls(messages: list[Any]) -> bool:
    """Return whether an agent response contains any tool invocation.

    A retry after a tool-only response is allowed to turn the tool result into
    user-facing text, but must not replay side-effecting tools such as agent
    dispatch or direct media sends.
    """
    for message in messages:
        tool_calls = (
            message.get("tool_calls")
            if isinstance(message, Mapping)
            else getattr(message, "tool_calls", None)
        )
        if tool_calls:
            return True
    return False


# ---------------------------------------------------------------------------
# Notification injection (agent & timer)
# ---------------------------------------------------------------------------
def make_system_trigger_message(text: str, trigger_type: str) -> dict[str, str]:
    """Build an internally marked queue entry for non-human graph input."""
    return {
        "type": "text",
        "text": text,
        SYSTEM_TRIGGER_KEY: trigger_type,
    }


def _build_notified_user_prompt(user_id: int, user_name: str | None = None) -> str:
    if user_id == 0:
        return ""

    display_name = (user_name or "").strip() or str(user_id)
    return (
        "## 被通知用户\n"
        f"- 用户名：{display_name}\n"
        f"- QQ号：{user_id}\n"
        f"- 如需提醒该用户，可在输出中插入 [CQ:at,qq={user_id}]；不要频繁 at。\n\n"
    )


def inject_agent_notification(
    user_id: int,
    group_id: int,
    agent_name: str,
    result: str,
    task: str,
    context: str = "",
    notified_user_name: str | None = None,
    start_conversation_cb: Any = None,
) -> None:
    """Inject an agent result into the conversation flow."""
    context_line = f"📋 派发背景：{context}\n" if context else ""
    notified_user_prompt = _build_notified_user_prompt(user_id, notified_user_name)
    notify_msg = (
        f"(SYSTEM) Agent '{agent_name}' 执行完毕。\n"
        f"{notified_user_prompt}"
        f"{context_line}"
        f"请简单提及任务原文内容，然后告诉用户执行结果。\n\n"
        f"## 该 Agent 执行的任务原文\n\n"
        "```\n"
        f"{task[:200]}\n\n"
        "```\n"
        f"## Agent 执行结果\n\n"
        f"{result}"
    )

    print(notify_msg)

    runtime = group_runtime_registry.get_or_create(group_id)
    state = runtime.conversation
    queued_message = make_system_trigger_message(notify_msg, "agent")
    # A graph can still be draining its final turn after ``is_chatting`` has
    # been cleared. Keep the notification on that graph's queue so a second
    # graph is not started for the same completion event.
    if state.is_chatting or getattr(state, "is_graph_running", False):
        if queued_message not in state.human_queue:
            state.human_queue.append(queued_message)
        else:
            print(
                f"🧩 [inject_agent_notification] Ignored duplicate result for {agent_name}"
            )
        print(f"🧩 [inject_agent_notification] Injected {agent_name} result into human_queue")
    else:
        if start_conversation_cb is not None:
            print(f"🧩 [inject_agent_notification] Starting new conversation for {agent_name} result")
            start_conversation_cb(user_id, group_id, notify_msg)
        else:
            _start_direct_conv(user_id, group_id, notify_msg)



def inject_timer(
    user_id: int,
    group_id: int,
    timer_prompt: str,
    start_conversation_cb: Any = None,
    notified_user_name: str | None = None,
) -> None:
    """Inject a timer prompt into the conversation flow.

    Args:
        user_id: QQ user ID to notify (0 means no user to @-mention).
    """
    # user_id=0: no user to notify.
    if user_id == 0:
        timer_msg = timer_prompt
        print(f"⏰ [inject_timer] timer (no user): {timer_prompt[:80]}...")
    else:
        notified_user_prompt = _build_notified_user_prompt(user_id, notified_user_name)
        timer_msg = (
            f"(SYSTEM) 定时任务已触发。\n"
            f"{notified_user_prompt}"
            f"{timer_prompt}"
        )
        print(f"⏰ [inject_timer] Timer message for user {user_id}: {timer_prompt[:80]}...")

    runtime = group_runtime_registry.get_or_create(group_id)
    state = runtime.conversation
    if state.is_chatting:
        state.human_queue.append(make_system_trigger_message(timer_msg, "timer"))
        print(f"⏰ [inject_timer] Injected timer into human_queue for user {user_id}")
    else:
        if start_conversation_cb is not None:
            print(f"⏰ [inject_timer] Starting new conversation for timer (user {user_id})")
            start_conversation_cb(user_id, group_id, timer_msg)
        else:
            _start_direct_conv(user_id, group_id, timer_msg)


def inject_hook(
    *,
    group_id: int,
    hook_name: str,
    prompt: str,
    event_text: str,
    notified_user_ids: list[int] | None = None,
    start_conversation_cb: Any = None,
) -> None:
    """Inject one Hook event into the owning group's conversation flow."""
    normalized_name = str(hook_name).strip() or "unnamed"
    normalized_prompt = str(prompt).strip()
    normalized_event = str(event_text).strip()
    normalized_notified_user_ids: list[int] = []
    for user_id in notified_user_ids or []:
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            continue
        if user_id not in normalized_notified_user_ids:
            normalized_notified_user_ids.append(user_id)
    if not normalized_event:
        raise ValueError("Hook event text must not be empty")
    notification_instruction = ""
    if normalized_notified_user_ids:
        notified = " ".join(
            f"[CQ:at,qq={user_id}]" for user_id in normalized_notified_user_ids
        )
        notification_instruction = (
            "## 处理与通知要求\n"
            "本事件指定了必须通知的相关用户。请在面向群的最终回复中使用以下 CQ at 标记"
            f"逐一提及他们，不要遗漏、替换或额外 at 无关用户：{notified}\n"
            "如果这是不可重复的一次性事件（例如活动开始、截止时间到达），请在完成本次"
            f"事件处理的同一轮调用 delete_hook 删除 Hook '{normalized_name}'，避免重复通知。\n"
            "如果用户要求持续监听，则不要删除 Hook；当下一轮的监听条件、目标或基准需要"
            "随本次事件推进（例如追剧进度或最新新闻游标）时，请在同一轮调用 update_hook，"
            "同步更新提示词和脚本，确保后续监听基于最新状态。\n\n"
        )
    hook_msg = (
        f"(SYSTEM) Hook '{normalized_name}' 监听的事件已触发。\n"
        "## 用户给定的 Hook 指令\n"
        f"{normalized_prompt}\n\n"
        f"{notification_instruction}"
        "## Hook 事件说明\n"
        f"{normalized_event}"
    )
    runtime = group_runtime_registry.get_or_create(group_id)
    state = runtime.conversation
    if state.is_chatting:
        state.human_queue.append(make_system_trigger_message(hook_msg, "hook"))
        print(f"🪝 [inject_hook] Injected Hook {normalized_name} into human_queue")
        return
    if start_conversation_cb is not None:
        start_conversation_cb(0, group_id, hook_msg)
    else:
        _start_direct_conv(0, group_id, hook_msg, trigger_type="hook")


def _start_direct_conv(
    user_id: int,
    group_id: int,
    notify_msg: str,
    *,
    trigger_type: str = "timer",
) -> None:
    """Start a new graph conversation targeting a specific group directly.

    Used when no callback is registered (e.g., /autoresponse debug command).
    Sends messages to the target group via bot.send_group_msg().
    """
    from ..handlers.dialogue import _start_conv_for_trigger

    _start_conv_for_trigger(
        user_id,
        group_id,
        notify_msg,
        trigger_type=trigger_type,
    )


# ---------------------------------------------------------------------------
# Role prompt & auxiliary queue management
# ---------------------------------------------------------------------------
def get_role_sys_prompt() -> str:
    return role_sys_prompt


def _select_compaction_model() -> Any:
    model_chosen = get_mini_model()
    if random.randint(0, 2) == 0:
        model_chosen = get_lite_model()
        print("Using lite model for compaction...")
    else:
        print("Using mini model for compaction...")
    return model_chosen


AUXILIARY_IMAGE_PLACEHOLDER = "[图片]"


def _image_part_url(part: Any) -> str:
    """Return the URL of an ``image_url`` / ``img_url`` content part."""
    if not isinstance(part, dict):
        return ""
    if part.get("type") not in {"image_url", "img_url"}:
        return ""
    value = part.get("image_url", part.get("img_url"))
    if isinstance(value, dict):
        value = value.get("url")
    return value if isinstance(value, str) else ""


def _without_auxiliary_image_payloads(messages: list[dict]) -> list[dict]:
    """Replace inline ``data:`` image parts with a short text placeholder.

    Auxiliary context identifies an image by its sandbox path, which already
    appears in the entry's text (``![图片](/tmp/...)``).  Carrying the base64
    payload as well only inflates every later request that consumes the queue
    -- most importantly the compaction call -- without adding information, so
    inline payloads are dropped at the queue boundary.  Small network image
    URLs are kept as-is.
    """
    cleaned: list[dict] = []
    for message in messages:
        if _image_part_url(message).startswith("data:"):
            cleaned.append({"type": "text", "text": AUXILIARY_IMAGE_PLACEHOLDER})
        else:
            cleaned.append(message)
    return cleaned


def _summarize_auxiliary_messages(model: Any, queue: list[dict]) -> str:
    result = model.invoke(
        [
            SystemMessage(AUXILIARY_COMPACTION_PROMPT),
            HumanMessage(_without_auxiliary_image_payloads(queue)),  # type: ignore
        ]
    )
    return result.content.__str__()


async def _summarize_auxiliary_messages_async(
    model: Any, queue: list[dict]
) -> str:
    result = await _invoke_model(
        model,
        [
            SystemMessage(AUXILIARY_COMPACTION_PROMPT),
            HumanMessage(_without_auxiliary_image_payloads(queue)),  # type: ignore
        ],
    )
    return result.content.__str__()


def _trim_auxiliary_queue(runtime: Any) -> None:
    queue = runtime.auxiliary_messages_queue
    overflow = len(queue) - CONTEXT_QUEUE_LEN
    if overflow > 0:
        del queue[:overflow]
    runtime.auxiliary_source_queue.clear()


def _compact_auxiliary_messages_sync(runtime: Any) -> None:
    if len(runtime.auxiliary_messages_queue) <= CONTEXT_QUEUE_LEN:
        return
    try:
        summary = _summarize_auxiliary_messages(
            _select_compaction_model(),
            list(runtime.auxiliary_messages_queue),
        )
        runtime.auxiliary_messages_queue.clear()
        runtime.auxiliary_messages_queue.append(
            {"type": "text", "text": "### 历史聊天记录总结：" + summary}
        )
        runtime.auxiliary_source_queue.clear()
    except Exception:
        print("❌ Failed to summarize auxiliary messages")
        traceback.print_exc()
        _trim_auxiliary_queue(runtime)


def append_auxiliary_message(
    messages: list[dict], source_entries: list[dict] | None = None
) -> None:
    """Append auxiliary context for synchronous callers and tests.

    Async handlers should use :func:`append_auxiliary_message_async` so a slow
    compaction call cannot block the NoneBot event loop.
    """
    if not messages:
        return
    runtime = _runtime()
    runtime.auxiliary_messages_queue.extend(
        _without_auxiliary_image_payloads(messages)
    )
    runtime.auxiliary_source_queue.extend(source_entries or [])
    _compact_auxiliary_messages_sync(runtime)


async def append_auxiliary_message_async(
    messages: list[dict], source_entries: list[dict] | None = None
) -> None:
    """Append auxiliary context without blocking the event loop on compaction.

    Compaction has no wall-clock cap: the provider can legitimately need longer
    than a minute for a full queue, and aborting the call would discard the
    summary and leave the queue to be trimmed instead.
    """
    if not messages:
        return
    runtime = _runtime()
    runtime.auxiliary_messages_queue.extend(
        _without_auxiliary_image_payloads(messages)
    )
    runtime.auxiliary_source_queue.extend(source_entries or [])
    if len(runtime.auxiliary_messages_queue) <= CONTEXT_QUEUE_LEN:
        return

    async with runtime.auxiliary_compaction_lock:
        if len(runtime.auxiliary_messages_queue) <= CONTEXT_QUEUE_LEN:
            return
        queue_snapshot = list(runtime.auxiliary_messages_queue)
        source_count = len(runtime.auxiliary_source_queue)
        try:
            summary = await _summarize_auxiliary_messages_async(
                _select_compaction_model(),
                queue_snapshot,
            )
            runtime.auxiliary_messages_queue[:len(queue_snapshot)] = [
                {"type": "text", "text": "### 历史聊天记录总结：" + summary}
            ]
            del runtime.auxiliary_source_queue[:source_count]
        except Exception:
            print("❌ Failed to summarize auxiliary messages")
            traceback.print_exc()
            _trim_auxiliary_queue(runtime)


def _snapshot_auxiliary_queue() -> tuple[list[dict], list[dict]]:
    """Return a non-destructive snapshot of the auxiliary queues."""
    runtime = _runtime()
    return (
        runtime.auxiliary_messages_queue.copy(),
        runtime.auxiliary_source_queue.copy(),
    )




# ---------------------------------------------------------------------------
# Shared state accessors
# ---------------------------------------------------------------------------
def _get_ai_answer() -> Any:
    return _conversation_state().ai_answer


def _get_human_queue() -> list[dict]:
    return _conversation_state().human_queue


def _clear_human_queue() -> None:
    state = _conversation_state()
    state.human_queue.clear()
    state.human_source_queue.clear()


def _set_graph_running(value: bool) -> None:
    _conversation_state().is_graph_running = value


def _set_current_query_user_id(uid: int | None) -> None:
    _conversation_state().current_query_user_id = uid


def set_current_query_user_id(uid: int | None) -> None:
    _set_current_query_user_id(uid)


def _build_current_todo_prompt() -> str:
    """Delete expired todos and build the current group's prompt section."""
    from ..prompts import build_todo_prompt

    try:
        from ..todo import get_store

        todo_store = get_store()
        deleted = todo_store.delete_expired()
        if deleted:
            print(f"[todo] Deleted {deleted} expired item(s)")
        group_id = get_current_group_id()
        if group_id is None or group_id <= 0:
            return build_todo_prompt([], available=False)
        return build_todo_prompt(todo_store.list_items(group_id))
    except Exception:
        print("❌ Failed to load todo prompt")
        traceback.print_exc()
        return build_todo_prompt([], available=False)


# ===========================================================================
# Graph nodes
# ===========================================================================

# ---------------------------------------------------------------------------
# AI node
# ---------------------------------------------------------------------------
async def ai_node(state: MessagesState) -> dict:
    """Generate AI response using LLM with tools and memory."""
    runtime = _runtime()
    conversation_state = runtime.conversation
    print("Enter ai_node")
    reset_capture_flag()
    t_start = time.time()

    _MEMORY_TOTAL_LIMIT = 50
    last_content = state["messages"][-1].content
    chatting_user_ids = extract_user_ids_from_content(last_content)
    admin_mode_enabled = is_admin_mode_message(last_content, ADMIN_QQ_ID)

    aux_queue, aux_sources = _snapshot_auxiliary_queue()
    if aux_queue:
        last_human_content = state["messages"][-1].content
        if isinstance(last_human_content, str):
            last_human_content = [{"type": "text", "text": last_human_content}]
        merged_content = (
            [{"type": "text", "text": "## 背景聊天记录："}]
            + aux_queue
            + [{"type": "text", "text": "## 当前聊天记录："}]
            + last_human_content
        )
        last_human_msg: Any = HumanMessage(merged_content)  # type: ignore
    else:
        last_human_msg = HumanMessage(state["messages"][-1].content)

    print("Start chat intent judge...")
    t_judge_start = time.time()
    if _has_injected_human_message(state):
        print("[chat_intend_judge] Bypassed for injected system message")
    else:
        try:
            # Jev is a System One model: send the current state and a closed
            # Choice question to its ``/systemone`` endpoint.  The model does
            # not generate JSON text, so the selected label can be consumed
            # directly without the old chat-model parser.
            intent_model = get_intent_model()
            intent_message = _without_image_url_parts([last_human_msg])[0]
            intent_state = getattr(intent_message, "content", intent_message)
            try:
                json.dumps(intent_state, ensure_ascii=False)
            except TypeError:
                intent_state = str(intent_state)

            intent_response = await intent_model.root_async_client.post(
                "/systemone",
                cast_to=object,
                body={
                    "model": getattr(intent_model, "model_name", "jev-1.13-free"),
                    "state": intent_state,
                    "questions": {
                        "chat_intent": {
                            "type": "choice",
                            "instructions": "当前消息最符合哪一种意图？",
                            "criteria": CHAT_INTENT_URGENCY_TYPES,
                        }
                    },
                },
            )
            intent_answer = intent_response["answers"]["chat_intent"]
            intent_choice = str(intent_answer.get("choice", "无需回复"))
            intent_confidence = intent_answer.get("confidence")
            intent_reason = f"Jev 选择“{intent_choice}”"
            if intent_confidence is not None:
                intent_reason += f"，置信度 {float(intent_confidence):.2f}"
            intent_result = ChatIntentJudgeResult(
                is_response=(
                    intent_choice in CHAT_INTENT_URGENCY_TYPES
                    and intent_choice != "无需回复"
                ),
                urgency_type=(
                    intent_choice
                    if intent_choice in CHAT_INTENT_URGENCY_TYPES
                    else ""
                ),
                brief_reason=intent_reason,
            )
        except Exception as exc:
            reason = _result_reason(None, exc)
            print(f"[chat_intend_judge] Response skipped: {reason}")
            return {"messages": []}

        if not _chat_intent_is_eligible(intent_result):
            reason = _result_reason(intent_result)
            print(f"[chat_intend_judge] Response skipped: {reason}")
            return {"messages": []}

        print(
            "[chat_intend_judge] Response approved: "
            f"{intent_result.urgency_type} ({intent_result.brief_reason.strip()})"
        )
    t_judge_end = time.time()
    print(f"Elapsed time of chat_intend_judge: {t_judge_end - t_judge_start:.3f}s")

    if isinstance(last_content, list) and len(last_content) > 0:
        text_parts: list[str] = []
        for part in last_content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = str(part.get("text", "")).strip()
                if t:
                    text_parts.append(t)
            elif isinstance(part, str) and part.strip():
                text_parts.append(part.strip())
        if text_parts:
            per_item = _MEMORY_TOTAL_LIMIT // len(text_parts)
            mem_parts: list[str] = []
            for text in reversed(text_parts):
                mem = query_memory(text, user_ids=chatting_user_ids, max_results=per_item)
                if mem:
                    mem_parts.append(mem)
            memory_summary = "\n".join(mem_parts)
        else:
            memory_summary = ""
    else:
        memory_summary = query_memory(str(last_content), user_ids=chatting_user_ids)

    print("Memory retrieved: \n" + memory_summary)

    chat_provider_used = get_model_provider()
    model_chosen = get_advance_model(thinking=True)
    sys_prompt = _combined_system_prompt()
    sys_prompt += build_lively_tone_prompt(LIVELY_TONE_ENABLED)
    if admin_mode_enabled:
        sys_prompt += build_admin_mode_prompt(ADMIN_QQ_ID)
        print("[admin] Enabled ADMIN MODE")

    from ..character_proxy import (
        build_active_character_proxy_role_prompt,
        get_character_proxy,
    )

    character_proxy = get_character_proxy()
    if character_proxy is not None:
        sys_prompt += "\n\n" + build_active_character_proxy_role_prompt(
            character_proxy
        )

    # Inject available skills into system prompt
    skill_mgr = get_skill_manager()
    skill_list = skill_mgr.list_skills()
    skill_prompt = build_skill_prompt(skill_list)
    if skill_prompt:
        sys_prompt += skill_prompt
        print(f"[skills] Injected {len(skill_list)} skill(s) into system prompt")

    from ..mcp.manager import get_mcp_manager

    mcp_servers = [item for item in get_mcp_manager().list_servers() if item.enabled]
    mcp_prompt = build_mcp_server_prompt([
        {"name": item.name, "description": item.description}
        for item in mcp_servers
    ])
    if mcp_prompt:
        sys_prompt += mcp_prompt
        print(f"[mcp] Injected {len(mcp_servers)} server description(s) into system prompt")

    # Inject running agent states into system prompt
    agent_prompt = build_agent_state_prompt()
    if agent_prompt:
        sys_prompt += agent_prompt
        print("[agents] Injected agent state info into system prompt")

    timer_overview = await get_timer_overview()
    sys_prompt += "\n\n" + timer_overview
    print("[timers] Injected timer overview into system prompt")

    sys_prompt += _build_current_todo_prompt()
    print("[todo] Injected todo policy and active items into system prompt")

    # Inject the available face-mark vocabulary on every invocation.
    _face_dict: dict[str, list[str]] = {}
    face_list = [
        f.name
        for f in store.get_plugin_data_file("faces").iterdir()
        if f.is_file() and f.name.lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    for fname in face_list:
        emotion = fname.split("_")[0]
        _face_dict.setdefault(emotion, []).append(fname)
    emotions = list(_face_dict.keys())
    face_prompt = build_face_injection_prompt(emotions)

    if face_prompt:
        sys_prompt += face_prompt
        print(f"[face] Injected face prompt with {len(emotions)} emotions")

    sys_prompt += f"\n\n# 当前日期与时间\n{get_date()}"

    ai_text: str = ""
    llm_error_type: str | None = None  # Track specific error type for user-facing messages
    replyable_message_ids: set[int] = set()  # Init to satisfy static analysis; always set in try block
    replyable_senders: dict[int, int] = {}  # Same: message_id -> sender QQ
    try:
        mem_msg = (
            []
            if memory_summary.strip() == ""
            else [
                HumanMessage(build_memory_context_prompt(memory_summary))
            ]
        )
        conversation_history = _without_bootstrap_role_prompt(
            state["messages"][:-1]
        )
        agent_messages = conversation_history + mem_msg + [last_human_msg]
        if admin_mode_enabled:
            agent_messages = _without_image_url_parts(agent_messages)
        replyable_message_ids = _extract_replyable_message_ids(agent_messages)
        replyable_senders = _extract_replyable_senders(agent_messages)

        print("Start chat_agent invocation.")

        t_invocation_start = time.monotonic()

        set_shell_executor_limit(3)  # chat_agent: max 3 shell_executor calls per round
        invocation_messages = agent_messages
        response_texts: list[str] = []
        active_mcp_tools: list[Any] = []
        retry_without_tools = False
        for attempt in range(2):
            t_pass_start = time.monotonic()
            tools_for_attempt = (
                []
                if retry_without_tools
                else get_chat_tools() + active_mcp_tools
            )
            chat_agent = create_agent(
                model_chosen,
                tools=tools_for_attempt,
                system_prompt=sys_prompt,
            )
            retrying_agent = chat_agent.with_retry(stop_after_attempt=5)
            try:
                response = await retrying_agent.ainvoke(
                    {"messages": invocation_messages},  # type: ignore
                    {"recursion_limit": 20},
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failed_elapsed = time.monotonic() - t_invocation_start
                switched_to = report_chat_elapsed(
                    failed_elapsed,
                    provider=chat_provider_used,
                    started_at=t_invocation_start,
                )
                print(
                    f"[chat_agent] pass={attempt + 1} failed "
                    f"elapsed={time.monotonic() - t_pass_start:.3f}s",
                    flush=True,
                )
                if switched_to is not None:
                    print(
                        f"[provider-switch] failed chat_agent took "
                        f"{failed_elapsed:.1f}s; switching provider "
                        f"'{chat_provider_used}' -> '{switched_to}'",
                        flush=True,
                    )
                raise
            response_messages = response.get("messages", [])
            from ..mcp.tools import consume_requested_tools, make_dynamic_tools

            requested = consume_requested_tools()
            print(
                f"[chat_agent] pass={attempt + 1} completed "
                f"elapsed={time.monotonic() - t_pass_start:.3f}s "
                f"requested_mcp={requested!r} active_mcp_tools={len(active_mcp_tools)}",
                flush=True,
            )
            if requested and attempt == 0:
                grouped: dict[str, list[str]] = {}
                for server_name, tool_name in requested:
                    grouped.setdefault(server_name, []).append(tool_name)
                for server_name, names in grouped.items():
                    try:
                        infos = await get_mcp_manager().discover_tools(server_name)
                    except Exception as exc:
                        print(
                            f"⚠️ [mcp] Skipping unavailable server "
                            f"{server_name!r}: {type(exc).__name__}: {exc}"
                        )
                        continue
                    active_mcp_tools.extend(make_dynamic_tools(
                        server_name,
                        [item for item in infos if item.name in names],
                    ))
                invocation_messages = response_messages
                continue
            new_messages = _new_agent_messages(
                invocation_messages, response_messages
            )
            for message in new_messages[:-1]:
                control_text = _message_text(message)
                if control_text and not _has_visible_text(control_text):
                    response_texts.append(control_text)
            current_text = (
                _message_text(new_messages[-1]) if new_messages else ""
            )
            if current_text:
                response_texts.append(current_text)
            if (
                _has_visible_text(current_text)
                or conversation_state.end_requested
                or attempt == 1
            ):
                break
            print("No visible AI text returned; invoking chat_agent again...")
            if response_messages:
                invocation_messages = response_messages
            # The first pass may have already performed an irreversible tool
            # action.  The follow-up pass only needs to phrase its result; it
            # must not be able to invoke the same tool a second time.
            retry_without_tools = _contains_tool_calls(new_messages)

        ai_text = "\n".join(response_texts)

        t_invocation_end = time.monotonic()

        elapsed_invocation = t_invocation_end - t_invocation_start
        print(f"Elapsed time of chat_agent invocation: {elapsed_invocation}s")

        # Provider auto-switching: a slow (>150s) chat_agent invocation marks
        # the current provider slow (3h cooldown) and switches the standard
        # model to the next healthy candidate (ruoli <-> waw).
        switched_to = report_chat_elapsed(
            elapsed_invocation,
            provider=chat_provider_used,
            started_at=t_invocation_start,
        )
        if switched_to is not None:
            print(
                f"[provider-switch] chat_agent took {elapsed_invocation:.1f}s "
                f"(> {SLOW_THRESHOLD_SECONDS:.0f}s); switching provider "
                f"'{chat_provider_used}' -> '{switched_to}'"
            )
        elif elapsed_invocation > SLOW_THRESHOLD_SECONDS:
            current_provider = get_model_provider()
            if current_provider == chat_provider_used:
                print(
                    f"[provider-switch] chat_agent took {elapsed_invocation:.1f}s "
                    f"(> {SLOW_THRESHOLD_SECONDS:.0f}s) but all candidate "
                    f"providers are in cooldown; staying on '{chat_provider_used}'"
                )
            else:
                print(
                    f"[provider-switch] chat_agent took {elapsed_invocation:.1f}s "
                    f"(> {SLOW_THRESHOLD_SECONDS:.0f}s); provider is already "
                    f"'{current_provider}' after another invocation"
                )

        # LLM outputs plain text directly
        print(f"Raw AI response: {ai_text}")
    except LLMLimitExceededError:
        llm_error_type = "rate_limit"
        ai_text = ""
    except LLMAuthError:
        llm_error_type = "auth_error"
        ai_text = ""
    except Exception:
        llm_error_type = "other"
        ai_text = ""
        print("❌ Bad invoke in chat_agent")
        traceback.print_exc()

    # ── Handle LLM-specific errors before any output processing ──
    if llm_error_type == "rate_limit":
        _err_answer = _get_ai_answer()
        if _err_answer:
            await _err_answer("⚠️ 模型请求过于频繁或配额已用完，请稍后再试。")
        return {"messages": []}
    if llm_error_type == "auth_error":
        _err_answer = _get_ai_answer()
        if _err_answer:
            await _err_answer("❌ 模型认证失败，请检查配置。")
        return {"messages": []}

    ai_text_clean, reply_to_message_id = _parse_reply_directive(
        str(ai_text),
        replyable_message_ids,
    )

    # ── Extract face tag from ai_text ──
    face_emotion: str | None = None
    match = FACE_TAG_PATTERN.search(ai_text_clean)
    if match:
        face_emotion = match.group(1).strip()
        ai_text_clean = FACE_TAG_PATTERN.sub("", ai_text_clean).strip()
        print(f"[face] Detected face tag: {face_emotion}")

    # ── Extract memory record from ai_text ──
    mem_records, ai_text_clean = _extract_memory_records(ai_text_clean)
    if mem_records:
        print(f"[memory] Extracted {len(mem_records)} memory record(s)")

    ai_text_clean = ai_text_clean.strip()

    # The Agent just addressed specific members: the native reply target and
    # every @ mention. Promote them into chat_peers so their following messages
    # keep joining this conversation instead of the auxiliary context.
    _register_addressed_chat_peers(
        conversation_state,
        reply_to_message_id=reply_to_message_id,
        replyable_senders=replyable_senders,
        visible_text=ai_text_clean,
    )

    # Keep the model response unchanged in graph history. Control tags are
    # parsed and removed only from the user-facing text above.
    ai_text_history = str(ai_text)
    end_requested = conversation_state.end_requested
    if end_requested:
        print("[end_conversation] Suppressed the final AI reply.")
    else:
        if ai_text_clean:
            _ai_answer = _get_ai_answer()
            if _ai_answer:
                if reply_to_message_id is not None:
                    await _ai_answer(
                        ai_text_clean,
                        reply_to_message_id=reply_to_message_id,
                    )
                else:
                    await _ai_answer(ai_text_clean)

    t_mem_start = time.time()

    # ── Resolve QQ numbers → usernames and save memory record ──
    from ..memory import add_mem
    for mem_record in mem_records:
        content = str(mem_record.get("content", "")).strip()
        qq_numbers = mem_record.get("qq_numbers", [])
        if content:
            people: list[dict] = []
            current_group_id = get_current_group_id()
            if qq_numbers and current_group_id is not None:
                try:
                    bot = group_runtime_registry.get_bot(current_group_id)
                    for qq in qq_numbers:
                        user_name = await get_group_member_name(
                            bot, current_group_id, qq
                        )
                        people.append({"user_id": qq, "user_name": user_name})
                except Exception as e:
                    print(f"[memory] Failed to resolve usernames for QQ numbers: {e}")
            add_mem(content, people=people)

    t_mem_end = time.time()

    # ── Send face image if tag matched a valid emotion ──
    _ai_answer_cb = _get_ai_answer()
    if (
        not end_requested
        and face_emotion
        and _face_dict.get(face_emotion)
        and _ai_answer_cb
    ):
        face_filename = random.choice(_face_dict[face_emotion])
        print(f"[face] Send face: {face_filename}")
        face_path = str(store.get_plugin_data_file("faces").absolute()) + "/" + face_filename
        with open(face_path, "rb") as f:
            base64_str = base64.b64encode(f.read()).decode("utf-8")
        face_msg = MessageSegment.image("base64://" + base64_str, cache=False)
        try:
            await _ai_answer_cb(face_msg)
        except Exception:
            print("❌ Failed to send face image")
            traceback.print_exc()

    print(f"Elapsed time of ai_node: t_writing_mem={t_mem_end - t_mem_start}s, t_chat_agent={t_mem_start - t_start}s")
    messages = [AIMessage(ai_text_history)]
    return {"messages": messages}


# ---------------------------------------------------------------------------
# Human node
# ---------------------------------------------------------------------------
async def human_node(state: MessagesState) -> dict:
    runtime = _runtime()
    conversation_state = runtime.conversation
    print("Enter human_node")

    if conversation_state.end_requested:
        runtime.last_was_auxiliary_only = False
        runtime.last_was_system_trigger = False
        return {"messages": [SystemMessage("__end__")]}

    t_start = time.time()
    while not _get_human_queue():
        await asyncio.sleep(0.3)
        if time.time() - t_start >= 60 * 5:
            runtime.last_was_auxiliary_only = (
                not _get_human_queue() and bool(runtime.auxiliary_messages_queue)
            )
            runtime.last_was_system_trigger = False
            return {"messages": [SystemMessage("__end__")]}

    human_queue = _get_human_queue().copy()
    _clear_human_queue()

    runtime.last_was_auxiliary_only = (
        not human_queue and bool(runtime.auxiliary_messages_queue)
    )
    runtime.last_was_system_trigger = any(
        isinstance(part, dict) and SYSTEM_TRIGGER_KEY in part
        for part in human_queue
    )
    human_queue = [
        {key: value for key, value in part.items() if key != SYSTEM_TRIGGER_KEY}
        if isinstance(part, dict)
        else part
        for part in human_queue
    ]

    return {"messages": [HumanMessage(human_queue)]}  # type: ignore


# ---------------------------------------------------------------------------
# Chat-end detection node
# ---------------------------------------------------------------------------
async def chat_end_detect_node(state: MessagesState) -> dict:
    print("Enter chat_end_detect_node")

    if _runtime().last_was_system_trigger:
        return {"messages": []}

    from ..character_proxy import message_mentions_character_proxy

    if message_mentions_character_proxy(state["messages"][-1].content):
        print("[character_proxy] Nickname or alias detected; continuing chat.")
        return {"messages": []}

    from openai import APITimeoutError

    response = "yes"
    msg_count = 0
    for msg in state["messages"]:
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            msg_count += len(content)
        else:
            msg_count += 1
    print("MSG LEN:", msg_count)

    if "初芽" in str(state["messages"][-1].content) or len(state["messages"]) < 4:
        response = "no"
    else:
        try:
            detect_model = get_lite_model()

            match random.randint(0, 3):
                case 0:
                    detect_model = get_lite_model()
                    print("Using lite model in chat_end_detect_node...")
                case 1 | 2:
                    detect_model = get_mini_model()
                    print("Using mini model in chat_end_detect_node...")
                case 3:
                    response = "no"
                    print("Directly continue chat.")
                    raise InterruptedError("Directly continue chat without detection.")

            detect_result = await asyncio.wait_for(
                _invoke_model(
                    detect_model,
                    state["messages"][-6:]
                    + [SystemMessage(CHAT_END_DETECT_PROMPT)],
                ),
                timeout=10,
            )
            response = str(
                detect_result.content if hasattr(detect_result, "content") else detect_result
            )
        except (APITimeoutError, LLMLimitExceededError, LLMAuthError):
            # Rate-limit / timeout / auth errors → silently continue
            pass
        except InterruptedError:
            pass
        except Exception:
            print("❌ Bad invoke in chat_end_detect")
            traceback.print_exc()

    if response == "yes":
        return {"messages": [SystemMessage("__end__")]}

    if len(state["messages"]) > 60:
        ids = []
        for message in state["messages"]:
            if message.type == "human" or message.type == "ai":
                ids.append(message.id)
            if len(ids) == 2:
                break
        return {"messages": [RemoveMessage(ids[0]), RemoveMessage(ids[1])]}

    return {"messages": []}


# ---------------------------------------------------------------------------
# Finish node
# ---------------------------------------------------------------------------
async def finish_conversation_node(state: MessagesState) -> dict:
    runtime = _runtime()
    print("Enter finish_conversation_node")

    runtime.last_was_system_trigger = False
    _set_graph_running(False)
    _clear_human_queue()
    runtime.conversation.end_requested = False

    # Container auto-stop is handled by infra's reference counting; finish does
    # not forcefully tear it down here.

    # ── Save this conversation round to auxiliary queue for future context ──
    conv_messages: list[dict] = []
    _BOT_NAME = "初芽"
    _BOT_ID = 0
    _now_str = get_date()

    for msg in state["messages"]:
        if msg.type == "system":
            continue

        if msg.type == "tool":
            # Merge tool result into the last message in conv_messages
            if conv_messages:
                last_entry = conv_messages[-1]
                try:
                    last_obj = json.loads(last_entry["text"])
                    tool_content = str(msg.content).strip()
                    if tool_content:
                        existing = last_obj.get("content", "")
                        if isinstance(existing, str):
                            last_obj["content"] = existing + f"\n[Tool Result: {tool_content}]"
                        last_entry["text"] = json.dumps(last_obj, ensure_ascii=False)
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            continue

        if msg.type == "human":
            content = msg.content
            if isinstance(content, list):
                human_texts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        human_texts.append(str(part.get("text", "")))
                    elif isinstance(part, str):
                        human_texts.append(part)
            else:
                human_texts = [str(content)]

            for text in human_texts:
                if not text.strip():
                    continue
                try:
                    normalized = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    normalized = None
                if isinstance(normalized, dict):
                    conv_messages.append({"type": "text", "text": text})
                    continue
                fallback = message_to_json("用户", 0, text, _now_str)
                conv_messages.append(
                    {
                        "type": "text",
                        "text": json.dumps(fallback, ensure_ascii=False),
                    }
                )
            continue

        # Flatten list content (multimodal messages) to plain text
        content = msg.content
        if isinstance(content, list):
            text_parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                elif isinstance(part, str):
                    text_parts.append(part)
            text = " ".join(text_parts)
        else:
            text = str(content)

        if not text.strip():
            continue

        if msg.type == "ai":
            obj = message_to_json(_BOT_NAME, _BOT_ID, text, _now_str)
            conv_messages.append({
                "type": "text",
                "text": json.dumps(obj, ensure_ascii=False),
            })

    if conv_messages:
        await append_auxiliary_message_async(conv_messages)

    _ai_answer = _get_ai_answer()
    if _ai_answer:
        await _ai_answer("[CONVERSATION END]")

    _set_current_query_user_id(None)

    print("⚒️ Conversation end.")
    return {}
