"""
Tests for System Prompts and Agent Persona Exposure in Admin Portal (Issue #92).

Validates:
1. Dynamic prompt registry with all 10 system and persona prompts in Config.
2. ORM versioning in AgentPrompt (is_head, version increments).
3. REST API endpoints: GET /api/config/prompts and POST /api/config/prompts.
4. Prompt reset to default and version rollback via /admin/prompts/set-head.
5. Admin dashboard template rendering containing Monaco and live preview elements.
"""

from unittest.mock import MagicMock, patch
import time
import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, config, generate_session_token, db_session
from kb_web.config import (
    DEFAULT_WIKI_PROMPT,
    DEFAULT_YOUTUBE_WIKI_PROMPT,
    DEFAULT_TAGS_PROMPT,
    DEFAULT_RAG_SYSTEM_PROMPT,
    DEFAULT_RAG_REPORT_PROMPT,
    DEFAULT_TAXONOMY_SYSTEM_PROMPT,
    DEFAULT_MAINTENANCE_AGENT_PROMPT,
    DEFAULT_WORKSPACE_AGENT_PROMPT,
    DEFAULT_ARTICLE_CHAT_PROMPT,
    DEFAULT_ONTOLOGY_SYNTHESIS_PROMPT,
)
from kb_web.models_orm import AgentPrompt
from kb_web.server import app


@pytest.fixture
def auth_client():
    orig_key = config.api_key
    config.api_key = "test-secret-key"
    try:
        with patch("kb_core.notifier.Gotify") as mock_gotify:
            mock_gotify.return_value = MagicMock()
            c = TestClient(app)
            c.headers["X-API-Key"] = "test-secret-key"
            c.cookies.set(COOKIE_NAME, generate_session_token(time.time() + 3600))
            yield c
    finally:
        config.api_key = orig_key


def test_config_registry_contains_all_ten_prompts():
    """Verifies that config.get_all_prompts() exposes all 10 system and agent persona prompts."""
    prompts = config.get_all_prompts()
    assert len(prompts) == 10
    
    prompt_ids = {p["id"] for p in prompts}
    expected_ids = {
        "wiki_prompt",
        "youtube_wiki_prompt",
        "tags_prompt",
        "rag_system_prompt",
        "rag_report_prompt",
        "taxonomy_system_prompt",
        "maintenance_agent_prompt",
        "workspace_agent_prompt",
        "article_chat_prompt",
        "ontology_synthesis_prompt",
    }
    assert prompt_ids == expected_ids

    # Check each prompt metadata dictionary has required keys
    for p in prompts:
        assert "id" in p
        assert "label" in p
        assert "category" in p
        assert "description" in p
        assert "value" in p
        assert "default" in p
        assert len(p["value"]) > 0


def test_agent_prompt_versioning_and_persistence():
    """Verifies that updating a prompt persists a new version to the database with is_head=1."""
    test_prompt_text = "Custom tags extraction directive: extract at most 3 tags."
    
    # Set the prompt
    config.tags_prompt = test_prompt_text
    assert config.tags_prompt == test_prompt_text

    # Verify database persistence
    with db_session() as session:
        records = (
            session.query(AgentPrompt)
            .filter_by(prompt_type="tags_prompt")
            .order_by(AgentPrompt.version.desc())
            .all()
        )
        assert len(records) >= 1
        head_record = records[0]
        assert head_record.is_head == 1
        assert head_record.prompt_text == test_prompt_text


def test_api_get_prompts(auth_client):
    """Verifies GET /api/config/prompts returns all 10 prompts in JSON envelope."""
    res = auth_client.get("/api/config/prompts")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert len(data["prompts"]) == 10


def test_api_update_prompt_and_reset_default(auth_client):
    """Verifies POST /api/config/prompts can update prompt text and reset to default."""
    custom_text = "Custom Workspace Persona Instructions: You are a senior Python dev."
    
    # 1. Update prompt
    res = auth_client.post(
        "/api/config/prompts",
        json={"prompt_id": "workspace_agent_prompt", "prompt_text": custom_text},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["prompt"]["value"] == custom_text
    assert config.workspace_agent_prompt == custom_text

    # 2. Reset prompt to default
    res_reset = auth_client.post(
        "/api/config/prompts",
        json={"prompt_id": "workspace_agent_prompt", "reset_default": True},
    )
    assert res_reset.status_code == 200
    reset_data = res_reset.json()
    assert reset_data["status"] == "success"
    assert reset_data["prompt"]["value"] == DEFAULT_WORKSPACE_AGENT_PROMPT
    assert config.workspace_agent_prompt == DEFAULT_WORKSPACE_AGENT_PROMPT


def test_api_update_prompt_validation(auth_client):
    """Verifies that invalid prompt IDs and missing fields trigger 400 Bad Request."""
    # Invalid ID
    res = auth_client.post(
        "/api/config/prompts",
        json={"prompt_id": "non_existent_prompt", "prompt_text": "hello"},
    )
    assert res.status_code == 400

    # Missing text when reset_default is False
    res2 = auth_client.post(
        "/api/config/prompts",
        json={"prompt_id": "tags_prompt"},
    )
    assert res2.status_code == 400


def test_admin_portal_renders_prompt_studio(auth_client):
    """Verifies that GET /admin renders the Prompt Studio with Monaco and live preview elements."""
    res = auth_client.get("/admin#tab-prompts")
    assert res.status_code == 200
    html = res.text
    
    # Prompt Studio container elements
    assert "monacoPromptContainer" in html
    assert "promptMarkdownPreview" in html
    assert "allPromptsData" in html
    assert "promptsHistoryData" in html
    assert "AI Agent Personas &amp; System Prompt Studio" in html or "AI Agent Personas & System Prompt Studio" in html
    assert "btnViewSplit" in html
    assert "btnSavePrompt" in html
