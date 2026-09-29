import json
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, db_session, generate_session_token, config
from kb_web.models_orm import Collection, CollectionItem, ChunkEmbedding
from kb_web.server import app


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
def auth_client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def test_sync_collection_qdrant_unconfigured(auth_client, monkeypatch):
    """Verifies error handling when Qdrant host is not configured."""
    monkeypatch.setattr(config, "qdrant_host_url", None)
    resp = auth_client.post("/collections/view/1/sync")
    assert resp.status_code == 500
    data = resp.json()
    assert data["status"] == "error"
    assert "not configured" in data["message"].lower()


def test_sync_collection_qdrant_creates_missing_collection_on_server(auth_client, monkeypatch):
    """Verifies that syncing a non-existent collection creates it on the server and in Qdrant."""
    monkeypatch.setattr(config, "qdrant_host_url", "http://mock-qdrant:6333")
    monkeypatch.setattr(config, "qdrant_api_key", None)

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 404  # Collection does not exist in Qdrant yet

    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200
    mock_put_resp.raise_for_status = MagicMock()

    created_in_qdrant = []

    def mock_httpx_send(request, *args, **kwargs):
        url = str(request.url)
        if request.method == "GET" and "/collections/" in url:
            return mock_get_resp
        elif request.method == "PUT" and "/collections/" in url:
            created_in_qdrant.append(url)
            return mock_put_resp
        return mock_get_resp

    with patch("httpx.Client.get", return_value=mock_get_resp), \
         patch("httpx.Client.put", return_value=mock_put_resp):
        resp = auth_client.post("/collections/view/New%20Special%20Collection/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "verified/created" in data["message"].lower()

    # Verify collection was created on the local server
    with db_session() as session:
        col = session.query(Collection).filter_by(title="New Special Collection").first()
        assert col is not None
        # Clean up
        session.query(Collection).filter_by(id=col.id).delete()


def test_sync_collection_qdrant_with_vector_points(auth_client, monkeypatch):
    """Verifies Qdrant synchronization when vector items exist."""
    monkeypatch.setattr(config, "qdrant_host_url", "http://mock-qdrant:6333")
    monkeypatch.setattr(config, "qdrant_api_key", "secret-test-key")

    # Setup test collection with one item and one chunk embedding
    test_url = "https://example.com/sync-test-article"
    with db_session() as session:
        col = Collection(title="Test Sync Vectors", created_at="2026-09-13T12:00:00")
        session.add(col)
        session.flush()
        col_id = col.id

        session.add(
            CollectionItem(
                collection_id=col_id,
                source_type="articles",
                source_id=test_url,
                item_order=1,
            )
        )
        session.add(
            ChunkEmbedding(
                source_type="articles",
                source_id=test_url,
                source_title="Sync Article",
                chunk_number=0,
                chunk_content="Sample content for Qdrant vector sync",
                chunk_vector=[0.1] * 768,
            )
        )

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200  # Already exists in Qdrant

    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 200
    mock_put_resp.raise_for_status = MagicMock()

    uploaded_batches = []

    def mock_put(url, headers=None, json=None, *args, **kwargs):
        if "/points" in url:
            uploaded_batches.append(json)
        return mock_put_resp

    with patch("httpx.Client.get", return_value=mock_get_resp), \
         patch("httpx.Client.put", side_effect=mock_put):
        resp = auth_client.post(f"/collections/view/{col_id}/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "synchronized 1 points" in data["message"].lower()
        assert len(uploaded_batches) == 1
        assert len(uploaded_batches[0]["points"]) == 1
        assert uploaded_batches[0]["points"][0]["payload"]["source_id"] == test_url

    # Cleanup
    with db_session() as session:
        session.query(ChunkEmbedding).filter_by(source_id=test_url).delete()
        session.query(CollectionItem).filter_by(collection_id=col_id).delete()
        session.query(Collection).filter_by(id=col_id).delete()
