"""
Unit tests for Evals Studio model classification, per-model generation options,
free-form prompt testing, and prompt promotion endpoints.
"""

import time
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient

from kb_web.server import app, config
from kb_web.base import COOKIE_NAME, generate_session_token
from kb_web.routers.evals import classify_model_type


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def test_classify_model_type():
    """Verify strict classification of Ollama models into llm, decision, and embedding categories."""
    # LLMs
    assert classify_model_type("qwen2.5:7b") == "llm"
    assert classify_model_type("llama3.2:3b") == "llm"
    assert classify_model_type("mistral:7b-instruct") == "llm"
    assert classify_model_type("gemma2:9b") == "llm"

    # Decision models
    assert classify_model_type("d1") == "decision"
    assert classify_model_type("d1:latest") == "decision"
    assert classify_model_type("tev1") == "decision"
    assert classify_model_type("tev1:14b") == "decision"
    assert classify_model_type("systemone-gating") == "decision"

    # Embedding models
    assert classify_model_type("embeddinggemma") == "embedding"
    assert classify_model_type("nomic-embed-text") == "embedding"
    assert classify_model_type("bge-m3:latest") == "embedding"
    assert classify_model_type("all-minilm") == "embedding"


@patch("kb_web.routers.evals._get_ollama_client")
def test_evals_studio_page_categorized_models(mock_get_client, client: TestClient):
    """GET /evals renders with separate lists for llm_models, decision_models, and embedding_models."""
    mock_cli = MagicMock()
    mock_cli.list.return_value = {
        "models": [
            {"model": "qwen2.5:7b"},
            {"model": "d1"},
            {"model": "tev1"},
            {"model": "embeddinggemma"},
            {"model": "nomic-embed-text"},
        ]
    }
    mock_get_client.return_value = mock_cli

    resp = client.get("/evals")
    assert resp.status_code == 200
    assert "Per-Model Parameter Overrides" in resp.text
    assert "Add Empty Prompt" in resp.text
    assert "Set As... ▾" in resp.text


def test_promote_prompt_to_system_instruction(client: TestClient):
    """POST /api/evals/prompts/promote updates server system prompt in configuration."""
    original_wiki = config.wiki_prompt
    test_prompt_text = "TEST PROMPT: You are a hyper-concise technical synthesizer."

    try:
        resp = client.post(
            "/api/evals/prompts/promote",
            json={
                "target_type": "system_prompt",
                "target_id": "wiki_prompt",
                "prompt_text": test_prompt_text,
                "prompt_name": "Test Synthesizer",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "success"
        assert config.wiki_prompt == test_prompt_text

        # Invalid target rejected
        bad_resp = client.post(
            "/api/evals/prompts/promote",
            json={
                "target_type": "system_prompt",
                "target_id": "nonexistent_prompt_id",
                "prompt_text": "text",
            },
        )
        assert bad_resp.status_code == 400
    finally:
        config.wiki_prompt = original_wiki
        config.save()


@patch("kb_web.routers.evals._get_ollama_client")
def test_matrix_run_with_model_options(mock_get_client, client: TestClient):
    """POST /api/evals/matrix/run passes model_options to Ollama client."""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_resp = MagicMock()
    mock_resp.message.content = "Evaluated response"
    mock_resp.eval_count = 50
    mock_resp.eval_duration = 1000000000
    mock_client.chat.return_value = mock_resp

    payload = {
        "models": ["qwen2.5:7b"],
        "prompts": [{"id": "p1", "name": "Prompt 1", "text": "Synthesize this."}],
        "input_text": "Sample input text to evaluate",
        "temperature": 0.2,
        "max_tokens": 1024,
        "model_options": {
            "qwen2.5:7b": {
                "temperature": 0.05,
                "top_p": 0.85,
                "top_k": 30,
                "num_predict": 512,
            }
        },
    }

    resp = client.post("/api/evals/matrix/run", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["response"] == "Evaluated response"

    # Verify options passed to chat
    _, kwargs = mock_client.chat.call_args
    passed_options = kwargs.get("options", {})
    assert passed_options.get("temperature") == 0.05
    assert passed_options.get("top_p") == 0.85
    assert passed_options.get("top_k") == 30
    assert passed_options.get("num_predict") == 512
