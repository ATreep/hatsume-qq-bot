"""Tests for forward message parsing module."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "hatsume/plugins/hatsume-plugin"
FORWARD_PATH = BASE / "handlers/forward.py"


def _setup_package_hierarchy() -> None:
    """Set up package stubs so relay imports resolve."""
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", BASE),
        ("hatsume.plugins.hatsume-plugin.handlers", BASE / "handlers"),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod


def _stub_nonebot() -> None:
    """Set up nonebot package hierarchy with pure stubs (no real imports)."""
    for name in list(sys.modules):
        if name.startswith("nonebot"):
            del sys.modules[name]

    # Stub MessageSegment: callable(type, data) + static .text() / .image()
    class _MessageSegment:
        def __init__(self, type_name: str = "", data: dict | None = None):
            self.type = type_name
            self.data = data or {}
        @staticmethod
        def text(text: str) -> "_MessageSegment":
            return _MessageSegment("text", {"text": text})
        @staticmethod
        def image(file=None, **kwargs) -> "_MessageSegment":
            data = {"file": file} if file is not None else {}
            data.update(kwargs)
            return _MessageSegment("image", data)
        def __repr__(self):
            return f"MessageSegment({self.type}, {self.data})"

    # Stub Message: list-like with extract_plain_text
    class _Message(list):
        def extract_plain_text(self) -> str:
            parts = []
            for seg in self:
                if seg.type == "text":
                    parts.append(seg.data.get("text", ""))
            return "".join(parts)
        def __repr__(self):
            return f"Message({list.__repr__(self)})"

    nonebot_mod = types.ModuleType("nonebot")
    nonebot_mod.__path__ = []
    sys.modules["nonebot"] = nonebot_mod

    adapters_mod = types.ModuleType("nonebot.adapters")
    adapters_mod.__path__ = []
    adapters_mod.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters"] = adapters_mod

    onebot_mod = types.ModuleType("nonebot.adapters.onebot")
    onebot_mod.__path__ = []
    sys.modules["nonebot.adapters.onebot"] = onebot_mod

    v11_mod = types.ModuleType("nonebot.adapters.onebot.v11")
    v11_mod.Message = _Message
    v11_mod.MessageSegment = _MessageSegment
    v11_mod.MessageEvent = type("MessageEvent", (), {})
    v11_mod.PokeNotifyEvent = type("PokeNotifyEvent", (), {})
    v11_mod.GroupMessageEvent = type("GroupMessageEvent", (), {})
    v11_mod.Bot = type("Bot", (), {})
    sys.modules["nonebot.adapters.onebot.v11"] = v11_mod

# Ensure nonebot stubs are set up at module level for cross-test isolation
_stub_nonebot()


def _stub_config() -> None:
    """Stub config module so import of MAX_FORWARD_DEPTH works."""
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.MAX_FORWARD_DEPTH = 3
    config_mod.FORWARD_API_TIMEOUT_SECONDS = 10
    config_mod.BOT_QQ_ID = 1234567890
    config_mod.CONTEXT_QUEUE_LEN = 50
    config_mod.IMAGE_MAX_PIXELS = 36_000_000
    config_mod.IMAGE_MAX_SIZE_BYTES = 9 * 1024 * 1024
    config_mod.MESSAGE_MAX_LENGTH = 2000
    config_mod.REPLY_MAX_LENGTH = 200
    config_mod.USER_INPUT_CONFIRM_DURING_TIME = 10
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod


def _load_utils() -> types.ModuleType:
    """Load utils.py module."""
    utils_spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", BASE / "utils/__init__.py"
    )
    utils_mod = importlib.util.module_from_spec(utils_spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = utils_mod
    utils_spec.loader.exec_module(utils_mod)
    return utils_mod


def _load_forward() -> types.ModuleType:
    """Load forward.py module with all dependencies stubbed."""
    _setup_package_hierarchy()
    _stub_nonebot()
    _stub_config()
    _load_utils()

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.handlers.forward", FORWARD_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.handlers.forward"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# T008: has_forward_segment
# ---------------------------------------------------------------------------

class TestHasForwardSegment:

    @classmethod
    def setup_class(cls):
        cls.forward = _load_forward()

    def test_forward_segment_present(self):
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        msg = Message([
            MessageSegment.text("hello"),
            MessageSegment("forward", {"id": "test_forward_123"}),
        ])
        result = self.forward.has_forward_segment(msg)
        assert result == "test_forward_123"

    def test_forward_segment_absent(self):
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        msg = Message([
            MessageSegment.text("hello"),
            MessageSegment.image("http://example.com/img.jpg"),
        ])
        result = self.forward.has_forward_segment(msg)
        assert result is None

    def test_multiple_segments_first_forward(self):
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        msg = Message([
            MessageSegment.text("hello"),
            MessageSegment("forward", {"id": "first_forward"}),
            MessageSegment("forward", {"id": "second_forward"}),
        ])
        result = self.forward.has_forward_segment(msg)
        assert result == "first_forward"

    def test_empty_message(self):
        from nonebot.adapters.onebot.v11 import Message
        msg = Message([])
        result = self.forward.has_forward_segment(msg)
        assert result is None


# ---------------------------------------------------------------------------
# T009: parse_forward_messages
# ---------------------------------------------------------------------------

class TestParseForwardMessages:

    @classmethod
    def setup_class(cls):
        cls.forward = _load_forward()

    @pytest.mark.asyncio
    async def test_flat_forward_single_node(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value={
            "message": [{
                "type": "node",
                "data": {
                    "user_id": "123456",
                    "nickname": "张三",
                    "content": [{"type": "text", "data": {"text": "今天天气真好"}}],
                },
            }]
        })
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert len(messages) == 1
        assert messages[0]["type"] == "message"
        assert messages[0]["user"]["id"] == 123456
        assert messages[0]["user"]["name"] == "张三"
        assert messages[0]["content"] == "今天天气真好"

    @pytest.mark.asyncio
    async def test_flat_forward_multiple_nodes(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[
            {"user_id": 111, "nickname": "张三", "content": [{"type": "text", "data": {"text": "消息1"}}]},
            {"user_id": 222, "nickname": "李四", "content": [{"type": "text", "data": {"text": "消息2"}}]},
            {"user_id": 333, "nickname": "王五", "content": [{"type": "text", "data": {"text": "消息3"}}]},
        ])
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_vendor_messages_envelope_and_nested_sender(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value={
            "messages": [{
                "sender": {"user_id": 456, "nickname": "李四"},
                "message": [{"type": "text", "data": {"text": "兼容格式"}}],
                "time": 12345,
            }]
        })
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert messages[0]["user"] == {"id": 456, "name": "李四"}
        assert messages[0]["content"] == "兼容格式"
        assert messages[0]["time"] == "12345"

    @pytest.mark.asyncio
    async def test_api_failure_returns_placeholder(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(side_effect=Exception("API error"))
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert len(messages) == 1
        assert "合并转发消息获取失败" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_empty_response(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[])
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_invalid_response_returns_placeholder(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value={"unexpected": []})
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert len(messages) == 1
        assert "获取失败" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_node_content_as_string(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[
            {"user_id": 111, "nickname": "张三", "content": "直接文本内容"}
        ])
        messages = await self.forward.parse_forward_messages(mock_bot, "test_id")
        assert len(messages) == 1
        assert messages[0]["content"] == "直接文本内容"

    @pytest.mark.asyncio
    async def test_mixed_content_preserves_text_image_and_nested_forward_order(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(side_effect=[
            {"message": [{
                "type": "node",
                "data": {
                    "user_id": "111",
                    "nickname": "张三",
                    "content": [
                        {"type": "text", "data": {"text": "前文"}},
                        {"type": "image", "data": {"url": "https://example.com/a.jpg"}},
                        {"type": "forward", "data": {"id": "nested"}},
                        {"type": "text", "data": {"text": "后文"}},
                    ],
                },
            }]},
            {"message": [{
                "type": "node",
                "data": {
                    "user_id": "222",
                    "nickname": "李四",
                    "content": "嵌套内容",
                },
            }]},
        ])

        messages = await self.forward.parse_forward_messages(mock_bot, "root")

        assert [message["type"] for message in messages] == [
            "message", "forward", "message"
        ]
        assert "前文" in messages[0]["content"]
        assert "https://example.com/a.jpg" in messages[0]["content"]
        assert messages[1]["messages"][0]["content"] == "嵌套内容"
        assert messages[2]["content"] == "后文"

    @pytest.mark.asyncio
    async def test_inline_forward_messages_are_parsed_without_an_api_fetch(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value={
            "message": [{"type": "node", "data": {
                "user_id": 111,
                "nickname": "外层用户",
                "content": [{"type": "forward", "data": {
                    "id": "unused-inline-id",
                    "messages": [{"type": "node", "data": {
                        "user_id": 222,
                        "nickname": "内层用户",
                        "content": [
                            {"type": "text", "data": {"text": "内层消息"}}
                        ],
                    }}],
                }}],
            }}]
        })

        messages = await self.forward.parse_forward_messages(mock_bot, "root")

        assert messages[0]["type"] == "forward"
        assert messages[0]["messages"][0]["user"] == {
            "id": 222,
            "name": "内层用户",
        }
        assert messages[0]["messages"][0]["content"] == "内层消息"
        mock_bot.call_api.assert_awaited_once_with("get_forward_msg", id="root")

    @pytest.mark.asyncio
    async def test_inline_node_segment_is_parsed_recursively(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[{
            "user_id": 111,
            "nickname": "外层用户",
            "content": [{"type": "node", "data": {
                "user_id": 222,
                "nickname": "内层用户",
                "content": "node 内的消息",
            }}],
        }])

        messages = await self.forward.parse_forward_messages(mock_bot, "root")

        assert messages[0]["type"] == "forward"
        assert messages[0]["messages"][0]["content"] == "node 内的消息"
        mock_bot.call_api.assert_awaited_once_with("get_forward_msg", id="root")

    @pytest.mark.asyncio
    async def test_raw_inline_sender_record_preserves_sender_and_content(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[{
            "user_id": 111,
            "nickname": "外层用户",
            "content": [{"type": "forward", "data": {
                "content": {
                    "sender": {"user_id": 333, "nickname": "原始内层用户"},
                    "message": [
                        {"type": "text", "data": {"text": "原始内层消息"}}
                    ],
                },
            }}],
        }])

        messages = await self.forward.parse_forward_messages(mock_bot, "root")

        nested = messages[0]["messages"][0]
        assert nested["user"] == {"id": 333, "name": "原始内层用户"}
        assert nested["content"] == "原始内层消息"
        mock_bot.call_api.assert_awaited_once_with("get_forward_msg", id="root")

    @pytest.mark.asyncio
    async def test_inline_nesting_obeys_the_depth_limit(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[{
            "user_id": 1,
            "nickname": "A",
            "content": [{"type": "forward", "data": {
                "messages": [{"type": "node", "data": {
                    "user_id": 2,
                    "nickname": "B",
                    "content": "不会展开",
                }}],
            }}],
        }])

        messages = await self.forward.parse_forward_messages(mock_bot, "d3", depth=3)

        assert messages[0]["type"] == "forward"
        assert messages[0]["depth"] == 4
        assert "嵌套层数过多" in messages[0]["messages"][0]["content"]
        mock_bot.call_api.assert_awaited_once_with("get_forward_msg", id="d3")

    @pytest.mark.asyncio
    async def test_depth_three_is_parsed_and_depth_four_is_truncated(self):
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(side_effect=[
            {"message": [{"type": "node", "data": {
                "user_id": 1, "nickname": "A",
                "content": [{"type": "forward", "data": {"id": "d4"}}],
            }}]},
        ])

        messages = await self.forward.parse_forward_messages(mock_bot, "d3", depth=3)

        assert messages[0]["type"] == "forward"
        assert messages[0]["depth"] == 4
        assert "嵌套层数过多" in messages[0]["messages"][0]["content"]
        mock_bot.call_api.assert_awaited_once_with("get_forward_msg", id="d3")


# ---------------------------------------------------------------------------
# resolve_forward_content
# ---------------------------------------------------------------------------

class TestResolveForwardContent:

    @classmethod
    def setup_class(cls):
        cls.forward = _load_forward()

    @pytest.mark.asyncio
    async def test_no_forward_segment_returns_none(self):
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        mock_bot = MagicMock()
        msg = Message([MessageSegment.text("hello")])
        result = await self.forward.resolve_forward_content(mock_bot, msg)
        assert result is None

    @pytest.mark.asyncio
    async def test_forward_segment_resolves(self):
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        mock_bot = MagicMock()
        mock_bot.call_api = AsyncMock(return_value=[
            {"user_id": 111, "nickname": "张三", "content": [{"type": "text", "data": {"text": "hi"}}]},
        ])
        msg = Message([MessageSegment("forward", {"id": "fw123"})])
        result = await self.forward.resolve_forward_content(mock_bot, msg)
        assert result is not None
        assert len(result) == 1


# ---------------------------------------------------------------------------
# collect_people_from_messages
# ---------------------------------------------------------------------------

class TestCollectPeopleFromMessages:

    @classmethod
    def setup_class(cls):
        cls.forward = _load_forward()

    def test_flat_messages(self):
        messages = [
            {"type": "message", "user": {"id": 111, "name": "张三"}, "content": "hi"},
            {"type": "message", "user": {"id": 222, "name": "李四"}, "content": "hello"},
        ]
        people = self.forward.collect_people_from_messages(messages)
        assert len(people) == 2

    def test_nested_messages(self):
        messages = [
            {
                "type": "forward",
                "user": {"id": 111, "name": "转发者"},
                "messages": [
                    {"type": "message", "user": {"id": 222, "name": "张三"}, "content": "hi"},
                    {"type": "message", "user": {"id": 333, "name": "李四"}, "content": "hello"},
                ],
            }
        ]
        people = self.forward.collect_people_from_messages(messages)
        assert len(people) == 3

    def test_deduplicate_people(self):
        messages = [
            {"type": "message", "user": {"id": 111, "name": "张三"}, "content": "hi"},
            {"type": "message", "user": {"id": 111, "name": "张三"}, "content": "hello again"},
        ]
        people = self.forward.collect_people_from_messages(messages)
        assert len(people) == 1


# ---------------------------------------------------------------------------
# T005: Forward segment detection in message segment loop
# ---------------------------------------------------------------------------

class TestForwardSegmentInMessageLoop:

    def test_forward_segment_visible_in_iteration(self):
        """Verify that a forward segment appears when iterating message segments."""
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        msg = Message([
            MessageSegment.text("look at this"),
            MessageSegment("forward", {"id": "fw_test_123"}),
        ])

        segment_types: list[str] = []
        forward_ids: list[str] = []
        for seg in msg:
            segment_types.append(seg.type)
            if seg.type == "forward":
                forward_ids.append(seg.data.get("id", ""))

        assert "forward" in segment_types, (
            "forward segment type must appear when iterating message"
        )
        assert "fw_test_123" in forward_ids

    def test_plain_message_collects_forward_marker(self):
        """Simulate plain_message building: forward segments produce a marker."""
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        msg = Message([
            MessageSegment.text("hello"),
            MessageSegment("forward", {"id": "fw_abc"}),
        ])

        plain_message = ""
        for msg_seg in msg:
            match msg_seg.type:
                case "text":
                    plain_message += msg_seg.data.get("text", "")
                case "forward":
                    fwd_id = msg_seg.data.get("id", "")
                    plain_message += f" [合并转发消息 id={fwd_id}] "

        assert "合并转发消息" in plain_message
        assert "fw_abc" in plain_message

    def test_no_forward_segment_plain_message_unchanged(self):
        """Normal message without forward: plain_message is unaffected."""
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        msg = Message([
            MessageSegment.text("hello"),
            MessageSegment.text(" world"),
        ])

        plain_message = ""
        for msg_seg in msg:
            match msg_seg.type:
                case "text":
                    plain_message += msg_seg.data.get("text", "")
                case "forward":
                    fwd_id = msg_seg.data.get("id", "")
                    plain_message += f" [合并转发消息 id={fwd_id}] "

        assert plain_message == "hello world"
        assert "合并转发" not in plain_message
