"""Tests for JSON message format pipeline (message_to_json, pipeline output)."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "hatsume/plugins/hatsume-plugin"


def _load_utils() -> types.ModuleType:
    """Load utils.py with config stubbed."""
    # Stub config
    config_mod = types.ModuleType("hatsume.plugins.hatsume-plugin.config")
    config_mod.MAX_FORWARD_DEPTH = 3
    config_mod.BOT_QQ_ID = 1234567890
    sys.modules["hatsume.plugins.hatsume-plugin.config"] = config_mod

    # Package hierarchy
    for name, path in [
        ("hatsume", ROOT / "hatsume"),
        ("hatsume.plugins", ROOT / "hatsume/plugins"),
        ("hatsume.plugins.hatsume-plugin", BASE),
    ]:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = [str(path)]
            sys.modules[name] = mod

    # Stub nonebot
    if "nonebot" not in sys.modules:
        sys.modules["nonebot"] = types.ModuleType("nonebot")
    if "nonebot.adapters" not in sys.modules:
        adapters = types.ModuleType("nonebot.adapters")
        adapters.__path__ = []
        sys.modules["nonebot.adapters"] = adapters
    if not hasattr(sys.modules["nonebot.adapters"], "Bot"):
        sys.modules["nonebot.adapters"].Bot = type("Bot", (), {})

    spec = importlib.util.spec_from_file_location(
        "hatsume.plugins.hatsume-plugin.utils", BASE / "utils/__init__.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume.plugins.hatsume-plugin.utils"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# T010: message_to_json
# ---------------------------------------------------------------------------

class TestMessageToJson:

    @classmethod
    def setup_class(cls):
        cls.utils = _load_utils()

    def test_plain_message(self):
        result = self.utils.message_to_json(
            user_name="张三", user_id=123456,
            content="今天天气真好", msg_time="2026/05/31 18:30:00",
        )
        assert result["type"] == "message"
        assert result["time"] == "2026/05/31 18:30:00"
        assert result["user"] == {"id": 123456, "name": "张三"}
        assert result["content"] == "今天天气真好"
        assert result["reply_to"] is None

    def test_reply_message(self):
        result = self.utils.message_to_json(
            user_name="李四", user_id=789012,
            content="好啊我请客", msg_time="2026/05/31 18:32:00",
            reply_to={"user": {"id": 123456, "name": "张三"}, "content": "晚上去吃饭吗？"},
        )
        assert result["type"] == "message"
        assert result["reply_to"] is not None
        assert result["reply_to"]["user"]["name"] == "张三"

    def test_message_with_depth(self):
        result = self.utils.message_to_json(
            user_name="王五", user_id=333,
            content="嵌套消息", msg_time="", depth=1,
        )
        assert result["depth"] == 1

    def test_message_without_depth(self):
        result = self.utils.message_to_json(
            user_name="赵六", user_id=444,
            content="普通消息", msg_time="",
        )
        assert "depth" not in result

    def test_content_as_array(self):
        result = self.utils.message_to_json(
            user_name="张三", user_id=111,
            content=[{"type": "text", "text": "看图"}],
            msg_time="",
        )
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    def test_json_serializable(self):
        result = self.utils.message_to_json(
            user_name="张三", user_id=123456,
            content="测试消息", msg_time="2026/05/31 18:30:00",
        )
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed == result


class TestBuildForwardJson:

    @classmethod
    def setup_class(cls):
        cls.utils = _load_utils()

    def test_build_forward(self):
        messages = [
            {"type": "message", "user": {"id": 222, "name": "张三"}, "content": "hi"},
        ]
        result = self.utils.build_forward_json("转发者", 111, messages, "2026/05/31 18:35:00")
        assert result["type"] == "forward"
        assert result["user"]["id"] == 111
        assert result["user"]["name"] == "转发者"
        assert len(result["messages"]) == 1

    def test_forward_json_serializable(self):
        result = self.utils.build_forward_json("转发者", 111, [], "")
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["type"] == "forward"
