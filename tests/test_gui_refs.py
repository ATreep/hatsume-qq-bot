"""Focused contracts for expiring and rejecting semantic element references."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin/gui_automation.py"
spec = importlib.util.spec_from_file_location("gui_automation_test", SOURCE)
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


class ReferenceTests(unittest.TestCase):
    def test_chrome_inspect_includes_dom_attributes_and_values(self):
        class Socket:
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            page = directory / "page.json"
            state = directory / "state.json"
            page.write_text(json.dumps({"targetId": "target-1"}))

            def cdp_call(_ws, method, params=None, call_id=1):
                del call_id
                if method == "DOM.getDocument":
                    return {"root": {"backendNodeId": 1}}
                if method == "Accessibility.getFullAXTree":
                    return {"nodes": [{
                        "role": {"value": "button"},
                        "backendDOMNodeId": 7,
                        "name": {"value": "Search"},
                        "ignored": False,
                    }]}
                if method == "DOM.describeNode":
                    self.assertEqual(params, {"backendNodeId": 7})
                    return {"node": {
                        "attributes": ["id", "search", "data-kind", "primary"],
                    }}
                raise AssertionError(method)

            with patch.object(gui, "CHROME_PAGE", page), \
                    patch.object(gui, "CDP_STATE", state), \
                    patch.object(
                        gui,
                        "_cdp_connect",
                        return_value=(Socket(), {
                            "id": "target-1",
                            "url": "https://example.test",
                            "title": "Example",
                        }),
                    ), \
                    patch.object(gui, "_cdp_call", side_effect=cdp_call):
                result = gui._chrome_inspect("target-1")

        self.assertEqual(
            result["elements"][0]["attributes"],
            {"id": "search", "data-kind": "primary"},
        )

    def test_coordinate_click_rejects_screen_boundary(self):
        with patch.object(gui.subprocess, "run", return_value=SimpleNamespace(stdout="1280 800\n")) as run:
            with self.assertRaisesRegex(RuntimeError, "坐标越界"):
                gui._click_coordinates(1280, 400, "left", 1)
            self.assertEqual(run.call_count, 1)

    def test_coordinate_click_uses_runtime_display_size(self):
        with patch.object(gui.subprocess, "run", return_value=SimpleNamespace(stdout="640 480\n")) as run:
            result = gui._click_coordinates(639, 479, "middle", 2)
            self.assertEqual((result["width"], result["height"]), (640, 480))
            self.assertEqual(run.call_args.args[0], ["xdotool", "mousemove", "--sync", "639", "479",
                            "click", "--repeat", "2", "--delay", "100", "2"])

    def test_drag_activates_app_and_releases_mouse(self):
        with patch.object(
            gui.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="1280 800\n"),
        ) as run, \
                patch.object(gui, "_activate_application_id") as activate, \
                patch.object(gui.time, "sleep") as sleep:
            result = gui._drag("a11y-app-1", 10, 20, 110, 220, 1000)

        activate.assert_called_once_with("a11y-app-1")
        self.assertEqual(result["start"], {"x": 10, "y": 20})
        self.assertEqual(result["end"], {"x": 110, "y": 220})
        self.assertEqual(run.call_args_list[1].args[0], [
            "xdotool", "mousemove", "--sync", "10", "20"
        ])
        self.assertEqual(run.call_args_list[2].args[0], ["xdotool", "mousedown", "1"])
        move_calls = [
            call.args[0] for call in run.call_args_list
            if call.args[0][:3] == ["xdotool", "mousemove", "--sync"]
        ]
        self.assertGreaterEqual(len(move_calls), 3)
        self.assertEqual(move_calls[0], ["xdotool", "mousemove", "--sync", "10", "20"])
        self.assertEqual(move_calls[-1], ["xdotool", "mousemove", "--sync", "110", "220"])
        self.assertEqual(run.call_args_list[-1].args[0], ["xdotool", "mouseup", "1"])
        self.assertTrue(sleep.called)

    def test_keyboard_focus_on_another_process_is_rejected(self):
        node = SimpleNamespace(get_process_id=lambda: 42, getRoleName=lambda: "frame", name="Terminal")
        replies = [SimpleNamespace(stdout="0x01 0 42 host Terminal\n"),
                   SimpleNamespace(stdout=""), SimpleNamespace(stdout=""),
                   SimpleNamespace(stdout="99\n")]
        with patch.object(gui.subprocess, "run", side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, "键盘焦点"):
                gui._activate_window(node)

    def test_ambiguous_window_is_rejected_before_keyboard_input(self):
        node = SimpleNamespace(get_process_id=lambda: 42, getRoleName=lambda: "frame", name="Missing")
        with patch.object(gui.subprocess, "run", return_value=SimpleNamespace(stdout="0x01 0 42 host Other\n")):
            with self.assertRaisesRegex(RuntimeError, "唯一确定"):
                gui._activate_window(node)

    def test_expired_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"created": time.time() - 601}))
            with self.assertRaisesRegex(RuntimeError, "过期"):
                gui._load(path)

    def test_missing_and_corrupt_snapshots_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with self.assertRaisesRegex(RuntimeError, "失效"):
                gui._load(path)
            path.write_text("{broken")
            with self.assertRaisesRegex(RuntimeError, "失效"):
                gui._load(path)

    def test_old_desktop_id_never_resolves_to_new_node(self):
        with patch.object(gui, "_load", return_value={"paths": {"a11y-new-1": [0]}}), \
             patch.object(gui, "_atspi_resolve") as resolve:
            with self.assertRaisesRegex(RuntimeError, "找不到元素"):
                gui._atspi_action("a11y-old-1", "click")
            resolve.assert_not_called()

    def test_old_browser_id_never_connects_to_another_node(self):
        with patch.object(gui, "_load", return_value={"elements": [{"id": "cdp-new-1", "backendNodeId": 2}]}), \
             patch.object(gui, "_cdp_connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "找不到 Chrome 元素"):
                gui._chrome_action("cdp-old-1", "click")
            connect.assert_not_called()

    def test_chrome_set_text_uses_trusted_input_and_verifies_value(self):
        class Socket:
            def close(self):
                pass

        calls = []

        def cdp_call(_ws, method, params=None, call_id=1):
            del call_id
            calls.append((method, params or {}))
            if method == "DOM.getDocument":
                return {"root": {"backendNodeId": 1}}
            if method == "DOM.resolveNode":
                return {"object": {"objectId": "remote-1"}}
            if method == "Runtime.callFunctionOn":
                function = params["functionDeclaration"]
                if "return this.isContentEditable" in function:
                    return {"result": {"value": "new value"}}
                return {"result": {"value": True}}
            if method == "Input.insertText":
                return {}
            if method == "Page.bringToFront":
                return {}
            raise AssertionError(method)

        with patch.object(
            gui,
            "_load",
            return_value={
                "targetId": "target-1",
                "document": 1,
                "elements": [{"id": "cdp-input-1", "backendNodeId": 7}],
            },
        ), patch.object(gui, "_cdp_connect", return_value=(Socket(), {"id": "target-1"})), \
                patch.object(gui, "_cdp_call", side_effect=cdp_call):
            result = gui._chrome_action("cdp-input-1", "set_text", "new value")

        self.assertEqual(result["value"], "new value")
        input_calls = [params for method, params in calls if method == "Input.insertText"]
        self.assertEqual(input_calls, [{"text": "new value"}])
        selection_calls = [
            params for method, params in calls if method == "Runtime.callFunctionOn"
        ]
        self.assertIn("this.select()", selection_calls[0]["functionDeclaration"])

    def test_cdp_skips_events_and_raises_protocol_errors(self):
        class Socket:
            def __init__(self, messages): self.messages = iter(messages)
            def send(self, message): self.sent = json.loads(message)
            def recv(self): return json.dumps(next(self.messages))
        socket = Socket([{"method": "Page.event"}, {"id": 1, "result": {"value": 42}}])
        self.assertEqual(gui._cdp_call(socket, "Test.method"), {"value": 42})
        self.assertEqual(socket.sent["method"], "Test.method")
        with self.assertRaisesRegex(RuntimeError, "detached"):
            gui._cdp_call(Socket([{"id": 1, "error": "detached"}]), "Test.method")
