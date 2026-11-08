"""Exercise production send_text through LangChain without booting NoneBot.

Group state, text conversion, memory storage, and delivery are substituted;
Message is represented as a list because these tests target call limits.
"""

import ast
import contextlib
import io
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.tools import tool


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "hatsume/plugins/hatsume-plugin/graph/tools.py"
)
TREE = ast.parse(SOURCE.read_text())
CODE = compile(
    ast.Module(
        body=[
            node for node in TREE.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in {"_message_id_suffix", "send_text"}
        ],
        type_ignores=[],
    ),
    str(SOURCE),
    "exec",
)


class SendTextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sender = AsyncMock(side_effect=range(1001, 1021))
        self.memories = AsyncMock(return_value=0)
        self.runtime = SimpleNamespace(
            group_id=123456,
            send_text_count=0,
            replyable_message_ids=set(),
            replyable_senders={},
            conversation=SimpleNamespace(ai_answer=self.sender, chat_peers=set()),
        )
        package = "_send_text_test_plugin"
        config = ModuleType(f"{package}.config")
        config.BOT_QQ_ID = 999
        state = ModuleType(f"{package}.state")
        state.peer_session_id = lambda group_id, user_id: f"{group_id}:{user_id}"
        module = ModuleType(f"{package}.graph.tools")
        module.__package__ = f"{package}.graph"
        module.__dict__.update({
            "Any": Any,
            "MemoryRecordInput": Any,
            "tool": tool,
            "Message": list,
            "CQ_AT_PATTERN": re.compile(r"\[CQ:at,qq=(\d+)\]"),
            "get_current_group_runtime": lambda: self.runtime,
            "mask_secret_keys": lambda text: text,
            "auto_convert_text": AsyncMock(side_effect=lambda text: [text]),
            "_record_memories": self.memories,
        })
        self.enterContext(patch.dict(sys.modules, {
            config.__name__: config,
            state.__name__: state,
            module.__name__: module,
        }))
        exec(CODE, module.__dict__)
        self.send_text = module.send_text

    async def send(self, text, **kwargs):
        return await self.send_text.ainvoke({"text": text, **kwargs})

    async def test_third_and_later_calls_reach_delivery(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for index in range(5):
                result = await self.send(f"message {index}")
                self.assertIn("文字已成功发送", result)
                self.assertIn(f"[replyable_message_id:{1001 + index}]", result)
        self.assertEqual(self.sender.await_count, 5)
        self.assertEqual(
            [call.args[0] for call in self.sender.await_args_list],
            [[f"message {index}"] for index in range(5)],
        )
        self.assertEqual(self.runtime.replyable_message_ids, set(range(1001, 1006)))
        self.assertIn("send attempt=3", output.getvalue())
        self.assertIn("message_id=1005", output.getvalue())

    async def test_silent_calls_do_not_block_later_messages(self):
        for text in ("", None, "  " ):
            self.assertIn("静默模式", await self.send(text))
        self.sender.assert_not_awaited()
        self.assertEqual(self.memories.await_count, 3)
        for index in range(3):
            self.assertIn("文字已成功发送", await self.send(f"message {index}"))
        self.assertEqual(self.sender.await_count, 3)

    async def test_repeated_silent_calls_work_without_send_channel(self):
        self.runtime.conversation.ai_answer = None
        for _ in range(4):
            self.assertIn("静默模式", await self.send(""))
        self.sender.assert_not_awaited()
        self.assertEqual(self.memories.await_count, 4)

    async def test_failed_sends_do_not_block_later_messages(self):
        self.sender.side_effect = [False, RuntimeError("delivery unavailable"), 1003, 1004]
        self.assertIn("消息未能发送", await self.send("first"))
        self.assertIn("delivery unavailable", await self.send("second"))
        self.assertIn("文字已成功发送", await self.send("third"))
        self.assertIn("文字已成功发送", await self.send("fourth"))
        self.assertEqual(self.sender.await_count, 4)
        self.assertEqual(self.runtime.replyable_message_ids, {1003, 1004})

    async def test_third_call_can_reply_to_previously_sent_message(self):
        await self.send("first")
        await self.send("second")
        result = await self.send("third", reply_to_message_id=1001)
        self.assertIn("文字已成功发送", result)
        self.sender.assert_awaited_with(["third"], reply_to_message_id=1001)

    async def test_missing_channel_and_invalid_reply_still_fail(self):
        self.runtime.conversation.ai_answer = None
        self.assertIn("发送通道未就绪", await self.send("message"))
        self.runtime.conversation.ai_answer = self.sender
        self.assertIn("reply_to_message_id 不在", await self.send("message", reply_to_message_id=42))
        self.sender.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
