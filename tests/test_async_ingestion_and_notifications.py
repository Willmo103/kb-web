"""
Tests for background ingestion pipeline, zero data loss guarantee,
LLM timeout configuration, and notification feed.
"""

import time
import anyio
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.config import Config
from kb_web.base import config, db_session, COOKIE_NAME, generate_session_token, _get_ollama_client
from kb_web.models import HTMLPage
from kb_web.models_orm import FetchedPage, IngestionNotification
from kb_web.pipeline import record_notification, run_ingest_pipeline_background


@pytest.fixture(autouse=True)
def mock_gotify(monkeypatch):
    class DummyGotify:
        def __init__(self, *args, **kwargs):
            self.POST_ENABLED = False
        def send_notification(self, *args, **kwargs) -> None:
            pass
    import kb_core.notifier
    import kb_web.config
    monkeypatch.setattr(kb_core.notifier, "Gotify", DummyGotify)
    monkeypatch.setattr(kb_web.config, "Gotify", DummyGotify)


@pytest.fixture
def client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def test_config_ollama_timeout():
    assert config.ollama_timeout == 1200.0
    client = _get_ollama_client()
    assert client.timeout == 1200.0


def test_notifications_api_lifecycle(client: TestClient):
    with db_session() as session:
        # Clear existing notifications
        session.query(IngestionNotification).delete()
        session.commit()

    # Record test notification
    record_notification(
        stage="Test Ingestion",
        status="success",
        message="Test page fetched and saved",
        url="https://example.com/test-notification",
    )

    # Fetch notifications via API
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["notifications"]) >= 1
    assert data["notifications"][0]["stage"] == "Test Ingestion"
    assert data["notifications"][0]["is_read"] is False

    # Mark notifications as read
    read_resp = client.post("/api/notifications/read")
    assert read_resp.status_code == 200
    assert read_resp.json()["status"] == "success"

    check_resp = client.get("/api/notifications")
    assert check_resp.json()["notifications"][0]["is_read"] is True

    # Clear notifications
    clear_resp = client.post("/api/notifications/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "success"

    empty_resp = client.get("/api/notifications")
    assert len(empty_resp.json()["notifications"]) == 0


def test_background_pipeline_zero_data_loss(monkeypatch):
    test_url = "https://example.com/zero-data-loss-test"

    # Clean up any existing row
    with db_session() as session:
        session.query(FetchedPage).filter_by(url=test_url).delete()
        session.query(IngestionNotification).filter_by(url=test_url).delete()
        session.commit()

    mock_page = HTMLPage(
        url=test_url,
        title="Resilient Content",
        html_content="<html><body><article><h1>Resilient Content</h1><p>Must never be lost.</p></article></body></html>",
        md_content="# Resilient Content\n\nMust never be lost.",
        links=["https://example.com/sublink"],
        html_content_hash="mock_hash_1",
        md_content_hash="mock_hash_2",
        fetched_at="2026-10-12T12:00:00",
    )

    monkeypatch.setattr("kb_web.pipeline.fetch_url", lambda url: mock_page)

    # Force downstream AI wiki stage to fail intentionally to verify zero data loss
    def failing_wiki(*args, **kwargs):
        raise RuntimeError("Simulated Ollama downstream timeout or crash")

    monkeypatch.setattr("kb_web.pipeline.extract_wiki_content", failing_wiki)
    monkeypatch.setattr("kb_web.pipeline.extract_tags_content", lambda *args, **kwargs: ["test"])
    monkeypatch.setattr("kb_web.pipeline.generate_gemma_embeddings_for_page", lambda *args, **kwargs: None)
    monkeypatch.setattr("kb_web.pipeline.update_article_embedding", lambda *args, **kwargs: None)

    # Run the async background pipeline
    result = anyio.run(run_ingest_pipeline_background, test_url)

    # Verify that FetchedPage was saved IMMEDIATELY in Stage 1 despite Stage 2 failure
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        assert page is not None, "FetchedPage must be persisted immediately on fetch (zero data loss guarantee)"
        assert page.title == "Resilient Content"
        assert "Must never be lost" in page.html_content
        assert "Must never be lost" in page.md_content

        # Verify notifications recorded the initial fetch and the downstream error
        notifs = session.query(IngestionNotification).filter_by(url=test_url).all()
        stages = [n.stage for n in notifs]
        assert "fetch" in stages
        wiki_notif = next(n for n in notifs if n.stage == "wiki" and n.status == "failed")
        assert wiki_notif is not None
        assert "Simulated Ollama" in wiki_notif.message
