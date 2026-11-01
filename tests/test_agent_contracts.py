"""Contracts for model-visible Agent behavior and confidence policy."""

from pathlib import Path
import unittest

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
        self.assertNotIn("below 0.40", text)

    def test_send_text_documents_optional_memories(self):
        text = (PLUGIN / "graph/tools.py").read_text(encoding="utf-8")
        self.assertIn("memories: list[MemoryRecordInput] | None = None", text)
        self.assertIn("省略或传空列表不会阻止文字发送", text)


if __name__ == "__main__":
    unittest.main()
