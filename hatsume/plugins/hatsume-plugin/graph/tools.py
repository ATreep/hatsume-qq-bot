"""LangChain tools for the chat agent: memory, search, shell, browser."""

from __future__ import annotations

import asyncio
import contextvars
import os as _os
import random
import shlex
import ssl
import subprocess
import traceback
import urllib.request
import urllib.error
from typing import TYPE_CHECKING, Annotated, Any, Callable, Literal, TypedDict

import requests
from langchain_core.tools import tool as _langchain_tool
from langchain_community.tools import DuckDuckGoSearchRun
from nonebot.adapters.onebot.v11 import MessageSegment
from pydantic import Field

from ..infra import run_cmd, ensure_container_running

from ..memory import query_mems
from .agents import get_agent_list, get_agent_handler

if TYPE_CHECKING:
    from ..timer.schedule import SchedulePlan


PositiveTimerStep = Annotated[int, Field(strict=True, gt=0)]
IsoWeekday = Annotated[int, Field(strict=True, ge=1, le=7)]
MonthDay = Annotated[int, Field(strict=True, ge=1, le=31)]
ImageSearchCount = Annotated[int, Field(strict=True, ge=1, le=10)]
ImageOrientation = Literal["landscape", "portrait", "square"]


class WeeklyTimePoint(TypedDict):
    weekday: IsoWeekday
    time: str


class MonthlyTimePoint(TypedDict):
    day: MonthDay
    time: str


# ---------------------------------------------------------------------------
# Debug-logging tool wrapper — wraps every @tool with call logging
# ---------------------------------------------------------------------------
def _format_tool_input(input_data: Any) -> str:
    """Format tool input for debug logging: show key=repr(value) pairs."""
    if isinstance(input_data, dict):
        return ", ".join(f"{k}={v!r}" for k, v in input_data.items())
    return repr(input_data)


def _wrap_tool_ainvoke(tool_obj: Any) -> Any:
    """Monkey-patch tool.ainvoke to print debug log before every call.

    Uses object.__setattr__ because StructuredTool is a Pydantic model
    and its __setattr__ rejects non-field attribute assignment.

    If tool_obj has no ainvoke (e.g. test mock returning a plain function),
    return it unchanged.
    """
    if not hasattr(tool_obj, "ainvoke"):
        return tool_obj

    _original_ainvoke = tool_obj.ainvoke

    async def _logged_ainvoke(input_data: Any, *args: Any, **kwargs: Any) -> Any:
        args_str = _format_tool_input(input_data)
        print(f"🔧 [tool] {tool_obj.name}({args_str})")
        return await _original_ainvoke(input_data, *args, **kwargs)

    object.__setattr__(tool_obj, "ainvoke", _logged_ainvoke)
    return tool_obj


def tool(*args: Any, **kwargs: Any) -> Any:
    """Drop-in replacement for @tool that adds debug logging on every call."""
    if len(args) == 1 and callable(args[0]):
        # Bare @tool  (no parentheses)
        return _wrap_tool_ainvoke(_langchain_tool(args[0]))
    # @tool(...)  with arguments
    def decorator(func: Any) -> Any:
        return _wrap_tool_ainvoke(_langchain_tool(*args, **kwargs)(func))
    return decorator

# ---------------------------------------------------------------------------
# Deferred references — set by the graph layer before use
# ---------------------------------------------------------------------------
_ai_answer: Any = None
_current_memory_query_user_id: int | None = None
_end_conversation_callback: Callable[[], None] | None = None
_generate_video_used: bool = False
def _not_rate_limited() -> bool:
    return False


def _noop() -> None:
    return None


_is_video_rate_limited: Callable[[], bool] = _not_rate_limited
_update_video_time: Callable[[], None] = _noop
_is_generate_image_rate_limited: Callable[[], bool] = _not_rate_limited
_update_generate_image_time: Callable[[], None] = _noop
_current_group_id: int | None = None

# Agent notification callback (set by chat.py)
_agent_notification_callback: Callable[[int, int, str], None] | None = None


async def _resolve_notified_user_name(user_id: int, group_id: int | None) -> str | None:
    if user_id == 0:
        return None
    try:
        from nonebot import get_bot
        from ..utils import get_group_member_name

        return await get_group_member_name(get_bot(), group_id, user_id)
    except Exception as e:
        print(f"❌ failed to resolve notified user name: user={user_id} err={e}")
        return None


# ---------------------------------------------------------------------------
# shell_executor per-context call limit (contextvars isolate chat vs coding agent)
# ---------------------------------------------------------------------------
_shell_call_count: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_shell_call_count", default=0
)
_shell_max_calls: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "_shell_max_calls", default=None
)


def set_shell_executor_limit(max_calls: int | None) -> None:
    """Set the per-context shell_executor call limit.

    Call with ``max_calls=3`` before invoking chat_agent (limits to 3 calls).
    Call with ``max_calls=None`` before invoking coding_agent (no limit).
    Resets the call counter to 0.
    """
    _shell_max_calls.set(max_calls)
    _shell_call_count.set(0)


def set_current_group_id(group_id: int | None) -> None:
    """Set the current group ID for timer tool context."""
    global _current_group_id
    _current_group_id = group_id


def get_current_group_id() -> int | None:
    """Return the current group ID without exposing an imported scalar snapshot."""
    return _current_group_id


def configure_tool_callbacks(
    query_user_id: int | None,
    answer_fn: Any = None,
    is_video_rate_limited: Callable[[], bool] | None = None,
    update_video_time: Callable[[], None] | None = None,
    is_generate_image_rate_limited: Callable[[], bool] | None = None,
    update_generate_image_time: Callable[[], None] | None = None,
    end_conversation_fn: Callable[[], None] | None = None,
) -> None:
    global _ai_answer, _current_memory_query_user_id
    global _is_video_rate_limited, _update_video_time
    global _is_generate_image_rate_limited, _update_generate_image_time
    global _end_conversation_callback
    _ai_answer = answer_fn
    _current_memory_query_user_id = query_user_id
    _end_conversation_callback = end_conversation_fn
    if is_video_rate_limited is not None:
        _is_video_rate_limited = is_video_rate_limited
    if update_video_time is not None:
        _update_video_time = update_video_time
    if is_generate_image_rate_limited is not None:
        _is_generate_image_rate_limited = is_generate_image_rate_limited
    if update_generate_image_time is not None:
        _update_generate_image_time = update_generate_image_time


def configure_agent_notification_callback(cb: Callable[[int, int, str], None]) -> None:
    """Register callback for starting conversation when agent finishes outside active chat.
    Callback signature: cb(user_id: int, group_id: int, notify_msg: str) -> None"""
    global _agent_notification_callback
    _agent_notification_callback = cb # type: ignore


_send_image_count: int = 0
_send_video_count: int = 0


def reset_capture_flag() -> None:
    global _generate_video_used, _send_image_count, _send_video_count
    _generate_video_used = False
    _send_image_count = 0
    _send_video_count = 0




def query_memory(query: str, user_ids: list[int] | None = None, max_results: int | None = None) -> str:
    """Shared memory query logic."""
    from datetime import datetime

    memory_summary = ""
    results = query_mems(
        str(query), user_ids=user_ids, max_limit=max_results
    )

    if len(results) > 0:
        formatted = []
        for content, ts in results:
            dt = datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M:%S")
            formatted.append(f"- ({dt}) {content}")
        memory_summary = "\n".join(formatted)

    if memory_summary != "":
        print("Memory search results: \n" + memory_summary)

    return memory_summary


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def find_memory(query: str) -> str:
    """
    搜索记忆。
    你的 query 必须清晰地提供 用户名、动作、物品名 等关键信息，且只包含单个词语与空格分割，不要使用完整一句话。
    若不清楚具体用户名、动作、物品名，则不要在 query 中提及它们，不要使用 "用户"、"群友"、"做过"、"东西" 等不具体的词语。
    此工具的输出用户无法看到。

    例如，当用户询问类似以下内容时，你必须调用此工具：
    - 谁喜欢购物？
    - 那个打篮球厉害的
    - 我上个周去过哪里来着
    - 爱吃青草的那个群友
    …

    ## 示例 query：
    ```
    大壮 擅长 高尔夫
    ```
    """
    print("Call query_memory tool:", query)
    return query_memory(query)


@tool
def search_web(query: str) -> str:
    """
    当用户明确指出需要网络搜索或用户提及未知事物时，使用此工具查找搜索引擎。
    search_web 仅能提供简要的网络搜索答案。
    输入搜索关键字。

    注意：
    若提供了 URL，请使用 coding_agent 爬取网页内容阅读。
    禁止将 URL 直接作为关键字搜索。
    """
    print("Search the web: ", query)
    try:
        return DuckDuckGoSearchRun().run(query)
    except Exception:
        print("Search failed.")
        return "search_web 没有找到相关结果"


def _fetch_pexels_search(
    query: str,
    count: int,
    orientation: ImageOrientation | None,
    api_key: str,
    base_url: str,
) -> Any:
    """Fetch one page from Pexels without blocking the async caller."""
    params: dict[str, str | int] = {"query": query, "per_page": count, "page": 1}
    if orientation is not None:
        params["orientation"] = orientation
    response = requests.get(
        f"{base_url.rstrip('/')}/v1/search",
        params=params,
        headers={
            "Accept": "application/json",
            "Authorization": api_key,
            "User-Agent": "Hatsume/1.0",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


@tool
async def search_image(
    query: str,
    count: ImageSearchCount = 3,
    orientation: ImageOrientation | None = None,
) -> str:
    """
    使用 Pexels 搜索真实照片，返回可发送的图片 URL、说明、摄影师和来源页面。
    此工具只搜索图片，不会直接发送；选定结果后使用 send_image 发送 image_url。

    ## 参数：
    - query: 简洁、具体的图片搜索关键词，优先使用英文关键词
    - count: 返回结果数，范围 1 到 10，默认 3
    - orientation: 可选构图方向：landscape、portrait 或 square

    ## 使用场景：
    - 用户希望查找或查看现有的真实照片、素材图、风景图时使用
    - 用户要求创作一张新图片时不要使用，应调用 generate_image
    """
    normalized_query = query.strip()
    if not normalized_query:
        return "错误：图片搜索关键词不能为空。"
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        return "错误：count 必须是 1 到 10 之间的整数。"
    if orientation not in (None, "landscape", "portrait", "square"):
        return "错误：orientation 必须是 landscape、portrait 或 square。"

    from .. import config

    api_key = getattr(config, "PIXELS_API_KEY", "").strip()
    if not api_key:
        return "图片搜索不可用：未配置 PIXELS_API_KEY。"
    base_url = getattr(config, "PEXELS_BASE_URL", "https://api.pexels.com")

    print(f"Search Pexels images: {normalized_query!r}")
    try:
        payload = await asyncio.to_thread(
            _fetch_pexels_search,
            normalized_query,
            count,
            orientation,
            api_key,
            base_url,
        )
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 0
        print(f"Pexels image search HTTP error: {status_code or 'unknown'}")
        if status_code in (401, 403):
            return "图片搜索失败：PIXELS_API_KEY 无效或无权访问 Pexels API。"
        if status_code == 429:
            return "图片搜索失败：Pexels API 请求过于频繁，请稍后重试。"
        if status_code:
            return f"图片搜索失败：Pexels API 返回 HTTP {status_code}。"
        return "图片搜索失败：Pexels API 返回了未知 HTTP 错误。"
    except requests.exceptions.SSLError as e:
        print(f"Pexels image search SSL error: {e}")
        return "图片搜索失败：无法验证 Pexels API 的 SSL 证书。"
    except requests.exceptions.Timeout as e:
        print(f"Pexels image search timeout: {e}")
        return "图片搜索失败：连接 Pexels API 超时。"
    except requests.exceptions.ConnectionError as e:
        print(f"Pexels image search network error: {e}")
        return "图片搜索失败：暂时无法连接 Pexels API。"
    except requests.exceptions.InvalidJSONError as e:
        print(f"Pexels image search response error: {e}")
        return "图片搜索失败：Pexels API 返回了无效数据。"
    except requests.exceptions.RequestException as e:
        print(f"Pexels image search request error: {e}")
        return "图片搜索失败：Pexels API 请求异常。"

    if not isinstance(payload, dict) or not isinstance(payload.get("photos"), list):
        return "图片搜索失败：Pexels API 返回了无效数据。"

    results: list[str] = []
    for photo in payload["photos"]:
        if not isinstance(photo, dict) or not isinstance(photo.get("src"), dict):
            continue
        image_url = photo["src"].get("large") or photo["src"].get("original")
        if not isinstance(image_url, str) or not image_url.startswith("https://"):
            continue
        alt_value = photo.get("alt")
        photographer_value = photo.get("photographer")
        source_url_value = photo.get("url")
        alt: str = alt_value if isinstance(alt_value, str) else ""
        photographer: str = (
            photographer_value if isinstance(photographer_value, str) else "Unknown"
        )
        source_url: str = (
            source_url_value if isinstance(source_url_value, str) else ""
        )
        details = [
            f"{len(results) + 1}. {alt or normalized_query}",
            f"   image_url: {image_url}",
        ]
        if source_url.startswith("https://"):
            details.append(
                f"   attribution: Photo by {photographer} on Pexels: {source_url}"
            )
        else:
            details.append(f"   attribution: Photo by {photographer} on Pexels")
        results.append("\n".join(details))
        if len(results) >= count:
            break

    if not results:
        return f"Pexels 没有找到与 {normalized_query!r} 匹配的图片。"
    return (
        f"Pexels 找到 {len(results)} 张图片。需要展示时，将所选结果的 image_url "
        "传给 send_image。\n\n" + "\n\n".join(results)
    )


@tool
def get_avatar(qq_id: int) -> str:
    """
    获取用户的QQ头像URL。
    输入用户的QQ号，返回该用户的头像链接。

    ## 参数：
    - qq_id: 用户的QQ号（一串数字）

    ## 使用场景：
    - 需要获取某人的头像图片时使用
    - 获取某人的形象时使用
    """
    from ..utils import get_qq_avatar_url
    print(f"Get avatar: QQ {qq_id}")
    return get_qq_avatar_url(qq_id)


@tool
async def view_image(image_url: str) -> str:
    """
    使用轻量模型读取一张图片，并返回客观、详细的文字描述。此工具不会发送图片。

    ## 参数：
    - image_url: 图片地址，支持：
        1) HTTP/HTTPS 网络图片 URL
        2) 沙盒内图片的 file:// 绝对路径，如 "file:///work/image.png"
    """
    url = image_url.strip()
    if not url:
        return "❌ 错误：image_url 不能为空。"

    if url.startswith("file://"):
        sandbox_path = url[7:]
        if not sandbox_path.startswith("/"):
            return "❌ 错误：file:// 后必须是沙盒内的绝对路径。"

        await ensure_container_running()
        quoted_path = shlex.quote(sandbox_path)
        mime_output = await run_cmd(
            f"file --mime-type -b -- {quoted_path} 2>&1; echo '::EXIT::'$?",
            timeout=30,
        )
        if "::EXIT::" not in mime_output:
            return "❌ 无法读取沙盒图片：未获得文件检测结果。"
        mime_text, mime_exit = mime_output.rsplit("::EXIT::", 1)
        mime = mime_text.strip()
        if mime_exit.strip() != "0":
            return f"❌ 无法读取沙盒图片：{mime or '(no output)'}"
        if not mime.startswith("image/"):
            return f"❌ 错误：该沙盒文件不是图片（MIME: {mime}）。"

        b64_output = await run_cmd(
            f"base64 -w 0 -- {quoted_path} 2>&1; echo '::EXIT::'$?",
            timeout=30,
        )
        if "::EXIT::" not in b64_output:
            return "❌ 无法读取沙盒图片：未获得文件内容。"
        b64_text, b64_exit = b64_output.rsplit("::EXIT::", 1)
        b64_data = b64_text.strip()
        if b64_exit.strip() != "0" or not b64_data:
            return f"❌ 无法读取沙盒图片：{b64_data or '(no output)'}"
        url = f"data:{mime};base64,{b64_data}"
    elif not url.startswith(("http://", "https://")):
        return "❌ 错误：仅支持 HTTP/HTTPS URL 或 file:// 沙盒绝对路径。"

    from langchain.messages import HumanMessage
    from ..models import get_lite_model

    prompt = (
        "请客观、详细地描述这张图片。说明其中可见的人物、物体、场景、动作、"
        "画面风格和重要细节，并准确抄录清晰可见的文字。只返回图片描述。"
    )
    try:
        response = await get_lite_model().ainvoke(
            [
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ]
                )
            ]
        )
    except Exception as e:
        print(f"❌ view_image failed: {e}")
        traceback.print_exc()
        return f"❌ 图片读取失败：{e}"

    content = response.content
    if isinstance(content, list):
        description = "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        ).strip()
    else:
        description = str(content).strip()
    return description or "❌ 图片读取失败：模型未返回描述。"


# ---- Helper: export a random photo from macOS Photos "ACG" album ----
# Returns the host file path on success, or an "❌ ..." error string on failure.
# Extracted so both the random_acg_photo tool (LLM → Docker sandbox) and the
# poke handler (direct send) can reuse the same Photo-export logic.

_MACOS_TMP = "/tmp/hatsume_acg_export"


async def _export_random_acg_photo() -> str:
    """Export a random photo from the 'ACG' album in macOS Photos.

    Returns the absolute host path to the exported file, or a string starting
    with  "❌" describing the error.
    """
    import shutil as _shutil

    # 1. Clean and recreate macOS temp export directory
    if _os.path.exists(_MACOS_TMP):
        _shutil.rmtree(_MACOS_TMP)
    _os.makedirs(_MACOS_TMP, exist_ok=True)

    # 2. AppleScript: query "ACG" album, pick random photo, export
    applescript = f'''
    try
        tell application "Photos"
            if not (exists album "ACG") then
                error "ALBUM_NOT_FOUND"
            end if
            set targetAlbum to album "ACG"
            set allPhotos to every media item of targetAlbum
            set photoCount to count of allPhotos
            if photoCount is 0 then
                error "ALBUM_EMPTY"
            end if
            set randomIndex to random number from 1 to photoCount
            set thePhoto to item randomIndex of allPhotos
            set exportDir to POSIX file "{_MACOS_TMP}"
            export {{thePhoto}} to exportDir with using originals
        end tell
    on error errMsg
        return "ERROR:" & errMsg
    end try
    '''

    result = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True,
        timeout=30,
    )

    stdout_text = result.stdout.decode("utf-8", errors="replace").strip()

    # Check for AppleScript-level errors
    if stdout_text.startswith("ERROR:"):
        err_msg = stdout_text[len("ERROR:"):].strip()
        if "ALBUM_NOT_FOUND" in err_msg:
            return "❌ 错误：未找到名为 'ACG' 的相簿。"
        if "ALBUM_EMPTY" in err_msg:
            return "❌ 错误：'ACG' 相簿中没有照片。"
        return f"❌ 错误：Photos 操作失败：{err_msg}"

    # Check for osascript process failure (Photos not running, permissions, etc.)
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        combined = (stdout_text + " " + stderr_text).strip()
        if "not running" in combined.lower() or "application isn't running" in combined.lower():
            return "❌ 错误：无法访问 Photos 应用，请确认 Photos.app 已打开并授权。"
        return f"❌ 错误：Photos 操作失败：{combined}"

    # 3. Find exported file
    exported = [
        f for f in _os.listdir(_MACOS_TMP)
        if _os.path.isfile(_os.path.join(_MACOS_TMP, f))
    ]
    if not exported:
        return "❌ 错误：照片导出失败，未找到导出文件。"

    host_file = _os.path.join(_MACOS_TMP, exported[0])
    return host_file


@tool
async def random_acg_photo() -> str:
    """
    从 Treep 的相册中随机获取一张动漫藏图。

    照片会被导出并复制到沙盒容器中。返回沙盒内的绝对路径。
    获取到路径后，你需要调用 send_image 工具，并在路径前加上 "file://" 前缀来发送图片。

    ## 返回值示例：
    - 成功：/tmp/apple_photo_export_260711_143025.jpg
    - 失败：❌ 错误描述

    ## 使用场景：
    - 用户想要一张随机的图片时
    - 用户提到想看"二次元"、"动漫"、"ACG" 图时
    """
    from datetime import datetime
    from ..config import CONTAINER_NAME

    host_file = await _export_random_acg_photo()
    if host_file.startswith("❌"):
        return host_file

    _, ext = _os.path.splitext(host_file)
    if not ext:
        ext = ".jpg"

    # Ensure sandbox container is running
    await ensure_container_running()

    # Generate a timestamped, randomized sandbox path and docker cp
    timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
    random_suffix = f"{random.randint(0, 999999):06d}"
    sandbox_name = f"apple_photo_export_{timestamp}_{random_suffix}{ext}"
    sandbox_path = f"/tmp/{sandbox_name}"

    cp_result = subprocess.run(
        ["docker", "cp", host_file, f"{CONTAINER_NAME}:{sandbox_path}"],
        capture_output=True,
        timeout=30,
    )
    if cp_result.returncode != 0:
        stderr = cp_result.stderr.decode("utf-8", errors="replace").strip()
        return f"❌ 错误：无法复制文件到沙盒：{stderr}"

    print(f"📷 [random_acg_photo] Exported {host_file} → sandbox {sandbox_path}")
    return sandbox_path


@tool
async def send_image(image_url: str) -> str:
    """
    发送一张图片给用户。

    ## 参数：
    - image_url: 图片的 URL 地址，支持
        1) HTTP/HTTPS URL 
        2) base64 data URI 格式（如 "base64://..."）
        3) 沙盒文件绝对路径（如 "file:///work/path/to/image.jpg"）

    ## 注意：
    - 每次调用只能发送一张图片
    - 用户需要知道你发送图片的意图以及图片内容的意义。
    """
    global _send_image_count

    if not image_url or not image_url.strip():
        return "❌ 错误：image_url 不能为空。"

    if _send_image_count >= 3:
        return "图片发送失败：一轮发言中你最多只能发送3张图片。"

    _send_image_count += 1

    url = image_url.strip()
    print(f"Send image: {url[:100]}...")

    # Resolve file:// URLs by reading the file from the sandbox
    if url.startswith("file://"):
        sandbox_path = url[7:]  # strip "file://"
        print(f"  → reading sandbox file: {sandbox_path}")

        await ensure_container_running()
        b64_output = await run_cmd(
            f'base64 -w 0 "{sandbox_path}" 2>&1; echo "::EXIT::$?"',
            timeout=30,
        )

        # Split exit code from base64 data
        if "::EXIT::" in b64_output:
            b64_data, exit_part = b64_output.rsplit("::EXIT::", 1)
            exit_code = exit_part.strip()
        else:
            b64_data = b64_output
            exit_code = "1"

        if exit_code != "0" or not b64_data.strip():
            err_msg = b64_data.strip() or "(no output)"
            print(f"❌ sandbox file read failed (exit={exit_code}): {err_msg[:200]}")
            return f"❌ 无法读取沙盒文件：{err_msg[:300]}"

        url = "base64://" + b64_data.strip()
        print(f"  → resolved to base64 data URI ({len(b64_data)} chars)")

    try:
        if _ai_answer:
            await _ai_answer(MessageSegment.image(url))
        else:
            return "❌ 错误：无法发送图片（发送通道未就绪）。"
    except Exception as e:
        print(f"❌ send_image failed: {e}")
        traceback.print_exc()
        return f"❌ 图片发送失败: {e}"

    return "图片已成功发送给用户。"


@tool
async def send_video(video_url: str) -> str:
    """
    发送一个视频给用户。当你需要直接向用户展示某个视频时使用此工具。

    ## 参数：
    - video_url: 视频地址，支持
        1) HTTP/HTTPS URL
        2) 沙盒文件绝对路径（如 "/work/path/to/video.mp4"）
        3) 沙盒 file:// 绝对路径（如 "file:///work/path/to/video.mp4"）

    ## 注意：
    - 每轮 ai_node 最多调用一次
    - 每次调用只能发送一个视频
    - 视频会直接发送给用户，你不需要再额外描述视频内容
    """
    global _send_video_count

    if not video_url or not video_url.strip():
        return "❌ 错误：video_url 不能为空。"

    if _send_video_count >= 1:
        return "视频发送失败：一轮发言中你最多只能发送1个视频。"

    _send_video_count += 1

    url = video_url.strip()
    print(f"Send video: {url[:100]}...")

    if url.startswith("file://"):
        url = url[7:]

    if url.startswith("/"):
        sandbox_path = url
        print(f"  → reading sandbox video file: {sandbox_path}")
        await ensure_container_running()
        b64_output = await run_cmd(
            f'base64 -w 0 {shlex.quote(sandbox_path)} 2>&1; echo "::EXIT::$?"',
            timeout=120,
        )

        if "::EXIT::" in b64_output:
            b64_data, exit_part = b64_output.rsplit("::EXIT::", 1)
            exit_code = exit_part.strip()
        else:
            b64_data = b64_output
            exit_code = "1"

        if exit_code != "0" or not b64_data.strip():
            err_msg = b64_data.strip() or "(no output)"
            print(f"❌ sandbox video read failed (exit={exit_code}): {err_msg[:200]}")
            return f"❌ 无法读取沙盒视频文件：{err_msg[:300]}"

        url = "base64://" + b64_data.strip()
        print(f"  → resolved video to base64 data URI ({len(b64_data)} chars)")

    try:
        if _ai_answer:
            await _ai_answer(MessageSegment.video(file=url))
        else:
            return "❌ 错误：无法发送视频（发送通道未就绪）。"
    except Exception as e:
        print(f"❌ send_video failed: {e}")
        traceback.print_exc()
        return f"❌ 视频发送失败: {e}"

    return "视频已成功发送给用户。"


@tool
async def generate_image(prompt: str, image_urls: list[str]) -> str:
    """
    AI 图片生成工具。

    ## 参数：
    - prompt: 图片描述，支持中文或英文。描述越详细，生成效果越好。
    - image_urls: 参考图片的 URL 列表，可以为空列表 []。支持 HTTP URL 和 沙盒文件的绝对路径（file:// 开头）。请将所有相关的参考图片都通过 URL 的形式放到这个列表中，禁止将图片链接放在提示词中。
    
    ## 注意：
    - 如果用户要求将给定图片修改为你自己的形象，除了在 prompts 中描述你自己的特征外，还需要在 image_urls 中添加你自己头像的链接 （使用 get_avatar 工具获取）。
    - 如果你要向 image_urls 传入多张图片，你需要在 prompts 中用序号标注 图1、图2、... ，并分别描述这些图片的内容。
    - 在得到生成图片的 URL 或路径后，请迅速通过 send_image 工具发送给用户，或者保存到特定位置。禁止将图片 URL 直接返回给用户。
    """
    from ..models import generate_image_for_volc, generate_image_for_kege

    if _is_generate_image_rate_limited():
        return "❌ 图片生成请求过于频繁，请 3 分钟后再试。"

    print(f"Generate image: {prompt}")
    _update_generate_image_time()
    try:
        if random.random() <= 0.5 or len(image_urls) > 0:
            print("Using Seedream 5.0 Lite...")
            url = await generate_image_for_volc(prompt, images=image_urls)
            result_msg = f"图片生成成功。\n临时 URL：{url}\n"
        else:
            print("Using grok-imagine-image...")
            url = generate_image_for_kege(prompt)
            result_msg = f"图片生成成功（此次请求不支持参考图）\n临时 URL：{url}"
    except Exception as e:
        print(f"❌ generate_image failed: {e}")
        traceback.print_exc()
        return f"❌ 图片生成失败: {e}"

    return result_msg

@tool
async def generate_video(prompt: str, image_url: str = "") -> str:
    """
    AI 视频生成工具。根据文字描述生成短视频（Seedance），并返回视频 URL。

    ## 参数：
    - prompt: 视频描述，支持中文或英文。描述越详细，生成效果越好。
    - image_url: 可选，一张参考图片的 URL（HTTP URL 或 base64 data URI）。仅支持单张参考图。

    ## 注意：
    - 视频生成耗时较长（通常 2-10 分钟），请提醒用户耐心等待
    - 生成后你必须调用 send_video 工具把返回的 URL 发送给用户，禁止将视频 URL 直接返回给用户

    ## 返回值：
    返回视频生成状态与临时 URL。
    """
    global _generate_video_used
    from ..models import generate_video_for, choose_video_model

    if _generate_video_used:
        return "❌ 视频生成工具在本轮对话中已被调用过，禁止重复调用。"

    if _is_video_rate_limited():
        return "❌ 视频生成请求过于频繁，请稍后再试。"

    print(f"Generate video: {prompt}, image_url: {image_url[:80] if image_url else '(none)'}")

    model = choose_video_model()
    url = None
    try:
        url = await generate_video_for(prompt, image_url=image_url or None, model=model)
    except Exception as e:
        print(f"❌ generate_video failed: {e}")
        traceback.print_exc()
        return f"❌ 视频生成失败: {e}"

    _update_video_time()
    _generate_video_used = True

    if url is None:
        return f"❌ 视频生成失败（模型 Seedance {model} Pro）。"

    _audio_note = "该模型不支持生成声音。" if model == "1.0" else ""
    note = f"\n{_audio_note}" if _audio_note else ""
    return f"✅ 视频已生成成功（模型 Seedance {model} Pro）。\n临时 URL：{url}{note}"


@tool
async def shell_executor(shell: str, timeout: int) -> str:
    """
    在 Kali Linux 无桌面沙箱环境中执行 bash shell（当前工作目录 pwd 为 /work），并返回输出结果。
    timeout 参数为命令执行时长，单位为秒，超过该时长会被强制终止。一般设为 180 秒。

    ## 约束：
    - 此工具无法执行交互式命令，如安装包时必须使用 `apt install -y` 或 `apt install --assume-yes`。
    - /work 为公共工作目录，如果需要编写项目，请在 /work 中创建一个子目录继续。
    - 只有你自己可以访问沙盒，用户无法访问沙盒。
    - 禁止将沙盒中的路径告诉用户。你必须通过描述、调用工具或上传到 GitHub 仓库的方式向用户展示沙盒中的文件。
    """
    max_calls = _shell_max_calls.get()
    if max_calls is not None:
        count = _shell_call_count.get()
        if count >= max_calls:
            return (
                "❌ 禁止多次调用 shell_executor，"
                "请将你的原始任务使用 agent_dispatch 完整地派发给 coding_agent。"
            )
        _shell_call_count.set(count + 1)

    print("Executing shell: \n\r", shell)
    await ensure_container_running()
    result = await run_cmd(shell, timeout=timeout)
    print("Shell result: \n\r", result)
    return result

# ---------------------------------------------------------------------------
# Timer tools
# ---------------------------------------------------------------------------
async def _create_scheduled_timer(
    user_id: int, prompt: str, plan: SchedulePlan
) -> str:
    """Persist and register one already-validated timer-v2 schedule."""
    if _current_group_id is None:
        return "错误：无法确定当前群聊 ID。"

    from ..timer import get_store
    from ..timer.executor import add_jobs_for_task

    store = get_store()
    if prompt_error := store.validate_prompt(prompt):
        return prompt_error
    task_id = store.create_task(_current_group_id, user_id, prompt, plan)
    add_jobs_for_task(task_id, store)
    return (
        f"定时任务已创建（ID: {task_id}）\n"
        f"内容：{prompt}\n"
        f"类型：{plan.mode}\n"
        f"计划触发：{plan.total_occurrences} 次"
    )


@tool
async def create_daily_timer(
    user_id: int,
    prompt: str,
    start_at: str,
    end_at: str,
    time_points: list[str],
    step: PositiveTimerStep = 1,
) -> str:
    """创建按天重复的定时任务。

    参数：user_id 是通知对象 QQ ID（全体传 0）；prompt 必须非空、不包含时间信息，
    且最多 500 个字符；
    start_at 和 end_at 是含时区的 ISO 8601 起止时刻且边界均包含；step 必须为正整数，
    表示每隔 step 天触发；time_points 最多 5 个，且每项必须严格使用 HH:MM:SS。

    示例：create_daily_timer(123, "提醒喝水", "2026-08-01T00:00:00+08:00",
    "2026-08-10T23:59:59+08:00", ["09:00:00", "18:00:00"], 2)
    """
    from ..timer.schedule import ScheduleValidationError, build_daily_plan

    try:
        plan = build_daily_plan(start_at, end_at, time_points, step)
    except ScheduleValidationError as exc:
        return str(exc)
    return await _create_scheduled_timer(user_id, prompt, plan)


@tool
async def create_weekly_timer(
    user_id: int,
    prompt: str,
    start_at: str,
    end_at: str,
    time_points: list[WeeklyTimePoint],
    step: PositiveTimerStep = 1,
) -> str:
    """创建按周重复的定时任务。

    参数：user_id 是通知对象 QQ ID（全体传 0）；prompt 必须非空、不包含时间信息，
    且最多 500 个字符；start_at/end_at 是含时区且边界均包含的 ISO 8601 时刻；step 必须为正整数，
    表示每隔 step 周触发；time_points 最多 5 个，每项为 weekday（1=周一，7=周日）
    和严格 HH:MM:SS 格式的 time。

    示例：create_weekly_timer(123, "提醒周会", "2026-08-01T00:00:00+08:00",
    "2026-12-31T23:59:59+08:00", [{"weekday": 1, "time": "09:00:00"}], 2)
    """
    from ..timer.schedule import ScheduleValidationError, build_weekly_plan

    try:
        plan = build_weekly_plan(start_at, end_at, time_points, step)
    except ScheduleValidationError as exc:
        return str(exc)
    return await _create_scheduled_timer(user_id, prompt, plan)


@tool
async def create_monthly_timer(
    user_id: int,
    prompt: str,
    start_at: str,
    end_at: str,
    time_points: list[MonthlyTimePoint],
    step: PositiveTimerStep = 1,
) -> str:
    """创建按月重复的定时任务。

    参数：user_id 是通知对象 QQ ID（全体传 0）；prompt 必须非空、不包含时间信息，
    且最多 500 个字符；start_at/end_at 是含时区且边界均包含的 ISO 8601 时刻；step 必须为正整数，
    表示每隔 step 个月触发；time_points 最多 5 个，每项为 day（1..31）和严格
    HH:MM:SS 格式的 time，不存在该日期的月份自动跳过。

    示例：create_monthly_timer(123, "提醒结算", "2026-08-01T00:00:00+08:00",
    "2027-07-31T23:59:59+08:00", [{"day": 31, "time": "18:00:00"}], 1)
    """
    from ..timer.schedule import ScheduleValidationError, build_monthly_plan

    try:
        plan = build_monthly_plan(start_at, end_at, time_points, step)
    except ScheduleValidationError as exc:
        return str(exc)
    return await _create_scheduled_timer(user_id, prompt, plan)


@tool
async def create_at_timer(
    user_id: int, prompt: str, trigger_times: list[str]
) -> str:
    """创建指定时刻触发的定时任务。

    trigger_times 必须是未来、互不重复、含时区的 ISO 8601 时间列表，最多 10 个。
    user_id 是通知对象 QQ ID（全体传 0）；prompt 必须非空、不包含时间信息，且最多 500 个字符。

    示例：create_at_timer(123, "提醒吃药",
    ["2026-08-01T09:00:00+08:00", "2026-08-02T18:00:00+08:00"])
    """
    from ..timer.schedule import ScheduleValidationError, build_at_plan

    try:
        plan = build_at_plan(trigger_times)
    except ScheduleValidationError as exc:
        return str(exc)
    return await _create_scheduled_timer(user_id, prompt, plan)


# ---------------------------------------------------------------------------
# Todo tools
# ---------------------------------------------------------------------------
@tool
async def create_todo(
    initiator_qq_id: int,
    content: str,
    permitted_finisher: str,
    completion_event: str,
) -> str:
    """创建一个最长保留 48 小时的当前群待办。

    当“当前聊天记录”出现值得在未来条件满足时继续完成的事情，可以主动调用；
    禁止仅根据“背景聊天记录”创建。initiator_qq_id 必须是提出该待办的用户 QQ ID。
    content 描述将来要做的事情；permitted_finisher 必须严格说明谁能完成；
    completion_event 必须严格说明什么可观察事件代表完成。三个文本参数均最多 500 字符。
    """
    group_id = get_current_group_id()
    if group_id is None or group_id <= 0:
        return "错误：无法确定当前群聊 ID，待办功能不可用。"

    try:
        from nonebot import get_bot
        from ..utils import get_group_member_name

        initiator_name = await get_group_member_name(
            get_bot(), group_id, initiator_qq_id
        )
    except Exception:
        initiator_name = str(initiator_qq_id)

    try:
        from ..todo import TodoValidationError, get_store
    except Exception as exc:
        print(f"❌ create_todo failed to load store: {exc}")
        traceback.print_exc()
        return "错误：待办数据库暂时不可用。"

    try:
        result = get_store().create_item(
            group_id,
            initiator_qq_id,
            initiator_name,
            content,
            permitted_finisher,
            completion_event,
        )
    except TodoValidationError as exc:
        return str(exc)
    except Exception as exc:
        print(f"❌ create_todo failed: {exc}")
        traceback.print_exc()
        return "错误：待办数据库暂时不可用。"

    if result.status == "full":
        return "错误：当前群已有 15 个活动待办，无法创建更多待办。"
    if result.item is None:
        return "错误：待办创建失败。"
    item = result.item
    if result.status == "duplicate":
        return f"未重复创建：相同的活动待办已存在（ID: {item['id']}）。"
    return (
        f"待办已创建（ID: {item['id']}）。\n"
        f"发起人：{item['initiator_group_name']}({item['initiator_qq_id']})\n"
        f"内容：{item['content']}\n"
        f"完成条件：\n{item['finish_condition']}"
    )


@tool
def mark_todo(todo_id: int) -> str:
    """在当前群待办的严格完成条件已经满足时，将其标记完成并删除。

    可以结合近期对话上下文判断，但 Permitted finisher 和 Completion event 必须同时满足。
    不确定时禁止调用。禁止把过期当作完成；过期待办由系统自动删除。
    """
    group_id = get_current_group_id()
    if group_id is None or group_id <= 0:
        return "错误：无法确定当前群聊 ID，待办功能不可用。"

    try:
        from ..todo import get_store

        item = get_store().mark_item(group_id, todo_id)
    except Exception as exc:
        print(f"❌ mark_todo failed: {exc}")
        traceback.print_exc()
        return "错误：待办数据库暂时不可用。"
    if item is None:
        return "错误：当前群找不到该活动待办。"
    return (
        f"待办已因完成条件满足而完成并删除（不是因为过期）。\n"
        f"待办 ID：{item['id']}\n"
        f"发起人：{item['initiator_group_name']}({item['initiator_qq_id']})\n"
        f"内容：{item['content']}\n"
        f"完成条件：\n{item['finish_condition']}\n"
        "你必须在本轮自然回复中包含 "
        f"[CQ:at,qq={item['initiator_qq_id']}]，明确告诉发起人该待办已完成，"
        "并说明原因是完成条件已满足，而不是待办过期。"
    )


@tool
async def list_timers() -> str:
    """
    查看当前群的所有定时任务，按尚未完成和已完成分组。
    频率任务显示完整起止范围、间隔、时间点和进度；指定时刻任务显示每个触发时间及状态。
    """
    return await get_timer_overview()


def _format_timer_timestamp(timestamp: float) -> str:
    from datetime import datetime

    from ..timer.schedule import SHANGHAI

    return datetime.fromtimestamp(timestamp, tz=SHANGHAI).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _format_frequency_rule(task: dict[str, Any], points: list[dict[str, Any]]) -> str:
    mode = task["schedule_type"]
    step = int(task["step"])
    if mode == "daily":
        schedule_type = "每天" if step == 1 else f"每 {step} 天"
        point_text = "、".join(sorted(str(point["clock_time"]) for point in points))
    elif mode == "weekly":
        schedule_type = "每周" if step == 1 else f"每 {step} 周"
        weekday_names = ("", "周一", "周二", "周三", "周四", "周五", "周六", "周日")
        ordered = sorted(points, key=lambda point: (point["period_value"], point["clock_time"]))
        point_text = "、".join(
            f"{weekday_names[int(point['period_value'])]} {point['clock_time']}"
            for point in ordered
        )
    else:
        schedule_type = "每月" if step == 1 else f"每 {step} 个月"
        ordered = sorted(points, key=lambda point: (point["period_value"], point["clock_time"]))
        point_text = "、".join(
            f"{int(point['period_value'])} 日 {point['clock_time']}"
            for point in ordered
        )
    return (
        f"  类型：{schedule_type}\n"
        f"  范围：{_format_timer_timestamp(task['start_at'])} 至 "
        f"{_format_timer_timestamp(task['end_at'])}\n"
        f"  时间点：{point_text}"
    )


def _next_timer_occurrence(
    task: dict[str, Any], points: list[dict[str, Any]]
) -> float | None:
    from ..timer.schedule import occurrence_at_index

    candidates = [
        occurrence_at_index(task, point, int(point["processed_occurrences"]))
        for point in points
        if point["processed_occurrences"] < point["planned_occurrences"]
    ]
    return min(candidates, default=None)


async def get_timer_overview(group_id: int | None = None) -> str:
    """Return the exact timer overview shared by the tool and system prompt."""
    resolved_group_id = group_id if group_id is not None else _current_group_id
    if resolved_group_id is None:
        return "错误：无法确定当前群聊 ID。"

    from ..timer import get_store
    store = get_store()
    tasks = store.list_tasks_by_group(resolved_group_id)

    # Look up user names (cache per user_id for tasks sharing the same owner)
    user_names: dict[int, str] = {}
    try:
        from nonebot import get_bot
        from ..utils import get_group_member_name
        bot = get_bot()
        for task in tasks:
            uid = task["user_id"]
            if uid != 0 and uid not in user_names:
                user_names[uid] = await get_group_member_name(
                    bot, resolved_group_id, uid
                )
    except Exception:
        pass  # fall back to showing raw user_id

    pending_tasks: list[str] = []
    completed_tasks: list[str] = []
    for task in tasks:
        tid = task["id"]
        uid = task["user_id"]
        prompt = task["prompt"]
        user_name = user_names.get(uid)
        if uid == 0:
            owner = "无"
        elif user_name and user_name != str(uid):
            owner = f"@{user_name}({uid})"
        else:
            owner = str(uid)
        points = store.get_points_for_task(tid)
        next_occurrence = _next_timer_occurrence(task, points)
        next_text = (
            _format_timer_timestamp(next_occurrence)
            if next_occurrence is not None
            else "无"
        )
        details = (
            _format_frequency_rule(task, points)
            if task["schedule_type"] != "at"
            else "  类型：指定时间\n  触发时间：\n"
            + "\n".join(
                "    - "
                + _format_timer_timestamp(float(point["exact_at"]))
                + (
                    "：已完成"
                    if point["processed_occurrences"] >= point["planned_occurrences"]
                    else "：未完成"
                )
                for point in points
            )
        )
        summary = (
            f"- 任务 ID：{tid}\n"
            f"  提醒用户：{owner}\n"
            f"  任务提示词：{prompt}\n"
            f"{details}\n"
            f"  计划触发：{task['total_occurrences']} 次；"
            f"已处理：{task['processed_occurrences']} 次\n"
            f"  下一次触发：{next_text}"
        )
        target = (
            pending_tasks
            if task["processed_occurrences"] < task["total_occurrences"]
            else completed_tasks
        )
        target.append(summary)

    title = (
        "# 当前群的定时任务"
        if group_id is None
        else f"# 群 {resolved_group_id} 的定时任务"
    )
    return (
        f"{title}\n\n"
        "## 尚未完成的定时任务\n"
        + ("\n\n".join(pending_tasks) if pending_tasks else "无")
        + "\n\n## 已完成的定时任务\n"
        + ("\n\n".join(completed_tasks) if completed_tasks else "无")
    )


@tool
async def delete_timer(task_id: int) -> str:
    """
    删除指定 ID 的定时任务及其所有触发器。
    只能删除当前群的定时任务。

    ## 参数：
    - task_id: 要删除的任务 ID
    """
    global _current_group_id

    if _current_group_id is None:
        return "错误：无法确定当前群聊 ID。"

    from ..timer import get_store
    store = get_store()

    task = store.get_task(task_id)
    if task is None:
        return f"错误：任务 ID {task_id} 不存在。"

    if task["group_id"] != _current_group_id:
        return f"错误：任务 ID {task_id} 不属于当前群。"

    # Cancel APScheduler jobs
    from ..timer.executor import cancel_task_jobs
    cancel_task_jobs(task_id, store)

    store.delete_task(task_id)
    return f"定时任务（ID: {task_id}）已删除。"


# ---------------------------------------------------------------------------
# Skill tools
# ---------------------------------------------------------------------------
@tool
async def skill_loader(name: str) -> str:
    """
    加载指定名称的技能文件，获取该技能的详细指令内容。

    ## 参数：
    - name: 技能名称（与可用技能列表中显示的名称一致）

    ## 行为：
    - 如果该技能在本次对话中已经加载过，返回提示信息（去重）
    - 如果技能存在，返回完整的技能指令内容
    - 如果技能不存在，返回错误信息

    ## 使用时机：
    - 当用户的需求匹配某个技能的描述时，调用此工具加载该技能
    - 加载后，你会获得该技能的详细指令，按照指令执行即可
    """
    from ..skills import get_skill_manager
    return get_skill_manager().load_skill(name)


@tool
async def skill_remove(name: str) -> str:
    """
    删除指定名称的技能文件。

    ## ⚠️ 重要约束：
    - **仅在用户明确要求删除某个技能时才调用此工具**
    - 用户模糊提及或讨论某个技能时，不要调用此工具
    - 用户必须明确表达删除意图（如"删除技能XXX"、"移除XXX技能"），才可调用
    - 禁止在未获得用户明确许可的情况下删除任何技能

    ## 参数：
    - name: 要删除的技能名称

    ## 行为：
    - 如果技能存在，删除对应文件并返回成功信息
    - 如果技能不存在，返回错误信息
    """
    from ..skills import get_skill_manager
    return get_skill_manager().remove_skill(name)


@tool
def skill_download(url: str) -> str:
    """
    从给定的 raw URL 下载技能 markdown 文件并保存到技能目录。

    ## 参数：
    - url: skill markdown 文件的 raw URL（原始文本 URL，非 HTML 页面）

    ## 行为：
    - 下载 URL 内容，解析 YAML frontmatter 提取技能名称
    - 保存为 data/hatsume-plugin/skills/{name}.md
    - 如果同名技能已存在，覆盖并提示
    - 清除 SkillManager 缓存，使新技能立即可用

    ## 错误处理：
    - URL 无法访问 → 返回错误信息
    - 下载内容无有效 frontmatter → 返回错误信息
    - name 字段缺失或为空 → 返回错误信息

    ## 使用时机：
    - 用户明确要求下载/安装某个技能
    - 用户提供了一个 skill 文件的 URL
    """
    from ..skills import get_skill_manager
    from ..config import SKILLS_DIR

    # Download (use unverified SSL context for environments with missing root certs)
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as response:
            content = response.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"❌ skill_download URL error: {e}")
        return f"错误：无法访问 URL：{e.reason}"
    except Exception as e:
        print(f"❌ skill_download download error: {e}")
        return f"错误：下载失败：{e}"

    if not content.strip():
        return "错误：下载内容为空。"

    # Parse frontmatter for name
    mgr = get_skill_manager()
    meta = mgr.parse_frontmatter_text(content)
    if meta is None:
        return "错误：下载内容不是有效的技能文件（缺少 YAML frontmatter 或 'name' 字段）。"

    name = str(meta.get("name", "")).strip()
    if not name:
        return "错误：无法从下载内容中解析技能名称。"

    # Save
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = SKILLS_DIR / f"{name}.md"
    existed = file_path.exists()
    try:
        file_path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"❌ skill_download write error: {e}")
        return f"错误：保存技能文件失败：{e}"

    # Clear cache so next list_skills / load_skill picks up the new/updated file
    mgr._content_cache.pop(name, None)

    if existed:
        print(f"✅ skill_download overwrote skill '{name}'")
        return f"✅ 技能 '{name}' 已下载（覆盖了已有文件）。"
    else:
        print(f"✅ skill_download installed skill '{name}'")
        return f"✅ 技能 '{name}' 已下载。"


@tool
def skill_create(content: str) -> str:
    """
    根据提供的完整技能内容创建一个新技能或覆盖已有技能。

    ## 参数：
    - content: 完整的技能 markdown 内容。必须以 --- 开头的 YAML frontmatter 开始，
      frontmatter 中必须包含 name（技能名称）和 description（技能描述）两个字段。

    ## 行为：
    - 从 frontmatter 中自动解析 name 和 description
    - 保存为 data/hatsume-plugin/skills/{name}.md
    - 如果同名技能已存在，覆盖并提示
    - 创建后技能立即可用（无需重启）

    ## frontmatter 示例：
    ```
    ---
    name: my-skill
    description: 简短描述该技能的功能
    version: 1.0.0
    author: 作者名
    ---
    # 技能指令内容
    ...
    ```

    ## 使用时机：
    - 用户明确要求创建或编写一个新技能
    - 用户提供了完整的技能内容（含 frontmatter）
    """
    from ..skills import get_skill_manager

    mgr = get_skill_manager()
    meta = mgr.parse_frontmatter_text(content)
    if meta is None:
        return "错误：内容不是有效的技能文件（缺少 --- frontmatter 或 'name' 字段）。"

    name = meta["name"]
    description = meta.get("description", "").strip()
    if not description:
        return f"错误：frontmatter 中缺少 'description' 字段。技能 '{name}' 需要描述才能被识别。"

    return mgr.save_skill(name, content)


@tool
async def membersearch(query: str) -> str:
    """
    在当前群聊中模糊搜索群成员。根据用户提供的模糊/不完整昵称，查找匹配的群成员信息。

    ## 参数：
    - query: 模糊搜索关键词，支持部分昵称、群名片等。如 "菠萝"

    ## 返回：
    返回一个 JSON 数组，每个元素包含：
    - username: 群成员的用户名（优先群名片，无群名片则使用昵称）
    - id: 成员的 QQ 号
    - level: 成员的活跃等级

    列表最多返回 5 个结果，排在越前面的结果越准确。

    ## 使用场景：
    - 用户提到某个不完整的名字，你需要确定具体是谁
    - 有人提到"那个叫什么菠萝的"，你搜索 "菠萝" 来找出可能的成员
    """
    import json
    from nonebot import get_bot
    from ..utils import search_group_members

    global _current_group_id

    if _current_group_id is None:
        return json.dumps({"error": "错误：无法确定当前群聊 ID。"}, ensure_ascii=False)

    try:
        bot = get_bot()
        results = await search_group_members(bot, _current_group_id, query)
    except Exception as e:
        print(f"❌ membersearch failed: {e}")
        import traceback
        traceback.print_exc()
        return json.dumps({"error": f"搜索失败: {e}"}, ensure_ascii=False)

    if not results:
        return "未找到匹配的群成员。"

    return json.dumps(results, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agent dispatch tool
# ---------------------------------------------------------------------------
# Build agent list string at module level (agents.py registered on import)
_AGENT_LIST_STR = "\n".join(
    f"- **{a['name']}**: {a['description']}" for a in get_agent_list()
)


@tool(description=f"""将特定任务分配给 Subagent 后台执行。Subagent 完成任务后会通知你。
    ## 注意
    - 禁止创建多个重复任务的 agent。
    - 派发 Agents 后，禁止sleep等待后台agents完成。
    - Agents 之间互相独立，可并行工作，且不共享上下文。

## 参数：
- agent_name: 内置 Agent 名称
- task: 要执行的任务描述。任务描述必须包含所有必要信息。子 Agent 的上下文将只包含 task 中的信息。
- context: 派发此 Agent 的背景上下文，需给出详细的上下文描述，大概300字左右，包括用户的对话背景、需求内容、以及为什么需要派发 Agent 来完成（必填）
- notified_user_id: 需要通知的用户 QQ ID，如果有用户向你发起了任务，必须传入其QQ号（可选，默认为 0。如果不需要 @ 提醒任何用户，请设置为 0）

## 可用 Agent：
{_AGENT_LIST_STR}""")
async def agent_dispatch(
    agent_name: str,
    task: str,
    context: str,
    notified_user_id: int = 0,
) -> str:

    handler = get_agent_handler(agent_name)
    if handler is None:
        available = ", ".join(a["name"] for a in get_agent_list())
        return f"错误：未知 Agent '{agent_name}'。可用 Agent: {available}"

    print(f"🧩 [agent_dispatch] Dispatching {agent_name} (notify_user={notified_user_id})")

    async def _run_and_notify() -> None:
        from .agents import add_agent_instance, set_agent_state
        import time as _time

        notified_user_name = await _resolve_notified_user_name(
            notified_user_id, _current_group_id
        )

        instance_id = add_agent_instance(
            agent_name,
            status="running",
            task=task,
            context=context,
            user_id=notified_user_id,
            user_name=notified_user_name,
            started_at=_time.time(),
        )
        try:
            result = await handler(task, notified_user_id)
        except Exception:
            print(f"❌ Agent {agent_name} failed")
            traceback.print_exc()
            result = f"Agent '{agent_name}' 执行失败。"
        set_agent_state(agent_name, instance_id=instance_id, status="done", result=result)

        from .nodes import inject_agent_notification
        if _agent_notification_callback is not None:
            inject_agent_notification(
                user_id=notified_user_id,
                group_id=_current_group_id or 0,
                agent_name=agent_name,
                result=result,
                task=task,
                context=context,
                notified_user_name=notified_user_name,
                start_conversation_cb=_agent_notification_callback,
            )
        else:
            print("❌ _agent_notification_callback is None, agent result lost")

    asyncio.create_task(_run_and_notify())
    return f"✅ Agent '{agent_name}' 开始执行任务，任务完成后将通知你。"


@tool
async def respond_to_shell_prompt(
    request_id: str,
    text: str,
) -> str:
    """向后台 shell 进程的 stdin 请求发送回复。

    当后台 shell agent 发出 SHELL_STDIN_REQUEST 通知时，
    使用此 tool 将所需信息传递给进程。

    Args:
        request_id: 通知中的 request_id，格式为 stdin_<proc_id>_<seq>
        text: 要传递的原始信息（如密码、确认、token 等）。
              后台 shell agent 的代码模型会将其转换为进程实际需要的格式。

    Returns:
        成功或失败的描述信息。
    """
    from .agents import _stdin_queues

    q = _stdin_queues.pop(request_id, None)
    if q is None:
        return (
            f"错误：找不到 pending stdin 请求 (request_id={request_id})。"
            f"可能该请求已超时、已被处理、或 request_id 不正确。"
        )

    await q.put(text)
    return f"✅ 已成功向后台进程发送 stdin 输入 (request_id={request_id})。"


@tool
async def create_character_proxy(
    proxied_user_id: int,
    during_time: int = 180,
) -> str:
    """
    开始为指定用户代理发言。
    开启后，其他用户 @ 该用户时，你也会收到通知。
    仅当用户明确要求你代替自己回复其他群成员时调用。

    Args:
        proxied_user_id: 被代理群成员的 QQ 用户 ID。
        during_time: 代理持续时间，单位为分钟，默认 180 分钟，最长 1440 分钟。
    """
    if during_time <= 0 or during_time > 24 * 60:
        return "代理持续时间必须大于 0 分钟且不能超过 1440 分钟。"

    from nonebot import get_bot

    from ..character_proxy import (
        activate_character_proxy,
        generate_character_profile,
        get_character_proxy,
        schedule_character_proxy_termination,
    )
    from ..utils import get_group_member_name

    if get_character_proxy() is not None:
        return "角色代理已经开启；当前状态下只能先终止它。"
    if _current_group_id is None:
        return "无法确定当前群，未开启角色代理。"

    user_name = await get_group_member_name(
        get_bot(), _current_group_id, proxied_user_id
    )
    profile = await generate_character_profile(proxied_user_id, user_name)
    activate_character_proxy(
        user_id=proxied_user_id,
        user_name=user_name,
        behavior_prompt=profile.behavior_prompt,
        aliases=profile.aliases,
        during_time=during_time,
    )
    schedule_character_proxy_termination(during_time)
    return f"已为 {user_name} 开启角色代理，将在 {during_time} 分钟后自动停止。"


@tool
def terminate_character_proxy() -> str:
    """终止对当前用户的代理发言。
    结束后，其他用户 @ 该用户时你将不会收到通知。
    仅当用户明确要求停止角色代理时调用。
    """
    from ..character_proxy import terminate_character_proxy_state

    previous = terminate_character_proxy_state()
    if previous is None:
        return "当前没有开启角色代理。"
    return f"已停止 {previous.user_name} 的角色代理。"


@tool
def end_conversation() -> str:
    """结束当前对话。

    执行此工具后，你不会再接收到任何聊天消息，直到有人主动提及你。
    当用户希望你不回话时使用。
    """
    if _end_conversation_callback is None:
        return "当前对话无法结束：对话状态尚未初始化。"
    _end_conversation_callback()
    return "当前对话已结束；不要继续回复，等待有人主动提及你。"


# Single registration point consumed by graph.nodes. Add new chat-facing tools here.
CHAT_TOOLS = [
    search_web,
    search_image,
    shell_executor,
    find_memory,
    view_image,
    generate_image,
    generate_video,
    send_image,
    send_video,
    get_avatar,
    random_acg_photo,
    create_daily_timer,
    create_weekly_timer,
    create_monthly_timer,
    create_at_timer,
    create_todo,
    mark_todo,
    list_timers,
    delete_timer,
    skill_loader,
    skill_remove,
    skill_download,
    skill_create,
    membersearch,
    agent_dispatch,
    respond_to_shell_prompt,
    create_character_proxy,
    terminate_character_proxy,
    end_conversation,
]


def get_chat_tools() -> list[Any]:
    """Expose exactly one character-proxy lifecycle tool for current state."""
    from ..character_proxy import get_character_proxy

    unavailable = (
        terminate_character_proxy
        if get_character_proxy() is None
        else create_character_proxy
    )
    return [tool_item for tool_item in CHAT_TOOLS if tool_item is not unavailable]
