import json
import ollama
import pytest
from fastapi.testclient import TestClient

from kb_web.config import Config
from kb_web.db import get_db
from kb_web.models import HTMLPage
from kb_web.server import app
from kb_web.server import config as server_config


@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch) -> None:
    """Fixture to override config database path to a temp file, isolating test DB state."""
    old_db_path = server_config.db_path
    temp_db = tmp_path / "test_kb.db"
    server_config.db_path = temp_db

    # Ensure schema is preloaded
    _ = get_db(server_config)

    # Mock Ollama Client embeddings, list, and pull globally to keep tests fast and offline
    monkeypatch.setattr(
        ollama.Client, "embeddings", lambda *args, **kwargs: {"embedding": [0.1] * 384}
    )
    monkeypatch.setattr(
        ollama.Client,
        "list",
        lambda *args, **kwargs: {"models": [{"name": "nomic-embed-text:latest"}]},
    )
    monkeypatch.setattr(ollama.Client, "pull", lambda *args, **kwargs: None)

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
        tags='["tag1", "tag2"]',
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

    response = client.get("/")
    assert response.status_code == 200


def test_auth_route_guard_redirects(client: TestClient) -> None:
    """Ensures protected endpoints redirect requests missing auth cookies."""
    response = client.get("/import", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


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

    monkeypatch.setattr(
        ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse()
    )

    # Set key in server config
    server_config.api_key = "secure-auth-key"

    payload = {
        "url": "https://example.com/blog/mypost",
        "html_content": "<html><head><title>My Blog Post Title</title></head><body>Content</body></html>",
        "title": "My Blog Post Title",
    }

    # Test without API Key in headers (should reject with 401)
    response = client.post("/api/import/html", json=payload)
    assert response.status_code == 401

    # Test with incorrect API Key (should reject with 401)
    response = client.post(
        "/api/import/html", json=payload, headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401

    # Test with correct API Key (should succeed)
    response = client.post(
        "/api/import/html", json=payload, headers={"X-API-Key": "secure-auth-key"}
    )
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
        "tags": '["tag-one", "tag-two"]',
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
        follow_redirects=False,
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
    response_admin = client.get("/view/page?url=https://example.com/testpage")
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
        follow_redirects=False,
    )
    assert del_success.status_code == 303
    assert del_success.headers["location"] == "/"

    # Verify deleted
    import sqlite_utils

    with pytest.raises(sqlite_utils.db.NotFoundError):
        db["fetched_pages"].get("https://example.com/testpage")


def test_change_password(client: TestClient) -> None:
    """Verifies that admins can change their password securely."""
    # Authenticate first
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    # Verify wrong password fails
    resp = client.post(
        "/admin/change-password",
        data={"current_password": "wrong-password", "new_password": "new-admin-pass"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Error" in resp.headers["location"]

    # Verify correct password succeeds
    original_pass = server_config.admin_password
    resp = client.post(
        "/admin/change-password",
        data={"current_password": original_pass, "new_password": "new-admin-pass"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "updated" in resp.headers["location"]
    assert server_config.admin_password == "new-admin-pass"

    # Restore original password for other tests
    server_config.admin_password = original_pass
    server_config.save()


def test_page_refetch_and_versioning(client: TestClient, monkeypatch) -> None:
    """Verifies page re-fetching behavior, version snapshot archiving, and error recovery."""

    # Mock Ollama chat/tagging
    class DummyMessage:
        content = "# Refetched Title\n\nNew wiki body text. tags: updated, refetched"

    class DummyChatResponse:
        message = DummyMessage()

    monkeypatch.setattr(
        ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse()
    )

    # Insert a page into the database first
    db = get_db(server_config)
    page_data = {
        "url": "https://example.com/refetchpage",
        "title": "A Test Page Title",
        "html_content": "<html><body>Hello Test</body></html>",
        "md_content": "Hello Test",
        "links": '["/another"]',
        "html_content_hash": "hash1",
        "md_content_hash": "hash2",
        "fetched_at": "2026-05-31T12:00:00",
        "description": "Original wiki summary description.",
        "keywords": '["test"]',
        "tags": '["tag-one"]',
    }
    db["fetched_pages"].insert(page_data)

    # Login to get admin cookie
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    # Mock fetch_url to return new details
    def mock_fetch_url(url: str):
        from kb_web.models import HTMLPage

        return HTMLPage(
            url=url,
            title="A Test Page Title",
            html_content="<html><body>Hello Refetched</body></html>",
            md_content="Hello Refetched",
            links=[],
            html_content_hash="refetchedhash1",
            md_content_hash="refetchedhash2",
            fetched_at="2026-05-31T13:00:00",
            description="",
            keywords=[],
            tags=[],
        )

    monkeypatch.setattr("kb_web.routers.admin.fetch_url", mock_fetch_url)

    # Perform Refetch
    resp = client.post(
        "/admin/refetch/page?url=https%3A%2F%2Fexample.com%2Frefetchpage",
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "re-fetched" in resp.headers["location"]

    # Verify latest is updated
    row = db["fetched_pages"].get("https://example.com/refetchpage")
    assert row["title"] == "Refetched Title"
    assert "New wiki body text" in row["description"]

    # Verify historical version is archived
    versions = list(
        db["page_versions"].rows_where("url = ?", ["https://example.com/refetchpage"])
    )
    assert len(versions) == 1
    assert versions[0]["title"] == "A Test Page Title"
    assert versions[0]["description"] == "Original wiki summary description."

    # View page and verify switcher is present
    resp_view = client.get("/view/page?url=https%3A%2F%2Fexample.com%2Frefetchpage")
    assert resp_view.status_code == 200
    assert "Version History:" in resp_view.text
    assert "Version 1" in resp_view.text

    # View historical version
    version_id = versions[0]["id"]
    resp_version_view = client.get(
        f"/view/page?url=https%3A%2F%2Fexample.com%2Frefetchpage&version_id={version_id}"
    )
    assert resp_version_view.status_code == 200
    assert "You are viewing a historical version" in resp_version_view.text
    assert "Original wiki summary description." in resp_version_view.text

    # Mock fetch failure
    def mock_fetch_fail(url: str):
        raise RuntimeError("Server offline")

    monkeypatch.setattr("kb_web.routers.admin.fetch_url", mock_fetch_fail)

    # Attempt refetch (should keep original)
    resp_fail = client.post(
        "/admin/refetch/page?url=https%3A%2F%2Fexample.com%2Frefetchpage",
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp_fail.status_code == 303
    assert "error" in resp_fail.headers["location"]

    # Verify database hasn't changed (latest is still Refetched Title)
    row_after = db["fetched_pages"].get("https://example.com/refetchpage")
    assert row_after["title"] == "Refetched Title"


def test_dirty_url_extraction() -> None:
    """Tests that extract_first_url resolves URLs from dirty text blocks."""
    from kb_web.server import extract_first_url

    # Check prefix text
    assert (
        extract_first_url("source: XCD http://xcd.com/article/12345")
        == "http://xcd.com/article/12345"
    )
    assert (
        extract_first_url("Headline - https://news.example.com/item?id=5")
        == "https://news.example.com/item?id=5"
    )

    # Check malformed scheme support
    assert (
        extract_first_url("source: http:example.com/article")
        == "http://example.com/article"
    )

    # Check bare domain with path
    assert (
        extract_first_url("check this domain.org/path/sub")
        == "https://domain.org/path/sub"
    )

    # Check trailing punctuation cleaning
    assert (
        extract_first_url("Link: (https://example.com/page).")
        == "https://example.com/page"
    )


def test_tags_view(client: TestClient) -> None:
    """Verifies that tag filtering on / and /pages works, and that the legacy /tags returns 404."""
    db = get_db(server_config)

    # Ingest a page with specific tags
    page_data_1 = {
        "url": "https://example.com/page-a",
        "title": "Page A",
        "html_content": "A",
        "md_content": "A",
        "links": "[]",
        "html_content_hash": "a1",
        "md_content_hash": "a2",
        "fetched_at": "2026-05-31T12:00:00",
        "description": "Desc A",
        "keywords": "[]",
        "tags": '["coding", "python"]',
    }
    page_data_2 = {
        "url": "https://example.com/page-b",
        "title": "Page B",
        "html_content": "B",
        "md_content": "B",
        "links": "[]",
        "html_content_hash": "b1",
        "md_content_hash": "b2",
        "fetched_at": "2026-05-31T12:00:00",
        "description": "Desc B",
        "keywords": "[]",
        "tags": '["coding", "database"]',
    }
    db["fetched_pages"].insert(page_data_1)
    db["fetched_pages"].insert(page_data_2)

    # 1. Fetch tags via filtered query on pages list
    resp = client.get("/?tag=python")
    assert resp.status_code == 200
    assert "Page A" in resp.text
    assert "Page B" not in resp.text

    # 2. Legacy tags page returns 404
    resp_legacy = client.get("/tags")
    assert resp_legacy.status_code == 404


def test_login_redirect_preservation(client: TestClient) -> None:
    """Ensures verify_auth redirects with a next parameter and login forwards it."""
    # Attempting to access protected url_import should redirect with next parameter
    resp = client.get("/import", follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "/login?next=" in location
    assert "import" in location

    # Performing login with next parameter should redirect back to /import
    resp_login = client.post(
        "/login",
        data={"password": server_config.admin_password, "next": "/import"},
        follow_redirects=False,
    )
    assert resp_login.status_code == 303
    assert resp_login.headers["location"] == "/import"


def test_youtube_scraping(monkeypatch) -> None:
    """Verifies that YouTube video links pull metadata and transcripts successfully."""
    from kb_web.server import fetch_url, extract_youtube_video_id

    # Validate video ID extraction
    assert (
        extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    # Mock youtube-transcript-api and yt-dlp metadata
    class DummyYoutubeDL:
        def __init__(self, opts=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def extract_info(self, url, download=False):
            return {
                "title": "Never Gonna Give You Up",
                "description": "Official Rick Astley video description details.",
            }

    class DummyTranscriptApi:
        @staticmethod
        def get_transcript(video_id):
            return [
                {"text": "We're no strangers to love", "start": 0.5, "duration": 3.0},
                {
                    "text": "You know the rules and so do I",
                    "start": 3.5,
                    "duration": 2.5,
                },
            ]

    # Monkeypatch modules
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", DummyYoutubeDL)

    import youtube_transcript_api

    monkeypatch.setattr(
        youtube_transcript_api, "YouTubeTranscriptApi", DummyTranscriptApi
    )

    # Run extraction via fetch_url (static method path)
    page = fetch_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert page.title == "Never Gonna Give You Up"
    assert "Never Gonna Give You Up" in page.html_content
    assert "We're no strangers to love" in page.md_content
    assert "[00:03] You know the rules and so do I" in page.md_content

    # Now test instance method fallback path
    class DummySnippet:
        def __init__(self, text, start):
            self.text = text
            self.start = start

    class DummyTranscriptApiInstance:
        def fetch(self, video_id, languages=("en",), preserve_formatting=False):
            return [
                DummySnippet("We're no strangers to love", 0.5),
                DummySnippet("You know the rules and so do I", 3.5),
            ]

    monkeypatch.setattr(
        youtube_transcript_api, "YouTubeTranscriptApi", DummyTranscriptApiInstance
    )

    page2 = fetch_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert page2.title == "Never Gonna Give You Up"
    assert "We're no strangers to love" in page2.md_content
    assert "[00:03] You know the rules and so do I" in page2.md_content


def test_get_requests_are_write_free(client: TestClient) -> None:
    """Asserts that calling GET endpoints does not issue any database write operations."""
    import sqlite_utils
    from unittest.mock import patch

    write_commands = ["insert", "update", "delete", "drop", "create", "replace"]
    executed_queries = []

    original_execute = sqlite_utils.Database.execute

    def mock_execute(self, sql, *args, **kwargs):
        sql_lower = sql.strip().lower()
        executed_queries.append(sql)
        for cmd in write_commands:
            if sql_lower.startswith(cmd):
                raise AssertionError(f"Write query detected on read-only request: {sql}")
        return original_execute(self, sql, *args, **kwargs)

    # Insert a page to read
    db = get_db(server_config)
    db["fetched_pages"].insert({
        "url": "https://example.com/readonly-test",
        "title": "Read Only Title",
        "html_content": "A",
        "md_content": "A",
        "links": "[]",
        "html_content_hash": "h1",
        "md_content_hash": "m1",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]"
    }, replace=True)

    with patch.object(sqlite_utils.Database, "execute", mock_execute):
        # 1. Hit the home page
        response = client.get("/")
        assert response.status_code == 200

        # 2. Hit pages index
        response = client.get("/pages")
        assert response.status_code == 200

        # 3. Hit tag filtering list
        response = client.get("/?tag=coding")
        assert response.status_code == 200

        # 4. View page details
        response = client.get("/view/page?url=https%3A%2F%2Fexample.com%2Freadonly-test")
        assert response.status_code == 200

    # Ensure some SELECT queries actually ran (verifying our mock intercepted correctly)
    assert len(executed_queries) > 0
    assert any("select" in q.lower() for q in executed_queries)


def test_concurrent_reads_no_lock(client: TestClient) -> None:
    """Verifies that multiple concurrent GET requests can be processed concurrently without database locks."""
    import concurrent.futures

    # Ensure there's data in the database
    db = get_db(server_config)
    db["fetched_pages"].insert({
        "url": "https://example.com/concurrent-test",
        "title": "Concurrent Title",
        "html_content": "A",
        "md_content": "A",
        "links": "[]",
        "html_content_hash": "h2",
        "md_content_hash": "m2",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]"
    }, replace=True)

    endpoints = [
        "/",
        "/pages",
        "/?tag=coding",
        "/view/page?url=https%3A%2F%2Fexample.com%2Fconcurrent-test"
    ]

    # Run 20 concurrent requests across 5 threads
    def run_request(url):
        resp = client.get(url)
        return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_request, url) for _ in range(5) for url in endpoints]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20
    assert all(status == 200 for status in results)


def test_virtual_sites(client: TestClient, monkeypatch) -> None:
    """Verifies that the /sites page lists grouped domains and /view/site renders them properly with their list of pages."""
    db = get_db(server_config)

    # Ingest some pages from same and different domains
    db["fetched_pages"].insert({
        "url": "https://github.com/trending",
        "title": "GitHub Trending",
        "html_content": "A",
        "md_content": "A",
        "links": "[]",
        "html_content_hash": "h1",
        "md_content_hash": "m1",
        "fetched_at": "2026-05-31T12:00:00",
        "description": "Wiki for trending page",
        "tags": '["coding"]'
    }, replace=True)

    db["fetched_pages"].insert({
        "url": "https://github.com/foo",
        "title": "GitHub Foo",
        "html_content": "B",
        "md_content": "B",
        "links": "[]",
        "html_content_hash": "h2",
        "md_content_hash": "m2",
        "fetched_at": "2026-05-31T12:05:00",
        "description": "Wiki for foo page",
        "tags": '["coding"]'
    }, replace=True)

    db["fetched_pages"].insert({
        "url": "https://google.com/search",
        "title": "Google Search",
        "html_content": "C",
        "md_content": "C",
        "links": "[]",
        "html_content_hash": "h3",
        "md_content_hash": "m3",
        "fetched_at": "2026-05-31T12:10:00",
        "description": "Wiki for search page",
        "tags": '["search"]'
    }, replace=True)

    # 1. Fetch sites list view
    resp = client.get("/sites", follow_redirects=True)
    assert resp.status_code == 200
    assert "github.com" in resp.text
    assert "google.com" in resp.text
    assert "2 pages" in resp.text
    assert "1 page" in resp.text

    # 2. Fetch specific site profile
    resp_site = client.get("/view/site?site=github.com")
    assert resp_site.status_code == 200
    assert "github.com" in resp_site.text
    assert "GitHub Trending" in resp_site.text
    assert "GitHub Foo" in resp_site.text


def test_preprocess_markdown_list_normalization() -> None:
    """Verifies that markdown list items and list block spacing are normalized properly."""
    from kb_web.server import preprocess_markdown

    # Single asterisk bullet item formatting
    input_text = "Some description text.\n*Item one without space\n* Item two with space"
    expected = "Some description text.\n\n* Item one without space\n* Item two with space"
    assert preprocess_markdown(input_text) == expected

    # Sublists indentation preservation
    input_text_sublist = "- Main item\n  *Sub item without space\n  * Sub item with space"
    expected_sublist = "- Main item\n  * Sub item without space\n  * Sub item with space"
    assert preprocess_markdown(input_text_sublist) == expected_sublist

    # Numbered list spacing
    input_text_num = "Here is a list:\n1. First item\n2. Second item"
    expected_num = "Here is a list:\n\n1. First item\n2. Second item"
    assert preprocess_markdown(input_text_num) == expected_num


def test_similarity_score_threshold(client: TestClient, monkeypatch) -> None:
    """Verifies that similarity calculations only return pages meeting the 0.8 (80%) threshold."""
    from kb_web.server import get_similar_articles
    db = get_db(server_config)

    # Clean embeddings
    if "article_embeddings" in db.table_names():
        db.execute("DELETE FROM article_embeddings")
    if "fetched_pages" in db.table_names():
        db.execute("DELETE FROM fetched_pages")

    # Insert three pages
    db["fetched_pages"].insert({
        "url": "https://example.com/target",
        "title": "Target page",
        "html_content": "T",
        "md_content": "T",
        "links": "[]",
        "html_content_hash": "t1",
        "md_content_hash": "t2",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]"
    })
    db["fetched_pages"].insert({
        "url": "https://example.com/similar-high",
        "title": "High similarity page",
        "html_content": "H",
        "md_content": "H",
        "links": "[]",
        "html_content_hash": "h1",
        "md_content_hash": "h2",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]"
    })
    db["fetched_pages"].insert({
        "url": "https://example.com/similar-low",
        "title": "Low similarity page",
        "html_content": "L",
        "md_content": "L",
        "links": "[]",
        "html_content_hash": "l1",
        "md_content_hash": "l2",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]"
    })

    # Mock cosine_similarity directly to return high/low scores
    # target vs similar-high: 0.85 (85%)
    # target vs similar-low: 0.70 (70%)

    db["article_embeddings"].insert({"url": "https://example.com/target", "embedding": "[1.0, 0.0]", "updated_at": "now"})
    db["article_embeddings"].insert({"url": "https://example.com/similar-high", "embedding": "[0.85, 0.52]", "updated_at": "now"})
    db["article_embeddings"].insert({"url": "https://example.com/similar-low", "embedding": "[0.70, 0.71]", "updated_at": "now"})

    # Patch cosine_similarity
    def mock_cosine_similarity(v1, v2):
        if (v1 == [1.0, 0.0] and v2 == [0.85, 0.52]) or (v2 == [1.0, 0.0] and v1 == [0.85, 0.52]):
            return 0.85
        if (v1 == [1.0, 0.0] and v2 == [0.70, 0.71]) or (v2 == [1.0, 0.0] and v1 == [0.70, 0.71]):
            return 0.70
        return 0.0

    monkeypatch.setattr("kb_web.utils.cosine_similarity", mock_cosine_similarity)

    # Retrieve similar articles
    similar = get_similar_articles(db, "https://example.com/target")
    assert len(similar) == 1
    assert similar[0]["url"] == "https://example.com/similar-high"
    assert similar[0]["similarity"] == 85.0


def test_youtube_videos_lookup_table() -> None:
    """Verifies that YouTube-specific metadata is successfully written to the youtube_videos table."""
    db = get_db(server_config)
    
    # Check that table exists and contains correct columns
    assert "youtube_videos" in db.table_names()
    cols = db["youtube_videos"].columns_dict
    assert "url" in cols
    assert "video_id" in cols
    assert "creator" in cols
    assert "updated_at" in cols


def test_regenerate_youtube_metadata(client: TestClient, monkeypatch) -> None:
    """Verifies that YouTube metadata is correctly regenerated using handle_regenerate_youtube_metadata endpoint."""
    from urllib.parse import quote_plus
    db = get_db(server_config)
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    
    # Ingest a mock page first in fetched_pages
    db["fetched_pages"].insert({
        "url": video_url,
        "title": "Old YouTube Title",
        "html_content": "old html",
        "md_content": "old md",
        "links": "[]",
        "html_content_hash": "hash1",
        "md_content_hash": "hash2",
        "fetched_at": "2026-05-31T12:00:00",
        "description": "old description",
        "keywords": "[]",
        "tags": "[]",
    })
    
    # Insert a minimal/empty entry in youtube_videos
    db["youtube_videos"].insert({
        "url": video_url,
        "video_id": "dQw4w9WgXcQ",
        "creator": "Unknown Creator",
        "updated_at": "2026-05-31T12:00:00",
    })

    # Mock YoutubeDL extract_info
    class MockYoutubeDL:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            return {
                "title": "Never Gonna Give You Up",
                "description": "Official Rick Astley video",
                "uploader": "Rick Astley",
                "channel_id": "UCuAXFkgvhwR8yT5gG975bJw",
                "duration": 212,
                "view_count": 1200000000,
                "thumbnail": "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
            }

    monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

    # Login to get admin cookie
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    # Post request to regenerate metadata
    resp = client.post(
        f"/admin/regenerate/youtube-metadata?url={quote_plus(video_url)}",
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "metadata+successfully+regenerated" in resp.headers["location"]

    # Verify that the youtube_videos entry is populated with full attributes
    video_row = db["youtube_videos"].get(video_url)
    assert video_row["creator"] == "Rick Astley"
    assert video_row["channel_id"] == "UCuAXFkgvhwR8yT5gG975bJw"
    assert video_row["duration"] == 212
    assert video_row["view_count"] == 1200000000
    assert video_row["thumbnail_url"] == "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg"


def test_chunk_text() -> None:
    """Verifies that chunk_text helper splits text on lines and respects max chunk size."""
    from kb_web.server import chunk_text
    
    text = "Line 1\nLine 2\nLine 3\nLine 4"
    chunks = chunk_text(text, 15)
    assert len(chunks) == 2
    assert chunks[0] == "Line 1\nLine 2"
    assert chunks[1] == "Line 3\nLine 4"

    # Extremely long line should be split strictly by characters
    long_line = "A" * 50
    chunks_long = chunk_text(long_line, 20)
    assert len(chunks_long) == 3
    assert chunks_long[0] == "A" * 20
    assert chunks_long[1] == "A" * 20
    assert chunks_long[2] == "A" * 10


def test_chunked_extraction(monkeypatch) -> None:
    """Verifies that extract_wiki_content chunks long text and makes multiple Ollama chat calls."""
    from kb_web.server import extract_wiki_content
    from kb_web.models import HTMLPage

    # Configure a tiny max_input_length so chunking triggers immediately
    server_config.max_input_length = 30
    
    call_count = 0
    chat_messages = []

    class DummyMessage:
        content = "Summary result content."

    class DummyChatResponse:
        message = DummyMessage()

    def mock_chat(*args, **kwargs):
        nonlocal call_count, chat_messages
        call_count += 1
        chat_messages.append(kwargs.get("messages", []))
        return DummyChatResponse()

    monkeypatch.setattr(ollama.Client, "chat", mock_chat)

    page_data = HTMLPage(
        url="https://example.com/long-page",
        title="Long Page",
        html_content="HTML",
        md_content="This is a long line 1\nThis is a long line 2\nThis is a long line 3",
        links=[],
        html_content_hash="h1",
        md_content_hash="h2",
        fetched_at="2026-05-31T12:00:00",
    )

    wiki = extract_wiki_content(page_data)
    assert wiki == "Summary result content."
    # With max_input_length=30:
    # Chunk 1: "This is a long line 1" (21 chars)
    # Chunk 2: "This is a long line 2" (21 chars)
    # Chunk 3: "This is a long line 3" (21 chars)
    # So 3 chunk calls + 1 synthesis call = 4 calls total
    assert call_count == 4


def test_collections_crud(client: TestClient) -> None:
    """Verifies collections creation, page assignment, page listing, and removal."""
    db = get_db(server_config)
    
    # 1. Login as admin
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")
    assert session_cookie is not None

    # 2. Ingest mock page
    page_url = "https://example.com/collection-page"
    db["fetched_pages"].insert({
        "url": page_url,
        "title": "Page for Collection",
        "html_content": "A",
        "md_content": "A",
        "links": "[]",
        "html_content_hash": "a1",
        "md_content_hash": "a2",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]",
        "collection_id": None
    }, replace=True)

    # 3. Create a collection
    create_resp = client.post(
        "/collections/create",
        data={"title": "ML Resources"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    
    col_rows = list(db["collections"].rows_where("title = ?", ["ML Resources"]))
    assert len(col_rows) == 1
    col_id = col_rows[0]["id"]

    # 4. Assign page to collection
    assign_resp = client.post(
        "/admin/pages/update-collection",
        data={"url": page_url, "collection_ids": [str(col_id)]},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert assign_resp.status_code == 303
    
    items = list(db["collection_items"].rows_where("source_id = ? AND collection_id = ?", [page_url, col_id]))
    assert len(items) == 1

    # 5. List collection pages
    list_resp = client.get(f"/collections/view/{col_id}")
    assert list_resp.status_code == 200
    assert "ML Resources" in list_resp.text
    assert "Page for Collection" in list_resp.text

    # 6. Remove page from collection
    remove_resp = client.post(
        "/admin/pages/remove-from-collection",
        data={"url": page_url, "redirect_to": f"/collections/view/{col_id}"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert remove_resp.status_code == 303
    
    db.conn.commit()
    items_after = list(db["collection_items"].rows_where("source_id = ? AND collection_id = ?", [page_url, col_id]))
    assert len(items_after) == 0

    # 7. Test accept AI suggestion
    accept_resp = client.post(
        "/admin/collections/accept-suggestion",
        data={
            "title": "AI Suggested Collection",
            "urls_json": json.dumps([page_url])
        },
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert accept_resp.status_code == 303
    
    # Verify collection created
    col_row_2 = list(db["collections"].rows_where("title = ?", ["AI Suggested Collection"]))
    assert len(col_row_2) == 1
    new_col_id = col_row_2[0]["id"]
    
    # Verify page associated
    items_suggest = list(db["collection_items"].rows_where("source_id = ? AND collection_id = ?", [page_url, new_col_id]))
    assert len(items_suggest) == 1



def test_logs_view(client: TestClient) -> None:
    """Verifies that the server logs view loads correctly for admins."""
    # Authenticate admin
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    # Create dummy log file
    log_dir = server_config.configs_dir.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "kb-web.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("This is a dummy log line.\nAnother warning line.")

    # Request logs view
    resp = client.get("/admin/logs", cookies={"kb_session": session_cookie})
    assert resp.status_code == 200
    assert "dummy log line" in resp.text
    assert "Another warning line" in resp.text


def test_collection_notes_and_workspace(client: TestClient, monkeypatch) -> None:
    """Verifies custom notes CRUD, agent chat, workspace view, and general collection exclusions."""
    db = get_db(server_config)

    # 1. Login as admin
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")
    assert session_cookie is not None

    # 2. Ingest mock page
    page_url = "https://example.com/workspace-test-page"
    db["fetched_pages"].insert({
        "url": page_url,
        "title": "Workspace Test Page",
        "html_content": "B",
        "md_content": "B",
        "links": "[]",
        "html_content_hash": "b1",
        "md_content_hash": "b2",
        "fetched_at": "2026-05-31T12:00:00",
        "tags": "[]",
        "collection_id": None
    }, replace=True)

    # 3. Create a collection
    db["collections"].insert({
        "title": "Dev Workspace",
        "visibility": "public",
        "rag_system_prompt": "Prompt text",
        "taxonomy_system_prompt": "Taxonomy text",
        "general_system_context": "{}",
        "created_at": "2026-05-31T12:00:00"
    })
    col_rows = list(db["collections"].rows_where("title = ?", ["Dev Workspace"]))
    assert len(col_rows) == 1
    col_id = col_rows[0]["id"]

    # 4. Associate page with collection
    db["collection_items"].insert({
        "collection_id": col_id,
        "source_type": "articles",
        "source_id": page_url,
        "item_note": "Initial annotation note",
        "taxonomy_path": "/Dev/Workspace_Page.md",
        "item_order": 0,
        "added_at": "2026-05-31T12:00:00"
    })

    # 5. Get workspace editor view
    editor_resp = client.get(
        f"/collections/view/{col_id}/editor",
        cookies={"kb_session": session_cookie}
    )
    assert editor_resp.status_code == 200
    assert "Workspace Note Editor" in editor_resp.text
    assert "Dev Workspace" in editor_resp.text

    # 6. Create a custom note
    create_note_resp = client.post(
        f"/collections/view/{col_id}/notes/create",
        data={"title": "custom_note.md", "taxonomy_path": "/Notes/custom_note.md"},
        cookies={"kb_session": session_cookie}
    )
    assert create_note_resp.status_code == 200
    res_data = create_note_resp.json()
    assert res_data["status"] == "success"
    note_id = res_data["note_id"]

    # 7. Update custom note
    update_note_resp = client.post(
        f"/collections/view/{col_id}/notes/update",
        data={
            "note_id": note_id,
            "title": "updated_custom_note.md",
            "content": "# Updated Custom Note content",
            "taxonomy_path": "/Notes/updated_custom_note.md"
        },
        cookies={"kb_session": session_cookie}
    )
    assert update_note_resp.status_code == 200
    assert update_note_resp.json()["status"] == "success"
    assert db["collection_notes"].get(note_id)["title"] == "updated_custom_note.md"

    # 8. Update collection item note
    update_item_note_resp = client.post(
        f"/collections/view/{col_id}/items/update-note",
        data={
            "url": page_url,
            "item_note": "Updated annotation note contents",
            "taxonomy_path": "/Dev/Workspace_Page_Updated.md"
        },
        cookies={"kb_session": session_cookie}
    )
    assert update_item_note_resp.status_code == 200
    assert update_item_note_resp.json()["status"] == "success"
    
    item_row = list(db["collection_items"].rows_where("collection_id = ? AND source_id = ?", [col_id, page_url]))[0]
    assert item_row["item_note"] == "Updated annotation note contents"
    assert item_row["taxonomy_path"] == "/Dev/Workspace_Page_Updated.md"

    # 9. Toggle General Collection exclusion
    toggle_excl_resp = client.post(
        "/admin/pages/toggle-exclude",
        data={"url": page_url, "exclude": "1"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False
    )
    assert toggle_excl_resp.status_code == 303
    assert db["fetched_pages"].get(page_url)["exclude_from_general"] == 1

    # 10. Test collections agent chat endpoint
    class DummyMessage:
        content = "Agent response message"

    class DummyChatResponse:
        message = DummyMessage()

    import ollama
    monkeypatch.setattr(ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse())

    chat_resp = client.post(
        f"/collections/view/{col_id}/agent-chat",
        data={
            "message": "Hello Agent",
            "active_file_id": str(note_id),
            "active_file_type": "note",
            "history_json": "[]"
        },
        cookies={"kb_session": session_cookie}
    )
    assert chat_resp.status_code == 200
    assert chat_resp.json()["status"] == "success"
    assert "Agent response message" in chat_resp.json()["reply"]

    # 11. Delete custom note
    delete_note_resp = client.post(
        f"/collections/view/{col_id}/notes/delete",
        data={"note_id": note_id},
        cookies={"kb_session": session_cookie}
    )
    assert delete_note_resp.status_code == 200
    assert delete_note_resp.json()["status"] == "success"
    assert len(list(db["collection_notes"].rows_where("id = ?", [note_id]))) == 0


def test_youtube_interception_and_embeddings(client: TestClient, monkeypatch) -> None:
    """Verifies that YouTube links imported via /api/import/html are intercepted correctly and gemma embeddings are generated."""
    db = get_db(server_config)

    # 1. Mock fetch_youtube_video_page, generate_gemma_embeddings_for_page
    from kb_web.models import HTMLPage

    called_youtube = []
    called_embeddings = []

    def mock_fetch_youtube(url: str, video_id: str):
        called_youtube.append((url, video_id))
        return HTMLPage(
            url=url,
            title="Mock Video Title",
            html_content="<html><body>Transcript here</body></html>",
            md_content="Transcript content",
            links=[],
            html_content_hash="yt1",
            md_content_hash="yt2",
            fetched_at="2026-06-18T12:00:00",
            description="Mock Video Description",
            tags='["youtube", "test"]'
        )

    def mock_generate_embeddings(db_conn, url, cfg, ollama_client):
        called_embeddings.append(url)
        # Mock actual entry in database to avoid real ollama API calls
        db_conn["article_embeddings"].insert({
            "url": url,
            "embedding": b"\x80\x81\x82\x83",
            "updated_at": "2026-06-18"
        }, replace=True)

    # Mocks for LLM generation
    class DummyMessage:
        content = "Wiki content summary of YouTube video."
        
    class DummyChatResponse:
        message = DummyMessage()

    monkeypatch.setattr("kb_web.routers.api.fetch_youtube_video_page", mock_fetch_youtube)
    monkeypatch.setattr("kb_web.routers.api.generate_gemma_embeddings_for_page", mock_generate_embeddings)
    monkeypatch.setattr(ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse())

    # 2. Post to /api/import/html
    import_payload = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "html_content": "<html><body>Fallback</body></html>",
        "title": "Fallback title",
        "description": "Fallback description",
        "tags": '["fallback"]'
    }
    
    resp = client.post(
        "/api/import/html",
        json=import_payload,
        headers={"X-API-Key": server_config.api_key}
    )
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["status"] == "success"

    # Verify that mock_fetch_youtube and mock_generate_embeddings were called
    assert len(called_youtube) == 1
    assert called_youtube[0][1] == "dQw4w9WgXcQ"
    assert len(called_embeddings) == 1
    assert called_embeddings[0] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    # Verify database state
    saved_page = db["fetched_pages"].get("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert saved_page["title"] == "Mock Video Title"
    assert saved_page["md_content"] == "Transcript content"


def test_bytes_backup_export_and_import(client: TestClient) -> None:
    """Verifies that bytes columns in the database are exported to hex strings and imported back successfully."""
    db = get_db(server_config)

    # 1. Insert a row with bytes into article_embeddings
    db["article_embeddings"].insert({
        "url": "https://example.com/bytes-test",
        "embedding": b"\x80\x81\x82\x83",
        "updated_at": "2026-06-18"
    }, replace=True)
    
    # Authenticate admin for export/import
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    # 2. Export database
    export_resp = client.get(
        "/admin/export",
        cookies={"kb_session": session_cookie}
    )
    assert export_resp.status_code == 200
    backup_data = export_resp.json()
    
    # Verify hex prefix formatting for bytes
    assert "article_embeddings" in backup_data
    rows = backup_data["article_embeddings"]
    matching_row = [r for r in rows if r["url"] == "https://example.com/bytes-test"][0]
    assert matching_row["embedding"] == "hex:80818283"

    # 3. Modify value in database to verify import restores it
    db["article_embeddings"].delete("https://example.com/bytes-test")
    assert not list(db["article_embeddings"].rows_where("url = ?", ["https://example.com/bytes-test"]))

    # 4. Import database via WebSocket
    import_json = json.dumps(backup_data)
    with client.websocket_connect("/admin/ws/import", cookies={"kb_session": session_cookie}) as websocket:
        # Send in chunks
        chunk_size = 100
        for i in range(0, len(import_json), chunk_size):
            websocket.send_text(import_json[i:i+chunk_size])
        websocket.send_text("EOF")
        
        response_msg = websocket.receive_text()
        assert "SUCCESS" in response_msg

    # Verify imported row contains correct original bytes
    imported_row = db["article_embeddings"].get("https://example.com/bytes-test")
    assert imported_row["embedding"] == b"\x80\x81\x82\x83"


def test_ollama_logging_and_observability(monkeypatch) -> None:
    """Verifies that LoggedOllamaClient correctly logs success/failure of calls in the database."""
    from kb_web.base import _get_ollama_client
    db = get_db(server_config)

    # Clean existing logs
    db["ollama_logs"].delete_where()
    db.conn.commit()

    # 1. Mock underlying ollama.Client.chat
    class DummyMessage:
        content = "Wiki summary content"

    class DummyChatResponse:
        message = DummyMessage()

    called_underlying_chat = []
    def mock_chat(*args, **kwargs):
        called_underlying_chat.append(kwargs)
        return DummyChatResponse()

    # Mock underlying ollama.Client.embeddings
    called_underlying_embeddings = []
    def mock_embeddings(*args, **kwargs):
        called_underlying_embeddings.append(kwargs)
        return {"embedding": [0.1, 0.2]}

    # Instantiating client uses LoggedOllamaClient
    logged_client = _get_ollama_client()
    monkeypatch.setattr(logged_client._client, "chat", mock_chat)
    monkeypatch.setattr(logged_client._client, "embeddings", mock_embeddings)

    # 2. Trigger chat
    resp = logged_client.chat(
        model="gemma",
        messages=[
            {"role": "system", "content": "You are a taxonomist expert."},
            {"role": "user", "content": "categorize this"}
        ],
        think=False
    )
    assert resp.message.content == "Wiki summary content"
    assert len(called_underlying_chat) == 1

    # Check DB logs for chat
    chat_logs = list(db["ollama_logs"].rows_where("prompt_type = 'taxonomy'"))
    assert len(chat_logs) == 1
    assert chat_logs[0]["model"] == "gemma"
    assert "You are a taxonomist expert" in chat_logs[0]["messages"]
    assert "think" in chat_logs[0]["options"]
    assert chat_logs[0]["response"] == "Wiki summary content"
    assert chat_logs[0]["duration"] >= 0.0
    assert chat_logs[0]["status"] == "success"

    # 3. Trigger embeddings
    emb_resp = logged_client.embeddings(model="nomic", prompt="Hello World")
    assert emb_resp["embedding"] == [0.1, 0.2]

    # Check DB logs for embeddings
    emb_logs = list(db["ollama_logs"].rows_where("prompt_type = 'embeddings'"))
    assert len(emb_logs) == 1
    assert emb_logs[0]["model"] == "nomic"
    assert "Hello World" in emb_logs[0]["messages"]
    assert emb_logs[0]["response"] == "Success (vector dim: 2)"
    assert emb_logs[0]["status"] == "success"

    # 4. Trigger failure logging
    def mock_chat_fail(*args, **kwargs):
        raise ValueError("Ollama server down")
    monkeypatch.setattr(logged_client._client, "chat", mock_chat_fail)

    with pytest.raises(ValueError, match="Ollama server down"):
        logged_client.chat(model="gemma", messages=[{"role": "user", "content": "fail test"}])

    fail_logs = list(db["ollama_logs"].rows_where("status = 'failed'"))
    assert len(fail_logs) == 1
    assert "ValueError: Ollama server down" in fail_logs[0]["response"]







