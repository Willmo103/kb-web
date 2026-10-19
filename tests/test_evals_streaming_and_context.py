"""
Unit tests for Real-Time SSE Matrix Streaming, Dynamic Model Context Discovery,
Ollama Thinking Token Buffering, and Content Security Policy whitelisting.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import COOKIE_NAME, LoggedOllamaClient, generate_session_token
from kb_web.routers.evals import (
    MatrixRunRequest,
    get_model_context_info,
)


@pytest.fixture
def auth_client():
    client = TestClient(app)
    token = generate_session_token(expiry_time=9999999999.0)
    client.cookies.set(COOKIE_NAME, token)
    return client


def test_matrix_request_uncapped_tokens_validation():
    """Verify that MatrixRunRequest accepts context tokens above 16384 (e.g. 32768, 131072)."""
    # 32,768 tokens (the request that previously failed with 422)
    req = MatrixRunRequest(
        models=["gemma4:e4b"],
        prompts=[{"id": "test", "name": "Test", "text": "Test prompt"}],
        input_text="Sample input",
        max_tokens=32768,
        temperature=0.2,
    )
    assert req.max_tokens == 32768

    # High context model limit (131,072)
    req_high = MatrixRunRequest(
        models=["granite4.2:8b"],
        prompts=[{"id": "test", "name": "Test", "text": "Test prompt"}],
        input_text="Sample input",
        max_tokens=131072,
        temperature=0.2,
    )
    assert req_high.max_tokens == 131072


def test_get_model_context_info_runtime_ps():
    """Verify that get_model_context_info discovers runtime loaded context from ps()."""
    mock_cli = MagicMock()
    # Mock ps response
    mock_model = MagicMock()
    mock_model.name = "granite4.2:8b"
    mock_model.context_length = 32768
    mock_model.size_vram = 20000000
    mock_cli.ps.return_value = MagicMock(models=[mock_model])

    info = get_model_context_info("granite4.2:8b", mock_cli)
    assert info["context_length"] == 32768
    assert info["loaded"] is True
    assert info["source"] == "runtime_ps"


def test_get_model_context_info_show_fallback():
    """Verify that get_model_context_info extracts context from show() modelinfo."""
    mock_cli = MagicMock()
    # Empty ps
    mock_cli.ps.return_value = MagicMock(models=[])
    # Show response
    mock_show = MagicMock()
    mock_show.modelinfo = {"gemma4.context_length": 131072}
    mock_cli.show.return_value = mock_show

    info = get_model_context_info("gemma4:e4b", mock_cli)
    assert info["context_length"] == 131072
    assert info["loaded"] is False
    assert info["source"] == "modelinfo"


def test_evals_models_info_api(auth_client):
    """Test GET /api/evals/models/info returns structured model context data."""
    mock_cli = MagicMock()
    mock_m1 = MagicMock()
    mock_m1.model = "gemma4:e4b"
    mock_cli.list.return_value = MagicMock(models=[mock_m1])
    mock_cli.ps.return_value = MagicMock(models=[])
    mock_cli.show.return_value = MagicMock(modelinfo={"gemma4.context_length": 131072})

    with patch("kb_web.routers.evals._get_ollama_client", return_value=mock_cli):
        resp = auth_client.get("/api/evals/models/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "gemma4:e4b" in data["models"]
        assert data["models"]["gemma4:e4b"]["context_length"] == 131072


def test_matrix_stream_endpoint(auth_client):
    """Test POST /api/evals/matrix/stream produces SSE chunks with token streaming and thinking."""
    mock_cli = MagicMock()

    # Create mock chunks
    chunk1 = MagicMock()
    chunk1.message = MagicMock(content="", thinking="Thinking about the prompt...")
    chunk1.done = False

    chunk2 = MagicMock()
    chunk2.message = MagicMock(content="# Generated Wiki\n\nContent", thinking="")
    chunk2.done = True
    chunk2.eval_count = 25
    chunk2.eval_duration = 500000000

    mock_cli.chat.return_value = [chunk1, chunk2]
    mock_cli.ps.return_value = MagicMock(models=[])
    mock_cli.show.return_value = MagicMock(modelinfo={"gemma4.context_length": 131072})

    payload = {
        "models": ["gemma4:e4b"],
        "prompts": [{"id": "wiki_prompt", "name": "Wiki Prompt", "text": "Summarize this"}],
        "input_text": "Sample web content markdown",
        "max_tokens": 32768,
        "temperature": 0.2,
    }

    with patch("kb_web.routers.evals._get_ollama_client", return_value=mock_cli):
        resp = auth_client.post("/api/evals/matrix/stream", json=payload)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        body_text = resp.text
        assert "event: start" in body_text
        assert "event: run_start" in body_text
        assert "event: token" in body_text
        assert "event: item" in body_text
        assert "event: done" in body_text
        assert "Thinking about the prompt..." in body_text
        assert "# Generated Wiki" in body_text


def test_csp_header_allows_cloudflare_insights():
    """Verify Content-Security-Policy whitelists static.cloudflareinsights.com (SEC-02)."""
    client = TestClient(app)
    resp = client.get("/login")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "https://static.cloudflareinsights.com" in csp
    assert "https://cloudflareinsights.com" in csp
