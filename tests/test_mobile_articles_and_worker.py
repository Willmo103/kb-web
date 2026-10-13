"""
Unit and integration tests for Mobile Views polish, Dedicated Articles page,
and Autonomous Background Server Worker engine.
"""

import time
import json
import anyio
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import db_session, config, COOKIE_NAME, generate_session_token
from kb_web.models_orm import FetchedPage
from kb_web.worker import autonomous_worker, AutonomousWorker


@pytest.fixture
def client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def test_articles_route_renders_dedicated_view(client: TestClient):
    """Verifies /articles endpoint serves dedicated articles directory."""
    resp = client.get("/articles")
    assert resp.status_code == 200
    assert "Articles Directory" in resp.text
    assert "Knowledge Base" in resp.text
    assert 'href="/articles"' in resp.text


def test_articles_route_filters_and_search(client: TestClient):
    """Verifies /articles endpoint correctly processes search queries and tag filtering."""
    resp = client.get("/articles?q=python")
    assert resp.status_code == 200
    assert 'action="/articles"' in resp.text

    resp_tag = client.get("/articles?tag=programming")
    assert resp_tag.status_code == 200


def test_mobile_view_template_structures(client: TestClient):
    """Verifies mobile polish changes in base, admin, and pages_list templates."""
    # 1. Base template: Brand title Knowledge Base is not hidden on mobile
    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert "Knowledge Base" in resp_home.text
    # Verify brand title span exists without hidden sm:inline
    assert 'truncate max-w-[140px] xs:max-w-none">Knowledge Base</span>' in resp_home.text

    # 2. Left sidebar in pages_list is hidden on mobile
    assert "hidden lg:block w-60 flex-shrink-0" in resp_home.text

    # 3. Dedicated Articles link is present in desktop and mobile navigation
    assert 'href="/articles"' in resp_home.text


def test_admin_portal_mobile_tabs_and_margins(client: TestClient):
    """Verifies admin tab navigation is a static button grid and lower sections have margins."""
    resp = client.get("/admin")
    assert resp.status_code == 200
    # Verify static grid buttons instead of overflow-x-auto
    assert "grid grid-cols-2" in resp.text
    assert 'id="adminTabsNav"' in resp.text
    # Verify margins in tab-backups
    assert "space-y-8" in resp.text
    assert "Autonomous Server Worker" in resp.text


def test_worker_status_endpoint(client: TestClient):
    """Verifies /api/worker/status endpoint returns active status and metrics."""
    resp = client.get("/api/worker/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "is_running" in data
    assert "interval_minutes" in data
    assert "total_cycles" in data
    assert "wikis_curated_total" in data


def test_autonomous_worker_cycle_curation():
    """Verifies autonomous worker runs a single-item curation cycle."""
    async def _test():
        worker = AutonomousWorker()

        test_url = "https://example.com/test-worker-article"
        with db_session() as session:
            # Clean up any prior test record
            existing = session.query(FetchedPage).filter_by(url=test_url).first()
            if existing:
                session.delete(existing)
                session.commit()

            # Insert page lacking wiki and tags
            page = FetchedPage(
                url=test_url,
                title="Uncurated Article Title",
                description="",  # Missing wiki
                tags="[]",       # Missing tags
                html_content="<p>Test content</p>",
                md_content="Test content for autonomous worker",
                fetched_at="1990-01-01T00:00:00",
            )
            session.add(page)
            session.commit()

        with patch("kb_web.worker.extract_wiki_content", return_value="# Curated Header\n\nAI generated wiki summary."):
            with patch("kb_web.worker.extract_tags_content", return_value=["ai", "autonomous", "testing"]):
                with patch("kb_web.worker.update_article_embedding"):
                    with patch("kb_web.worker.generate_gemma_embeddings_for_page"):
                        result = await worker.run_cycle()

        assert result["status"] == "completed"
        assert result["curated_wiki_url"] == test_url
        assert result["curated_tags_url"] == test_url

        # Verify DB was updated
        with db_session() as session:
            updated = session.query(FetchedPage).filter_by(url=test_url).first()
            assert updated is not None
            assert "Curated Header" in updated.title or "Curated Header" in updated.description
            assert "ai" in updated.tags
            # Clean up
            session.delete(updated)
            session.commit()

    anyio.run(_test)


def test_autonomous_worker_graceful_error_handling():
    """Verifies autonomous worker handles LLM errors without raising uncaught exceptions."""
    async def _test():
        worker = AutonomousWorker()

        test_url = "https://example.com/test-failing-article"
        with db_session() as session:
            existing = session.query(FetchedPage).filter_by(url=test_url).first()
            if existing:
                session.delete(existing)
                session.commit()

            page = FetchedPage(
                url=test_url,
                title="Failing Article Title",
                description="",
                tags="[]",
                html_content="<p>Fail test</p>",
                md_content="Fail test content",
                fetched_at="2026-10-12T00:00:00",
            )
            session.add(page)
            session.commit()

        # Simulate Ollama connection failure
        with patch("kb_web.worker.extract_wiki_content", side_effect=ConnectionError("Ollama daemon unreachable")):
            with patch("kb_web.worker.extract_tags_content", side_effect=TimeoutError("Tag extraction timed out")):
                result = await worker.run_cycle()

        # Should finish gracefully without raising
        assert result["status"] == "completed"
        assert len(result["errors"]) >= 1

        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=test_url).first()
            if page:
                session.delete(page)
                session.commit()

    anyio.run(_test)
