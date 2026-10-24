"""Context management contracts through real LangChain graphs and filesystem I/O."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import PrivateAttr

ROOT = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"
PACKAGE = "agent_context_contract"


class SessionModel(FakeMessagesListChatModel):
    """Script agent actions; answer summary calls without consuming an action."""

    _inputs: list = PrivateAttr(default_factory=list)
    _summaries: list = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if str(messages[0].content).startswith("Summarize this agent session"):
            self._summaries.append(messages[0].content)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                "Goal: finish task. Prior output is archived. Next: inspect recent results."
            ))])
        self._inputs.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.modules = {}
        for name, directory in ((PACKAGE, ROOT), (f"{PACKAGE}.graph", ROOT / "graph")):
            module = ModuleType(name)
            module.__path__ = [str(directory)]
            self.modules[name] = module
        self.modules[f"{PACKAGE}.utils"] = SimpleNamespace(strip_thinking_tags=lambda text: text)
        self.modules[f"{PACKAGE}.group_runtime"] = SimpleNamespace(get_current_group_id=lambda: 123)
        self.modules[f"{PACKAGE}.infra"] = SimpleNamespace(LOCAL_WORKSPACE_PATH=self.directory)
        patcher = patch.dict(sys.modules, self.modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.context = load(f"{PACKAGE}.graph.context", ROOT / "graph/context.py")
        self.chat_loop = load(f"{PACKAGE}.graph.chat_loop", ROOT / "graph/chat_loop.py")
        self.agents = load(f"{PACKAGE}.graph.agents", ROOT / "graph/agents.py")
        self.context.CONTEXT_TRIGGER_TOKENS = 1200
        self.context.CONTEXT_KEEP_TOKENS = 300
        self.context.TOOL_OUTPUT_MAX_CHARS = 1800

    def model(self, *responses):
        return SessionModel(responses=list(responses))

    async def test_send_text_first_gate_blocks_until_send_text_is_attempted(self):
        middleware = self.chat_loop.SendTextFirstMiddleware()

        blocked_request = SimpleNamespace(
            tool_call={"name": "shell_executor", "id": "blocked"}
        )
        blocked_handler_called = False

        async def blocked_handler(_request):
            nonlocal blocked_handler_called
            blocked_handler_called = True
            return "should not run"

        blocked = await middleware.awrap_tool_call(blocked_request, blocked_handler)
        self.assertEqual(blocked.content, self.chat_loop.SEND_TEXT_FIRST_WARNING)
        self.assertFalse(blocked_handler_called)

        send_request = SimpleNamespace(
            tool_call={"name": "send_text", "id": "send"}
        )
        send_attempted = False

        async def send_handler(_request):
            nonlocal send_attempted
            send_attempted = True
            raise RuntimeError("send failed")

        with self.assertRaisesRegex(RuntimeError, "send failed"):
            await middleware.awrap_tool_call(send_request, send_handler)
        self.assertTrue(send_attempted)

        later_request = SimpleNamespace(
            tool_call={"name": "shell_executor", "id": "later"}
        )
        async def later_handler(_request):
            return "allowed"

        later = await middleware.awrap_tool_call(later_request, later_handler)
        self.assertEqual(later, "allowed")

    async def test_send_text_first_gate_state_survives_agent_reconstruction(self):
        middleware = self.chat_loop.SendTextFirstMiddleware()
        request = SimpleNamespace(tool_call={"name": "send_text", "id": "send"})
        async def send_handler(_request):
            return "sent"

        await middleware.awrap_tool_call(request, send_handler)

        later_request = SimpleNamespace(
            tool_call={"name": "dynamic_mcp_tool", "id": "mcp"}
        )
        async def mcp_handler(_request):
            return "mcp result"

        result = await middleware.awrap_tool_call(later_request, mcp_handler)
        self.assertEqual(result, "mcp result")

    def install_agent_fixtures(self, model):
        async def shell_executor(shell: str, timeout: int = 30) -> str:
            """Read a fixture log."""
            return "BEGIN\n" + "log line\n" * 2500 + "END"
        async def tinyfish_search(query: str, location: str | None = None, language: str | None = None) -> str:
            """Search a fixture index through TinyFish SDK."""
            return "Sources\n" + "source details\n" * 2500 + "https://example.test/docs"
        async def tinyfish_fetch(urls: list[str], format: str = "markdown", links: bool | None = None, image_links: bool | None = None) -> str:
            """Fetch a fixture page through TinyFish SDK."""
            return "Fetched source details"
        async def web_search(query: str) -> str:
            """Search a fixture index for the coding agent."""
            return await tinyfish_search(query)
        async def skill_loader(name: str) -> str:
            """Read a fixture skill."""
            return "skill instructions"
        tools = SimpleNamespace(
            shell_executor=tool(shell_executor),
            web_search=tool(web_search),
            tinyfish_search=tool("tinyfish_search")(tinyfish_search),
            tinyfish_fetch=tool("tinyfish_fetch")(tinyfish_fetch),
            skill_loader=tool(skill_loader), set_shell_executor_limit=lambda limit: None,
            _agent_notification_callback=None,
        )
        for name in ("generate_image", "search_image", "skill_create", "skill_download", "skill_remove"):
            setattr(tools, name, tools.skill_loader)
        sys.modules[f"{PACKAGE}.graph.tools"] = tools
        sys.modules["langchain_tinyfish"] = SimpleNamespace(
            TinyFishSearch=lambda: tools.tinyfish_search,
            TinyFishFetch=lambda: tools.tinyfish_fetch,
        )
        sys.modules[f"{PACKAGE}.models"] = SimpleNamespace(get_code_model=lambda: model, get_lite_model=lambda: model)
        sys.modules[f"{PACKAGE}.prompts"] = SimpleNamespace(
            CODING_AGENT_PROMPT="Complete coding work", WEB_RESEARCHER_PROMPT="Research sources",
            build_skill_prompt=lambda skills: "", BACKGROUND_SHELL_DECISION_PROMPT="Monitor command",
            BACKGROUND_SHELL_STDIN_RESOLUTION_PROMPT="Resolve stdin",
        )
        sys.modules[f"{PACKAGE}.skills"] = SimpleNamespace(get_skill_manager=lambda: SimpleNamespace(list_skills=lambda: []))
        return tools

    async def test_coding_and_research_handlers_compact_and_archive(self):
        for handler_name, tool_name, args in (
            ("_run_coding_agent", "shell_executor", {"shell": "read log"}),
            ("_run_web_researcher", "tinyfish_search", {"query": "docs"}),
        ):
            with self.subTest(handler=handler_name):
                model = self.model(
                    AIMessage("", tool_calls=[{"name": tool_name, "args": args, "id": "call1"}]),
                    AIMessage("", tool_calls=[{"name": tool_name, "args": args, "id": "call2"}]),
                    AIMessage("final report"),
                )
                self.install_agent_fixtures(model)
                result = await getattr(self.agents, handler_name)("old task details " * 1000, 0)
                self.assertEqual(result, "final report")
                self.assertGreaterEqual(len(model._summaries), 1)
                for messages in model._inputs:
                    calls = {call["id"] for m in messages if isinstance(m, AIMessage) for call in m.tool_calls}
                    outputs = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
                    self.assertEqual(calls, outputs)
                    self.assertTrue(all(len(m.content) <= 1800 for m in messages if isinstance(m, ToolMessage)))
        files = list((self.directory / ".hatsume-context/123").glob("output-*.txt"))
        self.assertEqual(len(files), 4)
        self.assertTrue(all(len(path.read_text()) > 1800 for path in files))

    async def test_chat_reminder_survives_compaction_and_second_mcp_pass(self):
        @tool
        def inspect_log() -> str:
            """Inspect the fixture log."""
            return "log\n" * 600
        responses = [AIMessage("", tool_calls=[{"name": "inspect_log", "args": {}, "id": f"round{i}"}]) for i in range(8)]
        model = self.model(*responses, AIMessage("first pass complete"), AIMessage("second pass complete"))
        messages = [HumanMessage("historical task " * 1000), AIMessage("old reply"), HumanMessage("current task")]
        loop = self.chat_loop.ChatLoopDelegationMiddleware(len(messages))
        middleware = [loop, *self.context.build_context_middleware(model)]
        first = create_agent(model, tools=[inspect_log], middleware=middleware)
        result = await first.ainvoke({"messages": messages}, {"recursion_limit": 60})
        self.assertGreater(len(model._summaries), 1)
        self.assertEqual(loop._rounds, 8)
        self.assertTrue(loop._reminded)
        reminders = [m for m in model._inputs[7] if m.id == loop.reminder_id]
        self.assertEqual(len(reminders), 1)
        second = create_agent(model, tools=[inspect_log], middleware=middleware)
        result = await second.ainvoke({"messages": result["messages"]})
        self.assertEqual(result["messages"][-1].content, "second pass complete")
        self.assertEqual(loop._rounds, 8)
        self.assertLessEqual(sum(m.id == loop.reminder_id for m in result["messages"]), 1)

    async def test_failed_summary_does_not_replace_history(self):
        class BrokenModel(SessionModel):
            def _generate(self, *args, **kwargs):
                raise RuntimeError("provider unavailable")
        middleware = self.context.build_context_middleware(BrokenModel(responses=[]))[-1]
        messages = [HumanMessage("important constraints " * 1000), AIMessage("decision"), HumanMessage("continue")]
        original = [m.content for m in messages]
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            await middleware.abefore_model({"messages": messages}, None)
        self.assertEqual([m.content for m in messages], original)
        empty = self.context.build_context_middleware(FakeMessagesListChatModel(responses=[AIMessage("")]))[-1]
        with self.assertRaisesRegex(ValueError, "empty summary"):
            await empty.abefore_model({"messages": messages}, None)

    def test_sync_tools_archive_losslessly_and_preserve_status(self):
        original = "头部\n" + "中文 error log\n" * 2000 + "尾部"
        output = ToolMessage(original, tool_call_id="call", status="error", artifact={"exit_code": 1})
        result = self.context.ToolOutputMiddleware().wrap_tool_call(None, lambda request: output)
        self.assertLessEqual(len(result.content), 1800)
        self.assertTrue(result.content.startswith("头部"))
        self.assertTrue(result.content.endswith("尾部"))
        self.assertEqual((result.status, result.artifact, result.tool_call_id), ("error", {"exit_code": 1}, "call"))
        files = list((self.directory / ".hatsume-context/123").glob("*.txt"))
        self.assertEqual(files[0].read_text(), original)
        self.assertIn(str(files[0]), result.content)

    async def test_small_and_multimodal_outputs_are_preserved(self):
        middleware = self.context.ToolOutputMiddleware()
        for content in ("small output", [{"type": "image_url", "image_url": {"url": "https://example.test/img.png"}}]):
            message = ToolMessage(content, tool_call_id="call")
            async def handler(request):
                return message
            result = await middleware.awrap_tool_call(None, handler)
            self.assertEqual(result.content, content)
        self.assertFalse((self.directory / ".hatsume-context").exists())

    async def test_mcp_text_blocks_share_a_budget_and_preserve_images(self):
        image = {"type": "image_url", "image_url": {"url": "https://example.test/img.png"}}
        text = "text " * 3000
        message = ToolMessage([
            {"type": "text", "text": text}, image, {"type": "text", "text": text},
        ], tool_call_id="mcp")
        async def handler(request):
            return message
        result = await self.context.ToolOutputMiddleware().awrap_tool_call(None, handler)
        self.assertEqual(result.content[1], image)
        self.assertEqual(len(result.content), 2)
        self.assertLessEqual(len(result.content[0]["text"]), 1800)
        files = list((self.directory / ".hatsume-context/123").glob("*.txt"))
        self.assertEqual(files[0].read_text(), text + "\n" + text)

    def test_sync_graph_summarizes_and_continues(self):
        model = self.model(AIMessage("sync complete"))
        agent = create_agent(model, tools=[], middleware=self.context.build_context_middleware(model))
        result = agent.invoke({"messages": [
            HumanMessage("historic facts " * 1000), AIMessage("past result"), HumanMessage("continue"),
        ]})
        self.assertEqual(result["messages"][-1].content, "sync complete")
        self.assertEqual(len(model._summaries), 1)

    async def test_coding_compaction_preserves_system_and_human_messages(self):
        model = self.model(AIMessage("continued"))
        middleware = self.context.build_context_middleware(
            model,
            preserve_system_human=True,
        )[-1]
        system = SystemMessage("coding policy: keep the requested files safe")
        initial_task = HumanMessage("implement the requested change")
        old_call = AIMessage(
            "",
            tool_calls=[{"name": "shell_executor", "args": {"cmd": "git status"}, "id": "old-call"}],
        )
        old_result = ToolMessage("old tool output " * 1000, tool_call_id="old-call")
        follow_up = HumanMessage("continue from the previous result")
        update = await middleware.abefore_model(
            {"messages": [system, initial_task, old_call, old_result, follow_up]},
            None,
        )

        self.assertIsNotNone(update)
        compacted = [message for message in update["messages"] if message.type != "remove"]
        self.assertEqual(compacted[0], system)
        self.assertEqual(compacted[1], initial_task)
        self.assertEqual(compacted[2].type, "human")
        self.assertIn("Here is a summary of the conversation to date:", compacted[2].content)
        self.assertEqual(compacted[3], follow_up)
        self.assertNotIn(old_call, compacted)
        self.assertNotIn(old_result, compacted)
        self.assertEqual(len(model._summaries), 1)

    async def test_background_shell_keeps_compacted_history_and_bounds_notifications(self):
        model = self.model(
            AIMessage(json.dumps({"cmd": "fixture", "description": "until finished", "total_timeout": 1000})),
            AIMessage("NOTIFY:30"), *[AIMessage("CONTINUE:30") for _ in range(6)], AIMessage("DONE"),
        )
        self.install_agent_fixtures(model)
        infra = sys.modules[f"{PACKAGE}.infra"]
        async def ready(group_id):
            pass
        infra.ensure_container_running = ready
        infra.start_background_cmd = lambda *args, **kwargs: "process.log"
        infra.read_background_output = lambda path, offset: ("BEGIN\n" + "process output\n" * 1000 + "END", offset + 1)
        infra.get_background_process = lambda *args, **kwargs: (SimpleNamespace(poll=lambda: None), None)
        infra.kill_background_cmd = lambda *args, **kwargs: ""
        notifications = []
        sys.modules[f"{PACKAGE}.graph.nodes"] = SimpleNamespace(inject_agent_notification=lambda **kwargs: notifications.append(kwargs))
        async def no_wait(seconds):
            pass
        instance = self.agents.add_agent_instance("background_shell", group_id=123, task="monitor")
        with self.agents.bind_agent_instance(instance), patch.object(asyncio, "sleep", no_wait):
            result = await self.agents._run_background_shell("monitor process", 0)
        self.assertIn("命令执行结束", result)
        self.assertIn("Full output:", result)
        self.assertGreater(len(model._summaries), 1)
        self.assertEqual(len(notifications), 1)
        self.assertLess(len(notifications[0]["result"]), 2200)
        self.assertLess(len(result), 2200)
        files = list((self.directory / ".hatsume-context/123").glob("*.txt"))
        self.assertTrue(any(len(p.read_text()) > 100_000 for p in files))


if __name__ == "__main__":
    unittest.main()
