"""Agent history, actual LangChain tool execution and cancellation contracts."""
import ast
import asyncio
import contextlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from typing import Annotated, Any

from langchain_core.tools import tool as langchain_tool
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from pydantic import Field

ROOT = Path(__file__).resolve().parents[1] / 'hatsume/plugins/hatsume-plugin'


class AgentHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.package = 'history_contract.graph'
        self.modules = {}
        for name in ('history_contract', self.package):
            module = ModuleType(name)
            module.__path__ = []
            self.modules[name] = module
        spec = importlib.util.spec_from_file_location(f'{self.package}.agents', ROOT / 'graph/agents.py')
        self.agents = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.agents)
        self.agents._AGENT_STATES.clear()
        self.agents._AGENT_HISTORY.clear()
        self.agents._agent_tasks.clear()
        self.modules[spec.name] = self.agents
        self.runtime = SimpleNamespace(group_id=123, agent_tasks=set(), conversation=SimpleNamespace(checked_agent_ids=set()))
        nodes_module = ModuleType(f'{self.package}.nodes')
        self.notifications = []
        nodes_module.inject_agent_notification = lambda **kwargs: self.notifications.append(kwargs)
        self.modules[nodes_module.__name__] = nodes_module
        @contextlib.contextmanager
        def bind_runtime(_runtime):
            yield
        async def resolve(*_args):
            return None
        self.ns = {'__package__': self.package, 'Any': Any, 'Annotated': Annotated,
                   'Field': Field, 'asyncio': asyncio, 'json': json,
                   '_langchain_tool': langchain_tool,
                   'get_current_group_runtime': lambda: self.runtime,
                   'bind_group_runtime': bind_runtime,
                   '_resolve_notified_user_name': resolve,
                   '_agent_notification_callback': lambda *_args: None,
                   '_AGENT_LIST_STR': '', 'get_agent_handler': lambda _: self.handler,
                   'get_agent_list': self.agents.get_agent_list}
        tree = ast.parse((ROOT / 'graph/tools.py').read_text())
        names = {'_format_tool_input', '_wrap_tool_ainvoke', 'tool', 'agent_dispatch',
                 'agent_work_history', 'agent_history_list', 'agent_stop'}
        selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        exec(compile(ast.Module(body=selected, type_ignores=[]), 'tools.py', 'exec'), self.ns)
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        async def handler(*_args):
            return 'complete'
        self.handler = handler

    def add(self, name='coding_agent', group_id=123, **kwargs):
        return self.agents.add_agent_instance(name, group_id=group_id, task='original prompt', user_id=456, **kwargs)

    async def invoke(self, name, **kwargs):
        return await self.ns[name].ainvoke(kwargs)

    def test_hash_metadata_retention_and_tail(self):
        with patch.object(self.agents.time, 'time', return_value=1000):
            ids = [self.add() for _ in range(7)]
        self.assertEqual(len(set(ids)), 7)
        self.assertEqual(list(self.agents._AGENT_HISTORY), ids[-5:])
        agent_id = ids[-1]
        self.assertEqual(len(agent_id), 16)
        header = self.agents._AGENT_HISTORY[agent_id][:2]
        self.assertEqual(header[0], 1000)
        self.assertEqual(json.loads(header[1])['task'], 'original prompt')
        for n in range(8):
            self.agents.record_agent_event(agent_id, {'tool': 'test', 'result': n})
        self.agents.finish_agent_history(agent_id, 'output')
        self.assertEqual(len(self.agents.get_agent_history(agent_id, -1)), 9)
        self.assertEqual(len(self.agents.get_agent_history(agent_id, 5)), 5)
        self.assertEqual(len(self.agents.get_agent_history(agent_id, 99)), 9)
        self.assertEqual(self.agents.get_agent_history(agent_id, 1), [{'output': 'output'}])
        for length in (0, -2, True):
            with self.assertRaises(ValueError):
                self.agents.get_agent_history(agent_id, length)
        snapshot = self.agents.get_agent_history(agent_id)
        snapshot[-1]['output'] = 'changed'
        self.assertEqual(self.agents.get_agent_history(agent_id, 1)[0]['output'], 'output')

    async def test_sync_and_async_tools_record_through_real_tool_node(self):
        agent_id = self.add()
        @self.ns['tool']
        def sync_tool(value: str) -> str:
            """Return sync value."""
            return f'sync:{value}'
        @self.ns['tool']
        async def async_tool(value: str) -> str:
            """Return async value."""
            return f'async:{value}'
        calls = [{'name': name, 'args': {'value': 'hello'}, 'id': str(i), 'type': 'tool_call'}
                 for i, name in enumerate(('sync_tool', 'async_tool'))]
        with self.agents.bind_agent_instance(agent_id):
            graph = StateGraph(MessagesState)
            graph.add_node('tools', ToolNode([sync_tool, async_tool]))
            graph.add_edge(START, 'tools')
            graph.add_edge('tools', END)
            result = await graph.compile().ainvoke({'messages': [AIMessage('', tool_calls=calls)]})
        self.assertEqual(len(result['messages']), 3)
        history = self.agents.get_agent_history(agent_id, -1)
        self.assertEqual(len(history), 2)
        by_name = {item['tool']: item for item in history}
        self.assertEqual(by_name['sync_tool']['result'], 'sync:hello')
        self.assertEqual(by_name['async_tool']['input']['kwargs']['value'], 'hello')

    async def test_stop_guard_cleanup_and_no_final_output(self):
        entered, released = asyncio.Event(), asyncio.Event()
        async def handler(*_args):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                released.set()
        self.handler = handler
        reply = await self.invoke('agent_dispatch', agent_name='coding_agent', task='task', context='context')
        await entered.wait()
        agent_id = self.agents.get_running_instances(123)[0]['instance_id']
        self.assertIn(agent_id, reply)
        self.assertIn('必须先', await self.invoke('agent_stop', agent_id=agent_id))
        self.assertEqual(json.loads(await self.invoke('agent_history_list')), [])
        self.assertEqual(json.loads(await self.invoke('agent_work_history', agent_id=agent_id, length=5)), [])
        self.assertIn('已停止', await self.invoke('agent_stop', agent_id=agent_id))
        self.assertTrue(released.is_set())
        self.assertEqual(self.agents.get_running_instances(123), [])
        self.assertEqual(self.runtime.agent_tasks, set())
        self.assertNotIn(agent_id, self.agents._agent_tasks)
        self.assertEqual(self.agents.get_agent_history(agent_id, -1), [])
        self.assertEqual(self.notifications, [])
        self.assertIn('没有运行', await self.invoke('agent_stop', agent_id=agent_id))
        listing = json.loads(await self.invoke('agent_history_list'))
        self.assertEqual(listing[0]['agent_id'], agent_id)

    async def test_completion_appends_output_and_notification_id(self):
        await self.invoke('agent_dispatch', agent_name='coding_agent', task='task', context='context')
        await asyncio.sleep(0)
        await asyncio.gather(*list(self.runtime.agent_tasks))
        state = self.agents.get_agent_state('coding_agent', 123)
        agent_id = state['instance_id']
        self.assertEqual(self.agents.get_agent_history(agent_id, -1), [{'output': 'complete'}])
        self.assertIn(agent_id, self.notifications[0]['result'])
        self.assertEqual(state['status'], 'done')

    async def test_foreign_agent_and_invalid_length_do_not_authorize_stop(self):
        agent_id = self.add(group_id=999)
        self.assertIn('不属于', await self.invoke('agent_work_history', agent_id=agent_id))
        self.assertEqual(json.loads(await self.invoke('agent_history_list')), [])
        agent_id = self.add()
        self.assertIn('必须为', await self.invoke('agent_work_history', agent_id=agent_id, length=0))
        self.assertNotIn(agent_id, self.runtime.conversation.checked_agent_ids)

    async def test_cancellation_before_dispatch_task_starts_clears_state(self):
        agent_id = self.add(status='running')
        async def loop():
            await asyncio.Event().wait()
        task = asyncio.create_task(loop())
        self.agents.track_agent_task(agent_id, 123, task)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.agents.get_running_instances(123), [])
        self.assertEqual(self.agents.get_agent_history(agent_id, -1), [])

    async def test_evicted_history_cannot_authorize_stop(self):
        agent_id = self.add()
        for _ in range(5):
            self.add()
        self.assertIn('已被淘汰', await self.invoke('agent_work_history', agent_id=agent_id))
        self.assertNotIn(agent_id, self.runtime.conversation.checked_agent_ids)

    async def test_previous_conversation_read_cannot_authorize_stop(self):
        agent_id = self.add(status='running')
        task = asyncio.create_task(asyncio.Event().wait())
        self.agents.track_agent_task(agent_id, 123, task)
        self.runtime.agent_tasks.add(task)
        await self.invoke('agent_work_history', agent_id=agent_id)
        self.runtime.conversation.checked_agent_ids.clear()
        self.assertIn('必须先', await self.invoke('agent_stop', agent_id=agent_id))
        await self.invoke('agent_work_history', agent_id=agent_id)
        await self.invoke('agent_stop', agent_id=agent_id)

    async def test_failed_tool_is_recorded_before_interruption(self):
        agent_id = self.add()
        @self.ns['tool']
        async def failing_tool(value: str) -> str:
            """Raise an error."""
            raise RuntimeError(value)
        with self.agents.bind_agent_instance(agent_id):
            with self.assertRaises(RuntimeError):
                await failing_tool.ainvoke({'value': 'failure'})
        records = self.agents.get_agent_history(agent_id, -1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['error'], 'RuntimeError: failure')
        self.assertNotIn('output', records[0])



if __name__ == '__main__':
    unittest.main()
