"""Actual LangChain GUI schemas and shell argument boundaries without bot boot."""
import ast
import json
from pathlib import Path
import shlex
from types import SimpleNamespace
from typing import Literal
import unittest
from unittest.mock import AsyncMock

from langchain_core.tools import tool

SOURCE = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin/graph/tools.py"
TREE = ast.parse(SOURCE.read_text())
NAMES = {"_run_gui_automation", "gui_inspect", "gui_click", "gui_focus", "gui_set_text",
         "gui_click_coordinates",
         "gui_drag",
         "gui_key", "gui_type", "gui_launch", "gui_screenshot", "chrome_open",
         "chrome_inspect", "chrome_click", "chrome_focus", "chrome_set_text"}


class GuiToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.run = AsyncMock(return_value='{"ok":true}')
        self.ready = AsyncMock()
        self.ns = {"tool": tool, "shlex": shlex, "Literal": Literal, "json": json,
                   "_GUI_AUTOMATION_SCRIPT": "/work/hatsume/gui_automation.py",
                   "get_current_group_runtime": lambda: SimpleNamespace(group_id=123),
                   "run_cmd": self.run, "ensure_container_running": self.ready}
        exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in NAMES], type_ignores=[]), str(SOURCE), "exec"), self.ns)

    async def test_text_is_one_literal_argument_and_group_is_bound(self):
        text = "中文 '; touch /tmp/bad; $(id) `id`\nnew line"
        await self.ns["chrome_set_text"].ainvoke({"element_id": "cdp-abc-1", "text": text})
        command = shlex.split(self.run.await_args.args[0])
        self.assertEqual(command[0], "HATSUME_GUI_GROUP_ID=123")
        self.assertEqual(command[-2:], ["cdp-abc-1", text])
        self.assertEqual(self.run.await_args.kwargs["group_id"], 123)

    async def test_invalid_browser_scheme_never_executes(self):
        result = await self.ns["chrome_open"].ainvoke({"url": "file:///etc/passwd"})
        self.assertIn("错误", result)
        self.run.assert_not_awaited()

    async def test_invalid_tree_limit_never_executes(self):
        self.assertIn("错误", await self.ns["gui_inspect"].ainvoke({"max_nodes": 501}))
        self.run.assert_not_awaited()

    async def test_coordinate_click_supports_right_double_click(self):
        await self.ns["gui_click_coordinates"].ainvoke({"x": 20, "y": 30, "button": "right", "clicks": 2})
        self.assertEqual(shlex.split(self.run.await_args.args[0])[-5:],
                         ["click-coordinates", "20", "30", "right", "2"])

    async def test_invalid_coordinate_input_never_executes(self):
        for arguments in [{"x": -1, "y": 30}, {"x": 20, "y": 30, "clicks": 3}]:
            self.assertIn("错误", await self.ns["gui_click_coordinates"].ainvoke(arguments))
        self.run.assert_not_awaited()

    async def test_drag_passes_app_and_coordinates(self):
        await self.ns["gui_drag"].ainvoke({
            "app_id": "a11y-app-1",
            "start_x": 10,
            "start_y": 20,
            "end_x": 100,
            "end_y": 120,
        })
        self.assertEqual(
            shlex.split(self.run.await_args.args[0])[-7:],
            ["drag", "a11y-app-1", "10", "20", "100", "120", "800.0"],
        )

    async def test_drag_rejects_invalid_arguments(self):
        result = await self.ns["gui_drag"].ainvoke({
            "app_id": "",
            "start_x": 0,
            "start_y": 0,
            "end_x": 10,
            "end_y": 10,
        })
        self.assertIn("错误", result)
        self.run.assert_not_awaited()

    def test_gui_tools_are_not_exposed_to_chat_agent(self):
        registration = next(n for n in TREE.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CHAT_TOOLS" for t in n.targets))
        registered = {e.id for e in registration.value.elts if isinstance(e, ast.Name)}
        self.assertFalse((NAMES - {"_run_gui_automation"}) & registered)
        for name in ["gui_click", "chrome_click"]:
            schema = self.ns[name].args_schema.model_json_schema()
            self.assertEqual(set(schema["properties"]), {"element_id"})
