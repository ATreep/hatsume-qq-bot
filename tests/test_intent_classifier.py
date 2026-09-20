"""Tests for intent classifier client — fully self-contained (no NoneBot dependency).

Each test imports the client module via importlib.util to bypass parent __init__.py.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure plugin dir is on sys.path
_plugin_dir = Path(__file__).resolve().parent.parent / "hatsume" / "plugins" / "hatsume-plugin"
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))


def _load_client_module():
    """Import intent_classifier.client using importlib.util."""
    client_path = _plugin_dir / "intent_classifier" / "client.py"

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hatsume_plugins_intent_classifier_client", str(client_path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hatsume_plugins_intent_classifier_client"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client_mod():
    return _load_client_module()


# ---------------------------------------------------------------------------
# 1. Normal success
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_normal_success(client_mod):
    """Valid JSON response → correct ClassificationResult."""
    ClassifierClient = client_mod.ClassifierClient

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_resp.text = AsyncMock(
        return_value=json.dumps({
            "tier": "fast",
            "model": "jev-1.13.0",
            "results": [{
                "label": "询价砍价",
                "confidence": 0.95,
                "scores": {"询价砍价": 0.95, "闲聊问候": 0.03,
                           "技术求助": 0.01, "吐槽卖惨": 0.01,
                           "指令请求": 0.0, "其他": 0.0},
                "ms": 120,
                "model": "jev-1.13.0",
            }],
        })
    )

    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = ClassifierClient()
        result = await client.classify("你好，这个多少钱？")

    assert result.label == "询价砍价"
    assert result.confidence == 0.95
    assert "询价砍价" in result.scores


# ---------------------------------------------------------------------------
# 2. Timeout
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeout(client_mod):
    """Connection/read timeout → degraded."""
    ClassifierClient = client_mod.ClassifierClient

    mock_session = MagicMock()
    async def enter_side_effect(*args, **kwargs):
        raise TimeoutError("read timed out")
    mock_session.__aenter__ = AsyncMock(side_effect=enter_side_effect)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = ClassifierClient()
        result = await client.classify("should degrade on timeout")

    assert result.label == client_mod.DEGRADED_LABEL


# ---------------------------------------------------------------------------
# 3. Non-2xx HTTP status
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_non_2xx_status(client_mod):
    """HTTP 429 or any non-2xx → degraded."""
    ClassifierClient = client_mod.ClassifierClient

    for status in [400, 429, 500, 502]:
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)
        mock_resp.text = AsyncMock(return_value=json.dumps({"error": f"http {status}"}))

        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            client = ClassifierClient()
            result = await client.classify(f"text for status {status}")

        assert result.label == client_mod.DEGRADED_LABEL, f"failed on status {status}"


# ---------------------------------------------------------------------------
# 4. Null label (smart-tier escalation)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_null_label(client_mod):
    """label field is null → degraded."""
    ClassifierClient = client_mod.ClassifierClient

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_resp.text = AsyncMock(
        return_value=json.dumps({
            "tier": "smart",
            "results": [{"label": None, "confidence": None, "scores": {}, "ms": 500}],
        })
    )

    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = ClassifierClient()
        result = await client.classify("re-asked by smart tier")

    assert result.label == client_mod.DEGRADED_LABEL


# ---------------------------------------------------------------------------
# 5. Invalid JSON body
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_json_body(client_mod):
    """Response body is not valid JSON → degraded."""
    ClassifierClient = client_mod.ClassifierClient

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    mock_resp.text = AsyncMock(return_value="not-json<<<garbage>>>")

    mock_session = MagicMock()
    mock_session.post.return_value = mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        client = ClassifierClient()
        result = await client.classify("malformed response")

    assert result.label == client_mod.DEGRADED_LABEL


# ---------------------------------------------------------------------------
# Config constants sanity checks
# ---------------------------------------------------------------------------
def test_default_labels_include_other(client_mod):
    assert "其他" in client_mod.DEFAULT_LABELS


def test_degraded_label_is_other(client_mod):
    assert client_mod.DEGRADED_LABEL == "其他"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
