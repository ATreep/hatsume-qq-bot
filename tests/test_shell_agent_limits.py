"""Chat timeout boundaries and task-local coding-agent exemptions."""
import ast
import asyncio
import contextvars
from dataclasses import dataclass, field
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from langchain_core.tools import tool

SOURCE = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin/graph/tools.py"
TREE = ast.parse(SOURCE.read_text())
NAMES = {"_ShellExecutorBudget", "set_shell_executor_limit", "shell_executor"}


class ShellAgentLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.run = AsyncMock(return_value="executed")
        self.ready = AsyncMock()
        self.ns = {"tool": tool, "contextvars": contextvars, "threading": threading,
                   "dataclass": dataclass, "field": field, "run_cmd": self.run,
                   "ensure_container_running": self.ready,
                   "get_current_group_runtime": lambda: SimpleNamespace(group_id=123)}
        nodes = [n for n in TREE.body if
                 isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in NAMES
                 or isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
                 and n.target.id == "_shell_executor_budget"]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), self.ns)
        self.shell = self.ns["shell_executor"]

    async def call(self, timeout):
        return await self.shell.ainvoke({"shell": "printf test", "timeout": timeout})

    async def test_over_limit_rejected_without_consuming_call_budget(self):
        self.ns["set_shell_executor_limit"](3)
        self.assertIn("60 秒", await self.call(61))
        self.run.assert_not_awaited()
        self.ready.assert_not_awaited()
        self.assertEqual(self.ns["_shell_executor_budget"].get().call_count, 0)
        self.assertEqual(await self.call(60), "executed")
        self.assertEqual(self.run.await_args.kwargs, {"timeout": 60, "group_id": 123})

    async def test_unbound_context_defaults_to_chat_cap(self):
        self.assertIn("60 秒", await self.call(61))
        self.run.assert_not_awaited()

    async def test_nonpositive_timeout_is_rejected(self):
        for timeout in [0, -1]:
            self.assertIn("正整数", await self.call(timeout))
        self.run.assert_not_awaited()

    async def test_coding_child_has_no_cap_and_preserves_parent(self):
        self.ns["set_shell_executor_limit"](3)
        async def coding():
            self.ns["set_shell_executor_limit"](None)
            for _ in range(4):
                self.assertEqual(await self.call(100000), "executed")
        await asyncio.create_task(coding())
        self.assertEqual(self.run.await_count, 4)
        self.assertIn("60 秒", await self.call(61))
        self.assertEqual(self.ns["_shell_executor_budget"].get().call_count, 0)

    async def test_three_call_limit_is_shared_with_child_tasks(self):
        self.ns["set_shell_executor_limit"](3)
        results = await asyncio.gather(*(self.call(1) for _ in range(4)))
        self.assertEqual(results.count("executed"), 3)
        self.assertEqual(self.run.await_count, 3)

    def test_description_explains_chat_cap_and_coding_exemption(self):
        self.assertIn("60 秒", self.shell.description)
        self.assertIn("coding_agent 不受", self.shell.description)
