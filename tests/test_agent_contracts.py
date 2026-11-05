"""Contracts for model-visible Agent behavior and confidence policy."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "hatsume/plugins/hatsume-plugin"


class AgentContractTests(unittest.TestCase):
    def test_current_model_prompts_do_not_expose_chat_agent_name(self):
        for path in (
            PLUGIN / "prompts.py",
            PLUGIN / "graph/tools.py",
            PLUGIN / "graph/chat_loop.py",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("[chat_agent]", text, str(path))

    def test_gui_claims_are_not_in_current_readme(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("hatsume-space-gui", text)
        self.assertNotIn("gui-sandbox.md", text)

    def test_confidence_threshold_and_log_are_consistent(self):
        text = (PLUGIN / "graph/nodes.py").read_text(encoding="utf-8")
        self.assertIn("CHAT_INTENT_CONFIDENCE_THRESHOLD = 0.20", text)
        self.assertIn("< CHAT_INTENT_CONFIDENCE_THRESHOLD", text)
        self.assertIn("below {CHAT_INTENT_CONFIDENCE_THRESHOLD:.2f}", text)
        self.assertIn("CHAT_END_CONFIDENCE_THRESHOLD = 0.60", text)
        self.assertIn("chat_end_confidence > CHAT_END_CONFIDENCE_THRESHOLD", text)
        self.assertIn("required>{CHAT_END_CONFIDENCE_THRESHOLD:.2f}", text)
        self.assertNotIn("below 0.40", text)

    def test_chat_end_requires_confidence_strictly_above_threshold(self):
        text = (PLUGIN / "graph/nodes.py").read_text(encoding="utf-8")
        start = text.index('            chat_end_answer = _jev_answer(jev_response, "chat_end")')
        end = text.index('            chat_intent_answer = ', start)
        import textwrap

        source = "def decide():\n" + textwrap.indent(textwrap.dedent(text[start:end]), "    ")
        code = compile(ast.parse(source), "chat_end_decision", "exec")
        for confidence, expected in (
            (0.59, False), (0.60, False), (0.6001, True), (1.0, True),
            (None, False), ("invalid", False), ("0.7", True),
            (float("nan"), False),
        ):
            with self.subTest(confidence=confidence):
                callback = Mock()
                namespace = {
                    "_jev_answer": lambda *_: {"choice": "结束", "confidence": confidence},
                    "jev_response": {},
                    "chat_end_bypassed": False,
                    "CHAT_END_CONFIDENCE_THRESHOLD": 0.60,
                    "conversation_state": SimpleNamespace(request_end_conversation=callback),
                }
                exec(code, namespace)
                namespace["decide"]()
                self.assertEqual(callback.called, expected)

    def test_send_text_documents_optional_memories(self):
        text = (PLUGIN / "graph/tools.py").read_text(encoding="utf-8")
        self.assertIn("memories: list[MemoryRecordInput] | None = None", text)
        self.assertIn("省略或传空列表不会阻止文字发送", text)


if __name__ == "__main__":
    unittest.main()
