"""Jev-routed coordinator for sandbox desktop and Chrome operations.

The coordinator owns routing and loop state. Low-level GUI calls and bounded
LLM branches are injected so routing stays testable without a live container.
"""

from __future__ import annotations

import json
import asyncio
from copy import deepcopy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


AsyncCall = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class CoordinatorDeps:
    jev: AsyncCall
    gui_inspect: AsyncCall
    chrome_inspect: AsyncCall
    native_action: AsyncCall
    chrome_action: AsyncCall
    branch: AsyncCall
    sleep: AsyncCall | None = None
    policy_prompt: str = ""


@dataclass(slots=True)
class SandboxComputerUseCoordinator:
    task: str
    deps: CoordinatorDeps
    max_iterations: int = 30
    iteration: int = 0
    recent_action: str | None = None
    history: list[str] = field(default_factory=list)
    consecutive_wait_iterations: int = 0
    suppress_wait_next_iteration: bool = False
    wait_option_suppressed: bool = False
    wait_selected_this_iteration: bool = False
    chrome_text_element_key: str | None = None
    chrome_text_element_iteration: int | None = None
    step3_decision: dict[str, Any] | None = None
    step3_llm_result: str | None = None
    step3_history: list[dict[str, Any]] = field(default_factory=list)

    async def run(self) -> str:
        """Run inspect, route, execute until a report or limit is reached."""
        last_state = self._state(windows=[])
        while self.iteration < self.max_iterations:
            if self.iteration and not self.wait_selected_this_iteration:
                self.consecutive_wait_iterations = 0
            self.iteration += 1
            self.wait_option_suppressed = self.suppress_wait_next_iteration
            self.suppress_wait_next_iteration = False
            self.wait_selected_this_iteration = False
            if (
                self.chrome_text_element_iteration is not None
                and self.iteration > self.chrome_text_element_iteration
            ):
                self.chrome_text_element_key = None
                self.chrome_text_element_iteration = None
            try:
                print(
                    f"[sandbox_computer_use] iteration={self.iteration} step=1 "
                    "action=gui_inspect"
                )
                raw = await self.deps.gui_inspect()
                inspection = _decode(raw)
                windows = _windows_from_inspection(inspection)
                await self._attach_current_chrome_urls(windows)
                state = self._state(windows=windows, inspection=None)
                last_state = state
                answer = await self._choose(
                    state,
                    "window_action",
                    _window_criteria(windows),
                )
                action = answer["choice"]
                print(
                    f"[sandbox_computer_use] iteration={self.iteration} step=2 "
                    f"window_action={action!r} confidence={answer['confidence']:.3f}"
                )

                if action == "finish_report":
                    self._record_non_wait_choice()
                    return await self.deps.branch("finish_report", state)
                if action == "open_application":
                    self._record_non_wait_choice()
                    result = await self.deps.branch("open_application", state)
                    self._record(result)
                    await self._step4_wait()
                    continue
                if action == "open_webpage":
                    self._record_non_wait_choice()
                    result = await self.deps.branch("open_webpage", state)
                    self._record(result)
                    await self._step4_wait()
                    continue

                window = next(
                    item for item in windows if item["id"] == action
                )
                if window["kind"] == "chrome":
                    result = await self._handle_chrome(window, inspection)
                else:
                    result = await self._handle_native(window, inspection)
                if result is not None:
                    return result
                await self._step4_wait()
            except Exception as exc:
                print(
                    f"[sandbox_computer_use] iteration={self.iteration} "
                    f"error={exc!r}"
                )
                self._record(f"error: {exc}")
                if self.iteration >= self.max_iterations:
                    break

        limit_message = (
            f"Sandbox computer-use iteration limit reached after {self.iteration} iterations."
        )
        self._record(limit_message)
        forced_state = {
            **last_state,
            "recent_action": self.recent_action,
            "iteration_limit_reached": True,
        }
        print(
            f"[sandbox_computer_use] iteration={self.iteration} "
            "forcing finish_report after iteration limit"
        )
        try:
            return await self.deps.branch("finish_report", forced_state)
        except Exception as exc:
            self._record(f"finish_report error: {exc}")
            return self._limit_report()

    async def _attach_current_chrome_urls(self, windows: list[dict[str, Any]]) -> None:
        """Add the currently selected Chrome tab URL to Step 2 window state."""
        for window in windows:
            if window["kind"] != "chrome":
                continue
            try:
                inspection = _decode(await self.deps.chrome_inspect(""))
                if isinstance(inspection, Mapping):
                    window["current_tab_url"] = str(inspection.get("url") or "")
                    window["current_tab_title"] = str(inspection.get("title") or "")
            except Exception as exc:
                print(
                    f"[sandbox_computer_use] current Chrome tab URL unavailable: {exc!r}"
                )

    async def _handle_native(
        self, window: dict[str, Any], desktop_inspection: Any
    ) -> str | None:
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=3 "
            f"inspect_native application={window['application']!r}"
        )
        inspection = _decode(await self.deps.gui_inspect(window["application"]))
        elements = _elements(inspection)
        state = self._state(
            windows=[window],
            selected_window=window,
            inspection=_inspection_without_elements(inspection),
        )
        answer = await self._choose(
            state,
            "element_action",
            _element_criteria(elements, include_wait=not self.wait_option_suppressed),
        )
        choice = answer["choice"]
        self._record_step3_decision("element_action", answer)
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=3 "
            f"native_element_action={choice!r} confidence={answer['confidence']:.3f}"
        )
        if choice == "finish_report":
            self._record_step3_history()
            self._record_non_wait_choice()
            return await self.deps.branch("finish_report", state)
        if choice in {"screenshot_coordinate_click", "screenshot_coordinate_drag"}:
            self._record_non_wait_choice()
            result = await self.deps.branch(choice, state)
            self._record_step3_history()
            self._record(result)
            return None
        if choice == "wait_before_operation":
            self._record_step3_history()
            self._record_wait_choice()
            return None
        self._record_non_wait_choice()
        element = _find_element(elements, choice)
        operation = await self._choose(
            {**state, "selected_element": element},
            "native_operation",
            {
                "click": "Activate the selected native control.",
                "set_text": "Replace text in the selected native input.",
                "focus_key": "Focus the control and send a key.",
                "focus_type": "Focus the control and type text.",
            },
        )
        self._record_step3_decision("native_operation", operation)
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=3 "
            f"native_operation={operation['choice']!r} confidence={operation['confidence']:.3f}"
        )
        result = await self.deps.native_action(
            operation["choice"], element, self.task
        )
        self._record_step3_history(
            clicked_element=(
                _clicked_element_context(element, window["application"])
                if operation["choice"] == "click"
                else None
            )
        )
        self._record(result)
        return None

    async def _handle_chrome(
        self, window: dict[str, Any], desktop_inspection: Any
    ) -> str | None:
        target_id = str(window.get("target_id", ""))
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=3 "
            f"inspect_chrome target_id={target_id!r}"
        )
        inspection = _decode(await self.deps.chrome_inspect(target_id))
        elements = _elements(inspection)
        state = self._state(
            windows=[window],
            selected_window=window,
            inspection=_inspection_without_elements(inspection),
        )
        excluded_keys: set[str] = set()
        if (
            self.chrome_text_element_key
            and self.chrome_text_element_iteration == self.iteration
        ):
            excluded_keys.add(self.chrome_text_element_key)
            state["follow_up_instruction"] = (
                "A text field was just filled. Choose the control that submits or searches "
                "the entered query; do not choose another text field."
            )
            print(
                f"[sandbox_computer_use] iteration={self.iteration} "
                f"excluding recently edited Chrome element key={self.chrome_text_element_key!r}"
            )
        answer = await self._choose(
            state,
            "chrome_element_action",
            _element_criteria(
                elements,
                include_wait=not self.wait_option_suppressed,
                include_attributes=True,
                exclude_keys=excluded_keys,
            ),
        )
        choice = answer["choice"]
        self._record_step3_decision("chrome_element_action", answer)
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=3 "
            f"chrome_element_action={choice!r} confidence={answer['confidence']:.3f}"
        )
        if choice == "finish_report":
            self._record_step3_history()
            self._record_non_wait_choice()
            return await self.deps.branch("finish_report", state)
        if choice in {"screenshot_coordinate_click", "screenshot_coordinate_drag"}:
            self._record_non_wait_choice()
            result = await self.deps.branch(choice, state)
            self._record_step3_history()
            self._record(result)
            return None
        if choice == "wait_before_operation":
            self._record_step3_history()
            self._record_wait_choice()
            return None
        self._record_non_wait_choice()
        element = _find_element(elements, choice)
        chrome_operations = {
            "chrome_click": "Click the selected Chrome page element.",
            "chrome_focus": "Focus the selected Chrome page element.",
        }
        if _is_editable_chrome_element(element):
            chrome_operations["chrome_set_text"] = (
                "Replace text in the selected Chrome input."
            )
        operation = await self._choose(
            {**state, "selected_element": element},
            "chrome_operation",
            chrome_operations,
        )
        self._record_step3_decision("chrome_operation", operation)
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=3 "
            f"chrome_operation={operation['choice']!r} confidence={operation['confidence']:.3f}"
        )
        if operation["choice"] == "chrome_set_text":
            self.step3_llm_result = None
        result = await self.deps.chrome_action(
            operation["choice"], element, self.task
        )
        if operation["choice"] == "chrome_set_text":
            self.step3_llm_result = _truncate_result(result)
            self.chrome_text_element_key = _element_key(element)
            self.chrome_text_element_iteration = self.iteration + 1
            print(
                f"[sandbox_computer_use] iteration={self.iteration} "
                f"remembering edited Chrome element key={self.chrome_text_element_key!r} "
                f"for next iteration"
            )
        self._record_step3_history(
            self.step3_llm_result if operation["choice"] == "chrome_set_text" else None,
            clicked_element=(
                _clicked_element_context(element, window["application"])
                if operation["choice"] == "chrome_click"
                else None
            ),
        )
        self._record(result)
        return None

    async def _choose(
        self,
        state: dict[str, Any],
        question_id: str,
        criteria: Mapping[str, str],
    ) -> dict[str, Any]:
        print(
            f"[sandbox_computer_use] iteration={self.iteration} decision="
            f"{question_id} candidates={list(criteria)}"
        )
        if question_id in {
            "element_action",
            "native_operation",
            "chrome_element_action",
            "chrome_operation",
        }:
            print(
                f"[sandbox_computer_use] iteration={self.iteration} step=3 "
                f"{question_id} criteria={dict(criteria)!r}"
            )
        response = await self.deps.jev(state, {question_id: {
            "type": "choice",
            "instructions": (
                f"{self.deps.policy_prompt}\n\n"
                f"Choose the best {question_id} for this task."
            ),
            "criteria": dict(criteria),
        }})
        answer = _answer(response, question_id)
        if answer is None:
            raise RuntimeError(f"Jev returned no {question_id} answer")
        choice = str(answer.get("choice", ""))
        confidence = float(answer.get("confidence", 0))
        print(
            f"[sandbox_computer_use] iteration={self.iteration} decision="
            f"{question_id} choice={choice!r} confidence={confidence:.3f}"
        )
        if choice not in criteria:
            fallback = await self.deps.branch(
                "jev_fallback",
                {**state, "question_id": question_id, "answer": answer},
            )
            raise RuntimeError(f"Jev fallback: {fallback}")
        return {"choice": choice, "confidence": confidence}

    def _state(
        self,
        *,
        windows: list[dict[str, Any]],
        selected_window: dict[str, Any] | None = None,
        inspection: Any = None,
    ) -> dict[str, Any]:
        return {
            "task": self.task,
            "windows": windows,
            "selected_window": selected_window,
            "inspection": inspection,
            "recent_action": self.recent_action,
            "step3_decision": self.step3_decision,
            "step3_llm_result": self.step3_llm_result,
            "step3_history": deepcopy(self.step3_history),
        }

    def _record_step3_decision(
        self, question_id: str, answer: Mapping[str, Any]
    ) -> None:
        """Keep the latest Step 3 Jev decisions available to the next choice."""
        choice = str(answer.get("choice", ""))
        confidence = float(answer.get("confidence", 0))
        if question_id in {"element_action", "chrome_element_action"}:
            self.step3_decision = {
                "question_id": question_id,
                "choice": choice,
                "confidence": confidence,
            }
            return
        decision = dict(self.step3_decision or {})
        decision["operation"] = {
            "question_id": question_id,
            "choice": choice,
            "confidence": confidence,
        }
        self.step3_decision = decision

    def _record_step3_history(
        self,
        llm_result: str | None = None,
        *,
        clicked_element: dict[str, Any] | None = None,
    ) -> None:
        """Keep the latest three completed Step 3 iterations for Jev context."""
        if self.step3_decision is None:
            return
        item = {
            "iteration": self.iteration,
            "decision": deepcopy(self.step3_decision),
            "llm_result": llm_result,
        }
        if clicked_element is not None:
            item["clicked_element"] = deepcopy(clicked_element)
        self.step3_history.append(item)
        del self.step3_history[:-3]

    def _record(self, result: Any) -> None:
        self.recent_action = _truncate_result(result)
        self.history.append(self.recent_action)

    def _record_wait_choice(self) -> None:
        self._record("wait_before_operation")
        self.wait_selected_this_iteration = True
        self.consecutive_wait_iterations += 1
        if self.consecutive_wait_iterations >= 3:
            self.suppress_wait_next_iteration = True

    def _record_non_wait_choice(self) -> None:
        self.consecutive_wait_iterations = 0

    async def _step4_wait(self) -> None:
        """Step 4: wait five seconds before restarting at Step 1."""
        print(
            f"[sandbox_computer_use] iteration={self.iteration} step=4 "
            "sleep=5s"
        )
        await (self.deps.sleep or asyncio.sleep)(5)

    def _limit_report(self) -> str:
        details = "; ".join(self.history[-4:]) or "no action completed"
        return f"Sandbox computer-use iteration limit reached after {self.iteration} iterations: {details}"


def _decode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


def _truncate_result(value: Any, limit: int = 500) -> str:
    return str(value)[-limit:]


def _answer(response: Any, question_id: str) -> Mapping[str, Any] | None:
    answers = (
        response.get("answers")
        if isinstance(response, Mapping)
        else getattr(response, "answers", response)
    )
    if not isinstance(answers, Mapping):
        return None
    answer = answers.get(question_id, answers)
    return answer if isinstance(answer, Mapping) else None


def _elements(inspection: Any) -> list[dict[str, Any]]:
    if not isinstance(inspection, Mapping):
        return []
    return [item for item in inspection.get("elements", []) if isinstance(item, dict)]


def _inspection_without_elements(inspection: Any) -> Any:
    """Keep inspection metadata while sending element choices only via criteria."""
    if not isinstance(inspection, Mapping):
        return inspection
    return {key: value for key, value in inspection.items() if key != "elements"}


def _windows_from_inspection(inspection: Any) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in _elements(inspection):
        application = str(element.get("application") or element.get("name") or "").strip()
        if not application or application in seen:
            continue
        seen.add(application)
        lower = application.casefold()
        kind = "chrome" if any(name in lower for name in ("chrome", "chromium")) else "native"
        windows.append({
            "id": f"window:{application}",
            "application": application,
            "app_id": element.get("id") if element.get("role") == "application" else None,
            "kind": kind,
        })
    return windows


def _window_criteria(windows: list[dict[str, Any]]) -> dict[str, str]:
    criteria = {
        item["id"]: (
            f"Operate the visible {item['application']} window."
            + (
                f" Current Chrome tab URL: {item['current_tab_url']}"
                if item.get("current_tab_url")
                else ""
            )
        )
        for item in windows
    }
    criteria.update({
        "open_application": "Open a new desktop application using the bounded LLM branch.",
        "open_webpage": "Open a new webpage in Chrome using the bounded LLM branch.",
        "finish_report": "Stop and inspect the current screenshot to write a final report.",
    })
    return criteria


def _element_criteria(
    elements: list[dict[str, Any]],
    *,
    include_wait: bool = True,
    include_attributes: bool = False,
    exclude_keys: set[str] | None = None,
) -> dict[str, str]:
    criteria: dict[str, str] = {}
    excluded = exclude_keys or set()
    for item in elements:
        if not item.get("id"):
            continue
        element_id = str(item["id"])
        if _element_key(item) in excluded:
            continue
        node_name = item.get("nodeName", item.get("role", ""))
        node_value = item.get("nodeValue", item.get("name", ""))
        role = item.get("role", "")
        description = f"{node_name or ''}{node_value or ''} role={role or ''}".strip()
        if include_attributes:
            if item.get("value") is not None:
                description += f" value={item['value']!r}"
            attributes = item.get("attributes")
            if isinstance(attributes, Mapping):
                description += f" attributes={dict(attributes)!r}"
            else:
                description += " attributes={}"
        criteria[element_id] = description
    criteria.update({
        "screenshot_coordinate_click": "Use a screenshot and original-pixel coordinates for the target.",
        "screenshot_coordinate_drag": "Use a screenshot and original-pixel start/end coordinates to drag the target.",
        "finish_report": "Stop and inspect the current screenshot to write a final report.",
    })
    if include_wait:
        criteria["wait_before_operation"] = (
            "If the page is loading. Wait 5 seconds for page loading, and then redo your decision."
        )
    return criteria


def _element_key(element: Mapping[str, Any]) -> str:
    """Return a stable identity across Chrome accessibility snapshots."""
    backend_node_id = element.get("backendNodeId")
    if backend_node_id is not None:
        return f"backend:{backend_node_id}"
    return "semantic:" + "|".join(
        str(element.get(field) or "")
        for field in ("role", "name", "value")
    )


def _clicked_element_context(
    element: Mapping[str, Any], application: str
) -> dict[str, Any]:
    """Keep identifying details for an element that was actually clicked."""
    value = element.get("value")
    if value is None:
        value = element.get("nodeValue")
    return {
        "role": element.get("role"),
        "value": value,
        "description": element.get("description"),
        "name": element.get("name"),
        "application": element.get("application") or application,
    }


def _is_editable_chrome_element(element: Mapping[str, Any]) -> bool:
    role = str(element.get("role") or "").casefold()
    if role in {"textbox", "searchbox", "combobox", "spinbutton"}:
        return True
    properties = element.get("properties")
    return isinstance(properties, Mapping) and properties.get("editable") in {
        True,
        "plaintext",
        "true",
    }


def _find_element(elements: list[dict[str, Any]], element_id: str) -> dict[str, Any]:
    for element in elements:
        if element.get("id") == element_id:
            return element
    raise RuntimeError(f"Jev selected an unknown element: {element_id}")
