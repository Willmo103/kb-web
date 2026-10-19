"""
Unit tests for Eval Datasets, Ollama d1/SystemOne sanitization, and Admin Agent Configurations.
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import LoggedOllamaClient, config, db_session
from kb_web.models_orm import AgentConfiguration, EvalDataset, FetchedPage
from kb_web.agent_config import (
    ensure_default_agent_configs,
    get_agent_config,
    list_agent_configs,
    save_agent_config,
)


@pytest.fixture(autouse=True)
def init_agent_configs():
    """Ensure test database has default agent configurations seeded."""
    ensure_default_agent_configs()


def test_agent_configurations_defaults():
    """Verify that all default agents are seeded with complete parameter profiles."""
    configs = list_agent_configs()
    assert len(configs) >= 11

    agent_ids = {c["id"] for c in configs}
    assert "maintenance_agent" in agent_ids
    assert "wiki_curation" in agent_ids
    assert "link_crawler" in agent_ids
    assert "rag_eval" in agent_ids

    # Spotlight check: Maintenance & Error Diagnosis Agent
    maint = get_agent_config("maintenance_agent")
    assert maint is not None
    assert maint["category"] in ("diagnostics", "System Maintenance")
    assert maint["call_type"] == "llm"
    assert "get_system_logs" in maint["tools"] or "search_logs" in maint["tools"]
    assert maint["enabled"] is True


def test_save_agent_configuration():
    """Test updating agent parameters in the database."""
    updated = save_agent_config("maintenance_agent", {
        "model": "gemma4:e4b",
        "temperature": 0.15,
        "thinking": True,
        "num_predict": 4096,
    })
    assert updated is not None
    assert updated["model"] == "gemma4:e4b"
    assert updated["temperature"] == 0.15
    assert updated["thinking"] is True
    assert updated["num_predict"] == 4096

    # Verify persistence
    fetched = get_agent_config("maintenance_agent")
    assert fetched["model"] == "gemma4:e4b"
    assert fetched["temperature"] == 0.15


def test_logged_ollama_client_systemone_sanitization():
    """Test that LoggedOllamaClient.systemone strips options and normalizes questions."""
    mock_raw_client = MagicMock()
    mock_raw_client.systemone.return_value = {
        "answers": {
            "relevance": {"type": "noul", "noul": 0.95}
        }
    }

    client = LoggedOllamaClient(host="http://localhost:11434")
    client._client = mock_raw_client
    
    # Intentionally pass options and question criteria
    resp = client.systemone(
        model="d1",
        state={"url": "https://example.com"},
        questions={
            "relevance": {
                "question": "Is this article relevant?",
                "type": "probability",
                "criteria": {"true": "Relevant", "false": "Irrelevant"}
            }
        },
        options={"temperature": 0.2, "num_ctx": 16384},  # Must be stripped!
    )

    assert "relevance" in resp["answers"]
    # Check that options was NOT passed to raw_client.systemone
    call_kwargs = mock_raw_client.systemone.call_args[1]
    assert "options" not in call_kwargs
    assert call_kwargs["model"] == "d1"
    assert "relevance" in call_kwargs["questions"]
    q = call_kwargs["questions"]["relevance"]
    assert q["type"] == "noul"
    assert "instructions" in q


def test_eval_dataset_min_20_rows_validation():
    """Verify that eval datasets strictly reject saving when less than 20 rows match."""
    from kb_web.routers.evals import create_eval_dataset, CreateDatasetRequest, DatasetFilter
    from fastapi import HTTPException

    mock_request = MagicMock()
    mock_request.cookies = {"kb_session": "valid_token"}

    # Seed 5 sample pages (less than 20)
    with db_session() as session:
        # Clear existing test pages and test datasets for strict count
        session.query(EvalDataset).filter_by(name="Test Small Dataset").delete()
        session.query(FetchedPage).filter(FetchedPage.url.like("https://test-eval-%")).delete()
        for i in range(5):
            p = FetchedPage(
                url=f"https://test-eval-{i}.com",
                title=f"Test Article {i}",
                md_content=f"Content {i}",
                tags="test-tag",
            )
            session.add(p)
        session.commit()

    try:
        with patch("kb_web.routers.evals.verify_session_token", return_value=True):
            # Attempt to save dataset targeting test-tag (only 5 rows)
            req = CreateDatasetRequest(
                name="Test Small Dataset",
                description="Should fail validation",
                base_table="fetched_pages",
                selected_columns=["fetched_pages.url", "fetched_pages.title"],
                filters=[DatasetFilter(column="fetched_pages.url", operator="contains", value="https://test-eval-")],
                joins=[],
            )

            with pytest.raises(HTTPException) as exc_info:
                create_eval_dataset(req, mock_request)
            
            assert exc_info.value.status_code == 400
            assert "at least 20 rows" in exc_info.value.detail

            # Now seed 20 pages so total reaches 25
            with db_session() as session:
                for i in range(5, 25):
                    p = FetchedPage(
                        url=f"https://test-eval-{i}.com",
                        title=f"Test Article {i}",
                        md_content=f"Content {i}",
                        tags="test-tag",
                    )
                    session.add(p)
                session.commit()

            # Should now succeed!
            res = create_eval_dataset(req, mock_request)
            assert res["status"] == "success"
            assert res["dataset"]["row_count"] >= 20
    finally:
        with db_session() as session:
            session.query(EvalDataset).filter_by(name="Test Small Dataset").delete()
            session.query(FetchedPage).filter(FetchedPage.url.like("https://test-eval-%")).delete()
            session.commit()
