import json
import ollama
import pytest
from fastapi.testclient import TestClient

from kb_web.config import Config
from kb_web.db import get_db
from kb_web.models import HTMLPage
from kb_web.server import app
from kb_web.server import config as server_config
from kb_web.models_orm import (
    Base, FetchedPage, PageVersion, YouTubeVideo, Collection, CollectionItem, CollectionNote, CollectionAction,
    ChunkEmbedding, ArticleEmbedding, VideoEmbedding, TitleEmbedding, OllamaLog, SettingOllama, SettingExternal,
    AgentPrompt, CliApiKey, RegisteredClient, SystemLog, Link
)

TABLE_TO_MODEL = {
    "fetched_pages": FetchedPage,
    "page_versions": PageVersion,
    "youtube_videos": YouTubeVideo,
    "collections": Collection,
    "collection_items": CollectionItem,
    "collection_notes": CollectionNote,
    "collection_actions": CollectionAction,
    "chunk_embeddings": ChunkEmbedding,
    "article_embeddings": ArticleEmbedding,
    "video_embeddings": VideoEmbedding,
    "title_embeddings": TitleEmbedding,
    "ollama_logs": OllamaLog,
    "settings_ollama": SettingOllama,
    "settings_external": SettingExternal,
    "agent_prompts": AgentPrompt,
    "cli_api_keys": CliApiKey,
    "registered_clients": RegisteredClient,
    "system_logs": SystemLog,
    "links": Link,
}

class TableAdapter:
    def __init__(self, table_name, db_adapter):
        self.table_name = table_name
        self.db_adapter = db_adapter
        self.model_cls = TABLE_TO_MODEL[table_name]

    def insert(self, record, replace=True, pk=None):
        from kb_web.base import db_session
        from kb_web.models_orm import SafeVector
        clean_record = {}
        for k, v in record.items():
            if k in self.model_cls.__table__.columns:
                col_type = self.model_cls.__table__.columns[k].type
                if isinstance(col_type, SafeVector):
                    clean_record[k] = v
                elif isinstance(v, (list, dict)):
                    clean_record[k] = json.dumps(v)
                else:
                    clean_record[k] = v
            else:
                if isinstance(v, (list, dict)):
                    clean_record[k] = json.dumps(v)
                else:
                    clean_record[k] = v

        with db_session() as session:
            pks = [c.name for c in self.model_cls.__table__.primary_key.columns]
            pk_vals = {pk_col: clean_record[pk_col] for pk_col in pks if pk_col in clean_record}
            
            existing = None
            if len(pk_vals) == len(pks) and pks:
                existing = session.query(self.model_cls).filter_by(**pk_vals).first()
            
            if existing and replace:
                for k, v in clean_record.items():
                    setattr(existing, k, v)
            else:
                session.add(self.model_cls(**clean_record))
        return self

    def upsert(self, record, pk=None):
        return self.insert(record, replace=True, pk=pk)

    def insert_all(self, records, pk=None, replace=True):
        for r in records:
            self.insert(r, replace=replace, pk=pk)
        return self

    def get(self, pk_value):
        from kb_web.base import db_session
        with db_session() as session:
            pks = [c.name for c in self.model_cls.__table__.primary_key.columns]
            if not pks:
                raise KeyError("No primary key found for table.")
            if isinstance(pk_value, tuple):
                filter_kwargs = {pks[i]: pk_value[i] for i in range(len(pk_value))}
            else:
                filter_kwargs = {pks[0]: pk_value}
            
            row = session.query(self.model_cls).filter_by(**filter_kwargs).first()
            if not row:
                from sqlite_utils.db import NotFoundError
                raise NotFoundError(f"Record {pk_value} not found.")
            
            res = {}
            for col in row.__table__.columns:
                val = getattr(row, col.name)
                res[col.name] = val
            return res

    def update(self, pk_value, record):
        from kb_web.base import db_session
        with db_session() as session:
            pks = [c.name for c in self.model_cls.__table__.primary_key.columns]
            if isinstance(pk_value, tuple):
                filter_kwargs = {pks[i]: pk_value[i] for i in range(len(pk_value))}
            else:
                filter_kwargs = {pks[0]: pk_value}
            row = session.query(self.model_cls).filter_by(**filter_kwargs).first()
            if row:
                for k, v in record.items():
                    if isinstance(v, (list, dict)):
                        setattr(row, k, json.dumps(v))
                    else:
                        setattr(row, k, v)
        return self

    def delete(self, pk_value):
        from kb_web.base import db_session
        with db_session() as session:
            pks = [c.name for c in self.model_cls.__table__.primary_key.columns]
            if isinstance(pk_value, tuple):
                filter_kwargs = {pks[i]: pk_value[i] for i in range(len(pk_value))}
            else:
                filter_kwargs = {pks[0]: pk_value}
            session.query(self.model_cls).filter_by(**filter_kwargs).delete()
        return self

    def delete_where(self, clause=None, params=None):
        from kb_web.base import db_session
        with db_session() as session:
            from sqlalchemy import text
            if not clause:
                sql = f"DELETE FROM {self.table_name}"
                session.execute(text(sql))
            else:
                sql = clause
                bind_params = {}
                if params:
                    for idx, val in enumerate(params):
                        bind_params[f"param_{idx}"] = val
                    for idx in range(len(params)):
                        sql = sql.replace("?", f":param_{idx}", 1)
                sql = f"DELETE FROM {self.table_name} WHERE {sql}"
                session.execute(text(sql), bind_params)
        return self

    def count_where(self, clause, params=None):
        from kb_web.base import db_session
        with db_session() as session:
            from sqlalchemy import text
            sql = clause
            bind_params = {}
            if params:
                for idx, val in enumerate(params):
                    bind_params[f"param_{idx}"] = val
                for idx in range(len(params)):
                    sql = sql.replace("?", f":param_{idx}", 1)
            full_sql = f"SELECT COUNT(*) FROM {self.table_name} WHERE {sql}"
            res = session.execute(text(full_sql), bind_params).scalar()
            return res or 0

    def rows_where(self, clause, params=None, order_by=None):
        from kb_web.base import db_session
        with db_session() as session:
            from sqlalchemy import text
            sql = clause
            bind_params = {}
            if params:
                for idx, val in enumerate(params):
                    bind_params[f"param_{idx}"] = val
                for idx in range(len(params)):
                    sql = sql.replace("?", f":param_{idx}", 1)
            full_sql = f"SELECT * FROM {self.table_name}"
            if sql.strip():
                full_sql += f" WHERE {sql}"
            if order_by:
                full_sql += f" ORDER BY {order_by}"
            res = session.execute(text(full_sql), bind_params).mappings().all()
            return [dict(r) for r in res]

    @property
    def rows(self):
        from kb_web.base import db_session
        with db_session() as session:
            rows = session.query(self.model_cls).all()
            res = []
            for row in rows:
                r_dict = {}
                for col in row.__table__.columns:
                    r_dict[col.name] = getattr(row, col.name)
                res.append(r_dict)
            return res

    @property
    def columns_dict(self):
        res = {}
        for col in self.model_cls.__table__.columns:
            py_type = str
            if hasattr(col.type, "python_type"):
                try:
                    py_type = col.type.python_type
                except Exception:
                    pass
            res[col.name] = py_type
        return res

class DBAdapter:
    def __init__(self):
        pass

    def __getitem__(self, key):
        return TableAdapter(key, self)

    def table_names(self):
        return list(TABLE_TO_MODEL.keys())

    def execute(self, sql, params=None):
        from kb_web.base import db_session
        from sqlalchemy import text
        bind_params = {}
        if params:
            for idx, val in enumerate(params):
                bind_params[f"param_{idx}"] = val
            for idx in range(len(params)):
                sql = sql.replace("?", f":param_{idx}", 1)
        with db_session() as session:
            session.execute(text(sql), bind_params)
        return self

    def execute_returning_dicts(self, sql, params=None):
        from kb_web.base import db_session
        from sqlalchemy import text
        bind_params = {}
        if params:
            for idx, val in enumerate(params):
                bind_params[f"param_{idx}"] = val
            for idx in range(len(params)):
                sql = sql.replace("?", f":param_{idx}", 1)
        with db_session() as session:
            res = session.execute(text(sql), bind_params).mappings().all()
            return [dict(r) for r in res]

    @property
    def conn(self):
        class DummyConn:
            def commit(self):
                pass
            def close(self):
                pass
        return DummyConn()

import socket

def postgresql_available():
    try:
        with socket.create_connection(("localhost", 5433), timeout=1):
            return True
    except Exception:
        return False

db_params = ["sqlite"]
if postgresql_available():
    db_params.append("postgresql")

@pytest.fixture(params=db_params, autouse=True)
def setup_temp_db(request, tmp_path, monkeypatch) -> None:
    """Fixture to override config database path/url, isolating test DB state."""
    db_type = request.param
    
    old_database_url = server_config.database_url
    old_db_path = server_config.db_path
    old_configs_dir = server_config.configs_dir

    server_config.configs_dir = tmp_path / "configs"
    if db_type == "sqlite":
        temp_db = tmp_path / "test_kb.db"
        server_config.database_url = ""
        server_config.db_path = temp_db
    else:
        server_config.database_url = "postgresql+psycopg2://postgres:password@localhost:5433/kb_test"

    # Reset cached SQLAlchemy engine/SessionFactory to force reconnection
    import kb_web.base
    kb_web.base._engine = None
    kb_web.base._SessionFactory = None

    # Setup the database with tables using SQLAlchemy
    from kb_web.base import get_engine
    engine = get_engine()
    if db_type == "postgresql":
        # Drop all tables first for PostgreSQL clean test state
        Base.metadata.drop_all(engine)
    
    Base.metadata.create_all(engine)

    from kb_web.db import init_db
    init_db(None)

    # Monkeypatch the get_db helpers to use the SQLAlchemy adapter
    import sys
    monkeypatch.setattr(sys.modules[__name__], "get_db", lambda *args, **kwargs: DBAdapter())
    monkeypatch.setattr("kb_web.db.get_db", lambda *args, **kwargs: DBAdapter())
    monkeypatch.setattr("kb_web.base._get_db", lambda *args, **kwargs: DBAdapter())

    # Mock Ollama Client embeddings, list, and pull globally to keep tests fast and offline
    monkeypatch.setattr(
        ollama.Client, "embeddings", lambda *args, **kwargs: {"embedding": [0.1] * 1536}
    )
    monkeypatch.setattr(
        ollama.Client,
        "list",
        lambda *args, **kwargs: {"models": [{"name": "nomic-embed-text:latest"}]},
    )
    monkeypatch.setattr(ollama.Client, "pull", lambda *args, **kwargs: None)

    # Mock Gotify globally during tests to prevent real notifications if credentials exist in the environment
    class DummyGotify:
        def __init__(self, *args, **kwargs):
            self.POST_ENABLED = False

        def send_notification(self, *args, **kwargs) -> None:
            pass

    import kb_core.notifier
    import kb_web.config

    monkeypatch.setattr(kb_core.notifier, "Gotify", DummyGotify)
    monkeypatch.setattr(kb_web.config, "Gotify", DummyGotify)

    yield

    # Restore path after execution completes
    server_config.database_url = old_database_url
    server_config.db_path = old_db_path
    server_config.configs_dir = old_configs_dir
    
    # Clean up/reset engine cache again at end of test
    kb_web.base._engine = None
    kb_web.base._SessionFactory = None


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
                raise AssertionError(
                    f"Write query detected on read-only request: {sql}"
                )
        return original_execute(self, sql, *args, **kwargs)

    from sqlalchemy.engine.base import Connection
    original_execute_sqla = Connection.execute

    def mock_execute_sqla(self, statement, *args, **kwargs):
        sql_str = str(statement).strip().lower()
        executed_queries.append(sql_str)
        for cmd in write_commands:
            if sql_str.startswith(cmd):
                raise AssertionError(
                    f"Write query detected on read-only request: {sql_str}"
                )
        return original_execute_sqla(self, statement, *args, **kwargs)

    # Insert a page to read
    db = get_db(server_config)
    db["fetched_pages"].insert(
        {
            "url": "https://example.com/readonly-test",
            "title": "Read Only Title",
            "html_content": "A",
            "md_content": "A",
            "links": "[]",
            "html_content_hash": "h1",
            "md_content_hash": "m1",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
        },
        replace=True,
    )

    with patch.object(sqlite_utils.Database, "execute", mock_execute), \
         patch.object(Connection, "execute", mock_execute_sqla):
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
        response = client.get(
            "/view/page?url=https%3A%2F%2Fexample.com%2Freadonly-test"
        )
        assert response.status_code == 200

    # Ensure some SELECT queries actually ran (verifying our mock intercepted correctly)
    assert len(executed_queries) > 0
    assert any("select" in q.lower() for q in executed_queries)


def test_concurrent_reads_no_lock(client: TestClient) -> None:
    """Verifies that multiple concurrent GET requests can be processed concurrently without database locks."""
    import concurrent.futures

    # Ensure there's data in the database
    db = get_db(server_config)
    db["fetched_pages"].insert(
        {
            "url": "https://example.com/concurrent-test",
            "title": "Concurrent Title",
            "html_content": "A",
            "md_content": "A",
            "links": "[]",
            "html_content_hash": "h2",
            "md_content_hash": "m2",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
        },
        replace=True,
    )

    endpoints = [
        "/",
        "/pages",
        "/?tag=coding",
        "/view/page?url=https%3A%2F%2Fexample.com%2Fconcurrent-test",
    ]

    # Run 20 concurrent requests across 5 threads
    def run_request(url):
        resp = client.get(url)
        return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(run_request, url) for _ in range(5) for url in endpoints
        ]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 20
    assert all(status == 200 for status in results)


def test_virtual_sites(client: TestClient, monkeypatch) -> None:
    """Verifies that the /sites page lists grouped domains and /view/site renders them properly with their list of pages."""
    db = get_db(server_config)

    # Ingest some pages from same and different domains
    db["fetched_pages"].insert(
        {
            "url": "https://github.com/trending",
            "title": "GitHub Trending",
            "html_content": "A",
            "md_content": "A",
            "links": "[]",
            "html_content_hash": "h1",
            "md_content_hash": "m1",
            "fetched_at": "2026-05-31T12:00:00",
            "description": "Wiki for trending page",
            "tags": '["coding"]',
        },
        replace=True,
    )

    db["fetched_pages"].insert(
        {
            "url": "https://github.com/foo",
            "title": "GitHub Foo",
            "html_content": "B",
            "md_content": "B",
            "links": "[]",
            "html_content_hash": "h2",
            "md_content_hash": "m2",
            "fetched_at": "2026-05-31T12:05:00",
            "description": "Wiki for foo page",
            "tags": '["coding"]',
        },
        replace=True,
    )

    db["fetched_pages"].insert(
        {
            "url": "https://google.com/search",
            "title": "Google Search",
            "html_content": "C",
            "md_content": "C",
            "links": "[]",
            "html_content_hash": "h3",
            "md_content_hash": "m3",
            "fetched_at": "2026-05-31T12:10:00",
            "description": "Wiki for search page",
            "tags": '["search"]',
        },
        replace=True,
    )

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
    input_text = (
        "Some description text.\n*Item one without space\n* Item two with space"
    )
    expected = (
        "Some description text.\n\n* Item one without space\n* Item two with space"
    )
    assert preprocess_markdown(input_text) == expected

    # Sublists indentation preservation
    input_text_sublist = (
        "- Main item\n  *Sub item without space\n  * Sub item with space"
    )
    expected_sublist = (
        "- Main item\n  * Sub item without space\n  * Sub item with space"
    )
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
    db["fetched_pages"].insert(
        {
            "url": "https://example.com/target",
            "title": "Target page",
            "html_content": "T",
            "md_content": "T",
            "links": "[]",
            "html_content_hash": "t1",
            "md_content_hash": "t2",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
        }
    )
    db["fetched_pages"].insert(
        {
            "url": "https://example.com/similar-high",
            "title": "High similarity page",
            "html_content": "H",
            "md_content": "H",
            "links": "[]",
            "html_content_hash": "h1",
            "md_content_hash": "h2",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
        }
    )
    db["fetched_pages"].insert(
        {
            "url": "https://example.com/similar-low",
            "title": "Low similarity page",
            "html_content": "L",
            "md_content": "L",
            "links": "[]",
            "html_content_hash": "l1",
            "md_content_hash": "l2",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
        }
    )

    # Mock cosine_similarity directly to return high/low scores
    # target vs similar-high: 0.85 (85%)
    # target vs similar-low: 0.70 (70%)

    db["article_embeddings"].insert(
        {
            "url": "https://example.com/target",
            "embedding": [1.0, 0.0] + [0.0] * 1534,
            "updated_at": "now",
        }
    )
    db["article_embeddings"].insert(
        {
            "url": "https://example.com/similar-high",
            "embedding": [0.85, 0.52] + [0.0] * 1534,
            "updated_at": "now",
        }
    )
    db["article_embeddings"].insert(
        {
            "url": "https://example.com/similar-low",
            "embedding": [0.70, 0.71] + [0.0] * 1534,
            "updated_at": "now",
        }
    )

    # Patch cosine_similarity
    def mock_cosine_similarity(v1, v2):
        v1_2d = list(v1)[:2] if v1 else []
        v2_2d = list(v2)[:2] if v2 else []
        if (v1_2d == [1.0, 0.0] and v2_2d == [0.85, 0.52]) or (
            v2_2d == [1.0, 0.0] and v1_2d == [0.85, 0.52]
        ):
            return 0.85
        if (v1_2d == [1.0, 0.0] and v2_2d == [0.70, 0.71]) or (
            v2_2d == [1.0, 0.0] and v1_2d == [0.70, 0.71]
        ):
            return 0.70
        return 0.0

    monkeypatch.setattr("kb_web.utils.cosine_similarity", mock_cosine_similarity)

    # Retrieve similar articles
    similar = get_similar_articles(db, "https://example.com/target")
    assert len(similar) == 1
    assert similar[0]["url"] == "https://example.com/similar-high"
    assert similar[0]["similarity"] in (85.0, 85.3)


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
    db["fetched_pages"].insert(
        {
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
        }
    )

    # Insert a minimal/empty entry in youtube_videos
    db["youtube_videos"].insert(
        {
            "url": video_url,
            "video_id": "dQw4w9WgXcQ",
            "creator": "Unknown Creator",
            "updated_at": "2026-05-31T12:00:00",
        }
    )

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
    assert (
        video_row["thumbnail_url"]
        == "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
    )


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
    db["fetched_pages"].insert(
        {
            "url": page_url,
            "title": "Page for Collection",
            "html_content": "A",
            "md_content": "A",
            "links": "[]",
            "html_content_hash": "a1",
            "md_content_hash": "a2",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
            "collection_id": None,
        },
        replace=True,
    )

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

    items = list(
        db["collection_items"].rows_where(
            "source_id = ? AND collection_id = ?", [page_url, col_id]
        )
    )
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
    items_after = list(
        db["collection_items"].rows_where(
            "source_id = ? AND collection_id = ?", [page_url, col_id]
        )
    )
    assert len(items_after) == 0

    # 7. Test accept AI suggestion
    accept_resp = client.post(
        "/admin/collections/accept-suggestion",
        data={"title": "AI Suggested Collection", "urls_json": json.dumps([page_url])},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert accept_resp.status_code == 303

    # Verify collection created
    col_row_2 = list(
        db["collections"].rows_where("title = ?", ["AI Suggested Collection"])
    )
    assert len(col_row_2) == 1
    new_col_id = col_row_2[0]["id"]

    # Verify page associated
    items_suggest = list(
        db["collection_items"].rows_where(
            "source_id = ? AND collection_id = ?", [page_url, new_col_id]
        )
    )
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

    # Seed the DB logs table
    db = get_db(server_config)
    db["system_logs"].insert(
        {
            "timestamp": "2026-05-31T12:00:00",
            "level": "INFO",
            "module": "test",
            "message": "This is a dummy log line.",
            "traceback": "",
        }
    )
    db["system_logs"].insert(
        {
            "timestamp": "2026-05-31T12:01:00",
            "level": "WARNING",
            "module": "test",
            "message": "Another warning line.",
            "traceback": "",
        }
    )

    # Request logs view
    resp = client.get("/admin/logs", cookies={"kb_session": session_cookie})
    print("RESPONSE TEXT IS:\n", resp.text)
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
    db["fetched_pages"].insert(
        {
            "url": page_url,
            "title": "Workspace Test Page",
            "html_content": "B",
            "md_content": "B",
            "links": "[]",
            "html_content_hash": "b1",
            "md_content_hash": "b2",
            "fetched_at": "2026-05-31T12:00:00",
            "tags": "[]",
            "collection_id": None,
        },
        replace=True,
    )

    # 3. Create a collection
    db["collections"].insert(
        {
            "title": "Dev Workspace",
            "visibility": "public",
            "rag_system_prompt": "Prompt text",
            "taxonomy_system_prompt": "Taxonomy text",
            "general_system_context": "{}",
            "created_at": "2026-05-31T12:00:00",
        }
    )
    col_rows = list(db["collections"].rows_where("title = ?", ["Dev Workspace"]))
    assert len(col_rows) == 1
    col_id = col_rows[0]["id"]

    # 4. Associate page with collection
    db["collection_items"].insert(
        {
            "collection_id": col_id,
            "source_type": "articles",
            "source_id": page_url,
            "item_note": "Initial annotation note",
            "taxonomy_path": "/Dev/Workspace_Page.md",
            "item_order": 0,
            "added_at": "2026-05-31T12:00:00",
        }
    )

    # 5. Get workspace editor view
    editor_resp = client.get(
        f"/collections/view/{col_id}/editor", cookies={"kb_session": session_cookie}
    )
    assert editor_resp.status_code == 200
    assert "Workspace Note Editor" in editor_resp.text
    assert "Dev Workspace" in editor_resp.text

    # 6. Create a custom note
    create_note_resp = client.post(
        f"/collections/view/{col_id}/notes/create",
        data={"title": "custom_note.md", "taxonomy_path": "/Notes/custom_note.md"},
        cookies={"kb_session": session_cookie},
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
            "taxonomy_path": "/Notes/updated_custom_note.md",
        },
        cookies={"kb_session": session_cookie},
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
            "taxonomy_path": "/Dev/Workspace_Page_Updated.md",
        },
        cookies={"kb_session": session_cookie},
    )
    assert update_item_note_resp.status_code == 200
    assert update_item_note_resp.json()["status"] == "success"

    item_row = list(
        db["collection_items"].rows_where(
            "collection_id = ? AND source_id = ?", [col_id, page_url]
        )
    )[0]
    assert item_row["item_note"] == "Updated annotation note contents"
    assert item_row["taxonomy_path"] == "/Dev/Workspace_Page_Updated.md"

    # 9. Toggle General Collection exclusion
    toggle_excl_resp = client.post(
        "/admin/pages/toggle-exclude",
        data={"url": page_url, "exclude": "1"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert toggle_excl_resp.status_code == 303
    assert db["fetched_pages"].get(page_url)["exclude_from_general"] == 1

    # 10. Test collections agent chat endpoint
    class DummyMessage:
        content = "Agent response message"

    class DummyChatResponse:
        message = DummyMessage()

    import ollama

    monkeypatch.setattr(
        ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse()
    )

    chat_resp = client.post(
        f"/collections/view/{col_id}/agent-chat",
        data={
            "message": "Hello Agent",
            "active_file_id": str(note_id),
            "active_file_type": "note",
            "history_json": "[]",
        },
        cookies={"kb_session": session_cookie},
    )
    assert chat_resp.status_code == 200
    assert chat_resp.json()["status"] == "success"
    assert "Agent response message" in chat_resp.json()["reply"]

    # 11. Delete custom note
    delete_note_resp = client.post(
        f"/collections/view/{col_id}/notes/delete",
        data={"note_id": note_id},
        cookies={"kb_session": session_cookie},
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
            tags='["youtube", "test"]',
        )

    def mock_generate_embeddings(db_conn, url, cfg, ollama_client):
        called_embeddings.append(url)
        # Mock actual entry in database to avoid real ollama API calls
        db["article_embeddings"].insert(
            {"url": url, "embedding": [0.1] * 1536, "updated_at": "2026-06-18"},
            replace=True,
        )

    # Mocks for LLM generation
    class DummyMessage:
        content = "Wiki content summary of YouTube video."

    class DummyChatResponse:
        message = DummyMessage()

    monkeypatch.setattr(
        "kb_web.routers.api.fetch_youtube_video_page", mock_fetch_youtube
    )
    monkeypatch.setattr(
        "kb_web.routers.api.generate_gemma_embeddings_for_page",
        mock_generate_embeddings,
    )
    monkeypatch.setattr(
        ollama.Client, "chat", lambda *args, **kwargs: DummyChatResponse()
    )

    # 2. Post to /api/import/html
    import_payload = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "html_content": "<html><body>Fallback</body></html>",
        "title": "Fallback title",
        "description": "Fallback description",
        "tags": '["fallback"]',
    }

    resp = client.post(
        "/api/import/html",
        json=import_payload,
        headers={"X-API-Key": server_config.api_key},
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
    from sqlalchemy import Column, String, LargeBinary
    from kb_web.base import get_engine, db_session

    DummyBytesModel = None
    if hasattr(Base, "registry"):
        for m in list(Base.registry.mappers):
            if m.class_.__name__ == "DummyBytesModel":
                DummyBytesModel = m.class_
                break

    if DummyBytesModel is None:
        class DummyBytesModel(Base):
            __tablename__ = "dummy_bytes_table"
            id = Column(String, primary_key=True)
            data = Column(LargeBinary)

    TABLE_TO_MODEL["dummy_bytes_table"] = DummyBytesModel
    
    engine = get_engine()
    # Re-create dummy_bytes_table schema just in case
    try:
        DummyBytesModel.__table__.create(engine)
    except Exception:
        pass
    
    db = get_db(server_config)

    try:
        # 1. Insert a row with bytes into dummy_bytes_table
        db["dummy_bytes_table"].insert(
            {
                "id": "test-id",
                "data": b"\x80\x81\x82\x83",
            },
            replace=True,
        )

        # Authenticate admin for export/import
        login_resp = client.post(
            "/login",
            data={"password": server_config.admin_password},
            follow_redirects=False,
        )
        session_cookie = login_resp.cookies.get("kb_session")

        # 2. Export database
        export_resp = client.get("/admin/export", cookies={"kb_session": session_cookie})
        assert export_resp.status_code == 200
        backup_data = export_resp.json()

        # Verify hex prefix formatting for bytes
        assert "dummy_bytes_table" in backup_data
        rows = backup_data["dummy_bytes_table"]
        matching_row = [r for r in rows if r["id"] == "test-id"][0]
        assert matching_row["data"] == "hex:80818283"

        # 3. Modify value in database to verify import restores it
        db["dummy_bytes_table"].delete("test-id")
        assert not list(
            db["dummy_bytes_table"].rows_where(
                "id = ?", ["test-id"]
            )
        )

        # 4. Import database via WebSocket
        import_json = json.dumps(backup_data)
        with client.websocket_connect(
            "/admin/ws/import", cookies={"kb_session": session_cookie}
        ) as websocket:
            # Send in chunks
            chunk_size = 100
            for i in range(0, len(import_json), chunk_size):
                websocket.send_text(import_json[i : i + chunk_size])
            websocket.send_text("EOF")

            response_msg = websocket.receive_text()
            assert "SUCCESS" in response_msg

        # Verify imported row contains correct original bytes
        imported_row = db["dummy_bytes_table"].get("test-id")
        assert imported_row["data"] == b"\x80\x81\x82\x83"

    finally:
        # Clean up database table
        try:
            DummyBytesModel.__table__.drop(engine)
        except Exception:
            pass
        # Clean up registry
        TABLE_TO_MODEL.pop("dummy_bytes_table", None)
        try:
            Base.metadata.remove(DummyBytesModel.__table__)
        except Exception:
            pass
        if hasattr(Base, "registry"):
            try:
                Base.registry._class_to_mapper.pop(DummyBytesModel, None)
            except Exception:
                pass
            try:
                for m in list(Base.registry.mappers):
                    if m.class_ == DummyBytesModel:
                        try:
                            Base.registry._mappers.remove(m)
                        except Exception:
                            pass
            except Exception:
                pass


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
            {"role": "user", "content": "categorize this"},
        ],
        think=False,
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
        logged_client.chat(
            model="gemma", messages=[{"role": "user", "content": "fail test"}]
        )

    fail_logs = list(db["ollama_logs"].rows_where("status = 'failed'"))
    assert len(fail_logs) == 1
    assert "ValueError: Ollama server down" in fail_logs[0]["response"]


def test_ollama_think_config_save() -> None:
    """Verifies that ollama_think is correctly saved and loaded in the Config class."""
    from kb_web.config import Config

    cfg = Config()
    cfg.ollama_think = True
    cfg.save()

    cfg2 = Config()
    assert cfg2.ollama_think is True

    # Restore to False
    cfg2.ollama_think = False
    cfg2.save()


def test_title_embeddings_generation(monkeypatch) -> None:
    """Verifies that update_article_embedding correctly creates title embeddings."""
    from kb_web.utils import update_article_embedding
    from kb_web.config import Config
    import json

    db = DBAdapter()
    db["fetched_pages"].delete_where()
    db["title_embeddings"].delete_where()
    db["article_embeddings"].delete_where()

    db["fetched_pages"].insert(
        {
            "url": "https://example.com/test-title-embeddings",
            "title": "Special Custom Title",
            "tags": '["tech"]',
            "description": "Custom description",
            "html_content": "",
            "md_content": "",
            "links": "[]",
            "html_content_hash": "",
            "md_content_hash": "",
            "fetched_at": "",
        }
    )

    class DummyClient:
        def embeddings(self, model, prompt):
            return {"embedding": [0.1, 0.2, 0.3] + [0.0] * 1533}

    cfg = Config()
    client = DummyClient()

    # Run embedding update
    update_article_embedding(
        db, "https://example.com/test-title-embeddings", cfg, client
    )

    # Verify title embeddings exist
    row = db["title_embeddings"].get("https://example.com/test-title-embeddings")
    assert row is not None
    assert row["embedding"] == [0.1, 0.2, 0.3] + [0.0] * 1533


def test_extract_url_path_helper() -> None:
    """Tests the Jinja filter helper extract_url_path."""
    from kb_web.base import extract_url_path

    assert (
        extract_url_path("https://example.com/some/long/path/file.html")
        == "/some/long/path/file.html"
    )
    assert extract_url_path("https://example.com/") == "example.com"
    assert extract_url_path("invalid-url") == "invalid-url"


def test_offline_video_metadata() -> None:
    """Verifies schema contains local_path in youtube_videos table."""
    from kb_web.models_orm import YouTubeVideo
    assert "local_path" in YouTubeVideo.__table__.columns


def test_cron_subsystem_removal(client: TestClient) -> None:
    """Verifies that the cron subsystem has been removed, including routes and database tables."""
    from kb_web.models_orm import Base

    # 1. Verify tables are not defined in ORM metadata
    assert "cron_jobs" not in Base.metadata.tables
    assert "cron_job_runs" not in Base.metadata.tables

    # 2. Login as admin
    from kb_web.config import Config

    cfg = Config()
    login_resp = client.post(
        "/login",
        data={"password": cfg.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")
    assert session_cookie is not None

    # 3. Request cron dashboard and verify 404
    cron_resp = client.get("/admin/cron", cookies={"kb_session": session_cookie})
    assert cron_resp.status_code == 404


def test_sqlite_logging_handler() -> None:
    """Verifies that DatabaseLogHandler writes log records to the database system_logs table."""
    import logging
    from kb_web.base import DatabaseLogHandler, db_session
    from kb_web.models_orm import SystemLog

    # Clear existing logs for test predictability
    with db_session() as session:
        session.query(SystemLog).delete()

    handler = DatabaseLogHandler()
    logger = logging.getLogger("test_db_logger")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        logger.info("Test log message database")

        # Verify it exists in db via SQLAlchemy ORM
        with db_session() as session:
            rows = session.query(SystemLog).all()
            assert len(rows) == 1
            assert rows[0].message == "Test log message database"
            assert rows[0].level == "INFO"
    finally:
        logger.removeHandler(handler)


def test_crawler_domain_normalization(monkeypatch) -> None:
    """Verifies that the recursive crawler strips www. prefix when checking same-domain URLs."""
    from kb_web.routers.pages import run_recursive_crawl
    from kb_web.config import Config
    import json

    db = get_db(server_config)
    if "fetched_pages" in db.table_names():
        db.execute("DELETE FROM fetched_pages")

    # Insert page with links
    db["fetched_pages"].insert(
        {
            "url": "https://example.com/start",
            "title": "Start",
            "links": json.dumps(
                ["https://www.example.com/page1", "https://other.com/page2", "/page3"]
            ),
        }
    )

    ingested_urls = []

    def mock_ingest(db_handle, url, cfg, client):
        ingested_urls.append(url)
        db["fetched_pages"].insert(
            {"url": url, "title": "Ingested", "links": "[]"}
        )

    monkeypatch.setattr("kb_web.utils.ingest_url_sync", mock_ingest)

    cfg = Config()
    run_recursive_crawl(
        "https://example.com/start", depth=2, interval=0, config_obj=cfg
    )

    # Verify same-domain normalized links were crawled and different-domain links were skipped
    assert "https://www.example.com/page1" in ingested_urls
    assert "https://example.com/page3" in ingested_urls
    assert "https://other.com/page2" not in ingested_urls


def test_import_with_collection(client: TestClient, monkeypatch) -> None:
    """Verifies that importing a URL with collection parameters creates/links to collections."""

    db = get_db(server_config)

    # 1. Login as admin
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")
    assert session_cookie is not None

    # Mock fetch and ingestion
    from kb_web.models import HTMLPage

    dummy_page = HTMLPage(
        url="https://example.com/import-col-test",
        title="Import Collection Test",
        html_content="html",
        md_content="md",
        links=[],
        html_content_hash="h1",
        md_content_hash="h2",
        fetched_at="2026-05-31T12:00:00",
    )

    monkeypatch.setattr("kb_web.routers.admin.fetch_url", lambda *args: dummy_page)
    monkeypatch.setattr(
        "kb_web.routers.admin.extract_wiki_content", lambda *args: "Wiki description"
    )
    monkeypatch.setattr("kb_web.routers.admin.extract_tags_content", lambda *args: [])
    monkeypatch.setattr(
        "kb_web.routers.admin.update_article_embedding", lambda *args: None
    )
    monkeypatch.setattr(
        "kb_web.routers.admin.generate_gemma_embeddings_for_page", lambda *args: None
    )
    monkeypatch.setattr("kb_web.routers.admin.post_to_gotify", lambda *args: None)

    # Ingest URL with "new_collection"
    resp = client.post(
        "/import/url",
        data={
            "url": "https://example.com/import-col-test",
            "collection_id": "new_collection",
            "new_collection_title": "Import Target Collection",
        },
        cookies={"kb_session": session_cookie},
    )
    assert resp.status_code == 200

    # Check that collection was created
    col_rows = list(
        db["collections"].rows_where("title = ?", ["Import Target Collection"])
    )
    assert len(col_rows) == 1
    assert col_rows[0]["visibility"] == "public"
    col_id = col_rows[0]["id"]

    # Check page was linked
    item_rows = list(db["collection_items"].rows_where("collection_id = ?", [col_id]))
    assert len(item_rows) == 1
    assert item_rows[0]["source_id"] == "https://example.com/import-col-test"


def test_import_video_url_assigns_videos_type(client: TestClient, monkeypatch) -> None:
    """Verifies that importing a YouTube video sets source_type to 'videos' in collection_items."""
    db = get_db(server_config)

    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    from kb_web.models import HTMLPage

    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    dummy_page = HTMLPage(
        url=video_url,
        title="Rick Astley Video",
        html_content="html",
        md_content="md",
        links=[],
        html_content_hash="h1",
        md_content_hash="h2",
        fetched_at="2026-05-31T12:00:00",
    )

    monkeypatch.setattr("kb_web.routers.admin.fetch_url", lambda *args: dummy_page)
    monkeypatch.setattr(
        "kb_web.routers.admin.extract_wiki_content", lambda *args: "Wiki description"
    )
    monkeypatch.setattr("kb_web.routers.admin.extract_tags_content", lambda *args: [])
    monkeypatch.setattr(
        "kb_web.routers.admin.update_article_embedding", lambda *args: None
    )
    monkeypatch.setattr(
        "kb_web.routers.admin.generate_gemma_embeddings_for_page", lambda *args: None
    )
    monkeypatch.setattr("kb_web.routers.admin.post_to_gotify", lambda *args: None)

    resp = client.post(
        "/import/url",
        data={
            "url": video_url,
            "collection_id": "new_collection",
            "new_collection_title": "Video Target Collection",
        },
        cookies={"kb_session": session_cookie},
    )
    assert resp.status_code == 200

    col_rows = list(
        db["collections"].rows_where("title = ?", ["Video Target Collection"])
    )
    assert len(col_rows) == 1
    col_id = col_rows[0]["id"]

    item_rows = list(db["collection_items"].rows_where("collection_id = ?", [col_id]))
    assert len(item_rows) == 1
    assert item_rows[0]["source_id"] == video_url
    assert item_rows[0]["source_type"] == "videos"


def test_video_offline_checking(client: TestClient, monkeypatch, tmp_path) -> None:
    """Verifies video page shows correct player tag/badge if locally saved offline."""
    from urllib.parse import quote_plus

    db = get_db(server_config)
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    db["fetched_pages"].insert(
        {
            "url": video_url,
            "title": "Rick Astley Video",
            "html_content": "html",
            "md_content": "md",
            "links": "[]",
            "html_content_hash": "h1",
            "md_content_hash": "h2",
            "fetched_at": "2026-05-31T12:00:00",
            "description": "desc",
        }
    )
    db.conn.commit()

    # 1. Cloud stream state
    resp = client.get(f"/view/page?url={quote_plus(video_url)}")
    assert resp.status_code == 200
    assert "Cloud Stream" in resp.text

    # 2. Saved offline state
    old_configs_dir = server_config.configs_dir
    server_config.configs_dir = tmp_path / "configs"

    media_dir = server_config.configs_dir.parent / "media" / "videos"
    media_dir.mkdir(parents=True, exist_ok=True)
    video_file = media_dir / "dQw4w9WgXcQ.mp4"
    video_file.write_text("dummy mp4 content")

    resp = client.get(f"/view/page?url={quote_plus(video_url)}")
    assert resp.status_code == 200
    assert "Saved Offline" in resp.text

    server_config.configs_dir = old_configs_dir


def test_server_logs_limit_cookies_and_sorting(client: TestClient) -> None:
    """Verifies that logs are reverse-sorted, page count defaults, and limits persist in cookies."""
    import logging
    logging.disable(logging.INFO)

    try:
        db = get_db(server_config)
        db["system_logs"].delete_where()

        login_resp = client.post(
            "/login",
            data={"password": server_config.admin_password},
            follow_redirects=False,
        )
        session_cookie = login_resp.cookies.get("kb_session")

        for i in range(10):
            db["system_logs"].insert(
                {
                    "timestamp": f"2026-06-01T12:00:0{i}",
                    "level": "INFO",
                    "module": "test",
                    "message": f"Log message {i}",
                    "traceback": "",
                }
            )
        db.conn.commit()

        # Default is newest first (reverse sorted)
        resp = client.get("/admin/logs", cookies={"kb_session": session_cookie})
        assert resp.status_code == 200
        log_text = resp.text
        idx_9 = log_text.find("Log message 9")
        idx_0 = log_text.find("Log message 0")
        assert idx_9 != -1 and idx_0 != -1
        assert idx_9 < idx_0

        # Query limits
        resp = client.get("/admin/logs?limit=3", cookies={"kb_session": session_cookie})
        assert resp.status_code == 200
        assert "Log message 9" in resp.text
        assert "Log message 8" in resp.text
        assert "Log message 7" in resp.text
        assert "Log message 6" not in resp.text
        assert resp.cookies.get("log_limit") == "3"

        # Cookie overrides
        resp2 = client.get(
            "/admin/logs", cookies={"kb_session": session_cookie, "log_limit": "3"}
        )
        assert resp2.status_code == 200
        assert "Log message 9" in resp2.text
        assert "Log message 6" not in resp2.text
    finally:
        logging.disable(logging.NOTSET)


def test_settings_and_prompts_db_persistence(client: TestClient) -> None:
    """Verifies Config settings write to settings tables, version prompts, and allow rollbacks."""
    db = get_db(server_config)

    server_config.ollama_host = "http://db-test-host:11434"
    assert server_config.ollama_host == "http://db-test-host:11434"

    row = db["settings_ollama"].get("ollama_host")
    assert row["value"] == "http://db-test-host:11434"

    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    resp = client.post(
        "/admin/config",
        data={
            "ollama_host": "http://post-test-host:11434",
            "ollama_model": "test-gemma",
            "ollama_embedding_model": "test-nomic",
            "api_key": "test-key",
            "gotify_url": "",
            "gotify_token": "",
            "qdrant_host_url": "",
            "qdrant_api_key": "",
            "wiki_prompt": "Initial Wiki Prompt",
            "youtube_wiki_prompt": "Initial YT Prompt",
            "max_input_length": 25000,
            "ollama_think": "true",
        },
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    assert server_config.ollama_host == "http://post-test-host:11434"
    assert server_config.wiki_prompt == "Initial Wiki Prompt"

    prompts = list(
        db["agent_prompts"].rows_where(
            "prompt_type = 'wiki_prompt' ORDER BY version ASC"
        )
    )
    assert len(prompts) == 2
    assert prompts[0]["version"] == 1
    assert prompts[1]["version"] == 2
    assert prompts[1]["prompt_text"] == "Initial Wiki Prompt"
    assert prompts[1]["is_head"] == 1

    v1_id = prompts[0]["id"]
    resp2 = client.post(
        "/admin/prompts/set-head",
        data={"prompt_id": v1_id, "prompt_type": "wiki_prompt"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert resp2.status_code == 303

    assert server_config.wiki_prompt == prompts[0]["prompt_text"]
    assert db["agent_prompts"].get(v1_id)["is_head"] == 1


def test_descriptive_video_download_and_resolution(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    """Verifies that download_youtube_video creates descriptive filenames and pages.py resolves them dynamically."""
    from urllib.parse import quote_plus
    from pathlib import Path
    from kb_web.utils import download_youtube_video

    db = get_db(server_config)
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    video_id = "dQw4w9WgXcQ"

    db["fetched_pages"].insert(
        {
            "url": video_url,
            "title": "Rick Astley - Never Gonna Give You Up",
            "html_content": "html",
            "md_content": "md",
            "links": "[]",
            "html_content_hash": "h1",
            "md_content_hash": "h2",
            "fetched_at": "2026-05-31T12:00:00",
            "description": "desc",
        }
    )
    db["youtube_videos"].insert(
        {
            "url": video_url,
            "video_id": video_id,
            "creator": "RickAstleyVEVO",
            "channel_id": "UCuAXFKgjiqg_EMaCHwL7IAg",
            "duration": 212,
            "view_count": 1000000,
            "thumbnail_url": "",
            "local_path": "",
            "updated_at": "2026-05-31T12:00:00",
        }
    )
    db.conn.commit()

    class DummyYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def download(self, urls):
            out_pattern = self.opts["outtmpl"]
            out_file = Path(out_pattern.replace(".%(ext)s", ".mp4"))
            out_file.write_text("dummy mp4")

    monkeypatch.setattr("yt_dlp.YoutubeDL", DummyYoutubeDL)

    old_configs_dir = server_config.configs_dir
    server_config.configs_dir = tmp_path / "configs"

    local_path = download_youtube_video(video_id, server_config)

    filename = Path(local_path).name
    assert "RickAstleyVEVO" in filename
    assert "Never Gonna Give You Up" in filename
    assert video_id in filename
    assert filename.endswith(".mp4")

    resp = client.get(f"/view/page?url={quote_plus(video_url)}")
    assert resp.status_code == 200
    assert "Saved Offline" in resp.text
    assert f"/media/videos/{filename}" in resp.text

    server_config.configs_dir = old_configs_dir


def test_cli_client_server_integration(client: TestClient, monkeypatch) -> None:
    """Tests the new CLI API router endpoints for client registration, ingestion, operations, and querying."""
    db = get_db(server_config)

    # 1. Login to generate CLI key via administrative endpoints
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    # Call admin/cli/keys/create
    key_create_resp = client.post(
        "/admin/cli/keys/create",
        data={"name": "Test Key for Unit Tests"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert key_create_resp.status_code == 303

    # Check that key was generated in the database
    keys_in_db = list(db["cli_api_keys"].rows)
    assert len(keys_in_db) == 1
    api_key = keys_in_db[0]["key"]
    assert keys_in_db[0]["name"] == "Test Key for Unit Tests"

    # 2. Test Client Registration via POST /api/cli/register
    reg_resp = client.post(
        "/api/cli/register",
        headers={"X-API-Key": api_key},
        json={"computer_name": "Test-Client-Host"},
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json()["status"] == "success"

    # Check client registry
    clients = list(db["registered_clients"].rows)
    assert len(clients) == 1
    assert clients[0]["computer_name"] == "Test-Client-Host"
    assert clients[0]["api_key"] == api_key

    # 3. Test Invalid CLI API Key Authentication
    bad_resp = client.post(
        "/api/cli/register",
        headers={"X-API-Key": "invalidkey"},
        json={"computer_name": "Test-Client-Host"},
    )
    assert bad_resp.status_code == 403

    # 4. Test Ingestion endpoint POST /api/cli/import/url
    def mock_fetch_url(url: str):
        from kb_web.models import HTMLPage

        return HTMLPage(
            url=url,
            title="Ingestion CLI Page Title",
            html_content="<html><body>Ingest this body content</body></html>",
            md_content="Ingest this body content",
            links=[],
            html_content_hash="h1",
            md_content_hash="h2",
            fetched_at="2026-05-31T12:00:00",
            description="",
            keywords=[],
            tags=[],
        )

    # Mock Ollama chat responses
    class DummyMessage:
        content = (
            "# Ingestion CLI Page Title\nWiki entry description summary for CLI page."
        )

    class DummyChatResponse:
        message = DummyMessage()

    monkeypatch.setattr("kb_web.routers.cli_api.fetch_url", mock_fetch_url)
    monkeypatch.setattr(
        "kb_web.routers.cli_api._get_ollama_client",
        lambda: type(
            "DummyClient",
            (),
            {
                "chat": lambda *args, **kwargs: DummyChatResponse(),
                "pull": lambda *args, **kwargs: None,
            },
        )(),
    )

    import_resp = client.post(
        "/api/cli/import/url",
        headers={"X-API-Key": api_key},
        data={"url": "https://example.com/cli-import"},
    )
    assert import_resp.status_code == 200
    assert import_resp.json()["status"] == "success"

    # Verify article created in database
    row = db["fetched_pages"].get("https://example.com/cli-import")
    assert row["title"] == "Ingestion CLI Page Title"
    assert "Wiki entry" in row["description"]

    # 5. Test Listing endpoint GET /api/cli/pages
    list_resp = client.get(
        "/api/cli/pages", headers={"X-API-Key": api_key}, params={"limit": 5}
    )
    assert list_resp.status_code == 200
    pages = list_resp.json()
    assert len(pages) >= 1
    assert any(p["url"] == "https://example.com/cli-import" for p in pages)

    # 6. Test Collections list endpoint GET /api/cli/collections
    db["collections"].insert(
        {
            "id": 100,
            "title": "CLI Test Collection",
            "visibility": "private",
            "rag_system_prompt": "",
            "taxonomy_system_prompt": "",
            "general_system_context": "{}",
            "created_at": "2026-05-31T12:00:00",
        }
    )
    db.conn.commit()

    col_list_resp = client.get("/api/cli/collections", headers={"X-API-Key": api_key})
    assert col_list_resp.status_code == 200
    cols = col_list_resp.json()
    assert any(c["id"] == 100 for c in cols)

    # 7. Test Collections Add/Remove endpoint POST /api/cli/collections/item
    add_item_resp = client.post(
        "/api/cli/collections/item",
        headers={"X-API-Key": api_key},
        data={
            "action": "add",
            "collection_id": 100,
            "url": "https://example.com/cli-import",
        },
    )
    assert add_item_resp.status_code == 200
    assert add_item_resp.json()["status"] == "success"
    # verify item linked
    assert (
        db["collection_items"].count_where(
            "collection_id = ? AND source_id = ?",
            [100, "https://example.com/cli-import"],
        )
        == 1
    )

    # 8. Test Tags management endpoint GET /api/cli/tags and POST /api/cli/tags/operation
    db["fetched_pages"].update(
        "https://example.com/cli-import", {"tags": '["original-tag"]'}
    )
    db.conn.commit()

    tag_op_resp = client.post(
        "/api/cli/tags/operation",
        headers={"X-API-Key": api_key},
        data={
            "action": "add",
            "tag": "new-cli-tag",
            "url": "https://example.com/cli-import",
        },
    )
    assert tag_op_resp.status_code == 200
    assert "new-cli-tag" in tag_op_resp.json()["tags"]

    # 9. Test Agent query endpoint POST /api/cli/agent/query
    agent_resp = client.post(
        "/api/cli/agent/query", headers={"X-API-Key": api_key}, data={"query": "CLI"}
    )
    assert agent_resp.status_code == 200
    assert agent_resp.json()["status"] == "success"
    assert "Wiki entry" in agent_resp.json()["reply"]
    assert any(
        r["url"] == "https://example.com/cli-import"
        for r in agent_resp.json()["references"]
    )

    # 9.5 Test CLI Logs endpoint GET /api/cli/logs
    logs_cli_resp = client.get(
        "/api/cli/logs", headers={"X-API-Key": api_key}, params={"limit": 10}
    )
    assert logs_cli_resp.status_code == 200
    assert isinstance(logs_cli_resp.json(), list)

    # 10. Clean up keys and clients via admin endpoints
    key_del_resp = client.post(
        "/admin/cli/keys/delete",
        data={"key": api_key},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert key_del_resp.status_code == 303
    assert db["cli_api_keys"].count_where("key = ?", [api_key]) == 0

    client_del_resp = client.post(
        "/admin/cli/clients/delete",
        data={"computer_name": "Test-Client-Host"},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert client_del_resp.status_code == 303
    assert (
        db["registered_clients"].count_where("computer_name = ?", ["Test-Client-Host"])
        == 0
    )


def test_links_management_and_tracking(client: TestClient) -> None:
    """Tests the new links tracking endpoints: creation, redirects, deletion, and HTML bookmarks parsing."""
    db = get_db(server_config)

    # 1. Access GET /links publicly (should redirect to login)
    resp = client.get("/links", follow_redirects=False)
    assert resp.status_code == 303
    assert "login" in resp.headers.get("Location", "")

    # 2. Try to add link without logging in (should redirect to login)
    add_resp = client.post(
        "/links/add",
        data={
            "url": "https://example.com/test-ref",
            "title": "Test Ref",
            "description": "Quick reference link",
        },
        follow_redirects=False,
    )
    assert add_resp.status_code == 303
    assert "login" in add_resp.headers.get("Location", "")

    # 3. Log in to get session cookie
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")
    assert session_cookie is not None

    # Access GET /links with authentication
    resp_auth = client.get("/links", cookies={"kb_session": session_cookie})
    assert resp_auth.status_code == 200
    assert "Directory" in resp_auth.text

    # 4. Add link with session cookie
    add_resp = client.post(
        "/links/add",
        data={
            "url": "https://example.com/test-ref",
            "title": "Test Ref",
            "description": "Quick reference link",
        },
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert add_resp.status_code == 303
    assert add_resp.headers.get("Location") == "/links"

    # Verify link created in DB
    links = list(db["links"].rows)
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/test-ref"
    assert links[0]["title"] == "Test Ref"
    assert links[0]["click_count"] == 0
    link_id = links[0]["id"]

    # 5. Access redirect tracking GET /links/go publicly (should redirect to login)
    client.cookies.clear()
    go_resp_public = client.get(f"/links/go?id={link_id}", follow_redirects=False)
    assert go_resp_public.status_code == 303
    assert "login" in go_resp_public.headers.get("Location", "")

    # Access redirect tracking GET /links/go with authentication
    go_resp = client.get(
        f"/links/go?id={link_id}",
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert go_resp.status_code == 303
    assert go_resp.headers.get("Location") == "https://example.com/test-ref"

    # Check updated click count
    row = db["links"].get(link_id)
    assert row["click_count"] == 1
    assert row["last_clicked_at"] != ""

    # 6. Test Bookmarks HTML upload import
    mock_bookmarks_html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
    <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
    <TITLE>Bookmarks</TITLE>
    <H1>Bookmarks</H1>
    <DL><p>
        <DT><A HREF="https://example.com/imported-link-1">Imported Link 1</A>
        <DT><A HREF="https://example.com/imported-link-2">Imported Link 2</A>
    </DL><p>
    """

    import_resp = client.post(
        "/links/import-bookmarks",
        files={"file": ("bookmarks.html", mock_bookmarks_html, "text/html")},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert import_resp.status_code == 303
    assert import_resp.headers.get("Location") == "/links"

    # Verify imported links in database
    imported_rows = list(
        db["links"].rows_where("description = 'Imported from Bookmarks'")
    )
    assert len(imported_rows) == 2
    assert any(r["url"] == "https://example.com/imported-link-1" for r in imported_rows)
    assert any(r["url"] == "https://example.com/imported-link-2" for r in imported_rows)

    # 7. Delete a link
    del_resp = client.post(
        "/links/delete",
        data={"id": link_id},
        cookies={"kb_session": session_cookie},
        follow_redirects=False,
    )
    assert del_resp.status_code == 303

    # Verify link deleted
    assert db["links"].count_where("id = ?", [link_id]) == 0


def test_import_url_duplicate_checking(client: TestClient, monkeypatch) -> None:
    """Verifies duplicate checking behavior during URL import: identical content vs changed content."""
    db = get_db(server_config)

    # Login to get admin cookie
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    session_cookie = login_resp.cookies.get("kb_session")

    from kb_web.models import HTMLPage

    url = "https://example.com/duplicate-test-page"

    # 1. Clear existing matching page and versions
    if "fetched_pages" in db.table_names():
        db["fetched_pages"].delete_where("url = ?", [url])
    if "page_versions" in db.table_names():
        db["page_versions"].delete_where("url = ?", [url])
    db.conn.close()

    dummy_page_1 = HTMLPage(
        url=url,
        title="Duplicate Test Page v1",
        html_content="<html><head><title>Duplicate Test Page v1</title></head><body>v1 content</body></html>",
        md_content="v1 content",
        links=[],
        html_content_hash="hash_v1_html",
        md_content_hash="hash_v1_md",
        fetched_at="2026-05-31T12:00:00",
    )

    # Mock extractors/fetchers
    monkeypatch.setattr("kb_web.routers.admin.fetch_url", lambda *args: dummy_page_1)
    monkeypatch.setattr(
        "kb_web.routers.admin.extract_wiki_content", lambda *args: "Wiki description v1"
    )
    monkeypatch.setattr(
        "kb_web.routers.admin.extract_tags_content", lambda *args: ["v1"]
    )
    monkeypatch.setattr(
        "kb_web.routers.admin.update_article_embedding", lambda *args: None
    )
    monkeypatch.setattr(
        "kb_web.routers.admin.generate_gemma_embeddings_for_page", lambda *args: None
    )
    monkeypatch.setattr("kb_web.routers.admin.post_to_gotify", lambda *args: None)

    # Ingest v1
    resp1 = client.post(
        "/import/url", data={"url": url}, cookies={"kb_session": session_cookie}
    )
    assert resp1.status_code == 200
    _ = resp1.text

    # Verify saved
    db_verify = get_db(server_config)
    row = db_verify["fetched_pages"].get(url)
    assert row["title"] == "Duplicate Test Page v1"
    assert row["md_content_hash"] == "hash_v1_md"

    # Verify no versions archived yet
    versions = list(db_verify["page_versions"].rows_where("url = ?", [url]))
    assert len(versions) == 0
    db_verify.conn.close()

    # 2. Ingest duplicate v1 (identical hash) - should skip LLM extraction, not archive
    extracted_wiki_calls = 0

    def mock_extract_wiki(*args):
        nonlocal extracted_wiki_calls
        extracted_wiki_calls += 1
        return "Wiki description v1 updated"

    monkeypatch.setattr("kb_web.routers.admin.extract_wiki_content", mock_extract_wiki)

    resp2 = client.post(
        "/import/url", data={"url": url}, cookies={"kb_session": session_cookie}
    )
    assert resp2.status_code == 200
    _ = resp2.text

    # Verify that LLM extraction was NOT called (i.e. skipped because hashes were identical)
    assert extracted_wiki_calls == 0

    # Verify no versions archived
    db_verify = get_db(server_config)
    versions = list(db_verify["page_versions"].rows_where("url = ?", [url]))
    assert len(versions) == 0
    db_verify.conn.close()

    # 3. Ingest v2 (different hash) - should archive v1, run extraction, update fetched_pages
    dummy_page_2 = HTMLPage(
        url=url,
        title="Duplicate Test Page v2",
        html_content="<html><head><title>Duplicate Test Page v2</title></head><body>v2 content</body></html>",
        md_content="v2 content",
        links=[],
        html_content_hash="hash_v2_html",
        md_content_hash="hash_v2_md",
        fetched_at="2026-05-31T13:00:00",
    )
    monkeypatch.setattr("kb_web.routers.admin.fetch_url", lambda *args: dummy_page_2)
    monkeypatch.setattr(
        "kb_web.routers.admin.extract_wiki_content", lambda *args: "Wiki description v2"
    )
    monkeypatch.setattr(
        "kb_web.routers.admin.extract_tags_content", lambda *args: ["v2"]
    )

    resp3 = client.post(
        "/import/url", data={"url": url}, cookies={"kb_session": session_cookie}
    )
    assert resp3.status_code == 200
    _ = resp3.text

    # Verify updated in fetched_pages
    db_verify = get_db(server_config)
    row_updated = db_verify["fetched_pages"].get(url)
    assert row_updated["title"] == "Duplicate Test Page v2"
    assert row_updated["md_content_hash"] == "hash_v2_md"
    assert row_updated["description"] == "Wiki description v2"

    # Verify archived version
    versions = list(db_verify["page_versions"].rows_where("url = ?", [url]))
    assert len(versions) == 1
    assert versions[0]["title"] == "Duplicate Test Page v1"
    assert versions[0]["md_content_hash"] == "hash_v1_md"
    assert versions[0]["description"] == "Wiki description v1"
    db_verify.conn.close()


def test_orm_mappings_sqlite() -> None:
    """Verifies that SQLAlchemy ORM mappings work cleanly against SQLite."""
    from kb_web.base import get_engine, db_session
    from kb_web.models_orm import FetchedPage

    # Reset cached engine to guarantee initialization
    import kb_web.base

    kb_web.base._engine = None
    get_engine()

    # Insert a fetched page using ORM
    url = "https://example.com/sqlalchemy-test"
    with db_session() as session:
        # Clear existing
        session.query(FetchedPage).filter_by(url=url).delete()

        page = FetchedPage(
            url=url,
            title="SQLAlchemy Test Title",
            html_content="<html></html>",
            md_content="Content",
            links="[]",
            html_content_hash="h1",
            md_content_hash="m1",
            fetched_at="2026-08-14T00:00:00",
            description="SQLAlchemy ORM description",
            keywords="[]",
            tags="[]",
            collection_id=1,
            exclude_from_general=0,
        )
        session.add(page)

    # Read back and verify
    with db_session() as session:
        read_page = session.query(FetchedPage).filter_by(url=url).first()
        assert read_page is not None
        assert read_page.title == "SQLAlchemy Test Title"
        assert read_page.description == "SQLAlchemy ORM description"

        # Clean up
        session.delete(read_page)


def test_safe_vector_decorator() -> None:
    """Verifies that the custom SafeVector TypeDecorator serializes vectors to JSON strings on SQLite."""
    from kb_web.base import db_session
    from kb_web.models_orm import ArticleEmbedding
    from datetime import datetime

    url = "https://example.com/vector-decorator-test"
    test_vector = [0.1] * 1536

    from kb_web.models_orm import FetchedPage

    with db_session() as session:
        # Delete existing to prevent primary key / foreign key conflicts
        session.query(ArticleEmbedding).filter_by(url=url).delete()
        session.query(FetchedPage).filter_by(url=url).delete()

        # Insert parent page first to satisfy PostgreSQL foreign key
        page = FetchedPage(
            url=url,
            title="Decorator Test Page",
            html_content="html",
            md_content="md",
            links="[]",
            html_content_hash="h1",
            md_content_hash="h2",
            fetched_at=datetime.now().isoformat(),
            description="desc",
            tags="[]",
        )
        session.add(page)
        session.flush()

        emb = ArticleEmbedding(
            url=url, embedding=test_vector, updated_at=datetime.now().isoformat()
        )
        session.add(emb)

    # Retrieve and verify conversion
    with db_session() as session:
        retrieved = session.query(ArticleEmbedding).filter_by(url=url).first()
        assert retrieved is not None
        # Should be converted back to python float list
        assert retrieved.embedding == test_vector

        # Clean up
        session.delete(retrieved)


def test_session_dialect_config(monkeypatch) -> None:
    """Verifies that configuring a postgres database_url initializes the postgres engine."""
    from kb_web.base import get_engine
    import kb_web.base

    # Mock create_engine to verify parameters without establishing a real postgres connection
    created_engines = []
    from sqlalchemy import create_engine as real_create_engine

    def mock_create_engine(url, **kwargs):
        created_engines.append((url, kwargs))
        # Fall back to sqlite in memory to avoid real postgres connection error during test
        return real_create_engine("sqlite:///:memory:")

    monkeypatch.setattr(kb_web.base, "create_engine", mock_create_engine)

    # 1. Test postgres conversion
    monkeypatch.setattr(
        kb_web.base.config, "_database_url", "postgres://user:password@localhost/db"
    )
    # Reset engine cache to force re-initialization
    monkeypatch.setattr(kb_web.base, "_engine", None)

    get_engine()
    assert len(created_engines) == 1
    assert created_engines[0][0] == "postgresql+psycopg2://user:password@localhost/db"
    assert created_engines[0][1].get("pool_size") == 10

    # Restore config to fallback
    monkeypatch.setattr(kb_web.base.config, "_database_url", "")
    monkeypatch.setattr(kb_web.base, "_engine", None)
