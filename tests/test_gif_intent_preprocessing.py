import ast
from pathlib import Path
from typing import Any
from collections.abc import Mapping
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain.messages import HumanMessage


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "hatsume/plugins/hatsume-plugin/graph/nodes.py"


class GifIntentPreprocessingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        names = {
            "_is_gif_image_url",
            "_describe_gif_for_intent",
            "_replace_gifs_for_intent",
            "_prepare_jev_state_for_intent",
        }
        nodes = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ]
        self.vision = AsyncMock(
            return_value=SimpleNamespace(content="一只猫在动图中挥手。")
        )
        namespace = {
            "Any": Any,
            "Mapping": Mapping,
            "HumanMessage": HumanMessage,
            "get_view_image_model": lambda: SimpleNamespace(ainvoke=self.vision),
            "print": lambda *_args, **_kwargs: None,
        }
        exec(
            compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"),
            namespace,
        )
        self.is_gif = namespace["_is_gif_image_url"]
        self.prepare = namespace["_prepare_jev_state_for_intent"]

    def test_detects_gif_data_uri_and_url(self):
        self.assertTrue(self.is_gif("data:image/gif;base64,AAAA"))
        self.assertTrue(self.is_gif("https://example.test/a.gif?x=1"))
        self.assertFalse(self.is_gif("data:image/png;base64,AAAA"))

    async def test_replaces_gif_with_vision_text_and_removes_image_part(self):
        state = {
            "current_message": [
                {"type": "text", "text": "看看这个"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/gif;base64,AAAA"},
                },
            ],
            "recent_messages": [],
        }
        prepared = await self.prepare(state)
        parts = prepared["current_message"]
        self.assertEqual(parts[1]["type"], "text")
        self.assertIn("一只猫在动图中挥手", parts[1]["text"])
        self.vision.assert_awaited_once()
        request = self.vision.await_args.args[0][0]
        self.assertIsInstance(request, HumanMessage)
        self.assertEqual(request.content[1]["image_url"]["url"], "data:image/gif;base64,AAAA")

    async def test_reuses_one_description_for_duplicate_gif(self):
        gif = {"type": "image_url", "image_url": {"url": "x.gif"}}
        prepared = await self.prepare({"a": [gif], "b": [gif]})
        self.assertIn("一只猫在动图中挥手", prepared["a"][0]["text"])
        self.assertIn("一只猫在动图中挥手", prepared["b"][0]["text"])
        self.vision.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
