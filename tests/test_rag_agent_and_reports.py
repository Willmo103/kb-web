"""
Unit and integration tests for:
- Tag-searching, vector query-RAG, and text-searching sub-agents
- Multi-candidate deduplication and provenance aggregation
- tev1 decision scoring engine (testing up to 64 questions per turn)
- RAG report compilation and fallback generation
- RAG reports REST API endpoints (/reports/rag, /api/reports/rag/generate, /save-to-notes)
- Retirement of single-article chat and redirect of /conversations
- CLI rag report command
"""

import json
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kb_web.server import app
from kb_web.base import db_session, config
from kb_web.models_orm import (
    FetchedPage,
    Note,
    ChunkEmbedding,
    RagReport,
    CliApiKey,
)
from kb_web.rag_agent import (
    tag_search_subagent,
    vector_rag_subagent,
    text_search_subagent,
    aggregate_candidates,
    tev1_scoring_subagent,
    compile_rag_report,
    run_agentic_rag_pipeline,
)
import sys
from pathlib import Path

cli_src = Path(__file__).resolve().parent.parent / "kb-web-cli" / "src"
if str(cli_src) not in sys.path:
    sys.path.insert(0, str(cli_src))

from kb_web_cli.main import app as cli_app

runner = CliRunner()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client():
    import time
    from kb_web.base import COOKIE_NAME, generate_session_token
    c = TestClient(app)
    token = generate_session_token(time.time() + 3600)
    c.cookies.set(COOKIE_NAME, token)
    return c


def test_subagent_retrievals():
    """Verifies that tag, vector, and text sub-agents successfully retrieve matching candidate records."""
    test_url_tag = "https://example.com/pg-arch-test"
    test_url_text = "https://example.com/sqlite-perf-test"
    test_url_chunk = "https://example.com/vector-chunk-test"

    with db_session() as session:
        # Seed test pages
        if not session.query(FetchedPage).filter_by(url=test_url_tag).first():
            session.add(
                FetchedPage(
                    url=test_url_tag,
                    title="PostgreSQL Replication & Vector Indexing Architecture",
                    tags=json.dumps(["postgresql", "database", "pgvector", "replication"]),
                    description="Deep architecture on PostgreSQL streaming replication and pgvector indexes.",
                    md_content="# PostgreSQL Architecture\nDetailed guide to pgvector and replication.",
                    fetched_at="2026-10-02T10:00:00",
                )
            )

        if not session.query(FetchedPage).filter_by(url=test_url_text).first():
            session.add(
                FetchedPage(
                    url=test_url_text,
                    title="SQLite In-Memory Performance Analysis",
                    tags=json.dumps(["sqlite", "benchmarks"]),
                    description="Performance measurements comparing SQLite WAL mode to memory.",
                    md_content="# SQLite Benchmarks\nAnalysis of concurrency under write-heavy loads.",
                    fetched_at="2026-10-02T10:00:00",
                )
            )

        # Seed test chunk embedding - ensure clean 768-dim vector
        session.query(ChunkEmbedding).filter_by(source_id=test_url_chunk).delete()
        session.commit()
        session.add(
            ChunkEmbedding(
                source_type="articles",
                source_id=test_url_chunk,
                source_title="Vector Similarity Deep Dive",
                chunk_number=0,
                chunk_content="Cosine similarity between high-dimensional vector embeddings in Qdrant and pgvector.",
                chunk_vector=[0.01] * 768,
                model_name="embeddinggemma",
                created_at="2026-10-02T10:00:00",
            )
        )
        session.commit()

        # 1. Test Tag-searching Sub-Agent
        tag_hits = tag_search_subagent(session, "postgresql replication indexing", limit=5)
        assert len(tag_hits) >= 1
        urls_found = [h["url"] for h in tag_hits]
        assert test_url_tag in urls_found
        assert tag_hits[0]["match_type"] == "tag"

        # 2. Test Text-searching Sub-Agent
        text_hits = text_search_subagent(session, "SQLite concurrency benchmarks", limit=5)
        assert len(text_hits) >= 1
        assert any(h["url"] == test_url_text for h in text_hits)
        assert text_hits[0]["match_type"] == "text"

        # 3. Test Vector RAG Sub-Agent with mock embeddings client
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.01] * 768}
        vector_hits = vector_rag_subagent(session, mock_client, "Vector Similarity Deep Dive", active_model="embeddinggemma", limit=5)
        assert len(vector_hits) >= 1
        assert any(h["url"] == test_url_chunk for h in vector_hits)
        assert vector_hits[0]["match_type"] == "vector"

        # 4. Test Deduplication & Provenance Aggregation
        aggregated = aggregate_candidates(tag_hits, vector_hits, text_hits, max_candidates=10)
        assert len(aggregated) >= 1
        # Check structure
        first = aggregated[0]
        assert "url" in first
        assert "title" in first
        assert "match_types" in first
        assert "provenance_count" in first


def test_tev1_decision_scoring_matrix():
    """Verifies tev1 scoring sub-agent handling multiple questions per candidate (up to 64 questions per turn)."""
    candidates = [
        {
            "url": f"https://example.com/item-{i}",
            "title": f"Database Article {i}",
            "snippet": f"Implementation details and code snippets for module {i}: def setup_{i}(): pass",
            "match_types": ["tag", "vector"],
            "provenance_count": 2,
            "base_score": 0.8,
        }
        for i in range(5)
    ]

    mock_client = MagicMock()
    mock_resp = MagicMock()

    # Build answers for 5 candidates x 6 questions = 30 questions
    mock_answers = {}
    for i in range(5):
        prefix = f"c{i}"
        mock_answers[f"{prefix}_relevance"] = MagicMock(noul=0.9)
        mock_answers[f"{prefix}_code_quality"] = MagicMock(noul=0.85)
        mock_answers[f"{prefix}_depth"] = MagicMock(choice="deep")
        mock_answers[f"{prefix}_factual"] = MagicMock(noul=0.95)
        mock_answers[f"{prefix}_domain"] = MagicMock(choice="backend_database")
        mock_answers[f"{prefix}_include"] = MagicMock(noul=0.9)

    mock_resp.answers = mock_answers
    mock_client.systemone.return_value = mock_resp

    scored = tev1_scoring_subagent(
        client=mock_client,
        query="PostgreSQL database replication and code setup",
        candidates=candidates,
        tev1_model="tev1",
        purpose="Inspect code implementations",
    )

    assert len(scored) == 5
    first = scored[0]
    assert "tev1_eval" in first
    assert first["tev1_eval"]["relevance"] == 90.0
    assert first["tev1_eval"]["has_code"] is True
    assert first["tev1_eval"]["depth"] == "deep"
    assert first["tev1_eval"]["include"] is True
    assert first["tev1_eval"]["composite_score"] > 80.0


def test_report_compilation_and_fallback():
    """Verifies report synthesis via Ollama and fallback generation on error."""
    mock_client = MagicMock()
    mock_client.chat.return_value = MagicMock(
        message=MagicMock(
            content="# Comprehensive Database Architecture Report\n\n## Executive Summary\nPostgreSQL delivers high throughput.\n\n## Key Findings\n- Replication is robust.\n\n## Evidence & Citations Table\n| # | Source Title | Channel | tev1 Score | URL |\n| 1 | DB Guide | vector | 92.5% | https://example.com |"
        )
    )

    vetted = [
        {
            "url": "https://example.com/db-guide",
            "title": "DB Guide",
            "source_type": "article",
            "snippet": "Architecture notes.",
            "match_types": ["vector", "tag"],
            "tev1_eval": {
                "relevance": 92.5,
                "depth": "deep",
                "has_code": True,
                "composite_score": 90.0,
                "include": True,
            },
        }
    ]

    report = compile_rag_report(
        client=mock_client,
        query="Database Architecture Overview",
        vetted_candidates=vetted,
        synthesis_model="gemma4:latest",
    )
    assert report["title"] == "Comprehensive Database Architecture Report"
    assert "Executive Summary" in report["report_markdown"]
    assert len(report["sources"]) == 1

    # Test fallback generation when model throws exception
    mock_err_client = MagicMock()
    mock_err_client.chat.side_effect = RuntimeError("Model timeout")
    fallback_report = compile_rag_report(
        client=mock_err_client,
        query="Failing Model Query",
        vetted_candidates=vetted,
        synthesis_model="failing-model",
    )
    assert "RAG Research Report" in fallback_report["title"]
    assert "Evidence & Citations Table" in fallback_report["report_markdown"]
    assert len(fallback_report["sources"]) == 1


def test_rag_reports_api_workflow(auth_client, monkeypatch):
    """Tests the full REST API lifecycle: UI page, generation, listing, details, and Note export."""
    # Mock Ollama calls inside run_agentic_rag_pipeline
    mock_client = MagicMock()
    mock_client.embeddings.return_value = {"embedding": [0.01] * 768}
    mock_resp = MagicMock()
    mock_resp.answers = {
        "c0_relevance": MagicMock(noul=0.88),
        "c0_code_quality": MagicMock(noul=0.75),
        "c0_depth": MagicMock(choice="deep"),
        "c0_factual": MagicMock(noul=0.9),
        "c0_domain": MagicMock(choice="backend_database"),
        "c0_include": MagicMock(noul=0.85),
    }
    mock_client.systemone.return_value = mock_resp
    mock_client.chat.return_value = MagicMock(
        message=MagicMock(
            content="# Synthesized API Test Report\n\n## Executive Summary\nAll endpoints operating within specification.\n\n## Evidence & Citations Table\n| # | Title | Channel | Score | URL |\n| 1 | Architecture Guide | vector | 88% | https://example.com |"
        )
    )

    monkeypatch.setattr("kb_web.routers.rag_reports._get_ollama_client", lambda: mock_client)
    monkeypatch.setattr("kb_web.rag_agent._get_ollama_client", lambda: mock_client)

    # 1. Test HTML UI route
    ui_res = auth_client.get("/reports/rag")
    assert ui_res.status_code == 200
    assert "Agentic RAG Report Generator" in ui_res.text
    assert "tev1 Decision Gated" in ui_res.text

    # 2. Test POST /api/reports/rag/generate
    gen_res = auth_client.post(
        "/api/reports/rag/generate",
        json={
            "query": "PostgreSQL database view optimization and pgvector",
            "purpose": "Analyze view performance",
            "synthesis_model": "gemma4:latest",
            "tev1_model": "tev1",
        },
    )
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert "id" in data
    report_id = data["id"]
    assert "Synthesized API Test Report" in data["title"]
    assert "subagent_metrics" in data
    assert "tev1_evaluations" in data

    # 3. Test GET /api/reports/rag
    list_res = auth_client.get("/api/reports/rag")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    assert any(r["id"] == report_id for r in list_data["reports"])

    # 4. Test GET /api/reports/rag/{id}
    detail_res = auth_client.get(f"/api/reports/rag/{report_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == report_id
    assert "Executive Summary" in detail["report_markdown"]

    # 5. Test POST /api/reports/rag/{id}/save-to-notes
    note_res = auth_client.post(f"/api/reports/rag/{report_id}/save-to-notes")
    assert note_res.status_code == 200
    note_data = note_res.json()
    assert note_data["status"] == "success"
    assert "note://rag-reports/" in note_data["note_url"]
    assert "edit_url" in note_data

    # Verify note in database
    with db_session() as session:
        note = session.query(Note).filter_by(url=note_data["note_url"]).first()
        assert note is not None
        assert "Synthesized API Test Report" in note.title
        assert "Executive Summary" in note.content

    # 6. Test DELETE /api/reports/rag/{id}
    del_res = auth_client.delete(f"/api/reports/rag/{report_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_single_article_chat_eliminated_and_conversations_redirect(client, auth_client):
    """Verifies that single-article chat drawer has been removed and /conversations redirects to /reports/rag."""
    # 1. Verify /conversations redirects to /reports/rag
    conv_res = auth_client.get("/conversations", follow_redirects=False)
    assert conv_res.status_code == 302
    assert conv_res.headers.get("location") == "/reports/rag"

    # 2. Seed page and verify view_page.j2.html does NOT contain Chat About Article drawer
    test_page_url = "https://example.com/no-chat-drawer-test"
    with db_session() as session:
        if not session.query(FetchedPage).filter_by(url=test_page_url).first():
            session.add(
                FetchedPage(
                    url=test_page_url,
                    title="No Chat Drawer Page Test",
                    description="Test page without chat drawer.",
                    md_content="# Content\nSome body.",
                    fetched_at="2026-10-02T12:00:00",
                )
            )
            session.commit()

    page_res = auth_client.get(f"/view/page?url={test_page_url}")
    assert page_res.status_code == 200
    # Chat About Article button must be gone
    assert "Chat About Article" not in page_res.text
    assert "chat-drawer-backdrop" not in page_res.text
    assert "openChatDrawer" not in page_res.text
    # Replaced by RAG Research Report link
    assert "RAG Research Report" in page_res.text
    assert "/reports/rag?q=" in page_res.text


def test_cli_rag_report_help():
    """Verifies CLI commands for rag report."""
    res_help = runner.invoke(cli_app, ["rag", "--help"])
    assert res_help.exit_code == 0
    assert "report" in res_help.stdout

    res_report_help = runner.invoke(cli_app, ["rag", "report", "--help"])
    assert res_report_help.exit_code == 0
    assert "--output" in res_report_help.stdout
    assert "--save-notes" in res_report_help.stdout
