"""
Unit tests for Model Evaluation Studio (/evals), Raw Reporting Export, and Worker Cleanup in kb-web.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.base import generate_session_token, COOKIE_NAME
from kb_web.server import app
from kb_web.worker import autonomous_worker


@pytest.fixture
def auth_client():
    client = TestClient(app)
    token = generate_session_token(expiry_time=9999999999.0)
    client.cookies.set(COOKIE_NAME, token)
    return client


def test_evals_studio_page_requires_auth():
    unauth_client = TestClient(app)
    resp = unauth_client.get("/evals", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_evals_studio_page_authenticated(auth_client):
    resp = auth_client.get("/evals")
    assert resp.status_code == 200
    assert "Model Evaluation Studio" in resp.text
    assert "tabBtnMatrix" in resp.text
    assert "tabBtnDecision" in resp.text
    assert "tabBtnEmbedding" in resp.text


def test_evals_content_fetch_article(auth_client):
    # Fetch content with unknown article
    resp = auth_client.post(
        "/api/evals/content",
        json={"source_type": "article", "identifier": "https://nonexistent.org/test"},
    )
    assert resp.status_code == 404


def test_evals_matrix_run_mock(auth_client):
    mock_resp = MagicMock()
    mock_resp.message.content = "# Synthesized Test Article\n\nClean markdown content."
    mock_resp.eval_count = 120
    mock_resp.eval_duration = 2000000000  # 2.0s -> 60 tok/s

    with patch("kb_web.routers.evals._get_ollama_client") as mock_get_client:
        mock_cli = MagicMock()
        mock_cli.chat.return_value = mock_resp
        mock_get_client.return_value = mock_cli

        resp = auth_client.post(
            "/api/evals/matrix/run",
            json={
                "models": ["gemma4:latest"],
                "prompts": [{"id": "p1", "name": "Test Prompt", "text": "Synthesize this"}],
                "input_text": "Sample input markdown",
                "temperature": 0.2,
                "max_tokens": 1024,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_runs"] == 1
        result = data["results"][0]
        assert result["status"] == "success"
        assert result["model"] == "gemma4:latest"
        assert result["prompt_name"] == "Test Prompt"
        assert "Synthesized Test Article" in result["response"]
        assert result["tokens_per_sec"] == 60.0


def test_evals_decision_run_mock(auth_client):
    mock_ans = MagicMock()
    mock_ans.choice = "deep"
    mock_ans.noul = 0.95
    mock_ans.reasoning = "High technical density"

    mock_resp = MagicMock()
    mock_resp.answers = {"relevance_gate": mock_ans}

    with patch("kb_web.routers.evals._get_ollama_client") as mock_get_client:
        mock_cli = MagicMock()
        mock_cli.systemone.return_value = mock_resp
        mock_get_client.return_value = mock_cli

        resp = auth_client.post(
            "/api/evals/decision/run",
            json={
                "model": "d1",
                "state": {"url": "https://example.com/test"},
                "questions": {"relevance_gate": {"question": "Relevant?", "type": "choice"}},
                "context_window": 16384,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["model"] == "d1"
        assert "relevance_gate" in data["answers"]
        assert data["answers"]["relevance_gate"]["choice"] == "deep"
        assert data["answers"]["relevance_gate"]["noul"] == 0.95


def test_evals_embedding_run_mock(auth_client):
    with patch("kb_web.routers.evals._get_ollama_client") as mock_get_client:
        mock_cli = MagicMock()
        # Mock embeddings to return unit vectors
        mock_cli.embeddings.side_effect = [
            {"embedding": [1.0, 0.0, 0.0]},  # query
            {"embedding": [0.8, 0.6, 0.0]},  # cand 1
            {"embedding": [0.0, 1.0, 0.0]},  # cand 2
        ]
        mock_get_client.return_value = mock_cli

        resp = auth_client.post(
            "/api/evals/embedding/run",
            json={
                "models": ["nomic-embed-text"],
                "query": "vector indexing",
                "candidates": ["first text", "second text"],
                "top_k": 2,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        res = data["results"][0]
        assert res["status"] == "success"
        assert res["model"] == "nomic-embed-text"
        assert res["dimension"] == 3
        assert len(res["candidates"]) == 2
        assert res["candidates"][0]["similarity"] == 0.8


def test_worker_default_jobs_registered():
    """Verify that core jobs (wiki_curation, tag_curation, embedding_refresh) are registered in worker."""
    job_ids = [j["id"] for j in autonomous_worker.get_jobs()]
    assert "wiki_curation" in job_ids
    assert "tag_curation" in job_ids
    assert "embedding_refresh" in job_ids


def test_reports_export_raw_untruncated(auth_client):
    """Verify that report export does not contain truncated heavy column tokens like [Content: 77,805 chars]."""
    resp = auth_client.post(
        "/api/reports/export?format=csv",
        json={"table": "fetched_pages", "columns": ["url", "title", "md_content"]},
    )
    assert resp.status_code == 200
    assert "[Content:" not in resp.text
