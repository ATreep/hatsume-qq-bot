"""Dialogue handling: message pipeline/assembly and conversation orchestration."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import traceback
from io import BytesIO
from typing import Any

import requests
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent, MessageSegment
from PIL import Image

from ..config import (
    CONTEXT_QUEUE_LEN,
    IMAGE_MAX_PIXELS,
    IMAGE_MAX_SIZE_BYTES,
    MESSAGE_MAX_LENGTH,
    REPLY_MAX_LENGTH,
    USER_INPUT_CONFIRM_DURING_TIME,
)
from ..graph.builder import graph
from ..graph.nodes import (
    append_auxiliary_message,
    bind_state,
    get_role_sys_prompt,
    set_current_query_user_id,
)
from ..state import ConversationState
from ..utils import (
    build_forward_json,
    get_date,
    get_group_member_name,
    mask_secret_keys,
    message_to_json,
)
from ..utils.md_to_image import auto_convert_text

from .forward import (
    collect_people_from_messages,
    has_forward_segment,
    resolve_forward_content,
)

# ---- Section 2: Message Pipeline & Assembly ----


def _format_forward_for_reply(messages: list[dict[str, Any]], max_items: int = 10) -> str:
    """Format resolved forward messages into a readable text summary for reply_to content.

    Handles nested forwards recursively, showing a concise preview.
    """
    lines: list[str] = []
    total = len(messages)

    def _walk(msgs: list[dict[str, Any]], indent: int) -> int:
        count = 0
        for m in msgs:
            if lines and len(lines) >= max_items:
                return count
            prefix = "  " * indent
            user = m.get("user", {})
            name = user.get("name", "未知")
            if m.get("type") == "forward":
                nested = m.get("messages", [])
                lines.append(f"{prefix}{name}: [合并转发, {len(nested)}条]")
                count += 1
                count += _walk(nested, indent + 1)
            else:
                content = m.get("content", "")
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    )
                content = str(content).replace("\n", " ")
                if len(content) > 80:
                    content = content[:80] + "..."
                lines.append(f"{prefix}{name}: {content}")
                count += 1
        return count

    shown = _walk(messages, 0)
    header = f"[合并转发消息 ({total}条" + (f", 显示前{max_items}条)" if shown >= max_items else ")")
    return header + "\n" + "\n".join(lines) + "\n]"


async def get_human_message(bot: Bot, event: MessageEvent) -> tuple[list[dict], dict]:
    """Parse a QQ event into (content_parts, source_entry)."""
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    user_name = await get_group_member_name(bot, group_id, event.user_id)
    msg = event.original_message

    re_user_name = ""
    re_user_id = ""
    re_message = ""

    plain_message = ""
    source_people: list[dict[str, int | str]] = []
    seen_people: set[int] = set()

    def add_source_person(uid: int | str | None, uname: str | None) -> None:
        if uid is None:
            return
        try:
            normalized = int(uid)
        except (TypeError, ValueError):
            return
        if normalized in seen_people:
            return
        seen_people.add(normalized)
        source_people.append({"user_id": normalized, "user_name": uname or str(normalized)})

    add_source_person(event.user_id, user_name)

    if event.reply:
        re_user_id_raw = event.reply.sender.user_id
        if re_user_id_raw:
            re_user_name = await get_group_member_name(bot, group_id, re_user_id_raw)
            re_user_id = str(re_user_id_raw)
            add_source_person(re_user_id_raw, re_user_name)
        else:
            re_user_name = "Unknown"
            re_user_id = ""

        re_message = ""
        reply_has_forward = False
        for msg_seg in event.reply.message:
            match msg_seg.type:
                case "text":
                    re_message += msg_seg.data.get("text", "")
                case "image":
                    re_message += f" ![图片（临时链接）]({msg_seg.data.get('url', '')}) "
                case "forward":
                    reply_has_forward = True

        # Resolve forward content in the replied-to message
        if reply_has_forward:
            try:
                resolved = await resolve_forward_content(bot, event.reply.message)
                if resolved:
                    for person in collect_people_from_messages(resolved):
                        uid = person.get("user_id")
                        if uid and uid not in seen_people:
                            seen_people.add(int(uid))
                            source_people.append(person)
                    forward_text = _format_forward_for_reply(resolved)
                    if re_message:
                        re_message = re_message + "\n" + forward_text
                    else:
                        re_message = forward_text
            except Exception:
                print("❌ Failed to resolve forward content in reply")
                traceback.print_exc()
                if not re_message:
                    re_message = " [合并转发消息] "

        if len(re_message) > REPLY_MAX_LENGTH:
            re_message = re_message[:REPLY_MAX_LENGTH] + "...... （回复消息过长，无法全部显示）"

    for msg_seg in msg:
        match msg_seg.type:
            case "text":
                plain_message += msg_seg.data.get("text", "")
            case "at":
                at_qq = msg_seg.data.get("qq", "")
                if at_qq == "all":
                    plain_message += " @全体成员 "
                elif str(at_qq).isdigit():
                    try:
                        at_user_name = await get_group_member_name(bot, group_id, at_qq)
                        plain_message += f" @{at_user_name}({at_qq}) "
                        add_source_person(at_qq, at_user_name)
                    except Exception:
                        plain_message += f" @{at_qq} "
                        add_source_person(at_qq, str(at_qq))
            case "image":
                plain_message += f" ![图片（临时链接）]({msg_seg.data.get('url', '')}) "
            case "forward":
                forward_id_in_loop = msg_seg.data.get("id", "")
                plain_message += f" [合并转发消息 id={forward_id_in_loop}] "

    if len(plain_message) > MESSAGE_MAX_LENGTH:
        plain_message = plain_message[:MESSAGE_MAX_LENGTH] + "...... （用户消息过长，无法全部显示）"

    # Build reply_to dict for JSON format
    reply_to: dict[str, Any] | None = None
    if re_message != "" and re_user_name != "":
        reply_to = {
            "user": {"id": int(re_user_id) if re_user_id.isdigit() else 0, "name": re_user_name},
            "content": re_message,
        }

    # Check for forward message
    forward_id = has_forward_segment(msg)
    print(f"🔗 has_forward_segment result: {forward_id}")
    forward_messages: list[dict[str, Any]] | None = None

    if forward_id is not None:
        forward_messages = await resolve_forward_content(bot, msg)
        print(f"🔗 resolve_forward_content returned: {len(forward_messages) if forward_messages else 'None'} messages")
        if forward_messages is not None:
            for _i, _m in enumerate(forward_messages[:3]):
                print(f"  [{_i}] type={_m.get('type')}, user={_m.get('user',{}).get('name')}, content_preview={str(_m.get('content',''))[:50]}")
            # Collect people from forward messages
            for person in collect_people_from_messages(forward_messages):
                uid = person.get("user_id")
                if uid and uid not in seen_people:
                    seen_people.add(int(uid))
                    source_people.append(person)

    msg_time = get_date()

    # Build JSON message text
    if forward_messages is not None:
        msg_json = build_forward_json(
            user_name, event.user_id, forward_messages, msg_time,
        )
    else:
        msg_json = message_to_json(
            user_name, event.user_id, plain_message, msg_time, reply_to=reply_to,
        )

    rendered_text = json.dumps(msg_json, ensure_ascii=False)
    content: list[dict[str, Any]] = [{"type": "text", "text": rendered_text}]

    combined_msg = msg
    if event.reply:
        combined_msg += event.reply.message

    if combined_msg.count("image") > 0:
        for msg_seg in combined_msg.include("image"):
            url = msg_seg.data.get("url")
            try:
                response = requests.get(url, timeout=10)  # type: ignore
                response.raise_for_status()
                image_bytes = response.content

                if len(image_bytes) > IMAGE_MAX_SIZE_BYTES:
                    raise Exception(f"Image file size {len(image_bytes) / (1024*1024):.2f}MB exceeds 9MB limit")

                img = Image.open(BytesIO(image_bytes))
                if img.width * img.height >= IMAGE_MAX_PIXELS:
                    raise Exception(f"Image pixel size {img.width * img.height} exceeds 36000000 pixel limit")

                b64 = base64.b64encode(image_bytes).decode("utf-8")
                image_url = f"data:image/jpeg;base64,{b64}"

                content.append({"type": "image_url", "image_url": {"url": image_url}})
            except Exception as e:
                print("❌ Cannot download image: ", e)
                traceback.print_exc()

    source_entry = {
        "source_id": f"m{getattr(event, 'message_id', int(time.time() * 1000))}",
        "text": rendered_text,
        "people": source_people,
    }

    return content, source_entry


# ---- Section 3: Conversation Orchestration ----

# Module-level conversation state
conv_state = ConversationState()

# Wire commands module to share the same state
from .tools import _wire_conv_state  # noqa: E402
_wire_conv_state(conv_state)


def _start_conv_for_trigger(
    user_id: int, group_id: int, notify_msg: str, *, trigger_type: str = "agent",
) -> None:
    """Start a new conversation for an external trigger when not currently chatting.

    Uses bot.send_group_msg() to target the specific group directly.
    trigger_type: "agent" or "timer" — controls user_id=None behavior.
    Agent triggers use user_id=None when user_id==0 (no specific user to notify).
    Timer triggers always pass the effective user_id.
    """
    from nonebot import get_bot
    from ..graph.tools import configure_tool_callbacks as configure_tools

    bot = get_bot()

    async def _send_to_group(msg, at_id=None):
        if msg == "[CONVERSATION END]":
            conv_state.end_conversation()
            return
        text = mask_secret_keys(str(msg))
        if at_id:
            text = f"[CQ:at,qq={at_id}] {text}"
        try:
            await bot.send_group_msg(group_id=group_id, message=text)
        except Exception as e:
            print(f"❌ _send_to_group failed: group={group_id} err={e}")

    conv_state.ai_answer = _send_to_group
    conv_state.ai_answer_with_at = _send_to_group

    if user_id != 0:
        conv_state.activate_chat(f"group_{group_id}_{user_id}")

    effective_user_id: int | None = user_id
    if trigger_type == "agent" and user_id == 0:
        effective_user_id = None

    asyncio.create_task(
        start_new_conversation(
            conv_state, _send_to_group, configure_tools,
            user_id=effective_user_id,
            messages=[{"type": "text", "text": notify_msg}],
        )
    )


# Register the callback with tools.py (must happen after imports resolve)
from ..graph.tools import configure_agent_notification_callback  # noqa: E402
configure_agent_notification_callback(
    lambda uid, gid, msg: _start_conv_for_trigger(uid, gid, msg, trigger_type="agent")
)

# Register timer callback with executor (mirrors agent notification registration above)
try:
    from ..timer.executor import set_timer_conv_callback
    set_timer_conv_callback(
        lambda uid, gid, msg: _start_conv_for_trigger(uid, gid, msg, trigger_type="timer")
    )
except ImportError:
    pass  # Graceful degradation when timer executor deps aren't available


# ---------------------------------------------------------------------------
# Conversation startup (merged from handlers/conversation.py)
# ---------------------------------------------------------------------------
async def start_new_conversation(
    conv_state: ConversationState,
    ai_callback,
    configure_tools_fn,
    *,
    user_id: int | None = None,
    messages: list[dict] | None = None,
    sources: list[dict] | None = None,
    system_task_text: str | None = None,
    flush_idle: bool = False,
) -> None:
    """Set up and invoke the LangGraph conversation from scratch."""
    from langchain.messages import SystemMessage

    bind_state(conv_state)
    conv_state.end_requested = False

    configure_tools_fn(
        ai_callback,
        conv_state.retrieved_mem_keys,
        user_id,
        answer_fn=ai_callback,
        is_video_rate_limited=conv_state.is_video_rate_limited,
        update_video_time=lambda: setattr(conv_state, "last_video_time", time.time()),
        is_generate_image_rate_limited=conv_state.is_generate_image_rate_limited,
        update_generate_image_time=lambda: setattr(conv_state, "last_generate_image_time", time.time()),
        end_conversation_fn=conv_state.request_end_conversation,
    )

    if flush_idle:
        idle_msgs, idle_srcs = conv_state.flush_idle_to_auxiliary()
        append_auxiliary_message(idle_msgs, idle_srcs)

    if messages is not None:
        conv_state.human_queue.extend(messages)
        conv_state.human_source_queue.extend(sources or [])

    if system_task_text is not None:
        conv_state.human_queue.append({"type": "text", "text": system_task_text})

    if user_id is not None:
        set_current_query_user_id(user_id)

    conv_state.is_graph_running = True

    # Run graph in a cancellable task so /clear can stop it
    loop = asyncio.get_running_loop()
    conv_state._graph_task = loop.create_task(
        graph.ainvoke(
            {"messages": [SystemMessage(get_role_sys_prompt())]},
            {"recursion_limit": 100},
        )
    )
    try:
        await conv_state._graph_task
    except asyncio.CancelledError:
        print("🛑 [graph] Conversation cancelled by /clear")
    finally:
        conv_state._graph_task = None
        conv_state.is_graph_running = False


# ---------------------------------------------------------------------------
# Message sending
# ---------------------------------------------------------------------------
async def handle_ai_message(
    msg: str | Message | MessageSegment,
    matcher,
    at_id: int | None = None,
    retry: int = 0
) -> None:
    """Send AI response to the chat. Retries up to 5 times."""
    if retry >= 5:
        try:
            await matcher.send("（电波受到干扰...想要发出的内容丢失了...）")
        except Exception:
            pass
        return

    if msg == "[CONVERSATION END]":
        conv_state.end_conversation()
        print("Current conversation ends")
        return

    if isinstance(msg, str):
        if not msg.strip():
            await matcher.send("（电波受到干扰...想要发出的内容丢失了...）")
            return
        segments = await auto_convert_text(mask_secret_keys(msg))
    elif isinstance(msg, MessageSegment):
        if msg.type == "text":
            raw = str(msg.data.get("text", ""))
            segments = await auto_convert_text(mask_secret_keys(raw))
        else:
            segments = [msg]
    elif isinstance(msg, Message):
        segments = list(msg)
    else:
        segments = [msg]

    try:
        for seg in segments:
            if at_id:
                await matcher.send(MessageSegment.at(at_id) + " " + seg)
            else:
                await matcher.send(seg)
    except Exception as e:
        print("Send error: ", e)
        await asyncio.sleep(3)
        print(f"Retry sending message, {retry=}")
        await handle_ai_message(segments, matcher, retry=retry + 1) # type: ignore


# ---------------------------------------------------------------------------
# Chat entry points
# ---------------------------------------------------------------------------
async def start_chat(matcher, event: GroupMessageEvent) -> None:
    print("call start_chat")
    conv_state.activate_chat(event.get_session_id())
    await matcher.finish()


async def user_chat_handle(bot: Bot, event: GroupMessageEvent, user_chat_matcher) -> None:
    print("call user_chat")
    from ..graph.tools import set_current_group_id
    set_current_group_id(event.group_id)

    from ..character_proxy import activate_character_proxy_peer

    activate_character_proxy_peer(
        conv_state,
        message=event.original_message,
        sender_id=event.user_id,
        session_id=event.get_session_id(),
    )

    if not conv_state.is_chatting:
        try:
            idle_messages, idle_source_entry = await get_human_message(bot, event)
            conv_state.idle_queue.extend(idle_messages)
            conv_state.idle_source_queue.append(idle_source_entry)
        except Exception:
            await user_chat_matcher.finish()

        if len(conv_state.idle_queue) >= CONTEXT_QUEUE_LEN:
            print("idle queue full, flushing to auxiliary")
            conv_state.flush_idle_to_auxiliary()
        return

    session_id = event.get_session_id()
    if session_id in conv_state.chat_peers:
        print("Detected chat peers.")
    else:
        auxiliary_messages, auxiliary_source_entry = await get_human_message(bot, event)
        append_auxiliary_message(auxiliary_messages, [auxiliary_source_entry])
        print("Collected this auxiliary message.")
        return

    pending_messages, pending_source_entry = await get_human_message(bot, event)
    conv_state.pending_queue.extend(pending_messages)
    conv_state.pending_source_queue.append(pending_source_entry)
    print("💬 Added a new message into pending queue")

    async def send():
        debounce_event = asyncio.Event()
        conv_state._debounce_cancel = debounce_event
        try:
            print(f"⏱️ Waiting for user input confirmation for {USER_INPUT_CONFIRM_DURING_TIME} seconds...")
            await asyncio.wait_for(debounce_event.wait(), timeout=USER_INPUT_CONFIRM_DURING_TIME)
            return
        except asyncio.TimeoutError:
            pass


        try:
            print("💬 Flush pending queue and enter LangGraph.")
            pending_msgs, pending_srcs = conv_state.flush_pending()

            if conv_state.is_graph_running:
                print("Graph already running, feeding messages to queue...")
                conv_state.human_queue.extend(pending_msgs)
                conv_state.human_source_queue.extend(pending_srcs)
                return

            from ..graph.tools import configure_tool_callbacks as configure_tools

            async def ai_cb(msg, at_id=None):
                await handle_ai_message(msg, user_chat_matcher, at_id=at_id)

            conv_state.ai_answer = ai_cb
            conv_state.ai_answer_with_at = ai_cb
            await start_new_conversation(
                conv_state, ai_cb, configure_tools,
                user_id=event.user_id, flush_idle=True,
                messages=pending_msgs, sources=pending_srcs,
            )
        except Exception as e:
            print(f"Error in send() task: {e}")
            import traceback
            traceback.print_exc()

    if conv_state._debounce_cancel is not None:
        conv_state._debounce_cancel.set()

    print("create task: send")
    await send()
