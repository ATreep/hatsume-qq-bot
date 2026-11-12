"""OpenAI image role routing, sandbox boundaries, and failure handling."""

import asyncio
import base64
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from model_provider_support import PACKAGE, config

models = importlib.import_module(f"{PACKAGE}.models")
runtime = importlib.import_module(f"{PACKAGE}.group_runtime")
infra = importlib.import_module(f"{PACKAGE}.infra")


@pytest.fixture
def image_store(tmp_path, monkeypatch):
    store = config.ModelConfigStore(tmp_path)
    monkeypatch.setattr(config, "_store", store)
    store.save_provider(
        "probe", base_url="https://example.test/v1", api_key="fake-key",
        supported_apis=["openai_image_gen", "openai_image_edit"], create=True,
    )
    for role in ("image_gen", "image_edit"):
        store.use_model(role, "probe", f"group/{role.replace('_', '-')}")
    return store


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        models.httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("images", [[], ["https://example.test/source.png"]])
def test_base64_output_copied_to_current_sandbox(image_store, monkeypatch, images):
    image_bytes = b"image-response-bytes"
    encoded = base64.b64encode(image_bytes).decode()
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"b64_json": encoded}]}))
    copies = []

    async def copy(source, destination, *, timeout, group_id):
        assert source.read_bytes() == image_bytes
        copies.append((source, destination, timeout, group_id))

    monkeypatch.setattr(infra, "copy_host_file_to_sandbox", copy)
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=123)):
        result = asyncio.run(models.generate_image_for_openai("draw", images))
    source, destination, timeout, group_id = copies[0]
    assert result == f"file://{destination}"
    assert destination.startswith("/tmp/hatsume-generated-")
    assert (timeout, group_id) == (30, 123)
    assert not source.exists()
    assert encoded not in result


def test_base64_copy_failure_cleans_host_file(image_store, monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2U="}]}))
    sources = []

    async def fail_copy(source, *args, **kwargs):
        sources.append(source)
        raise OSError("copy failed")

    monkeypatch.setattr(infra, "copy_host_file_to_sandbox", fail_copy)
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=123)):
        with pytest.raises(OSError, match="copy failed"):
            asyncio.run(models.generate_image_for_openai("draw"))
    assert not sources[0].exists()


@pytest.mark.parametrize("source", ["/tmp/source.png", "file:///tmp/source.png"])
def test_sandbox_edit_input_preserves_group_boundary(image_store, monkeypatch, source):
    import json

    read = AsyncMock(return_value="data:image/png;base64,aW1hZ2U=")
    monkeypatch.setattr(infra, "read_sandbox_image_data_uri", read)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"url": "https://example.test/out.png"}]})

    mock_http(monkeypatch, handler)
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=456)):
        asyncio.run(models.generate_image_for_openai("edit", [source]))
    read.assert_awaited_once_with("/tmp/source.png", group_id=456)
    assert requests[0].url.path == "/v1/images/edits"
    assert json.loads(requests[0].content)["images"] == [{"image_url": read.return_value}]


@pytest.mark.parametrize("data", [[], [{}], [{"url": "file:///bad"}], [{"b64_json": "!invalid!"}], [None]])
def test_invalid_response_is_rejected(image_store, monkeypatch, data):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": data}))
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=123)):
        with pytest.raises(ValueError, match="OpenAI image response"):
            asyncio.run(models.generate_image_for_openai("draw"))


@pytest.mark.parametrize("images,role", [([], "image_gen"), (["https://example.test/in.png"], "image_edit")])
@pytest.mark.parametrize("failure", ["http", "invalid", "timeout"])
def test_image_role_failover(image_store, monkeypatch, images, role, failure):
    image_store.add_fallback(role, "probe", "backup-image")
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(500 if failure == "http" else 200, json={"data": []})
        return httpx.Response(200, json={"data": [{"url": "https://example.test/out.png"}]})

    mock_http(monkeypatch, handler)
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=123)):
        assert asyncio.run(models.generate_image_for_openai("draw", images)) == "https://example.test/out.png"
    import json
    assert [json.loads(r.content)["model"] for r in requests] == [f"group/{role.replace('_', '-')}", "backup-image"]


def test_cancellation_does_not_try_fallback(image_store, monkeypatch):
    image_store.add_fallback("image_gen", "probe", "backup")
    calls = []

    def handler(request):
        calls.append(request)
        raise asyncio.CancelledError

    mock_http(monkeypatch, handler)
    with runtime.bind_group_runtime(runtime.GroupRuntime(group_id=123)):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(models.generate_image_for_openai("draw"))
    assert len(calls) == 1


def test_example_image_roles():
    root = Path(__file__).resolve().parents[1] / "examples/model-config"
    store = config.ModelConfigStore(root)
    for role, api, model in [
        ("image_gen", "openai_image_gen", "group/image-gen"),
        ("image_edit", "openai_image_edit", "group/image-edit"),
    ]:
        settings = store.resolve(role, require_key=False)
        assert (settings["provider"], settings["api"], settings["model"]) == ("magpie", api, model)
