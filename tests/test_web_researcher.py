"""Run the researcher through real LangGraph with a scripted model and search fixture."""
import ast
from collections.abc import Mapping
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"


class SearchModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        if [item.name for item in tools] != [
            "tinyfish_search",
            "tinyfish_fetch",
            "shell_executor",
            "skill_loader",
        ]:
            raise AssertionError("Researcher must expose TinyFish SDK search/fetch plus shell_executor and skill_loader")
        return self


class WebResearcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_researcher_searches_and_returns_visible_report(self):
        calls = []
        fetch_calls = []
        @tool("tinyfish_search")
        def tinyfish_search(query: str, location: str | None = None, language: str | None = None) -> str:
            """Search the fixture index through TinyFish SDK."""
            calls.append(query)
            return "GNOME AT-SPI documentation https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/"
        @tool("tinyfish_fetch")
        def tinyfish_fetch(urls: list[str], format: str = "markdown", links: bool | None = None, image_links: bool | None = None) -> str:
            """Fetch fixture pages through TinyFish SDK."""
            fetch_calls.append(urls)
            return "Fetched GNOME AT-SPI documentation"
        @tool
        def shell_executor(shell: str, timeout: int) -> str:
            """Run a shell command in the fixture sandbox."""
            return ""
        @tool
        def skill_loader(name: str) -> str:
            """Load a skill in the fixture sandbox."""
            return ""
        report = "参考 GNOME AT-SPI 文档：https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/"
        model = SearchModel(responses=[
                    AIMessage(content="", tool_calls=[{"name": "tinyfish_search", "args": {"query": "GNOME AT-SPI"}, "id": "q1"}]),
            AIMessage(content="", tool_calls=[{"name": "tinyfish_fetch", "args": {"urls": ["https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/"]}, "id": "q2"}]),
            AIMessage(content=report),
        ])
        package = "researcher_test_plugin"
        modules = {}
        for name in [package, f"{package}.graph"]:
            module = ModuleType(name)
            module.__path__ = [str(ROOT / "graph" if name.endswith(".graph") else ROOT)]
            modules[name] = module
        modules[f"{package}.graph.tools"] = SimpleNamespace(
            shell_executor=shell_executor,
            skill_loader=skill_loader,
            set_shell_executor_limit=lambda _limit: None,
        )
        modules["langchain_tinyfish"] = SimpleNamespace(
            TinyFishSearch=lambda: tinyfish_search,
            TinyFishFetch=lambda: tinyfish_fetch,
        )
        modules[f"{package}.models"] = SimpleNamespace(get_lite_model=lambda: model)
        modules[f"{package}.prompts"] = SimpleNamespace(WEB_RESEARCHER_PROMPT="实际搜索并返回来源")
        modules[f"{package}.utils"] = SimpleNamespace(strip_thinking_tags=lambda value: value)
        tree = ast.parse((ROOT / "graph/agents.py").read_text())
        namespace = {"__package__": f"{package}.graph", "Any": Any, "Mapping": Mapping}
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in {"_run_web_researcher", "_extract_visible_agent_text"}]
        with patch.dict(sys.modules, modules), patch("builtins.print") as print_mock:
            exec(compile(ast.Module(body=nodes, type_ignores=[]), "researcher", "exec"), namespace)
            result = await namespace["_run_web_researcher"]("查找无障碍文档", 123)
        self.assertEqual(calls, ["GNOME AT-SPI"])
        self.assertEqual(fetch_calls, [["https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/"]])
        logs = [str(call.args[0]) for call in print_mock.call_args_list if call.args]
        self.assertTrue(any("[tinyfish_search]" in line for line in logs))
        self.assertTrue(any("[tinyfish_fetch]" in line for line in logs))
        self.assertEqual(result, report)

    def test_agent_is_registered_and_chat_has_no_search_tool(self):
        path = ROOT / "graph/agents.py"
        spec = importlib.util.spec_from_file_location("researcher_registry_test", path)
        registry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registry)
        self.assertIs(registry.get_agent_handler("web_researcher"), registry._run_web_researcher)
        self.assertIn("web_researcher", [a["name"] for a in registry.get_agent_list()])
        tree = ast.parse((ROOT / "graph/tools.py").read_text())
        registration = next(n for n in tree.body if isinstance(n, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == "CHAT_TOOLS" for t in n.targets))
        names = [n.id for n in registration.value.elts if isinstance(n, ast.Name)]
        self.assertNotIn("web_search", names)
        self.assertIn("agent_dispatch", names)
