"""LangGraph conversation nodes — merged into a single module.

Previously split across ai.py / human.py / detect.py / finish.py. They share
module-level state (the bound ConversationState, auxiliary queues, retrieved
memory keys) and human/detect/finish are thin shells over ai's accessors, so
keeping them in one module removes the cross-import churn without changing any
behavior. All public symbols the graph builder and tests rely on live here.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import random
import re
import time
import traceback
from typing import Any

from nonebot import get_bot
import nonebot_plugin_localstore as store
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.agents import create_agent
from langchain_core.messages import RemoveMessage
from langgraph.graph import MessagesState
from nonebot.adapters.onebot.v11 import MessageSegment

from ..models import get_advance_model, get_code_model, get_lite_model, get_mini_model
from ..prompts import (
    AUXILIARY_COMPACTION_PROMPT,
    CHAT_END_DETECT_PROMPT,
    build_agent_state_prompt,
    build_admin_mode_prompt,
    build_face_injection_prompt,
    build_memory_context_prompt,
    build_skill_prompt,
    role_sys_prompt,
)
from ..skills import get_skill_manager
from .tools import (
    get_chat_tools,
    get_timer_overview,
    _current_group_id,
    query_memory,
    reset_capture_flag,
    set_shell_executor_limit,
)

from ..utils import CQ_AT_PATTERN, get_group_member_name, get_date, message_to_json
from ..utils.md_to_image import auto_convert_text
from ..config import ADMIN_QQ_ID, CONTEXT_QUEUE_LEN

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
FACE_TAG_PATTERN = re.compile(r"\[[ \t]*hatsumeface:(.*?)\]")
MEMORY_RECORD_PATTERN = re.compile(
    r"\[[ \t]*memoryrecord:\s*(.+?)\]", re.DOTALL
)
MEMORY_KEYMAN_PATTERN = re.compile(r"\[[ \t]*memorykeyman:\s*(.+?)\]")
REPLY_DIRECTIVE_PATTERN = re.compile(r"\[[ \t]*reply:\s*([^\]\r\n]*)\]")
SYSTEM_TRIGGER_KEY = "_hatsume_system_trigger"
ADMIN_MODE_KEYWORD = "WORLDSKY"

# ---------------------------------------------------------------------------
# In-memory state (shared with tools.py via configure_tool_callbacks)
# ---------------------------------------------------------------------------
auxiliary_messages_queue: list[dict] = []
auxiliary_source_queue: list[dict] = []
_face_cooling_count: int = 0
_current_memory_query_user_id: int | None = None

# human-node bookkeeping (previously module-level in human.py)
_last_was_auxiliary_only: bool = False
_last_was_system_trigger: bool = False

# ---------------------------------------------------------------------------
# Shared bound ConversationState (set by handlers/chat.py via bind_state)
# ---------------------------------------------------------------------------
_state: Any = None


def bind_state(conversation_state: Any) -> None:
    global _state
    _state = conversation_state


# ---------------------------------------------------------------------------
# Memory record extraction
# ---------------------------------------------------------------------------
def _extract_memory_records(text: str) -> tuple[dict | None, str]:
    """Extract at most one [memoryrecord: ...] and optional [memorykeyman: ...] from text.

    Returns (record: dict with 'content' and 'qq_numbers' or None, cleaned_text).
    """
    cleaned = text

    # Extract keyman tag first (before removing record tag)
    keyman_match = MEMORY_KEYMAN_PATTERN.search(cleaned)
    qq_numbers: list[int] = []
    if keyman_match:
        qq_str = keyman_match.group(1).strip()
        for part in qq_str.split(","):
            part = part.strip()
            try:
                qq_numbers.append(int(part))
            except ValueError:
                pass
        cleaned = cleaned[: keyman_match.start()] + cleaned[keyman_match.end() :]

    # Extract memory record tag
    record_match = MEMORY_RECORD_PATTERN.search(cleaned)
    if record_match:
        content = record_match.group(1).strip()
        cleaned = cleaned[: record_match.start()] + cleaned[record_match.end() :]
        if content:
            return {"content": content, "qq_numbers": qq_numbers}, cleaned.strip()

    return None, text


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


def _extract_replyable_message_ids(messages: list[Any]) -> set[int]:
    """Collect top-level OneBot message IDs from human JSON shown to chat_agent."""
    replyable_ids: set[int] = set()
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
            if isinstance(message_id, int) and not isinstance(message_id, bool):
                replyable_ids.add(message_id)
    return replyable_ids


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
        f"请你简单复述一下任务原文内容，然后告诉用户执行结果。\n\n"
        f"## 该 Agent 执行的任务原文\n\n"
        "```\n"
        f"{task[:200]}\n\n"
        "```\n"
        f"## Agent 执行结果\n\n"
        f"{result}"
    )

    print(notify_msg)

    if _state and _state.is_chatting:
        _state.human_queue.append(make_system_trigger_message(notify_msg, "agent"))
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

    if _state and _state.is_chatting:
        _state.human_queue.append(make_system_trigger_message(timer_msg, "timer"))
        print(f"⏰ [inject_timer] Injected timer into human_queue for user {user_id}")
    else:
        if start_conversation_cb is not None:
            print(f"⏰ [inject_timer] Starting new conversation for timer (user {user_id})")
            start_conversation_cb(user_id, group_id, timer_msg)
        else:
            _start_direct_conv(user_id, group_id, timer_msg)


def _start_direct_conv(user_id: int, group_id: int, notify_msg: str) -> None:
    """Start a new graph conversation targeting a specific group directly.

    Used when no callback is registered (e.g., /autoresponse debug command).
    Sends messages to the target group via bot.send_group_msg().
    """
    from nonebot import get_bot
    from ..handlers.dialogue import (
        _send_group_ai_message,
        conv_state,
        start_new_conversation,
    )
    from .tools import configure_tool_callbacks as configure_tools

    bot = get_bot()

    async def _send_to_group(msg, reply_to_message_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        try:
            await _send_group_ai_message(
                bot,
                group_id,
                msg,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")

    conv_state.ai_answer = _send_to_group
    conv_state.activate_chat(f"group_{group_id}_{user_id}")

    asyncio.create_task(
        start_new_conversation(
            conv_state, _send_to_group, configure_tools,
            user_id=user_id,
            system_task_text=notify_msg,
        )
    )
    print(f"🎨 [_start_direct_conv] Started conversation for user {user_id} in group {group_id}")


# ---------------------------------------------------------------------------
# Role prompt & auxiliary queue management
# ---------------------------------------------------------------------------
def get_role_sys_prompt() -> str:
    return role_sys_prompt


def append_auxiliary_message(
    messages: list[dict], source_entries: list[dict] | None = None
) -> None:
    if len(messages) == 0:
        return
    auxiliary_messages_queue.extend(messages)
    auxiliary_source_queue.extend(source_entries or [])

    if len(auxiliary_messages_queue) > CONTEXT_QUEUE_LEN:
        try:
            model_chosen = get_mini_model()

            if random.randint(0, 2) == 0:
                model_chosen = get_lite_model()
                print("Using lite model for compaction...")
            else:
                print("Using mini model for compaction...")

            summary = model_chosen.invoke(
                [
                    SystemMessage(AUXILIARY_COMPACTION_PROMPT),
                    HumanMessage(auxiliary_messages_queue),  # type: ignore
                ]
            ).content.__str__()
            auxiliary_messages_queue.clear()
            auxiliary_messages_queue.append(
                {"type": "text", "text": "### 历史聊天记录总结：" + summary}
            )
            auxiliary_source_queue.clear()
        except Exception:
            print("❌ Failed to summarize auxiliary messages")
            traceback.print_exc()
            overflow = len(auxiliary_messages_queue) - CONTEXT_QUEUE_LEN
            if overflow > 0:
                del auxiliary_messages_queue[:overflow]
            auxiliary_source_queue.clear()


def _snapshot_auxiliary_queue() -> tuple[list[dict], list[dict]]:
    """Return a non-destructive snapshot of the auxiliary queues."""
    return auxiliary_messages_queue.copy(), auxiliary_source_queue.copy()




# ---------------------------------------------------------------------------
# Shared state accessors
# ---------------------------------------------------------------------------
def _get_ai_answer() -> Any:
    return _state.ai_answer if _state else None


def _get_human_queue() -> list[dict]:
    return _state.human_queue if _state else []


def _clear_human_queue() -> None:
    if _state:
        _state.human_queue.clear()
        _state.human_source_queue.clear()


def _set_graph_running(value: bool) -> None:
    if _state:
        _state.is_graph_running = value


def _set_current_query_user_id(uid: int | None) -> None:
    global _current_memory_query_user_id
    _current_memory_query_user_id = uid
    if _state:
        _state.current_query_user_id = uid


def set_current_query_user_id(uid: int | None) -> None:
    _set_current_query_user_id(uid)


# ===========================================================================
# Graph nodes
# ===========================================================================

# ---------------------------------------------------------------------------
# AI node
# ---------------------------------------------------------------------------
async def ai_node(state: MessagesState) -> dict:
    """Generate AI response using LLM with tools and memory."""
    global _face_cooling_count

    print("Enter ai_node")
    reset_capture_flag()
    t_start = time.time()

    _MEMORY_TOTAL_LIMIT = 50
    last_content = state["messages"][-1].content
    chatting_user_ids = extract_user_ids_from_content(last_content)
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

    admin_mode_enabled = is_admin_mode_message(last_content, ADMIN_QQ_ID)
    model_chosen = (
        get_code_model() if admin_mode_enabled else get_advance_model(thinking=True)
    )
    sys_prompt = get_role_sys_prompt()
    if admin_mode_enabled:
        sys_prompt += build_admin_mode_prompt(ADMIN_QQ_ID)
        print("[admin] Enabled ADMIN MODE with DEEPSEEK_V4_FLASH")

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

    # Inject running agent states into system prompt
    agent_prompt = build_agent_state_prompt()
    if agent_prompt:
        sys_prompt += agent_prompt
        print("[agents] Injected agent state info into system prompt")

    timer_overview = await get_timer_overview()
    sys_prompt += "\n\n" + timer_overview
    print("[timers] Injected timer overview into system prompt")

    # ── Face injection gate ──

    _face_cooling_count += 1
    _face_allowed = (
        random.randint(0, 1) == 0
        and _face_cooling_count >= 1
    )
    _face_dict: dict[str, list[str]] = {}
    if _face_allowed:
        face_list = [
            f.name
            for f in store.get_plugin_data_file("faces").iterdir()
            if f.is_file() and f.name.lower().endswith((".png", ".jpg", ".jpeg"))
        ]
        if face_list:
            for fname in face_list:
                emotion = fname.split("_")[0]
                _face_dict.setdefault(emotion, []).append(fname)
            emotions = list(_face_dict.keys())
            face_prompt = build_face_injection_prompt(emotions)
            if face_prompt:
                sys_prompt += face_prompt
                print(f"[face] Injected face prompt with {len(emotions)} emotions")
        _face_cooling_count = 0

    sys_prompt += f"\n\n# 当前日期与时间\n{get_date()}"

    chat_agent = create_agent(
        model_chosen,
        get_chat_tools(),
        system_prompt=sys_prompt,
    )

    print("Start building historical recording from auxiliary queue...")

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
        last_human_msg = state["messages"][-1]

    print("Start chat_agent invocation...")

    ai_text: str = ""
    try:
        mem_msg = (
            []
            if memory_summary.strip() == ""
            else [
                HumanMessage(build_memory_context_prompt(memory_summary))
            ]
        )
        agent_messages = state["messages"][:-1] + mem_msg + [last_human_msg]
        if admin_mode_enabled:
            agent_messages = _without_image_url_parts(agent_messages)
        replyable_message_ids = _extract_replyable_message_ids(agent_messages)
        set_shell_executor_limit(3)  # chat_agent: max 3 shell_executor calls per round
        response = await chat_agent.with_retry(
            stop_after_attempt=5
        ).ainvoke(
            {"messages": agent_messages},  # type: ignore
            {"recursion_limit": 60},
        )
        ai_text = response["messages"][-1].content
        if isinstance(ai_text, list):
            # Flatten list content to string (some models return content as list)
            ai_text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in ai_text
            )

        # LLM outputs plain text directly
        print(f"Raw AI response: {ai_text}")
    except Exception:
        print("❌ Bad invoke in chat_agent")
        traceback.print_exc()
        return {}

    ai_text_history, reply_to_message_id = _parse_reply_directive(
        str(ai_text),
        replyable_message_ids,
    )

    # ── Extract face tag from ai_text ──
    face_emotion: str | None = None
    ai_text_clean = ai_text_history
    match = FACE_TAG_PATTERN.search(ai_text_history)
    if match:
        face_emotion = match.group(1).strip()
        ai_text_clean = FACE_TAG_PATTERN.sub("", ai_text_history).strip()
        print(f"[face] Detected face tag: {face_emotion}")

    # ── Extract memory record from ai_text ──
    mem_record, ai_text_clean = _extract_memory_records(ai_text_clean)
    if mem_record:
        print("[memory] Extracted memory record from AI response")

    ai_text_clean = ai_text_clean.strip()
    end_requested = bool(
        _state is not None and getattr(_state, "end_requested", False)
    )
    if end_requested:
        print("[end_conversation] Suppressed the final AI reply.")
    elif ai_text_clean:
        _ai_answer = _get_ai_answer()
        if _ai_answer:
            if reply_to_message_id is not None:
                await _ai_answer(
                    ai_text_clean,
                    reply_to_message_id=reply_to_message_id,
                )
            elif CQ_AT_PATTERN.search(ai_text_clean):
                await _ai_answer(ai_text_clean)
            else:
                for seg in await auto_convert_text(ai_text_clean):
                    await _ai_answer(seg)

    t_mem_start = time.time()

    # ── Resolve QQ numbers → usernames and save memory record ──
    from ..memory import add_mem
    if mem_record:
        content = str(mem_record.get("content", "")).strip()
        qq_numbers = mem_record.get("qq_numbers", [])
        if content:
            people: list[dict] = []
            if qq_numbers and _current_group_id is not None:
                try:
                    bot = get_bot()
                    for qq in qq_numbers:
                        user_name = await get_group_member_name(bot, _current_group_id, qq)
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
        await _ai_answer_cb(face_msg)

    print(f"Elapsed time of ai_node: t_writing_mem={t_mem_end - t_mem_start}s, t_chat_agent={t_mem_start - t_start}s")
    return {"messages": [AIMessage(ai_text_history)]}


# ---------------------------------------------------------------------------
# Human node
# ---------------------------------------------------------------------------
async def human_node(state: MessagesState) -> dict:
    global _last_was_auxiliary_only, _last_was_system_trigger
    print("Enter human_node")

    if _state is not None and getattr(_state, "end_requested", False):
        _last_was_auxiliary_only = False
        _last_was_system_trigger = False
        return {"messages": [SystemMessage("__end__")]}

    t_start = time.time()
    while not _get_human_queue():
        await asyncio.sleep(0.3)
        if time.time() - t_start >= 60 * 5:
            _last_was_auxiliary_only = not _get_human_queue() and bool(auxiliary_messages_queue)
            _last_was_system_trigger = False
            return {"messages": [SystemMessage("__end__")]}

    human_queue = _get_human_queue().copy()
    _clear_human_queue()

    _last_was_auxiliary_only = not human_queue and bool(auxiliary_messages_queue)
    _last_was_system_trigger = any(
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

    if _last_was_system_trigger:
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

            detect_result = detect_model.invoke(
                state["messages"][-6:]
                + [
                    SystemMessage(CHAT_END_DETECT_PROMPT)
                ],
                timeout=10,
            )
            response = str(
                detect_result.content if hasattr(detect_result, "content") else detect_result
            )
        except APITimeoutError:
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
    global _last_was_system_trigger
    print("Enter finish_conversation_node")

    _last_was_system_trigger = False
    _set_graph_running(False)
    _clear_human_queue()
    if _state is not None:
        _state.end_requested = False

    # Container auto-stop is handled by infra's reference counting; finish does
    # not forcefully tear it down here.

    # Reset skill dedup for next conversation
    get_skill_manager().reset_conversation()

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
        append_auxiliary_message(conv_messages)

    _ai_answer = _get_ai_answer()
    if _ai_answer:
        await _ai_answer("[CONVERSATION END]")

    _set_current_query_user_id(None)

    print("⚒️ Conversation end.")
    return {}
