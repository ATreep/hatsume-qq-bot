"""Focused tests for Jev routing without a live desktop or remote model."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "hatsume/plugins/hatsume-plugin/graph/sandbox_computer_use.py"
)
SPEC = importlib.util.spec_from_file_location("sandbox_coordinator", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["sandbox_coordinator"] = MODULE
SPEC.loader.exec_module(MODULE)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def test_wait_option_is_suppressed_after_three_consecutive_waits(self):
        coordinator = MODULE.SandboxComputerUseCoordinator("wait", MODULE.CoordinatorDeps(
            *(None for _ in range(6))
        ))

        coordinator._record_wait_choice()
        coordinator._record_wait_choice()
        self.assertFalse(coordinator.suppress_wait_next_iteration)
        coordinator._record_wait_choice()
        self.assertTrue(coordinator.suppress_wait_next_iteration)

        coordinator._record_non_wait_choice()
        self.assertEqual(coordinator.consecutive_wait_iterations, 0)

    def test_chrome_element_criteria_includes_dom_attribute_values(self):
        criteria = MODULE._element_criteria(
            [{
                "id": "input-1",
                "role": "textbox",
                "name": "Search",
                "value": "",
                "attributes": {
                    "id": "search",
                    "placeholder": "Find docs",
                },
            }],
            include_attributes=True,
            include_wait=False,
        )

        self.assertIn("value=''", criteria["input-1"])
        self.assertIn(
            "attributes={'id': 'search', 'placeholder': 'Find docs'}",
            criteria["input-1"],
        )
        self.assertIn("screenshot_coordinate_drag", criteria)

    def test_window_state_keeps_application_root_id_for_drag(self):
        windows = MODULE._windows_from_inspection({
            "elements": [{
                "id": "a11y-app-1",
                "application": "Google Chrome",
                "role": "application",
                "name": "Google Chrome",
            }],
        })
        self.assertEqual(windows[0]["app_id"], "a11y-app-1")

    def test_context_keeps_three_step3_iterations(self):
        coordinator = MODULE.SandboxComputerUseCoordinator(
            "task", MODULE.CoordinatorDeps(*(None for _ in range(6)))
        )
        for iteration in range(1, 4):
            coordinator.iteration = iteration
            coordinator._record_step3_decision(
                "chrome_element_action",
                {"choice": f"element-{iteration}", "confidence": 0.9},
            )
            coordinator._record_step3_decision(
                "chrome_operation",
                {"choice": "chrome_set_text", "confidence": 0.9},
            )
            coordinator._record_step3_history(f"typed-{iteration}")

        state = coordinator._state(windows=[])
        self.assertEqual(
            [item["iteration"] for item in state["step3_history"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [item["llm_result"] for item in state["step3_history"]],
            ["typed-1", "typed-2", "typed-3"],
        )
        self.assertEqual(
            state["step3_history"][0]["decision"]["choice"],
            "element-1",
        )

    async def test_step3_decision_is_available_to_next_native_element_choice(self):
        states = []
        choices = iter([
            {"answers": {"window_action": {"choice": "window:Terminal", "confidence": 0.9}}},
            {"answers": {"element_action": {"choice": "button-1", "confidence": 0.9}}},
            {"answers": {"native_operation": {"choice": "click", "confidence": 0.9}}},
            {"answers": {"window_action": {"choice": "window:Terminal", "confidence": 0.9}}},
            {"answers": {"element_action": {"choice": "finish_report", "confidence": 0.9}}},
        ])

        async def inspect(application=""):
            if application:
                return {"elements": [{"id": "button-1", "role": "push button", "name": "Run"}]}
            return {"elements": [{"application": "Terminal"}]}

        async def jev(state, question):
            states.append((state, next(iter(question))))
            return next(choices)

        async def action(*_args):
            return "clicked"

        async def branch(kind, _state):
            return "report" if kind == "finish_report" else kind

        async def sleep(_seconds):
            return None

        deps = MODULE.CoordinatorDeps(jev, inspect, inspect, action, action, branch, sleep)
        self.assertEqual(await MODULE.SandboxComputerUseCoordinator("run", deps).run(), "report")

        second_element_state = [state for state, question in states if question == "element_action"][1]
        self.assertEqual(
            second_element_state["step3_decision"],
            {
                "question_id": "element_action",
                "choice": "button-1",
                "confidence": 0.9,
                "operation": {
                    "question_id": "native_operation",
                    "choice": "click",
                    "confidence": 0.9,
                },
            },
        )

    async def test_chrome_set_text_result_is_available_to_next_chrome_element_choice(self):
        states = []
        choices = iter([
            {"answers": {"window_action": {"choice": "window:Google Chrome", "confidence": 0.9}}},
            {"answers": {"chrome_element_action": {"choice": "input-1", "confidence": 0.9}}},
            {"answers": {"chrome_operation": {"choice": "chrome_set_text", "confidence": 0.9}}},
            {"answers": {"window_action": {"choice": "window:Google Chrome", "confidence": 0.9}}},
            {"answers": {"chrome_element_action": {"choice": "button-1", "confidence": 0.9}}},
            {"answers": {"chrome_operation": {"choice": "chrome_click", "confidence": 0.9}}},
            {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.9}}},
        ])

        async def inspect_gui():
            return {"elements": [{"application": "Google Chrome"}]}

        async def inspect_chrome(_target_id=""):
            return {
                "url": "https://example.test",
                "title": "Example",
                "elements": [
                    {"id": "input-1", "role": "textbox", "name": "Search", "value": ""},
                    {"id": "button-1", "role": "button", "name": "Search"},
                ],
            }

        async def jev(state, question):
            states.append((state, next(iter(question))))
            return next(choices)

        async def chrome_action(operation, _element, _task):
            return "LLM typed result" if operation == "chrome_set_text" else "clicked"

        async def branch(kind, _state):
            return "report" if kind == "finish_report" else kind

        async def sleep(_seconds):
            return None

        deps = MODULE.CoordinatorDeps(
            jev, inspect_gui, inspect_chrome, chrome_action, chrome_action, branch, sleep
        )
        self.assertEqual(await MODULE.SandboxComputerUseCoordinator("search", deps).run(), "report")

        second_element_state = [
            state for state, question in states if question == "chrome_element_action"
        ][1]
        self.assertEqual(
            second_element_state["step3_decision"],
            {
                "question_id": "chrome_element_action",
                "choice": "input-1",
                "confidence": 0.9,
                "operation": {
                    "question_id": "chrome_operation",
                    "choice": "chrome_set_text",
                    "confidence": 0.9,
                },
            },
        )
        self.assertEqual(second_element_state["step3_llm_result"], "LLM typed result")

    async def test_native_click_then_report_restarts_top_level_inspection(self):
        gui_calls = []
        actions = []
        waits = []
        choices = iter([
            {"answers": {"window_action": {"choice": "window:Terminal", "confidence": 0.9}}},
            {"answers": {"element_action": {"choice": "button-1", "confidence": 0.9}}},
            {"answers": {"native_operation": {"choice": "click", "confidence": 0.9}}},
            {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.9}}},
        ])

        async def gui_inspect(application=""):
            gui_calls.append(application)
            if application:
                return {"elements": [{"id": "button-1", "role": "push button", "name": "Run"}]}
            return {"elements": [{"application": "Terminal", "role": "application", "name": "Terminal"}]}

        async def jev(_state, _questions):
            return next(choices)

        async def native_action(operation, element, task):
            actions.append((operation, element["id"], task))
            return "clicked"

        async def branch(kind, _state):
            return "final report" if kind == "finish_report" else kind

        async def sleep(seconds):
            waits.append(seconds)

        deps = MODULE.CoordinatorDeps(
            jev=jev,
            gui_inspect=gui_inspect,
            chrome_inspect=gui_inspect,
            native_action=native_action,
            chrome_action=native_action,
            branch=branch,
            sleep=sleep,
        )
        result = await MODULE.SandboxComputerUseCoordinator("run task", deps).run()

        self.assertEqual(result, "final report")
        self.assertEqual(gui_calls, ["", "Terminal", ""])
        self.assertEqual(actions, [("click", "button-1", "run task")])
        self.assertEqual(waits, [5])

    async def test_open_webpage_branch_restarts_loop(self):
        choices = iter([
            {"answers": {"window_action": {"choice": "open_webpage", "confidence": 0.9}}},
            {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.9}}},
        ])
        inspected = 0
        branches = []
        waits = []

        async def gui_inspect():
            nonlocal inspected
            inspected += 1
            return {"elements": []}

        async def jev(_state, _questions):
            return next(choices)

        async def branch(kind, _state):
            branches.append(kind)
            return "opened" if kind == "open_webpage" else "report"

        async def unused(*_args):
            raise AssertionError("unused operation")

        async def sleep(seconds):
            waits.append(seconds)

        deps = MODULE.CoordinatorDeps(jev, gui_inspect, unused, unused, unused, branch, sleep)
        self.assertEqual(
            await MODULE.SandboxComputerUseCoordinator("open docs", deps).run(),
            "report",
        )
        self.assertEqual(inspected, 2)
        self.assertEqual(branches, ["open_webpage", "finish_report"])
        self.assertEqual(waits, [5])

    async def test_wait_before_operation_skips_action_and_waits(self):
        choices = iter([
            {"answers": {"window_action": {"choice": "window:Terminal", "confidence": 0.9}}},
            {"answers": {"element_action": {"choice": "wait_before_operation", "confidence": 0.9}}},
            {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.9}}},
        ])
        waits = []
        actions = []

        async def inspect(application=""):
            if application:
                return {"elements": [{"id": "button-1", "role": "push button", "name": "Run"}]}
            return {"elements": [{"application": "Terminal"}]}

        async def jev(_state, _questions):
            return next(choices)

        async def action(*args):
            actions.append(args)

        async def branch(kind, _state):
            return "report" if kind == "finish_report" else kind

        async def sleep(seconds):
            waits.append(seconds)

        deps = MODULE.CoordinatorDeps(jev, inspect, inspect, action, action, branch, sleep)
        self.assertEqual(await MODULE.SandboxComputerUseCoordinator("wait", deps).run(), "report")
        self.assertEqual(actions, [])
        self.assertEqual(waits, [5])

    async def test_iteration_limit_forces_finish_report(self):
        choices = iter([
            {"answers": {"window_action": {"choice": "window:Terminal", "confidence": 0.9}}},
            {"answers": {"element_action": {"choice": "wait_before_operation", "confidence": 0.9}}},
        ])
        branches = []
        forced_states = []

        async def inspect(application=""):
            if application:
                return {"elements": [{"id": "button-1", "role": "push button", "name": "Run"}]}
            return {"elements": [{"application": "Terminal"}]}

        async def jev(_state, _question):
            return next(choices)

        async def branch(kind, state):
            branches.append(kind)
            if kind == "finish_report":
                forced_states.append(state)
                return "forced report"
            return kind

        async def sleep(_seconds):
            return None

        deps = MODULE.CoordinatorDeps(jev, inspect, inspect, inspect, inspect, branch, sleep)
        result = await MODULE.SandboxComputerUseCoordinator(
            "limited task", deps, max_iterations=1
        ).run()

        self.assertEqual(result, "forced report")
        self.assertEqual(branches, ["finish_report"])
        self.assertTrue(forced_states[0]["iteration_limit_reached"])

    async def test_low_confidence_valid_choice_is_still_final(self):
        choices = iter([
            {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.1}}},
        ])
        branches = []

        async def jev(_state, _questions):
            return next(choices)

        async def branch(kind, _state):
            branches.append(kind)
            return "final report"

        async def inspect():
            return {"elements": [{"application": "Terminal"}]}

        async def action(*_args):
            raise AssertionError("unexpected action")

        deps = MODULE.CoordinatorDeps(jev, inspect, inspect, action, action, branch)
        result = await MODULE.SandboxComputerUseCoordinator(
            "uncertain task", deps, max_iterations=1
        ).run()
        self.assertEqual(result, "final report")
        self.assertEqual(branches, ["finish_report"])

    async def test_policy_prompt_is_included_in_jev_question(self):
        questions = []

        async def inspect():
            return {"elements": []}

        async def jev(_state, question):
            questions.append(question)
            return {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.9}}}

        async def branch(kind, _state):
            return "report"

        deps = MODULE.CoordinatorDeps(
            jev, inspect, inspect, branch, branch, branch,
            policy_prompt="shared sandbox policy",
        )
        await MODULE.SandboxComputerUseCoordinator("task", deps).run()
        self.assertIn("shared sandbox policy", questions[0]["window_action"]["instructions"])

    async def test_step2_includes_current_chrome_tab_url(self):
        states = []

        async def inspect_gui():
            return {"elements": [{"application": "Google Chrome"}]}

        async def inspect_chrome(_target_id=""):
            return {"url": "https://example.test/current", "title": "Example"}

        async def jev(state, _question):
            states.append(state)
            return {"answers": {"window_action": {"choice": "finish_report", "confidence": 0.2}}}

        async def branch(kind, _state):
            return "report"

        deps = MODULE.CoordinatorDeps(
            jev, inspect_gui, inspect_chrome, branch, branch, branch
        )
        self.assertEqual(await MODULE.SandboxComputerUseCoordinator("task", deps).run(), "report")
        self.assertEqual(states[0]["windows"][0]["current_tab_url"], "https://example.test/current")


if __name__ == "__main__":
    unittest.main()
