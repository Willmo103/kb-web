"""
Tests for:
1. Strict exclusion of decision models (d1, tev1) from generative completion selectors.
2. Dataset fields extraction endpoint for live Jinja syntax highlighting and completion.
3. Matrix evaluation dataset row retrieval with randomized sampling.
4. EvaluationRun database model persistence, listing, and deletion API endpoints.
5. Custom worker agent lifecycle (create, test-run, frozen snapshot publish with version increment, and delete).
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

import time
from kb_web.server import app
from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.models_orm import AgentConfiguration, EvalDataset, EvaluationRun, FetchedPage
from kb_web.agent_config import (
    delete_agent_config,
    ensure_default_agent_configs,
    get_agent_config,
    publish_agent_config,
    save_agent_config,
    test_run_agent_config as run_agent_test,
)
from kb_web.routers.evals import classify_model_type, _fetch_dataset_rows


@pytest.fixture
def auth_client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture(autouse=True)
def setup_defaults():
    ensure_default_agent_configs()


def test_decision_models_strict_classification_and_exclusion(auth_client):
    """Verify that d1, tev1, and decision-containing model names are classified as decision and excluded from LLMs."""
    assert classify_model_type("d1-preview:latest") == "decision"
    assert classify_model_type("tev1:16k") == "decision"
    assert classify_model_type("tev1-flash") == "decision"
    assert classify_model_type("my-decision-gate") == "decision"
    assert classify_model_type("systemone-router") == "decision"
    assert classify_model_type("qwen2.5:7b") == "llm"
    assert classify_model_type("gemma2:9b") == "llm"
    assert classify_model_type("bge-m3:latest") == "embedding"

    with patch("kb_web.routers.evals._get_ollama_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.list.return_value = {
            "models": [
                {"model": "gemma2:9b"},
                {"model": "d1:16k"},
                {"model": "tev1-classifier:latest"},
                {"model": "qwen2.5:7b"},
                {"model": "bge-m3:latest"},
            ]
        }
        mock_get_client.return_value = mock_client

        resp = auth_client.get("/evals")
        assert resp.status_code == 200
        content = resp.text

        # Verify d1 and tev1 are in decision gating models
        assert "d1:16k" in content
        assert "tev1-classifier:latest" in content

        # In matrixModelsList, d1 and tev1 must NOT appear
        matrix_models_slice = content.split('id="matrixModelsList"')[1].split('</div>')[0]
        assert "d1:16k" not in matrix_models_slice
        assert "tev1-classifier" not in matrix_models_slice
        assert "gemma2:9b" in matrix_models_slice
        assert "qwen2.5:7b" in matrix_models_slice


def test_dataset_fields_endpoint(auth_client):
    """Test GET /api/evals/datasets/{id}/fields returns columns for Jinja highlighting."""
    uid = int(time.time() * 1000)
    ds_id = None
    try:
        with db_session() as session:
            ds = EvalDataset(
                name=f"Test Fields Dataset {uid}",
                description="Testing dataset fields extraction",
                base_table="fetched_pages",
                selected_columns=json.dumps(["title", "url", "wiki", "tags", "reading_time_minutes"]),
                query_config=json.dumps({"filters": []}),
                row_count=10,
            )
            session.add(ds)
            session.commit()
            ds_id = ds.id

        resp = auth_client.get(f"/api/evals/datasets/{ds_id}/fields")
        assert resp.status_code == 200
        data = resp.json()
        assert "fields" in data
        assert "title" in data["fields"]
        assert "url" in data["fields"]
        assert "wiki" in data["fields"]
        assert "tags" in data["fields"]
        assert "reading_time_minutes" in data["fields"]
    finally:
        if ds_id:
            with db_session() as session:
                session.query(EvalDataset).filter(EvalDataset.id == ds_id).delete()
                session.commit()


def test_fetch_dataset_rows_randomized_and_sequential():
    """Verify _fetch_dataset_rows retrieves correct row count and supports randomization."""
    uid = int(time.time() * 1000)
    created_urls = [f"https://example.com/test-article-{uid}-{i}" for i in range(15)]
    ds_id = None
    try:
        with db_session() as session:
            # Create test dataset and pages with curated descriptions so AutonomousWorker doesn't touch them
            for i, url in enumerate(created_urls):
                page = FetchedPage(
                    url=url,
                    title=f"Article #{i}",
                    md_content=f"Content for article #{i}",
                    description=f"Curated wiki summary for article #{i}",
                    tags=f"tag-{i}",
                )
                session.add(page)
            session.commit()

            ds = EvalDataset(
                name=f"Sampling Test Dataset {uid}",
                description="Testing randomized row sampling",
                base_table="fetched_pages",
                selected_columns=json.dumps(["title", "url", "md_content", "tags"]),
                query_config=json.dumps({"filters": []}),
                row_count=15,
            )
            session.add(ds)
            session.commit()
            ds_id = ds.id

            # Sequential fetch
            rows_seq = _fetch_dataset_rows(session, ds, limit=5, randomize=False)
            assert len(rows_seq) == 5

            # Randomized fetch
            rows_rand = _fetch_dataset_rows(session, ds, limit=5, randomize=True)
            assert len(rows_rand) == 5
    finally:
        with db_session() as session:
            session.query(FetchedPage).filter(FetchedPage.url.in_(created_urls)).delete(synchronize_session=False)
            if ds_id:
                session.query(EvalDataset).filter(EvalDataset.id == ds_id).delete()
            session.commit()


def test_evaluation_runs_api_lifecycle(auth_client):
    """Test creating, listing, viewing, and deleting EvaluationRun records."""
    with db_session() as session:
        run = EvaluationRun(
            eval_type="matrix",
            title="Benchmark Gemma vs Qwen on Technical Wiki",
            status="completed",
            config_json=json.dumps({
                "models": ["gemma2:9b", "qwen2.5:7b"],
                "dataset_id": 1,
                "sample_limit": 5,
                "template": "{{ data.title }}\n{{ data.wiki }}",
                "randomize": True,
            }),
            results_json=json.dumps([
                {"model": "gemma2:9b", "latency_ms": 1200, "tokens": 450, "output": "Wiki output"},
                {"model": "qwen2.5:7b", "latency_ms": 950, "tokens": 420, "output": "Qwen output"},
            ]),
            metrics_json=json.dumps({"total_latency_ms": 2150, "avg_tok_per_sec": 38.5}),
        )
        session.add(run)
        session.commit()
        run_id = run.id

    # 1. List runs
    resp = auth_client.get("/api/evals/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert any(r["id"] == run_id for r in runs)

    # 2. Get run details
    resp_detail = auth_client.get(f"/api/evals/runs/{run_id}")
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["title"] == "Benchmark Gemma vs Qwen on Technical Wiki"
    assert len(detail["results_json"]) == 2
    assert detail["config_json"]["randomize"] is True

    # 3. Delete run
    resp_del = auth_client.delete(f"/api/evals/runs/{run_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["success"] is True

    # Verify deleted
    resp_check = auth_client.get(f"/api/evals/runs/{run_id}")
    assert resp_check.status_code == 404


def test_custom_worker_agent_lifecycle_and_frozen_snapshot():
    """Test full worker agent lifecycle: create, test run, publish snapshot commit, and delete."""
    agent_id = f"test_custom_crawler_agent_{int(time.time()*1000)}"

    # 1. Create worker agent
    created = save_agent_config(agent_id, {
        "name": "Custom Engineering Crawler",
        "category": "Crawlers & Ingestion",
        "description": "Custom autonomous link collector for systems engineering",
        "call_type": "llm",
        "model": "qwen2.5-coder:7b",
        "system_prompt": "You are a systems crawler agent.",
        "user_prompt_template": "Collect links for: {{ data.sample_input }}",
        "temperature": 0.2,
        "tools": ["search_urls", "fetch_metadata"],
    })
    assert created["id"] == agent_id
    assert created["version"] == 1
    assert created["is_published"] is False
    assert created["frozen_snapshot_json"] is None

    # 2. Test run worker agent
    with patch("kb_web.agent_config._get_ollama_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {"content": "Sample test extraction result."}
        }
        mock_get_client.return_value = mock_client

        test_result = run_agent_test(
            agent_id=agent_id,
            sample_data={"sample_input": "https://example.com/sys-eng-spec"},
        )
        assert test_result["status"] == "success"
        assert "Sample test extraction result." in test_result["output"]

    # 3. Publish frozen snapshot commit
    published = publish_agent_config(agent_id)
    assert published["is_published"] is True
    assert published["version"] == 2
    assert published["published_at"] is not None
    assert published["frozen_snapshot_json"] is not None
    snapshot = json.loads(published["frozen_snapshot_json"]) if isinstance(published["frozen_snapshot_json"], str) else published["frozen_snapshot_json"]
    assert snapshot["model"] == "qwen2.5-coder:7b"
    assert snapshot["version"] == 2

    # 4. Delete worker agent
    deleted = delete_agent_config(agent_id)
    assert deleted is True
    assert get_agent_config(agent_id) is None


def test_systemone_agent_test_run_does_not_use_chat_or_tools():
    """Verify that testing a decision agent invokes client.systemone and never client.chat or tools."""
    agent_id = f"test_systemone_decision_gate_{int(time.time()*1000)}"

    save_agent_config(agent_id, {
        "name": "Link Discovery Decision Gate",
        "category": "Decision Models",
        "description": "SystemOne native probability evaluation for link discovery",
        "call_type": "decision",
        "model": "d1:16k",
        "system_prompt": "",
        "user_prompt_template": json.dumps({"target_url": "{{ data.sample_input }}"}),
        "extra_options": {
            "questions": {
                "relevance": {
                    "instructions": "Is this link a core engineering spec?",
                    "type": "noul",
                    "criteria": {"true": "Core spec", "false": "Off topic"}
                }
            }
        },
    })

    with patch("kb_web.agent_config._get_ollama_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.systemone.return_value = {
            "answers": {
                "relevance": {"type": "noul", "noul": 0.92}
            }
        }
        mock_get_client.return_value = mock_client

        test_result = run_agent_test(
            agent_id=agent_id,
            sample_data={"sample_input": "https://example.com/kernel-spec"},
        )
        assert test_result["status"] == "success"
        assert mock_client.systemone.called
        assert not mock_client.chat.called
        assert "relevance" in test_result["output"]

    delete_agent_config(agent_id)
