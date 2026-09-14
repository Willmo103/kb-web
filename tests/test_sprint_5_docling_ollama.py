"""
Tests for Sprint 5: WebSocket Ingestion, Docling Integration, and Ollama Cache Settings.
Covers Issues #51, #36, #52, #53.
"""

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.config import Config
from kb_web.models_orm import (
    FetchedPage,
    OllamaChatCache,
    Source,
    UploadedDocument,
)
from kb_web.server import app, config as server_config
from kb_web.utils import (
    DOCLING_SUPPORTED_EXTENSIONS,
    DoclingClient,
    cached_ollama_chat,
    purge_expired_uploads,
)


@pytest.fixture(autouse=True)
def disable_gotify():
    old_url = server_config.gotify_url
    server_config.gotify_url = None
    with patch("kb_web.gotify.post_to_gotify"):
        yield
    server_config.gotify_url = old_url


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    client.cookies.set(COOKIE_NAME, generate_session_token(time.time() + 3600))
    return client


# ============================================================================
# 1. DoclingClient Tests
# ============================================================================

def test_docling_supported_extensions():
    """Verify supported document extensions and validation."""
    assert ".pdf" in DOCLING_SUPPORTED_EXTENSIONS
    assert "pdf" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".docx" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".pptx" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".xlsx" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".html" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".md" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".txt" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".csv" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".json" in DOCLING_SUPPORTED_EXTENSIONS
    assert ".exe" not in DOCLING_SUPPORTED_EXTENSIONS
    assert ".sh" not in DOCLING_SUPPORTED_EXTENSIONS


def test_docling_client_is_alive():
    """Test DoclingClient.is_alive() status check with mocked HTTP responses."""
    client = DoclingClient(docling_serve_url="http://mock-docling:5001")

    # Alive case
    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert client.is_alive() is True

    # Down / error case
    with patch("httpx.Client.get", side_effect=Exception("Connection refused")):
        assert client.is_alive() is False


def test_docling_convert_via_serve():
    """Test converting document using docling-serve HTTP endpoint."""
    client = DoclingClient(docling_serve_url="http://mock-docling:5001", ocr_enabled=True)

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"Hello from test document")
        temp_path = f.name

    try:
        with patch.object(client, "is_alive", return_value=True):
            with patch("httpx.Client.post") as mock_post:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.raise_for_status = MagicMock()
                mock_resp.json.return_value = {
                    "document": {
                        "export_to_markdown": "# Mocked Docling Title\n\nContent parsed via docling-serve."
                    }
                }
                mock_post.return_value = mock_resp

                res = client.convert_file(temp_path)
                assert "Mocked Docling Title" in res["markdown"]
                assert res.get("engine") == "docling-serve"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_docling_fallback_plain_text():
    """Test fallback to plaintext parsing when docling-serve and local docling are unavailable."""
    client = DoclingClient(docling_serve_url="http://mock-docling:5001")

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"# Native Markdown\n\nPlain text fallback test content.")
        temp_path = f.name

    try:
        with patch.object(client, "is_alive", return_value=False):
            with patch.dict("sys.modules", {"docling.document_converter": None}):
                res = client.convert_file(temp_path)
                assert "# Native Markdown" in res["markdown"]
                assert res.get("engine") == "text-fallback"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ============================================================================
# 2. Ollama Chat Cache Tests
# ============================================================================

def test_cached_ollama_chat_hit_and_miss():
    """Test deterministic caching of Ollama chat calls."""
    mock_ollama_client = MagicMock()
    mock_response = MagicMock()
    mock_response.message.content = "Cached AI summary response"
    mock_ollama_client.chat.return_value = mock_response

    test_model = "test-llama-model"
    test_messages = [{"role": "user", "content": f"Unique prompt test {time.time()}"}]

    # 1. First call: Cache Miss
    resp1 = cached_ollama_chat(
        mock_ollama_client,
        model=test_model,
        messages=test_messages,
        temperature=0.7,
        top_p=0.9,
    )
    assert resp1.message.content == "Cached AI summary response"
    assert mock_ollama_client.chat.call_count == 1

    # Verify stored in database
    with db_session() as session:
        cache_row = session.query(OllamaChatCache).filter_by(model_used=test_model).order_by(OllamaChatCache.created_at.desc()).first()
        assert cache_row is not None
        assert cache_row.response_text == "Cached AI summary response"
        assert cache_row.hit_count == 0
        prompt_hash = cache_row.prompt_hash

    # 2. Second call: Cache Hit (mock client should NOT be called again)
    resp2 = cached_ollama_chat(
        mock_ollama_client,
        model=test_model,
        messages=test_messages,
        temperature=0.7,
        top_p=0.9,
    )
    assert resp2.message.content == "Cached AI summary response"
    assert mock_ollama_client.chat.call_count == 1  # Still 1!

    # Verify hit_count incremented
    with db_session() as session:
        updated_row = session.query(OllamaChatCache).filter_by(prompt_hash=prompt_hash).first()
        assert updated_row.hit_count == 1


# ============================================================================
# 3. Purge Expired Uploads Tests
# ============================================================================

def test_purge_expired_uploads():
    """Test automatic cleanup of expired failed/pending uploads."""
    old_date = datetime.now() - timedelta(days=10)
    recent_date = datetime.now() - timedelta(days=1)

    with db_session() as session:
        session.query(UploadedDocument).filter(
            UploadedDocument.file_hash.in_(["hash_expired_123", "hash_recent_456"])
        ).delete()
        session.commit()

        # Expired row (10 days old, failed)
        expired_doc = UploadedDocument(
            filename="expired.pdf",
            file_hash="hash_expired_123",
            file_size=1024,
            storage_path="/tmp/fake/expired.pdf",
            status="failed",
            created_at=old_date,
        )
        # Recent row (1 day old)
        recent_doc = UploadedDocument(
            filename="recent.pdf",
            file_hash="hash_recent_456",
            file_size=2048,
            storage_path="/tmp/fake/recent.pdf",
            status="uploaded",
            created_at=recent_date,
        )
        session.add(expired_doc)
        session.add(recent_doc)
        session.commit()

    purged_count = purge_expired_uploads(days=7)
    assert purged_count >= 1

    with db_session() as session:
        assert session.query(UploadedDocument).filter_by(file_hash="hash_expired_123").first() is None
        assert session.query(UploadedDocument).filter_by(file_hash="hash_recent_456").first() is not None


# ============================================================================
# 4. Admin Settings & Cache Inspector Endpoints
# ============================================================================

def test_admin_docling_and_ollama_settings(auth_client):
    """Test persisting Docling and Ollama advanced kwargs in /admin/config."""
    res = auth_client.post(
        "/admin/config",
        data={
            "ollama_host": "http://localhost:11434",
            "ollama_model": "test-model",
            "ollama_embedding_model": "test-embed",
            "docling_serve_url": "http://192.168.0.50:5001",
            "docling_ocr_enabled": "true",
            "ollama_temperature": "0.45",
            "ollama_top_p": "0.85",
            "wiki_prompt": "Test Wiki Prompt",
            "youtube_wiki_prompt": "Test YT Prompt",
            "max_input_length": "20000",
            "ollama_think": "false",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert server_config.docling_serve_url == "http://192.168.0.50:5001"
    assert server_config.docling_ocr_enabled is True
    assert server_config.ollama_temperature == 0.45
    assert server_config.ollama_top_p == 0.85


def test_admin_test_docling_endpoint(auth_client):
    """Test /admin/test-docling connectivity check."""
    with patch("kb_web.utils.DoclingClient.is_alive", return_value=True):
        res = auth_client.post("/admin/test-docling", data={"docling_serve_url": "http://localhost:5001"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "Successfully connected" in data["message"]

    with patch("kb_web.utils.DoclingClient.is_alive", return_value=False):
        res = auth_client.post("/admin/test-docling", data={"docling_serve_url": "http://invalid-host:5001"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "error"


def test_admin_ollama_cache_management(auth_client):
    """Test viewing and clearing Ollama cache via admin endpoints."""
    # Seed a test cache row
    with db_session() as session:
        session.query(OllamaChatCache).delete()
        test_cache = OllamaChatCache(
            cache_key="test_cache_key_xyz",
            model="test-llama",
            prompt_text="What is knowledge base?",
            response_text="A knowledge base is a centralized repository of info.",
            hit_count=5,
        )
        session.add(test_cache)
        session.commit()

    # GET /admin/ollama/cache
    res = auth_client.get("/admin/ollama/cache")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["total"] >= 1
    assert any(i["cache_key"] == "test_cache_key_xyz" for i in data["items"])

    # POST /admin/ollama/cache/clear
    res_clear = auth_client.post(
        "/admin/ollama/cache/clear",
        headers={"Accept": "application/json"}
    )
    assert res_clear.status_code == 200
    assert res_clear.json()["status"] == "success"

    with db_session() as session:
        assert session.query(OllamaChatCache).count() == 0


# ============================================================================
# 5. File Ingestion Endpoints (HTTP & WebSocket)
# ============================================================================

def test_http_multipart_file_upload(auth_client):
    """Test HTTP POST /api/import/file ingestion with Docling conversion."""
    test_id = int(time.time() * 1000)
    file_content = f"# Architecture Overview {test_id}\n\nThis is a docling uploaded file test.".encode("utf-8")
    test_filename = f"test_arch_{test_id}.md"

    with patch("kb_web.utils.DoclingClient.convert_file") as mock_convert:
        mock_convert.return_value = {
            "markdown": "# Architecture Overview\n\nThis is a docling uploaded file test.",
            "docling_json": {"status": "ok", "pages": 1}
        }

        res = auth_client.post(
            "/api/import/file",
            files={"file": (test_filename, file_content, "text/markdown")},
            data={"custom_instructions": "Prioritize high-level architecture"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("success", "completed")
        assert "page_url" in data

        # Verify page created in database
        with db_session() as session:
            page = session.query(FetchedPage).filter_by(url=data["page_url"]).first()
            assert page is not None
            assert page.title == test_filename

            # Verify queue source created for tag/embedding processing
            source = session.query(Source).filter_by(id=data["source_id"]).first()
            assert source is not None
            assert source.status in ("pending", "processing", "failed")


def test_http_file_upload_blacklisted_extension(auth_client):
    """Test that dangerous file extensions (.exe, .sh) are rejected."""
    bad_content = b"echo 'malicious script'"
    res = auth_client.post(
        "/api/import/file",
        files={"file": ("hack.sh", bad_content, "application/x-sh")},
    )
    assert res.status_code == 400
    assert "Unsupported or blacklisted" in res.json()["detail"]


def test_websocket_chunked_file_upload(auth_client):
    """Test real-time WebSocket file upload streaming and completion."""
    ws_id = int(time.time() * 1000) + 1
    file_content = f"# WebSocket Ingestion {ws_id}\n\nLive streamed chunks test.".encode("utf-8")
    test_filename = f"ws_test_{ws_id}.md"
    file_size = len(file_content)

    with patch("kb_web.utils.DoclingClient.convert_file") as mock_convert:
        mock_convert.return_value = {
            "markdown": "# WebSocket Ingestion\n\nLive streamed chunks test.",
            "docling_json": {"status": "ok", "pages": 1}
        }

        with auth_client.websocket_connect("/api/import/file/upload") as ws:
            # 1. Handshake start
            ws.send_text(json.dumps({
                "type": "start",
                "filename": test_filename,
                "file_size": file_size,
            }))

            resp1 = json.loads(ws.receive_text())
            assert resp1["status"] == "ready"

            # 2. Send binary chunks
            ws.send_bytes(file_content)

            resp2 = json.loads(ws.receive_text())
            assert resp2["status"] in ("uploading", "ready")

            # 3. Send done
            ws.send_text(json.dumps({"type": "done"}))

            # 4. Receive processing and completion
            final_resp = None
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                if msg.get("status") in ("completed", "error"):
                    final_resp = msg
                    break

            assert final_resp is not None
            assert final_resp["status"] == "completed"
            assert "page_url" in final_resp

            # Verify UploadedDocument record
            with db_session() as session:
                doc = session.query(UploadedDocument).filter_by(filename=test_filename).first()
                assert doc is not None
                assert doc.status in ("parsed", "completed")
