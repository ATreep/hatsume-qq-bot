"""Sandbox computer-use Agent routing and singleton dispatch contracts."""

import ast
import asyncio
import contextlib
from pathlib import Path
import sys
import traceback
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.tools import tool


ROOT = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"


class SandboxComputerUseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agents_tree = ast.parse((ROOT / "graph/agents.py").read_text())
        self.tools_tree = ast.parse((ROOT / "graph/tools.py").read_text())
        self.states = {"sandbox_computer_use": []}
        package = "sandbox_computer_use_test.graph"
        self.package = package
        self.modules = {}
        for name in ("sandbox_computer_use_test", package):
            module = ModuleType(name)
            module.__path__ = []
            self.modules[name] = module

        agents_module = ModuleType(f"{package}.agents")
        get_running_node = next(
            node
            for node in self.agents_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_running_agent_instance"
        )
        helper_namespace = {"_AGENT_STATES": self.states}
        exec(
            compile(
                ast.Module(body=[get_running_node], type_ignores=[]),
                "agents.py",
                "exec",
            ),
            helper_namespace,
        )
        agents_module.get_running_agent_instance = helper_namespace[
            "get_running_agent_instance"
        ]
        agents_module.add_agent_instance = self.add_agent_instance
        agents_module.bind_agent_instance = self.bind_agent_instance
        agents_module.has_running_agent_task = lambda *_args: False
        agents_module.set_agent_state = self.set_agent_state
        agents_module.track_agent_task = lambda *_args: None
        agents_module.untrack_agent_task = lambda *_args: None
        self.modules[f"{package}.agents"] = agents_module

        nodes_module = ModuleType(f"{package}.nodes")
        nodes_module.inject_agent_notification = lambda **_kwargs: None
        self.modules[f"{package}.nodes"] = nodes_module

        self.runtime = SimpleNamespace(group_id=123, agent_tasks=set())

        async def handler(task, _user_id):
            await asyncio.sleep(0.02)
            return task

        self.handler = handler

        @contextlib.contextmanager
        def bind_group_runtime(_runtime):
            yield

        self.namespace = {
            "__package__": package,
            "tool": tool,
            "asyncio": asyncio,
            "traceback": traceback,
            "get_current_group_runtime": lambda: self.runtime,
            "get_agent_handler": lambda _name: self.handler,
            "get_agent_list": lambda: [],
            "_AGENT_LIST_STR": "",
            "_resolve_notified_user_name": self.resolve_user_name,
            "_agent_notification_callback": lambda **_kwargs: None,
            "bind_group_runtime": bind_group_runtime,
        }

        dispatch_node = next(
            node
            for node in self.tools_tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "agent_dispatch"
        )
        exec(
            compile(
                ast.Module(body=[dispatch_node], type_ignores=[]),
                "tools.py",
                "exec",
            ),
            self.namespace,
        )

    async def resolve_user_name(self, _user_id, _group_id):
        return None

    def add_agent_instance(self, name, *, group_id, **values):
        instance_id = f"{name}_{len(self.states[name]) + 1}"
        self.states[name].append(
            {
                "name": name,
                "group_id": group_id,
                "instance_id": instance_id,
                **values,
            }
        )
        return instance_id

    def set_agent_state(self, _name, *, instance_id, **values):
        instance = next(
            item
            for group in self.states.values()
            for item in group
            if item["instance_id"] == instance_id
        )
        instance.update(values)

    @contextlib.contextmanager
    def bind_agent_instance(self, _instance_id):
        yield

    async def test_parallel_dispatch_rejects_second_task_with_active_prompt(self):
        with patch.dict(sys.modules, self.modules):
            dispatch = self.namespace["agent_dispatch"]
            results = await asyncio.gather(
                dispatch.ainvoke(
                    {
                        "agent_name": "sandbox_computer_use",
                        "task": "active website task",
                        "context": "context one",
                    }
                ),
                dispatch.ainvoke(
                    {
                        "agent_name": "sandbox_computer_use",
                        "task": "parallel website task",
                        "context": "context two",
                    }
                ),
            )
            await asyncio.sleep(0.04)

        self.assertIn("开始执行任务", results[0])
        self.assertEqual(
            results[1],
            "sandbox_computer_use agent 只能单实例运行，禁止并行运行多个 "
            "sandbox_computer_use agents。\n"
            "当前 sandbox_computer_use 任务提示词：active website task",
        )
        self.assertEqual(len(self.states["sandbox_computer_use"]), 1)

    async def test_parallel_dispatch_from_other_group_hides_active_task(self):
        self.states["sandbox_computer_use"].append(
            {
                "name": "sandbox_computer_use",
                "group_id": 456,
                "instance_id": "sandbox_computer_use_other_group",
                "status": "running",
                "task": "private task from another group",
            }
        )
        with patch.dict(sys.modules, self.modules):
            result = await self.namespace["agent_dispatch"].ainvoke(
                {
                    "agent_name": "sandbox_computer_use",
                    "task": "new task",
                    "context": "context",
                }
            )

        self.assertEqual(result, "该agent正在被其他人占用，请稍后再尝试分发。")
        self.assertNotIn("private task from another group", result)

    def test_chat_tools_exclude_gui_and_sandbox_agent_has_requested_tools(self):
        chat_tools = next(
            node
            for node in self.tools_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "CHAT_TOOLS"
                for target in node.targets
            )
        )
        chat_names = {item.id for item in chat_tools.value.elts}
        gui_names = {
            "gui_inspect",
            "gui_click",
            "gui_click_coordinates",
            "gui_drag",
            "gui_focus",
            "gui_set_text",
            "gui_key",
            "gui_type",
            "gui_launch",
            "gui_screenshot",
            "chrome_open",
            "chrome_inspect",
            "chrome_click",
            "chrome_focus",
            "chrome_set_text",
        }
        self.assertFalse(chat_names & gui_names)

        computer_tools = next(
            node
            for node in self.agents_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_get_sandbox_computer_use_tools"
        )
        return_node = next(
            node
            for node in ast.walk(computer_tools)
            if isinstance(node, ast.Return)
        )
        tool_names = {item.id for item in return_node.value.elts}
        self.assertEqual(
            tool_names,
            {
                "web_search",
                "gui_inspect",
                "gui_click",
                "gui_click_coordinates",
                "gui_drag",
                "gui_focus",
                "gui_set_text",
                "gui_key",
                "gui_type",
                "gui_launch",
                "gui_screenshot",
                "chrome_open",
                "chrome_inspect",
                "chrome_click",
                "chrome_focus",
                "chrome_set_text",
                "view_image",
                "shell_executor",
                "load_skill",
            },
        )

        handler = next(
            node
            for node in self.agents_tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_run_sandbox_computer_use"
        )
        called_functions = {
            node.func.id
            for node in ast.walk(handler)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("get_code_model", called_functions)
        self.assertIn("get_lite_model", called_functions)

        source = (ROOT / "graph/agents.py").read_text()
        self.assertIn('if operation == "chrome_focus":', source)
        self.assertIn('context_mode="chrome_set_text"', source)
        self.assertIn('context_mode = {"open_application": "open", "open_webpage": "open"', source)


if __name__ == "__main__":
    unittest.main()
