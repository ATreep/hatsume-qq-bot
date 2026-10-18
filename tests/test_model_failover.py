"""Failover chains: config validation, commands, and real SDK requests locally."""

import asyncio
import importlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from model_provider_support import PACKAGE, commands, config

factory = importlib.import_module(f"{PACKAGE}.model_factory")


@pytest.fixture
def endpoint():
    """/good answers, /bad returns HTTP 400, /slow answers after 3 seconds."""
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, body))
            if self.path.startswith("/slow"):
                time.sleep(3)
            if self.path.startswith("/bad"):
                status, reply = 400, {"error": {"message": "bad", "type": "x"}}
            elif self.path.endswith("/embeddings"):
                status, reply = 200, {
                    "object": "list",
                    "model": body["model"],
                    "data": [
                        {"object": "embedding", "index": i, "embedding": [0.5, 0.5]}
                        for i in range(len(body["input"]))
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            else:
                status, reply = 200, {
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
            data = json.dumps(reply).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass  # The client gave up after its timeout.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _store(tmp_path, base="https://example.test", apis=("openai_chat_completions",)):
    store = config.ModelConfigStore(tmp_path)
    for name in ("bad", "slow", "good"):
        store.save_provider(
            name,
            base_url=f"{base}/{name}/v1",
            supported_apis=list(apis),
            api_key=f"{name}-key",
            create=True,
        )
    return store


def test_fallbacks_survive_primary_switch_and_block_provider_removal(tmp_path):
    store = _store(tmp_path)
    store.use_model("advance", "bad", "first")
    store.add_fallback("advance", "good", "backup")
    store.set_option("advance", "temperature", 0.3, fallback=1)
    store.set_timeout("advance", 12)
    store.use_model("advance", "slow", "second")
    chain = config.ModelConfigStore(tmp_path).resolve_chain("advance")
    assert [(e["provider"], e["model"]) for e in chain] == [
        ("slow", "second"),
        ("good", "backup"),
    ]
    assert chain[0]["timeout"] == 12 and chain[0]["options"] == {}
    assert chain[1]["options"] == {"temperature": 0.3}
    assert "fallbacks" not in store.resolve("advance")
    with pytest.raises(config.ModelConfigError, match="advance"):
        store.remove_provider("good")
    store.remove_fallback("advance", 1)
    assert "fallbacks" not in yaml.safe_load(store.models_path.read_text())["roles"]["advance"]
    store.remove_provider("good")


@pytest.mark.parametrize(
    "operation",
    [
        lambda s: s.set_timeout("advance", 0),
        lambda s: s.set_timeout("advance", True),
        lambda s: s.set_timeout("advance", 5, fallback=2),
        lambda s: s.add_fallback("embedding", "good", "x"),
        lambda s: s.remove_fallback("advance", 0),
    ],
)
def test_invalid_fallback_mutations_preserve_files(tmp_path, operation):
    store = _store(tmp_path)
    store.use_model("advance", "bad", "first")
    store.add_fallback("advance", "good", "backup")
    before = store.models_path.read_bytes()
    with pytest.raises(config.ModelConfigError):
        operation(store)
    assert store.models_path.read_bytes() == before


def test_hand_written_nested_fallbacks_are_rejected(tmp_path):
    store = _store(tmp_path)
    entry = {"provider": "good", "api": "openai_chat_completions", "model": "m", "options": {}}
    store.models_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "roles": {"lite": entry | {"fallbacks": [entry | {"fallbacks": []}]}},
            }
        )
    )
    with pytest.raises(config.ModelConfigError, match="fallback 1"):
        store.snapshot()


@pytest.mark.asyncio
async def test_commands_manage_chain(tmp_path):
    store = _store(tmp_path)
    await commands.model_command(store, "use lite bad first")
    await commands.model_command(store, "fallback add lite good backup")
    await commands.model_command(store, "timeout lite 20")
    await commands.model_command(store, "timeout lite 5 --fallback 1")
    result = await commands.model_command(
        store, "options lite max_tokens 64 --fallback 1"
    )
    assert "备用 1: good / backup" in result and "超时 5s" in result
    assert "good-key" not in result
    chain = store.resolve_chain("lite")
    assert chain[0]["timeout"] == 20
    assert (chain[1]["timeout"], chain[1]["options"]) == (5, {"max_tokens": 64})
    await commands.model_command(store, "timeout lite null")
    await commands.model_command(store, "fallback remove lite 1")
    assert len(store.resolve_chain("lite")) == 1 and "timeout" not in store.resolve("lite")


def test_single_entry_role_keeps_plain_sdk_model(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(config, "_store", store)
    store.use_model("lite", "good", "only")
    assert type(factory.get_model("lite")).__name__ == "ChatOpenAI"


def test_error_and_timeout_fall_through_to_next_provider(tmp_path, endpoint, monkeypatch):
    base, captured = endpoint
    store = _store(tmp_path, base)
    monkeypatch.setattr(config, "_store", store)
    store.use_model("advance", "bad", "first")
    store.add_fallback("advance", "slow", "second")
    store.set_timeout("advance", 0.5, fallback=1)
    store.add_fallback("advance", "good", "third")
    model = factory.get_model("advance")
    started = time.monotonic()
    result = asyncio.run(model.ainvoke("Say probe-ok"))
    assert "probe-ok" in str(result.content)
    assert time.monotonic() - started < 2.5
    assert [path.split("/")[1] for path, _ in captured] == ["bad", "slow", "good"]
    assert captured[-1][1]["model"] == "third"


def test_invocations_and_fallbacks_are_logged(tmp_path, endpoint, monkeypatch, capsys):
    base, _ = endpoint
    store = _store(tmp_path, base)
    monkeypatch.setattr(config, "_store", store)
    store.use_model("lite", "bad", "first")
    store.add_fallback("lite", "good", "backup")
    asyncio.run(factory.get_model("lite").ainvoke("hi"))
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "[llm] invoke lite: bad / first (1 messages)"
    assert lines[1].startswith("[llm] error lite: bad / first after ") and "(HTTP 400)" in lines[1]
    assert lines[2] == (
        "[failover] chat model lite: bad / first failed (HTTP 400); "
        "falling back to lite: good / backup (1/1)."
    )
    assert lines[3] == "[llm] invoke lite: good / backup (1 messages)"
    assert lines[4].startswith("[llm] done lite: good / backup in ")
    assert lines[5] == "[failover] chat model recovered with lite: good / backup."
    assert not any("key" in line for line in lines)

    store.use_model("mini", "good", "only")
    factory.get_model("mini").invoke("hi")
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(" in ")[0] for line in lines] == [
        "[llm] invoke mini: good / only (1 messages)",
        "[llm] done mini: good / only",
    ]


def test_last_error_is_raised_when_every_provider_fails(tmp_path, endpoint, monkeypatch):
    base, _ = endpoint
    store = _store(tmp_path, base)
    monkeypatch.setattr(config, "_store", store)
    store.use_model("mini", "bad", "first")
    store.add_fallback("mini", "bad", "second")
    with pytest.raises(Exception) as error:
        asyncio.run(factory.get_model("mini").ainvoke("hi"))
    assert getattr(error.value, "status_code", None) == 400


def test_bound_tools_and_create_agent_use_fallback(tmp_path, endpoint, monkeypatch):
    from langchain.agents import create_agent

    @tool
    def ping(text: str) -> str:
        """Echo text."""
        return text

    base, captured = endpoint
    store = _store(tmp_path, base)
    monkeypatch.setattr(config, "_store", store)
    store.use_model("coding", "bad", "first")
    store.add_fallback("coding", "good", "backup")
    agent = create_agent(factory.get_model("coding"), tools=[ping])
    result = asyncio.run(agent.ainvoke({"messages": [("user", "hello")]}))
    assert isinstance(result["messages"][-1], AIMessage)
    assert "probe-ok" in str(result["messages"][-1].content)
    assert captured[-1][1]["tools"][0]["function"]["name"] == "ping"
    # Synchronous invocation fails over as well.
    assert "probe-ok" in str(factory.get_model("coding").invoke("hi").content)


def test_embedding_failover(tmp_path, endpoint, monkeypatch):
    base, captured = endpoint
    store = _store(tmp_path, base, apis=("openai_embeddings",))
    monkeypatch.setattr(config, "_store", store)
    store.use_model("embedding", "bad", "emb")
    store.add_fallback("embedding", "good", "emb")
    model = factory.get_embedding_model()
    assert model.embed_query("hello") == [0.5, 0.5]
    assert asyncio.run(model.aembed_documents(["a", "b"])) == [[0.5, 0.5]] * 2
    assert captured[-1][0] == "/good/v1/embeddings"
