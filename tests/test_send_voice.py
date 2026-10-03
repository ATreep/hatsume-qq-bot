"""Run the focused production tool without booting NoneBot/model/database state.

HTTP, files, LangChain, and OneBot segments are real. Only group state and the
outgoing chat callback are substituted; production functions load from the AST.
"""

import ast
import asyncio
import base64
import tempfile
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import unquote, urlparse

import requests
from langchain_core.tools import tool
from nonebot.adapters.onebot.v11 import MessageSegment

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "hatsume/plugins/hatsume-plugin/graph/tools.py"
)
TREE = ast.parse(SOURCE.read_text())
NAMES = {
    "_format_tool_input",
    "_wrap_tool_ainvoke",
    "tool",
    "_download_voice_to_sandbox",
    "send_voice",
}
CODE = compile(
    ast.Module(
        body=[
            node
            for node in TREE.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in NAMES
        ],
        type_ignores=[],
    ),
    str(SOURCE),
    "exec",
)
AUDIO = b"ID3-test-audio"


class VoiceCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sender = AsyncMock()
        self.runtime = SimpleNamespace(
            group_id=123456, conversation=SimpleNamespace(ai_answer=self.sender)
        )
        self.ready = AsyncMock()
        self.namespace = {
            "asyncio": asyncio,
            "base64": base64,
            "uuid": uuid,
            "Path": Path,
            "Any": Any,
            "unquote": unquote,
            "urlparse": urlparse,
            "requests": requests,
            "_langchain_tool": tool,
            "MessageSegment": MessageSegment,
            "get_current_group_runtime": lambda: self.runtime,
            "ensure_container_running": self.ready,
        }
        exec(CODE, self.namespace)
        self.voice = self.namespace["send_voice"]

    async def send(self, url):
        return await self.voice.ainvoke({"voice_url": url})

    def assert_record(self):
        self.sender.assert_awaited_once()
        segment = self.sender.await_args.args[0]
        self.assertEqual(segment.type, "record")
        self.assertTrue(segment.data["file"].startswith("base64://"))
        self.assertEqual(base64.b64decode(segment.data["file"][9:]), AUDIO)
        self.ready.assert_awaited_once_with(self.runtime.group_id)


class SendVoiceFileTests(VoiceCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def audio(self, name):
        path = self.root / name
        path.write_bytes(AUDIO)
        return path

    async def test_encoded_file_uri_and_uppercase_mp3(self):
        self.assertIn("成功", await self.send(self.audio("声音 clip.MP3").as_uri()))
        self.assert_record()

    async def test_non_mp3_retains_original_file_and_reports_path(self):
        path = self.audio("clip.wav")
        result = await self.send(path.as_uri())
        self.assertIn("此工具仅支持 mp3 格式的声音，请处理后再发送。", result)
        self.assertIn(f"原声音文件在沙盒中的路径是：{path}", result)
        self.assertEqual(path.read_bytes(), AUDIO)
        self.sender.assert_not_awaited()

    async def test_missing_file_and_directory(self):
        for path in (self.root / "missing.mp3", self.root):
            self.assertIn("不存在或不是普通文件", await self.send(path.as_uri()))
        self.sender.assert_not_awaited()

    async def test_invalid_input_before_io(self):
        for url in (
            " ",
            "/tmp/voice.mp3",
            "ftp://example.com/voice.mp3",
            "base64://abc",
            "file://relative.mp3",
            "file://remote/tmp/voice.mp3",
            "file:///tmp/null%00.mp3",
            "https:///voice.mp3",
        ):
            with self.subTest(url=url):
                self.assertIn("失败", await self.send(url))
        self.ready.assert_not_awaited()
        self.sender.assert_not_awaited()

    async def test_send_channel_errors(self):
        path = self.audio("clip.mp3")
        self.runtime.conversation.ai_answer = None
        self.assertIn("发送通道未就绪", await self.send(path.as_uri()))
        self.runtime.conversation.ai_answer = self.sender
        self.sender.side_effect = RuntimeError("OneBot unavailable")
        self.assertIn("OneBot unavailable", await self.send(path.as_uri()))

    def test_registration_and_schema(self):
        registration = next(
            node
            for node in TREE.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "CHAT_TOOLS"
                for target in node.targets
            )
        )
        self.assertIn(
            "send_voice",
            [item.id for item in registration.value.elts if isinstance(item, ast.Name)],
        )
        self.assertEqual(self.voice.name, "send_voice")
        self.assertEqual(
            self.voice.args_schema.model_json_schema()["required"], ["voice_url"]
        )


class AudioHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/missing.mp3":
            self.send_error(404)
            return
        self.send_response(200)
        if path == "/interrupted.mp3":
            self.send_header("Content-Length", str(len(AUDIO) + 100))
        self.end_headers()
        self.wfile.write(AUDIO)

    def log_message(self, *_args):
        pass


class SendVoiceHttpTests(VoiceCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AudioHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.downloads = []
        real_download = self.namespace["_download_voice_to_sandbox"]

        def track_download(*args, **kwargs):
            path = real_download(*args, **kwargs)
            self.downloads.append(path)
            return path

        self.namespace["_download_voice_to_sandbox"] = track_download
        self.addCleanup(self.remove_downloads)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def remove_downloads(self):
        for path in self.downloads:
            path.unlink(missing_ok=True)

    async def test_mp3_download_and_record(self):
        self.assertIn(
            "成功", await self.send(self.origin + "/voice.MP3?signature=test")
        )
        path = self.downloads[0]
        self.assertEqual(path.parent, Path("/tmp"))
        self.assertTrue(path.name.startswith(f"hatsume-voice-{self.runtime.group_id}-"))
        self.assertEqual(path.suffix, ".MP3")
        self.assertEqual(path.read_bytes(), AUDIO)
        self.assert_record()

    async def test_non_mp3_and_extensionless_downloads_retained(self):
        for filename in ("voice.wav", "voice"):
            result = await self.send(f"{self.origin}/{filename}")
            path = self.downloads[-1]
            self.assertIn(f"原声音文件在沙盒中的路径是：{path}", result)
            self.assertEqual(path.read_bytes(), AUDIO)
        self.sender.assert_not_awaited()

    async def test_failed_downloads_remove_partial_files(self):
        pattern = f"hatsume-voice-{self.runtime.group_id}-*"
        before = set(Path("/tmp").glob(pattern))
        for filename in ("missing.mp3", "interrupted.mp3"):
            self.assertIn("声音发送失败", await self.send(f"{self.origin}/{filename}"))
        self.assertEqual(before, set(Path("/tmp").glob(pattern)))
        self.sender.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
