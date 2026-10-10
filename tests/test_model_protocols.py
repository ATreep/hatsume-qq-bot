"""Real SDK requests against a local HTTP server, without paid provider calls."""

import asyncio
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from model_provider_support import PACKAGE, commands, config

factory = importlib.import_module(f"{PACKAGE}.model_factory")


@pytest.fixture
def endpoint():
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, body, dict(self.headers)))
            if self.path.endswith("/chat/completions"):
                reply = {
                    "id": "chat-probe",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "probe-ok"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            elif self.path.endswith("/responses"):
                reply = {
                    "id": "resp_probe",
                    "object": "response",
                    "created_at": 1,
                    "model": body["model"],
                    "status": "completed",
                    "output": [
                        {
                            "id": "msg_probe",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "probe-ok",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                }
            elif self.path.endswith(("/images/generations", "/images/edits")):
                reply = {"data": [{"url": "https://example.test/result.png"}]}
            elif self.path.endswith("/embeddings"):
                reply = {
                    "object": "list",
                    "model": body["model"],
                    "data": [
                        {
                            "object": "embedding",
                            "index": i,
                            "embedding": [0.1, 0.2, 0.3],
                        }
                        for i in range(len(body["input"]))
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            else:
                reply = {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "probe-ok"}],
                            },
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 1,
                        "candidatesTokenCount": 1,
                        "totalTokenCount": 2,
                    },
                    "modelVersion": "gemini-probe",
                }
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    "images,endpoint_name",
    [([], "generations"), (["https://example.test/source.png"], "edits")],
)
def test_retained_sensenova_image_api(
    tmp_path, endpoint, monkeypatch, images, endpoint_name
):
    models = importlib.import_module(f"{PACKAGE}.models")
    runtime = importlib.import_module(f"{PACKAGE}.group_runtime")
    base, captured = endpoint
    store = config.ModelConfigStore(tmp_path)
    monkeypatch.setattr(config, "_store", store)
    store.save_provider(
        "probe",
        base_url=base + "/v1",
        supported_apis=["sensenova_images"],
        api_key="fake-local-key",
        create=True,
    )
    store.use_model("image_sensenova", "probe", "sensenova-probe")
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=123)):
        result = asyncio.run(
            models.generate_image_for_sensenova("Draw a flower", images)
        )
    assert result == "https://example.test/result.png"
    path, payload, headers = captured[0]
    assert path == f"/v1/images/{endpoint_name}"
    assert headers["Authorization"] == "Bearer fake-local-key"
    assert payload["model"] == "sensenova-probe"
    if images:
        assert payload["images"] == [{"image_url": images[0]}]
    else:
        assert "images" not in payload


@pytest.mark.parametrize(
    "api,model,option",
    [
        ("openai_chat_completions", "chat-probe", ("reasoning_effort", "low")),
        ("openai_responses", "response-probe", ("reasoning_effort", "high")),
        ("google_genai", "gemini-probe", ("thinking_level", "low")),
    ],
)
def test_command_to_yaml_to_real_sdk_request(
    tmp_path, endpoint, monkeypatch, api, model, option
):
    base, captured = endpoint
    store = config.ModelConfigStore(tmp_path)
    monkeypatch.setattr(config, "_store", store)
    url = base + ("/custom/v3" if api.startswith("openai") else "")
    commands.provider_command(store, f"add probe --base-url {url} --api {api}")
    store.save_provider("probe", api_key="fake-local-key")
    asyncio.run(commands.model_command(store, f"use advance probe {model}"))
    asyncio.run(
        commands.model_command(store, f"options advance {option[0]} {option[1]}")
    )
    result = asyncio.run(factory.get_model("advance").ainvoke("Say probe-ok"))
    assert "probe-ok" in str(result.content)
    path, payload, headers = captured[0]
    if api == "openai_chat_completions":
        assert path == "/custom/v3/chat/completions"
        assert payload["reasoning_effort"] == "low"
        assert payload["messages"][0]["content"] == "Say probe-ok"
    elif api == "openai_responses":
        assert path == "/custom/v3/responses"
        assert payload["reasoning"]["effort"] == "high"
        assert "previous_response_id" not in payload
    else:
        assert path == "/v1beta/models/gemini-probe:generateContent"
        thinking = payload["generationConfig"]["thinkingConfig"]
        assert (
            thinking.get("thinkingLevel", thinking.get("thinking_level", "")).lower()
            == "low"
        )
        assert payload["contents"][0]["parts"][0]["text"] == "Say probe-ok"
    if api.startswith("openai"):
        assert headers["Authorization"] == "Bearer fake-local-key"
    assert config.ModelConfigStore(tmp_path).resolve("advance")["api"] == api


def test_existing_model_keeps_snapshot_new_invocation_uses_switch(
    tmp_path, endpoint, monkeypatch
):
    base, captured = endpoint
    store = config.ModelConfigStore(tmp_path)
    monkeypatch.setattr(config, "_store", store)
    store.save_provider(
        "probe",
        base_url=base + "/v1",
        supported_apis=["openai_responses", "openai_chat_completions"],
        api_key="fake-local-key",
        create=True,
    )
    store.use_model("advance", "probe", "before-switch", "openai_responses")
    original = factory.get_model("advance")
    store.use_model("advance", "probe", "after-switch", "openai_chat_completions")
    asyncio.run(original.ainvoke("First"))
    asyncio.run(
        factory.get_model("advance").ainvoke(
            [HumanMessage("First"), AIMessage("Earlier answer"), HumanMessage("Next")]
        )
    )
    assert (
        captured[0][0] == "/v1/responses" and captured[0][1]["model"] == "before-switch"
    )
    assert (
        captured[1][0] == "/v1/chat/completions"
        and captured[1][1]["model"] == "after-switch"
    )
    assert len(captured[1][1]["messages"]) == 3


def test_embedding_role_uses_saved_connection_and_model(tmp_path, endpoint):
    base, captured = endpoint
    store = config.ModelConfigStore(tmp_path)
    store.save_provider(
        "probe",
        base_url=base + "/v1",
        supported_apis=["openai_embeddings"],
        api_key="fake-local-key",
        create=True,
    )
    store.use_model("embedding", "probe", "text-embedding-3-small")
    store.set_option("embedding", "dimensions", 3)
    model = factory.create_embedding_model(store.resolve("embedding"))
    assert model.embed_query("hello") == [0.1, 0.2, 0.3]
    assert captured[0][0] == "/v1/embeddings"
    assert captured[0][1]["model"] == "text-embedding-3-small"
    assert captured[0][1]["dimensions"] == 3


def test_check_command_reports_failure_without_echoing_sdk_error(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace

    store = config.ModelConfigStore(tmp_path)
    store.save_provider(
        "probe",
        base_url="https://example.test/v1",
        supported_apis=["openai_responses"],
        api_key="hidden-secret",
        create=True,
    )
    store.use_model("advance", "probe", "a-model")
    monkeypatch.setattr(
        factory,
        "create_chat_model",
        lambda _: SimpleNamespace(
            ainvoke=AsyncMock(
                side_effect=RuntimeError("request contained hidden-secret")
            )
        ),
    )
    result = asyncio.run(commands.model_command(store, "check advance"))
    assert "RuntimeError" in result and "hidden-secret" not in result
