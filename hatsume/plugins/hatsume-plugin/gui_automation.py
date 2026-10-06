"""Internal GUI automation bridge used by chat-facing tools.

The module is intentionally invoked by the LangChain tools rather than exposed
as a user-facing executable.  AT-SPI handles native desktop applications and
Chrome's DevTools Protocol handles page elements without converting semantic
targets back into guessed screen coordinates.
"""

from __future__ import annotations

import json
import fcntl
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid
import urllib.request
from typing import Any


GROUP_ID = int(os.environ.get("HATSUME_GUI_GROUP_ID", "0"))
STATE_DIR = Path("/run/hatsume/gui") / str(GROUP_ID)
AT_SPI_STATE = STATE_DIR / "hatsume-atspi-tree.json"
CDP_STATE = STATE_DIR / "hatsume-cdp-tree.json"
CHROME_PAGE = STATE_DIR / "chrome-page.json"
DISPLAY = os.environ.get("DISPLAY", ":99")
os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/hatsume/desktop-bus")


def _dump(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError("元素引用已失效，请先重新检查 GUI 元素") from exc
    if not isinstance(value, dict):
        raise RuntimeError("元素引用状态损坏，请先重新检查 GUI 元素")
    if time.time() - value.get("created", 0) > 600:
        raise RuntimeError("元素引用已过期，请重新检查")
    return value


def _rect(component: Any) -> list[int] | None:
    try:
        rect = component.getExtents(0)
        return [int(rect.x), int(rect.y), int(rect.width), int(rect.height)]
    except Exception:
        return None


def _atspi_children(node: Any) -> list[Any]:
    try:
        return [node.getChildAtIndex(i) for i in range(node.childCount)]
    except Exception:
        return []


def _atspi_snapshot(max_nodes: int, application: str = "") -> dict[str, Any]:
    try:
        import pyatspi
    except ImportError as exc:
        raise RuntimeError("GUI 镜像缺少 AT-SPI Python 绑定") from exc

    # Registry connects to the session accessibility bus.  The GUI entrypoint
    # starts a DBus session before applications are launched.
    desktop = pyatspi.Registry.getDesktop(0)
    nodes: list[dict[str, Any]] = []
    paths: dict[str, list[int]] = {}
    seen: set[str] = set()
    snapshot = uuid.uuid4().hex[:12]
    identities = {}
    visited = 0

    def walk(node: Any, path: list[int], app_name: str, depth: int) -> None:
        nonlocal visited
        visited += 1
        if len(nodes) >= max_nodes or depth > 20 or visited > 3000:
            return
        try:
            role = str(node.getRoleName() or "").strip()
            name = str(node.name or "").strip()
            description = str(node.description or "").strip()
            pid = node.get_process_id()
            showing = node.getState().contains(pyatspi.STATE_SHOWING)
            identity = f"{pid}:{path}:{role}:{name}"
            if identity in seen:
                return
            seen.add(identity)
        except Exception:
            return

        current_app = name if role == "application" and name else app_name
        actions: list[str] = []
        try:
            action = node.queryAction()
            actions = [str(action.getName(i)) for i in range(action.nActions)]
        except Exception:
            pass
        bounds = None
        try:
            bounds = _rect(node.queryComponent())
        except Exception:
            pass

        # Keep application roots and useful semantic controls.  Anonymous
        # layout containers are omitted to keep the model context compact.
        if role == "application" or (showing and (name or actions or role in {
            "push button",
            "toggle button",
            "check box",
            "radio button",
            "entry",
            "text",
            "combo box",
            "list item",
            "menu item",
            "tree item",
            "link",
            "table cell",
        })):
            element_id = f"a11y-{snapshot}-{len(nodes) + 1}"
            item = {
                "id": element_id,
                "application": current_app,
                "role": role,
                "name": name,
                "description": description,
                "actions": actions,
                "bounds": bounds,
                "enabled": node.getState().contains(pyatspi.STATE_ENABLED),
                "focused": node.getState().contains(pyatspi.STATE_FOCUSED),
                "selected": node.getState().contains(pyatspi.STATE_SELECTED),
                "checked": node.getState().contains(pyatspi.STATE_CHECKED),
                "expanded": node.getState().contains(pyatspi.STATE_EXPANDED),
            }
            try:
                text_iface = node.queryText()
                item["text"] = text_iface.getText(0, min(text_iface.characterCount, 500))
            except Exception:
                pass
            nodes.append(item)
            paths[element_id] = path
            identities[element_id] = [pid, node.path, role, name]

        for index, child in enumerate(_atspi_children(node)):
            walk(child, path + [index], current_app, depth + 1)

    for index, app in enumerate(_atspi_children(desktop)):
        if application and application.casefold() not in (app.name or "").casefold():
            continue
        walk(app, [index], "", 0)

    result = {"backend": "atspi", "display": DISPLAY, "elements": nodes, "paths": paths,
              "identities": identities, "created": time.time()}
    _save(AT_SPI_STATE, result)
    return {"backend": "atspi", "display": DISPLAY, "elements": nodes,
            "truncated": len(nodes) >= max_nodes or visited > 3000}


def _atspi_resolve(path: list[int]) -> Any:
    import pyatspi

    node = pyatspi.Registry.getDesktop(0)
    for index in path:
        node = node.getChildAtIndex(int(index))
    return node


def _activate_window(node: Any) -> None:
    """Activate the owning X11 window by PID/title, never by coordinates."""
    pid = str(node.get_process_id())
    ancestor = node
    title = ""
    while ancestor is not None:
        if ancestor.getRoleName() in {"frame", "dialog", "window"}:
            title = ancestor.name or ""
            break
        ancestor = ancestor.parent
    output = subprocess.run(["wmctrl", "-lp"], check=True, capture_output=True, text=True).stdout
    windows = [line.split(None, 4) for line in output.splitlines()]
    matches = [w for w in windows if len(w) == 5 and w[2] == pid and (not title or w[4] == title)]
    if len(matches) > 1:
        expected = _rect(ancestor.queryComponent())
        matching_frames = []
        for window in matches:
            geometry = subprocess.run(["xwininfo", "-id", window[0]],
                                      check=True, capture_output=True, text=True).stdout
            values = {name: int(re.search(pattern, geometry).group(1)) for name, pattern in {
                "X": r"Absolute upper-left X:\s+(-?\d+)",
                "Y": r"Absolute upper-left Y:\s+(-?\d+)",
                "WIDTH": r"Width:\s+(\d+)", "HEIGHT": r"Height:\s+(\d+)"}.items()}
            extents = subprocess.run(["xprop", "-id", window[0], "_NET_FRAME_EXTENTS"],
                                     check=True, capture_output=True, text=True).stdout
            borders = [int(n) for n in re.findall(r"\d+", extents.split("=", 1)[-1])]
            left, right, top, bottom = borders if len(borders) == 4 else [0, 0, 0, 0]
            frame = [int(values["X"]) - left, int(values["Y"]) - top,
                     int(values["WIDTH"]) + left + right, int(values["HEIGHT"]) + top + bottom]
            if expected and all(abs(a - b) <= 3 for a, b in zip(frame, expected)):
                matching_frames.append(window)
        matches = matching_frames
    if len(matches) != 1:
        raise RuntimeError("无法唯一确定控件所属窗口，请重新检查")
    subprocess.run(["wmctrl", "-ia", matches[0][0]], check=True)
    subprocess.run(["xdotool", "windowactivate", "--sync", matches[0][0]], check=True)
    focused_pid = subprocess.run(["xdotool", "getwindowfocus", "getwindowpid"],
                                 check=True, capture_output=True, text=True).stdout.strip()
    if focused_pid != pid:
        raise RuntimeError("目标窗口未获得键盘焦点；请先关闭当前展开的菜单或弹窗")


def _atspi_action(element_id: str, action_name: str, text: str | None = None) -> dict[str, Any]:
    state = _load(AT_SPI_STATE)
    paths = state.get("paths", {})
    path = paths.get(element_id)
    if not isinstance(path, list):
        raise RuntimeError(f"找不到元素 {element_id}，请先重新检查 GUI 元素")
    node = _atspi_resolve(path)
    identity = [node.get_process_id(), node.path, node.getRoleName(), node.name or ""]
    if identity != state["identities"].get(element_id):
        raise RuntimeError("桌面元素已变化，请重新检查")
    import pyatspi
    if not node.getState().contains(pyatspi.STATE_ENABLED):
        raise RuntimeError("桌面控件已禁用")

    if action_name == "focus":
        _activate_window(node)
        if (not node.queryComponent().grabFocus()
                and node.getRoleName() not in {"menu", "menu item", "frame", "dialog", "window"}):
            raise RuntimeError("控件不能获取焦点")
    elif action_name == "set_text":
        if text is None:
            raise RuntimeError("set_text 需要提供 text")
        _activate_window(node)
        node.queryComponent().grabFocus()
        editable = node.queryEditableText()
        if not editable.setTextContents(text):
            raise RuntimeError("控件不支持设置文本")
    elif action_name == "click":
        action = node.queryAction()
        names = [str(action.getName(i)).lower() for i in range(action.nActions)]
        preferred = ("click", "press", "activate", "open")
        index = next((names.index(name) for name in preferred if name in names), None)
        if index is None:
            raise RuntimeError(f"控件没有可激活操作，可用操作：{names}")
        if not action.doAction(index):
            raise RuntimeError(f"元素 {element_id} 的 AT-SPI 操作失败")
    else:
        raise RuntimeError(f"不支持的 AT-SPI 操作：{action_name}")

    return {"ok": True, "backend": "atspi", "id": element_id, "action": action_name}


def _http_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _chrome_target(target_id: str = "") -> dict[str, Any]:
    if not target_id:
        try:
            target_id = json.loads(CHROME_PAGE.read_text())["targetId"]
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("当前群没有 Chrome 页面，请先调用 chrome_open") from exc
    try:
        targets = _http_json("http://127.0.0.1:9222/json/list")
    except Exception as exc:
        raise RuntimeError("Chrome CDP 未运行，请先调用 chrome_open") from exc
    for target in targets:
        if (target.get("type") == "page" and target.get("webSocketDebuggerUrl")
                and (not target_id or target.get("id") == target_id)):
            return target
    raise RuntimeError("Chrome CDP 没有可操作的页面")


def _cdp_call(ws: Any, method: str, params: dict[str, Any] | None = None, call_id: int = 1) -> Any:
    ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == call_id:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message.get("result", {})


def _cdp_connect(target_id: str = "") -> tuple[Any, dict[str, Any]]:
    try:
        import websocket
    except ImportError as exc:
        raise RuntimeError("GUI 镜像缺少 websocket-client，无法连接 Chrome CDP") from exc
    target = _chrome_target(target_id)
    return websocket.create_connection(target["webSocketDebuggerUrl"], timeout=5, suppress_origin=True), target


def _chrome_open(url: str) -> dict[str, Any]:
    targets_ready = True
    try:
        _http_json("http://127.0.0.1:9222/json/version")
    except Exception:
        targets_ready = False
    if not targets_ready:
        subprocess.Popen(
            [
                "google-chrome",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--force-renderer-accessibility",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=9222",
                "--user-data-dir=/tmp/hatsume-chrome-cdp",
                "--window-size=1280,800",
                "about:blank",
            ],
            env={**os.environ, "DISPLAY": DISPLAY},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(50):
            try:
                _http_json("http://127.0.0.1:9222/json/version")
                break
            except Exception:
                time.sleep(0.1)
    try:
        target = _chrome_target()
    except RuntimeError:
        import websocket
        browser = _http_json("http://127.0.0.1:9222/json/version")
        browser_ws = websocket.create_connection(browser["webSocketDebuggerUrl"], timeout=5, suppress_origin=True)
        try:
            target_id = _cdp_call(browser_ws, "Target.createTarget", {"url": "about:blank"})["targetId"]
        finally:
            browser_ws.close()
        _save(CHROME_PAGE, {"targetId": target_id})
        target = _chrome_target(target_id)
    ws, target = _cdp_connect(target["id"])
    try:
        navigation = _cdp_call(ws, "Page.navigate", {"url": url})
        if navigation.get("errorText"):
            raise RuntimeError(f"Chrome 导航失败：{navigation['errorText']}")
        _cdp_call(ws, "Page.bringToFront")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status = _cdp_call(ws, "Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            frame = _cdp_call(ws, "Page.getFrameTree")["frameTree"]["frame"]
            if (status.get("result", {}).get("value") == "complete"
                    and (not navigation.get("loaderId") or frame.get("loaderId") == navigation["loaderId"])):
                break
            time.sleep(0.1)
    finally:
        ws.close()
    return {"ok": True, "backend": "cdp", "url": url, "targetId": target.get("id")}


def _chrome_dom_attributes(ws: Any, backend_node_id: int) -> dict[str, str]:
    """Return ordinary HTML attributes for one accessibility-tree DOM node."""
    node = _cdp_call(
        ws,
        "DOM.describeNode",
        {"backendNodeId": backend_node_id},
    ).get("node", {})
    raw_attributes = node.get("attributes", [])
    if not isinstance(raw_attributes, list):
        return {}
    return {
        str(raw_attributes[index]): str(raw_attributes[index + 1])
        for index in range(0, len(raw_attributes) - 1, 2)
    }


def _chrome_inspect(target_id: str = "") -> dict[str, Any]:
    owned_target = json.loads(CHROME_PAGE.read_text())["targetId"]
    if target_id and target_id != owned_target:
        raise RuntimeError("该 Chrome 页面不属于当前群")
    ws, target = _cdp_connect(target_id)
    try:
        document = _cdp_call(ws, "DOM.getDocument", {"depth": 0})["root"]["backendNodeId"]
        ax_nodes = _cdp_call(ws, "Accessibility.getFullAXTree")["nodes"]
        snapshot = uuid.uuid4().hex[:12]
        roles = {"button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio",
                 "menuitem", "tab", "treeitem", "option", "slider", "spinbutton"}
        elements = []
        for node in ax_nodes:
            role = node.get("role", {}).get("value", "")
            backend_id = node.get("backendDOMNodeId")
            if node.get("ignored") or not backend_id or role not in roles:
                continue
            properties = {p["name"]: p.get("value", {}).get("value") for p in node.get("properties", [])}
            try:
                attributes = _chrome_dom_attributes(ws, backend_id)
            except RuntimeError:
                # Accessibility inspection should still return a usable element
                # when Chrome cannot describe one stale DOM node.
                attributes = {}
            elements.append({"id": f"cdp-{snapshot}-{len(elements) + 1}",
                             "backendNodeId": backend_id, "role": role,
                             "name": node.get("name", {}).get("value", ""),
                             "value": node.get("value", {}).get("value"),
                             "properties": properties,
                             "attributes": attributes})
            if len(elements) >= 250:
                break
    finally:
        ws.close()
    if not isinstance(elements, list):
        raise RuntimeError("Chrome CDP 未返回可交互元素")
    state = {"backend": "cdp", "targetId": target.get("id"), "document": document,
             "elements": elements, "created": time.time()}
    _save(CDP_STATE, state)
    return {"backend": "cdp", "targetId": target.get("id"), "url": target.get("url"), "title": target.get("title"), "elements": elements}


def _chrome_action(element_id: str, action: str, text: str | None = None) -> dict[str, Any]:
    state = _load(CDP_STATE)
    element = next((x for x in state.get("elements", []) if x.get("id") == element_id), None)
    if not isinstance(element, dict) or not element.get("backendNodeId"):
        raise RuntimeError(f"找不到 Chrome 元素 {element_id}，请先重新检查 Chrome 元素")
    ws, _ = _cdp_connect(state["targetId"])
    try:
        _cdp_call(ws, "Page.bringToFront")
        document = _cdp_call(ws, "DOM.getDocument", {"depth": 0})["root"]["backendNodeId"]
        if document != state["document"]:
            raise RuntimeError("页面已导航，请重新检查 Chrome 元素")
        remote = _cdp_call(ws, "DOM.resolveNode", {"backendNodeId": element["backendNodeId"]})["object"]["objectId"]
        function = """function(action, text) {
            if (!this.isConnected || this.disabled) throw new Error('Element detached or disabled');
            if (action === 'click') { this.click(); }
            else if (action === 'focus') { this.focus(); }
            else if (action === 'set_text') {
                this.focus();
                if (this instanceof HTMLTextAreaElement || this instanceof HTMLInputElement) {
                    this.select();
                } else if (this.isContentEditable) {
                    const selection = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(this);
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
                else throw new Error('Element is not editable');
            } else throw new Error('Unsupported action');
            return true;
        }"""
        result = _cdp_call(ws, "Runtime.callFunctionOn", {"objectId": remote,
            "functionDeclaration": function, "arguments": [{"value": action}, {"value": text}], "returnByValue": True})
        if result.get("exceptionDetails") or result.get("result", {}).get("value") is not True:
            raise RuntimeError(str(result.get("exceptionDetails", "CDP 操作失败")))
        if action == "set_text":
            # Use Chrome's input pipeline instead of assigning the DOM property.
            # This produces trusted beforeinput/input events and lets controlled
            # inputs (React/Vue/etc.) update their own state as a real keystroke
            # would.  The JS call above only focuses and selects the old value.
            _cdp_call(ws, "Input.insertText", {"text": text or ""})
            # Input.insertText intentionally does not blur the control, so emit
            # change for pages that use it as their commit signal.  The value was
            # already entered through the trusted CDP input path.
            change = """function() {
                if (!this.isConnected || this.disabled) throw new Error('Element detached or disabled');
                this.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            }"""
            changed = _cdp_call(ws, "Runtime.callFunctionOn", {
                "objectId": remote,
                "functionDeclaration": change,
                "returnByValue": True,
            })
            if changed.get("exceptionDetails") or changed.get("result", {}).get("value") is not True:
                raise RuntimeError(str(changed.get("exceptionDetails", "CDP change 事件失败")))
            observed = _cdp_call(ws, "Runtime.callFunctionOn", {
                "objectId": remote,
                "functionDeclaration": """function() {
                    return this.isContentEditable ? this.textContent : this.value;
                }""",
                "returnByValue": True,
            })
            if observed.get("exceptionDetails"):
                raise RuntimeError(str(observed["exceptionDetails"]))
            observed_value = observed.get("result", {}).get("value")
            if observed_value != (text or ""):
                raise RuntimeError(
                    f"Chrome 元素 {element_id} 输入后值不一致：{observed_value!r}"
                )
    finally:
        ws.close()
    if result.get("result", {}).get("value") is False:
        raise RuntimeError(f"Chrome 元素 {element_id} 已不存在，请重新检查")
    result_value = {"ok": True, "backend": "cdp", "id": element_id, "action": action}
    if action == "set_text":
        result_value["value"] = text or ""
    return result_value


def _click_coordinates(x: int, y: int, button: str, clicks: int) -> dict[str, Any]:
    buttons = {"left": "1", "middle": "2", "right": "3"}
    if button not in buttons or clicks not in {1, 2}:
        raise RuntimeError("button 必须为 left/right/middle，clicks 必须为 1 或 2")
    geometry = subprocess.run(["xdotool", "getdisplaygeometry"], check=True,
                              capture_output=True, text=True).stdout
    width, height = map(int, geometry.split())
    if not (0 <= x < width and 0 <= y < height):
        raise RuntimeError(f"坐标越界：桌面尺寸 {width}x{height}，有效范围 0<=x<{width}、0<=y<{height}")
    subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y),
                    "click", "--repeat", str(clicks), "--delay", "100", buttons[button]], check=True)
    return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks,
            "display": DISPLAY, "width": width, "height": height}


def _activate_application_id(application_id: str) -> None:
    """Activate an application root returned by the latest AT-SPI inspection."""
    if not application_id:
        raise RuntimeError("gui_drag 需要提供 gui_inspect 返回的 app_id")
    state = _load(AT_SPI_STATE)
    paths = state.get("paths", {})
    path = paths.get(application_id)
    if not isinstance(path, list):
        raise RuntimeError(f"找不到应用 {application_id}，请先重新检查桌面")
    node = _atspi_resolve(path)
    if str(node.getRoleName()).casefold() != "application":
        raise RuntimeError(f"元素 {application_id} 不是应用根节点")
    pending = list(_atspi_children(node))
    while pending:
        candidate = pending.pop(0)
        try:
            role = str(candidate.getRoleName()).casefold()
        except Exception:
            role = ""
        if role in {"frame", "window", "dialog"}:
            node = candidate
            break
        pending.extend(_atspi_children(candidate))
    _activate_window(node)


def _drag(
    application_id: str,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    speed: float = 800.0,
) -> dict[str, Any]:
    """Drag between screen pixels with a human-like continuous mouse move."""
    if speed <= 0:
        raise RuntimeError("speed 必须为正数像素/秒")
    geometry = subprocess.run(["xdotool", "getdisplaygeometry"], check=True,
                              capture_output=True, text=True).stdout
    width, height = map(int, geometry.split())
    points = ((start_x, start_y), (end_x, end_y))
    if any(not (0 <= x < width and 0 <= y < height) for x, y in points):
        raise RuntimeError(
            f"拖拽坐标越界：桌面尺寸 {width}x{height}，"
            f"有效范围 0<=x<{width}、0<=y<{height}"
        )
    _activate_application_id(application_id)
    distance = ((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5
    duration = max(0.15, distance / speed)
    subprocess.run(
        ["xdotool", "mousemove", "--sync", str(start_x), str(start_y)],
        check=True,
        env={**os.environ, "DISPLAY": DISPLAY},
    )
    subprocess.run(["xdotool", "mousedown", "1"], check=True,
                   env={**os.environ, "DISPLAY": DISPLAY})
    try:
        steps = max(2, int(duration * 60) + 1)
        interval = duration / steps
        for index in range(1, steps + 1):
            progress = index / steps
            eased = progress * progress * (3.0 - 2.0 * progress)
            x = round(start_x + (end_x - start_x) * eased)
            y = round(start_y + (end_y - start_y) * eased)
            subprocess.run(
                ["xdotool", "mousemove", "--sync", str(x), str(y)],
                check=True,
                env={**os.environ, "DISPLAY": DISPLAY},
            )
            if index < steps:
                time.sleep(interval)
    finally:
        subprocess.run(["xdotool", "mouseup", "1"], check=True,
                       env={**os.environ, "DISPLAY": DISPLAY})
    return {
        "ok": True,
        "application_id": application_id,
        "start": {"x": start_x, "y": start_y},
        "end": {"x": end_x, "y": end_y},
        "speed": speed,
        "duration": duration,
        "display": DISPLAY,
        "width": width,
        "height": height,
    }


def _screenshot(path: str | None) -> dict[str, Any]:
    output = path or f"/tmp/gui-screenshots/{GROUP_ID}/{uuid.uuid4().hex}.png"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["scrot", "-D", DISPLAY, output], check=True)
    return {"ok": True, "path": output, "display": DISPLAY}


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit("missing GUI operation")
    operation = argv[1]
    if operation == "atspi-inspect":
        _dump(_atspi_snapshot(int(argv[2]) if len(argv) > 2 else 200, argv[3] if len(argv) > 3 else ""))
    elif operation in {"atspi-click", "atspi-focus", "atspi-set-text"}:
        text = argv[3] if len(argv) > 3 else None
        _dump(_atspi_action(argv[2], operation[6:].replace("-", "_"), text))
    elif operation == "chrome-open":
        _dump(_chrome_open(argv[2]))
    elif operation == "chrome-inspect":
        _dump(_chrome_inspect(argv[2] if len(argv) > 2 else ""))
    elif operation in {"chrome-click", "chrome-focus", "chrome-set-text"}:
        text = argv[3] if len(argv) > 3 else None
        _dump(_chrome_action(argv[2], operation[7:].replace("-", "_"), text))
    elif operation == "screenshot":
        _dump(_screenshot(argv[2] if len(argv) > 2 else None))
    elif operation == "click-coordinates":
        _dump(_click_coordinates(int(argv[2]), int(argv[3]), argv[4], int(argv[5])))
    elif operation == "drag":
        _dump(_drag(argv[2], int(argv[3]), int(argv[4]), int(argv[5]), int(argv[6]),
                    float(argv[7]) if len(argv) > 7 else 800.0))
    elif operation in {"key", "type"}:
        element_id = argv[3]
        terminal = False
        if element_id.startswith("cdp-"):
            _chrome_action(element_id, "focus")
            ws, _ = _cdp_connect(_load(CDP_STATE)["targetId"])
            try:
                _cdp_call(ws, "Page.bringToFront")
            finally:
                ws.close()
        else:
            _atspi_action(element_id, "focus")
            terminal = any(e["id"] == element_id and e["role"] == "terminal"
                           for e in _load(AT_SPI_STATE)["elements"])
        if operation == "type":
            subprocess.run(["xclip", "-selection", "clipboard", "-in"], input=argv[2].encode(),
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            argv[2] = "ctrl+shift+v" if terminal else "ctrl+v"
        subprocess.run(["xdotool", "key", "--clearmodifiers", argv[2]], check=True, env={**os.environ, "DISPLAY": DISPLAY})
        _dump({"ok": True, "key": argv[2]})
    elif operation == "launch":
        programs = {"terminal": ["xfce4-terminal", "--disable-server"], "file_manager": ["pcmanfm", "/work"]}
        application = argv[2]
        arguments = json.loads(argv[3]) if len(argv) > 3 else []
        if not application or application.startswith("-") or not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
            raise RuntimeError("启动程序需要合法的应用名称及字符串参数列表")
        process = subprocess.Popen(programs.get(application, [application]) + arguments,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        _dump({"ok": True, "application": application, "pid": process.pid})
    else:
        raise SystemExit(f"unknown GUI operation: {operation}")


if __name__ == "__main__":
    try:
        if GROUP_ID <= 0:
            raise RuntimeError("GUI 操作需要有效的群 ID")
        STATE_DIR.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (STATE_DIR.parent / "desktop.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            main(sys.argv)
    except Exception as exc:
        _dump({"ok": False, "error": str(exc)})
        raise SystemExit(1)
