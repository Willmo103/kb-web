import pytest
from fastapi.testclient import TestClient
import json
import ollama

from kb_web.config import Config
from kb_web.db import get_db
from kb_web.models import HTMLPage
from kb_web.server import app, config as server_config


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path) -> None:
    """Fixture to override config database path to a temp file, isolating test DB state."""
    old_db_path = server_config.db_path
    temp_db = tmp_path / "test_kb.db"
    server_config.db_path = temp_db

    # Ensure schema is preloaded
    _ = get_db(server_config)

    yield

    # Restore path after execution completes
    server_config.db_path = old_db_path


@pytest.fixture
def client() -> TestClient:
    """Fixture to obtain a TestClient instance targeting the FastAPI app."""
    return TestClient(app)


def test_config(tmp_path) -> None:
    """Ensures configuration properties fallback to default values correctly and can save."""
    cfg = Config()
    cfg.configs_dir = tmp_path
    assert cfg.ollama_host is not None
    assert cfg.admin_password == "admin123" or cfg.admin_password is not None

    # Test configuration saving and loading back
    cfg.ollama_host = "http://my-ollama-server:11434"
    cfg.ollama_model = "gemma5"
    cfg.api_key = "custom-key"
    cfg.save()

    cfg2 = Config()
    cfg2.configs_dir = tmp_path
    # Trigger reload by re-running __init__ logic
    cfg2.__init__()
    assert cfg2.ollama_host == "http://my-ollama-server:11434"
    assert cfg2.ollama_model == "gemma5"
    assert cfg2.api_key == "custom-key"


def test_models() -> None:
    """Validates that Pydantic models resolve relative links, parse keywords, and handle tags."""
    url = "https://example.com/sub/index.html"
    page = HTMLPage(
        url=url,
        title="Test Page Title",
        html_content="<html><body>hello</body></html>",
        md_content="hello",
        links=["/about", "https://google.com"],
        html_content_hash="hhash",
        md_content_hash="mhash",
        fetched_at="2026-05-30T12:00:00",
        keywords='["test", "keyword"]',
        tags='["tag1", "tag2"]'
    )
    # Relative path should map to absolute base URL
    assert "https://example.com/about" in page.links
    assert "https://google.com" in page.links
    assert page.keywords == ["test", "keyword"]
    assert page.tags == ["tag1", "tag2"]
    assert page.title == "Test Page Title"


def test_public_routes(client: TestClient) -> None:
    """Checks public endpoints for positive status codes."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "password" in response.text

    response = client.get("/pages")
    assert response.status_code == 200


def test_auth_route_guard_redirects(client: TestClient) -> None:
    """Ensures protected endpoints redirect requests missing auth cookies."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_flow(client: TestClient) -> None:
    """Tests password evaluations and cookie generation."""
    # Invalid password check
    response = client.post("/login", data={"password": "bad_password"})
    assert response.status_code == 200
    assert "Invalid security credentials" in response.text

    # Valid password check
    response = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "kb_session" in response.cookies


def test_api_html_import(client: TestClient, monkeypatch) -> None:
    """Tests the /api/import/html browser extension endpoint with API keys and mocks."""
    # Mock Ollama chat to avoid active model checks during unit tests
    class DummyMessage:
        content = "# Extracted Title\n\nWiki text body content. tags: tech, web, python"

    class DummyChatResponse:
        message = DummyMessage()

    monkeypatch.setattr(ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse())

    # Set key in server config
    server_config.api_key = "secure-auth-key"

    payload = {
        "url": "https://example.com/blog/mypost",
        "html_content": "<html><head><title>My Blog Post Title</title></head><body>Content</body></html>",
        "title": "My Blog Post Title"
    }

    # Test without API Key in headers (should reject with 401)
    response = client.post("/api/import/html", json=payload)
    assert response.status_code == 401

    # Test with incorrect API Key (should reject with 401)
    response = client.post("/api/import/html", json=payload, headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401

    # Test with correct API Key (should succeed)
    response = client.post("/api/import/html", json=payload, headers={"X-API-Key": "secure-auth-key"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify records inside the isolated database
    db = get_db(server_config)
    row = db["fetched_pages"].get("https://example.com/blog/mypost")
    assert row["title"] == "Extracted Title"
    assert "Extracted Title" in row["description"]
    assert row["tags"] is not None


def test_admin_only_features_and_deletion(client: TestClient) -> None:
    """Verifies that wiki / tag regeneration, manual tag editing, and page deletion are protected and only shown to admin."""
    # 1. Insert a page into the database
    db = get_db(server_config)
    page_data = {
        "url": "https://example.com/testpage",
        "title": "A Test Page Title",
        "html_content": "<html><body>Hello Test</body></html>",
        "md_content": "Hello Test",
        "links": '["/another"]',
        "html_content_hash": "hash1",
        "md_content_hash": "hash2",
        "fetched_at": "2026-05-31T12:00:00",
        "description": "This is a wiki summary description.",
        "keywords": '["test"]',
        "tags": '["tag-one", "tag-two"]'
    }
    db["fetched_pages"].insert(page_data)

    # 2. View page as non-admin (without cookies)
    response = client.get("/view/page?url=https://example.com/testpage")
    assert response.status_code == 200
    assert "A Test Page Title" in response.text
    assert "This is a wiki summary description." in response.text
    assert "tag-one" in response.text
    # Admin actions should not be visible
    assert "Regenerate Wiki" not in response.text
    assert "Regenerate Tags" not in response.text
    assert "Delete Entry" not in response.text
    assert "Edit Tags" not in response.text

    # 3. Attempt deletion without auth (before logging in to avoid cookie persistence)
    del_fail = client.post(
        "/admin/delete/page",
        data={"url": "https://example.com/testpage"},
        follow_redirects=False
    )
    assert del_fail.status_code == 303  # redirects to login
    assert db["fetched_pages"].get("https://example.com/testpage") is not None

    # 4. Log in as admin
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    session_cookie = login_resp.cookies.get("kb_session")
    assert session_cookie is not None

    # 5. View page as admin
    response_admin = client.get(
        "/view/page?url=https://example.com/testpage"
    )
    assert response_admin.status_code == 200
    # Admin actions should be visible
    assert "Regenerate Wiki" in response_admin.text
    assert "Regenerate Tags" in response_admin.text
    assert "Delete Entry" in response_admin.text
    assert "Edit Tags" in response_admin.text

    # 6. Attempt deletion with auth
    del_success = client.post(
        "/admin/delete/page",
        data={"url": "https://example.com/testpage"},
        follow_redirects=False
    )
    assert del_success.status_code == 303
    assert del_success.headers["location"] == "/pages"

    # Verify deleted
    import sqlite_utils
    with pytest.raises(sqlite_utils.db.NotFoundError):
        db["fetched_pages"].get("https://example.com/testpage")

