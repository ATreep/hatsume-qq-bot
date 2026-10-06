"""HTTP image/video URLs are downloaded before OneBot message creation."""

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
from unittest.mock import AsyncMock
from urllib.parse import unquote, urlparse

import requests
from langchain_core.tools import tool
from nonebot.adapters.onebot.v11 import MessageSegment


SOURCE = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin/graph/tools.py"
TREE = ast.parse(SOURCE.read_text())
NAMES = {"_download_http_media_to_tmp", "send_image", "send_video"}
CODE = compile(
    ast.Module(
        body=[node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES],
        type_ignores=[],
    ),
    str(SOURCE),
    "exec",
)
MEDIA = b"fixture-media-data"


class MediaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(MEDIA)

    def log_message(self, *_args):
        pass


class SendHttpMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MediaHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.downloads = []
        self.sender = AsyncMock()
        self.runtime = SimpleNamespace(
            group_id=23456,
            send_image_count=0,
            send_video_count=0,
            conversation=SimpleNamespace(ai_answer=self.sender),
        )
        self.ready = AsyncMock()
        namespace = {
            "asyncio": asyncio,
            "base64": base64,
            "uuid": uuid,
            "Path": Path,
            "unquote": unquote,
            "urlparse": urlparse,
            "requests": requests,
            "traceback": __import__("traceback"),
            "_langchain_tool": tool,
            "MessageSegment": MessageSegment,
            "get_current_group_runtime": lambda: self.runtime,
            "ensure_container_running": self.ready,
        }
        exec(CODE, namespace)
        self.namespace = namespace
        download = namespace["_download_http_media_to_tmp"]

        def track_download(*args, **kwargs):
            path = download(*args, **kwargs)
            self.downloads.append(path)
            return path

        namespace["_download_http_media_to_tmp"] = track_download
        self.addCleanup(self.remove_downloads)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def remove_downloads(self):
        for path in self.downloads:
            path.unlink(missing_ok=True)

    async def test_image_http_url_downloads_then_sends_base64(self):
        origin = f"http://127.0.0.1:{self.server.server_port}/picture.png"
        result = await self.namespace["send_image"].ainvoke({"image_url": origin})
        self.assertIn("成功", result)
        path = self.downloads[0]
        self.assertEqual(path.parent, Path("/tmp"))
        self.assertFalse(path.exists(), "temporary download is removed after send")
        segment = self.sender.await_args.args[0]
        self.assertEqual(segment.type, "image")
        self.assertTrue(segment.data["file"].startswith("base64://"))
        self.assertEqual(base64.b64decode(segment.data["file"][9:]), MEDIA)

    async def test_video_http_url_downloads_then_sends_base64(self):
        origin = f"http://127.0.0.1:{self.server.server_port}/clip.mp4"
        result = await self.namespace["send_video"].ainvoke({"video_url": origin})
        self.assertIn("成功", result)
        path = self.downloads[0]
        self.assertEqual(path.parent, Path("/tmp"))
        self.assertFalse(path.exists(), "temporary download is removed after send")
        segment = self.sender.await_args.args[0]
        self.assertEqual(segment.type, "video")
        self.assertTrue(segment.data["file"].startswith("base64://"))
        self.assertEqual(base64.b64decode(segment.data["file"][9:]), MEDIA)


if __name__ == "__main__":
    unittest.main()
