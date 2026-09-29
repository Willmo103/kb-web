import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.crawler import (
    ai_curate_candidate_links,
    extract_candidate_links,
    normalize_url,
    run_batch_crawl_ingestion,
)
from kb_web.models_orm import FetchedPage
from kb_web.server import app
import time


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_normalize_url():
    base = "https://example.com/docs/guides/"

    # Relative paths
    assert normalize_url(base, "quickstart") == "https://example.com/docs/guides/quickstart"
    assert normalize_url(base, "../api") == "https://example.com/docs/api"
    assert normalize_url(base, "/root-page") == "https://example.com/root-page"

    # Fragments & Tracking
    clean = normalize_url(base, "page?utm_source=twitter&ref=abc#section-1")
    assert clean == "https://example.com/docs/guides/page"

    # Preserving non-tracking query parameters
    param_url = normalize_url(base, "search?q=fastapi&sort=desc")
    assert "q=fastapi" in param_url
    assert "sort=desc" in param_url

    # Reject non-http
    assert normalize_url(base, "mailto:hello@example.com") is None
    assert normalize_url(base, "javascript:void(0)") is None
    assert normalize_url(base, "tel:+1234567890") is None
    assert normalize_url(base, "#just-anchor") is None
    assert normalize_url(base, "") is None


def test_extract_candidate_links():
    mock_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Documentation Site</title></head>
    <body>
        <h1>Welcome to Example Docs</h1>
        <a href="/intro">Introduction</a>
        <a href="/tutorial/step-1">Step 1</a>
        <a href="https://external.org/info">External Resource</a>
        <a href="/zh/intro">Chinese Translation</a>
        <a href="/terms-of-service">Terms</a>
        <a href="mailto:support@example.com">Email Us</a>
        <a href="#section-top">Jump to Top</a>
    </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.text = mock_html
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.raise_for_status = MagicMock()

    # Pre-insert one page in DB to test already_ingested flag
    with db_session() as session:
        session.query(FetchedPage).filter_by(url="https://example.com/intro").delete()
        page = FetchedPage(
            url="https://example.com/intro",
            title="Introduction",
            fetched_at="2026-09-13T10:00:00",
        )
        session.add(page)

    with patch("httpx.get", return_value=mock_resp):
        # 1. same_domain = True
        res = extract_candidate_links("https://example.com/index", same_domain=True)
        assert res["page_title"] == "Test Documentation Site"
        urls = [l["url"] for l in res["links"]]
        assert "https://example.com/intro" in urls
        assert "https://example.com/tutorial/step-1" in urls
        assert "https://external.org/info" not in urls  # Excluded by same_domain

        # Check already_ingested flag
        intro_item = next(l for l in res["links"] if l["url"] == "https://example.com/intro")
        assert intro_item["already_ingested"] is True

        step_item = next(l for l in res["links"] if l["url"] == "https://example.com/tutorial/step-1")
        assert step_item["already_ingested"] is False

        # 2. same_domain = False
        res_all = extract_candidate_links("https://example.com/index", same_domain=False)
        urls_all = [l["url"] for l in res_all["links"]]
        assert "https://external.org/info" in urls_all

    # Cleanup
    with db_session() as session:
        session.query(FetchedPage).filter_by(url="https://example.com/intro").delete()


def test_ai_curate_candidate_links():
    candidate_links = [
        {"url": "https://example.com/docs/quickstart", "title": "Quickstart Guide"},
        {"url": "https://example.com/docs/api-reference", "title": "API Reference"},
        {"url": "https://example.com/zh/docs/quickstart", "title": "Chinese Quickstart"},
        {"url": "https://example.com/privacy", "title": "Privacy Policy"},
        {"url": "https://example.com/login", "title": "User Login"},
    ]

    # Mock Ollama returning structured JSON
    mock_chat_resp = MagicMock()
    mock_chat_resp.message.content = json.dumps({
        "selected_urls": [
            "https://example.com/docs/quickstart",
            "https://example.com/docs/api-reference",
        ],
        "explanation": "Selected technical documentation; filtered out language variants and auth pages.",
    })

    mock_client = MagicMock()
    mock_client.chat = MagicMock(return_value=mock_chat_resp)

    res = ai_curate_candidate_links(
        seed_url="https://example.com/docs",
        page_title="Example Docs",
        links=candidate_links,
        custom_instructions="Focus exclusively on API reference and getting started guides",
        client=mock_client,
    )

    assert "https://example.com/docs/quickstart" in res["selected_urls"]
    assert "https://example.com/docs/api-reference" in res["selected_urls"]
    assert "https://example.com/zh/docs/quickstart" not in res["selected_urls"]
    assert "https://example.com/login" not in res["selected_urls"]
    assert "Selected technical documentation" in res["explanation"]

    # Verify custom_instructions was passed into system prompt
    call_args = mock_client.chat.call_args[1]
    system_msg = next(m["content"] for m in call_args["messages"] if m["role"] == "system")
    assert "Focus exclusively on API reference" in system_msg


def test_api_crawl_endpoints(client):
    token = generate_session_token(time.time() + 3600)
    auth_client = TestClient(app, cookies={COOKIE_NAME: token})

    # Mock candidate extraction for /api/crawl/discover
    mock_html = "<html><head><title>Mock Site</title></head><body><a href='/doc1'>Doc 1</a><a href='/doc2'>Doc 2</a></body></html>"
    mock_resp = MagicMock()
    mock_resp.text = mock_html
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp):
        # 1. Discover endpoint
        res = auth_client.post(
            "/api/crawl/discover",
            json={"url": "https://mysite.org", "same_domain": True, "max_links": 50},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["total_found"] == 2
        assert len(data["links"]) == 2

    # 2. AI Filter endpoint
    mock_ai_resp = MagicMock()
    mock_ai_resp.message.content = json.dumps({
        "selected_urls": ["https://mysite.org/doc1"],
        "explanation": "Selected doc1 as substantive article.",
    })
    with patch("kb_web.crawler._get_ollama_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value=mock_ai_resp)
        mock_get_client.return_value = mock_client

        res_ai = auth_client.post(
            "/api/crawl/ai-filter",
            json={
                "seed_url": "https://mysite.org",
                "page_title": "Mock Site",
                "links": [
                    {"url": "https://mysite.org/doc1", "title": "Doc 1"},
                    {"url": "https://mysite.org/doc2", "title": "Doc 2"},
                ],
                "custom_instructions": "Keep only doc1",
            },
        )
        assert res_ai.status_code == 200
        data_ai = res_ai.json()
        assert data_ai["status"] == "success"
        assert data_ai["selected_urls"] == ["https://mysite.org/doc1"]

    # 3. Enqueue endpoint
    with patch("kb_web.crawler.ingest_url_sync", return_value={"status": "success", "url": "https://mysite.org/doc1"}):
        res_enqueue = auth_client.post(
            "/api/crawl/enqueue",
            json={
                "urls": ["https://mysite.org/doc1", "https://mysite.org/doc2"],
                "collection_id": None,
                "new_collection_title": None,
            },
        )
        assert res_enqueue.status_code == 200
        data_enqueue = res_enqueue.json()
        assert data_enqueue["status"] == "success"
        assert data_enqueue["enqueued_count"] == 2
