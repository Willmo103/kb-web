"""
Unit and integration tests for Persistent Notifications History Portal (/notifications)
and API endpoints for pagination, filtering, single deletion, and batch deletion.
"""

from datetime import datetime
import time
import pytest
from starlette.testclient import TestClient

from kb_web.server import app
from kb_web.base import db_session, COOKIE_NAME, generate_session_token
from kb_web.models_orm import IngestionNotification


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def _create_sample_notifications(session, count=10):
    now_str = datetime.now().isoformat()
    notifs = []
    for i in range(count):
        stage = "fetch" if i % 2 == 0 else "wiki"
        status = "success" if i % 3 == 0 else ("failed" if i % 3 == 1 else "info")
        read = 1 if i % 4 == 0 else 0
        n = IngestionNotification(
            task_id=f"task_{i}_{int(time.time())}",
            url=f"https://example.com/item-{i}",
            title=f"Sample Item {i}",
            stage=stage,
            status=status,
            message=f"Notification message number {i} for testing",
            details=f"Technical trace details for event {i}",
            created_at=now_str,
            read=read,
        )
        session.add(n)
        notifs.append(n)
    session.commit()
    for n in notifs:
        session.refresh(n)
    return notifs


def test_notifications_history_page_render(client: TestClient):
    """GET /notifications renders the HTML notification history portal."""
    resp = client.get("/notifications")
    assert resp.status_code == 200
    assert "Notification History & Logs" in resp.text
    assert "searchInput" in resp.text


def test_notifications_pagination_and_counts(client: TestClient):
    """GET /api/notifications returns proper pagination, total_count, and unread_count."""
    with db_session() as session:
        session.query(IngestionNotification).delete()
        session.commit()
        created = _create_sample_notifications(session, count=15)

    resp = client.get("/api/notifications?limit=5&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total_count"] == 15
    assert len(data["notifications"]) == 5
    assert data["offset"] == 0
    assert data["limit"] == 5

    # Page 2
    resp2 = client.get("/api/notifications?limit=5&offset=5")
    data2 = resp2.json()
    assert len(data2["notifications"]) == 5
    # IDs should be descending
    assert data2["notifications"][0]["id"] < data["notifications"][0]["id"]


def test_notifications_filtering(client: TestClient):
    """Filtering notifications by stage, status, is_read, and search string."""
    with db_session() as session:
        session.query(IngestionNotification).delete()
        session.commit()
        _create_sample_notifications(session, count=12)

    # Filter by stage='fetch'
    resp = client.get("/api/notifications?stage=fetch")
    data = resp.json()
    assert all(n["stage"] == "fetch" for n in data["notifications"])

    # Filter by status='failed'
    resp = client.get("/api/notifications?status=failed")
    data = resp.json()
    assert all(n["status"] == "failed" for n in data["notifications"])

    # Filter by is_read=true
    resp = client.get("/api/notifications?is_read=true")
    data = resp.json()
    assert all(n["is_read"] is True for n in data["notifications"])

    # Search filter
    resp = client.get("/api/notifications?search=number 3")
    data = resp.json()
    assert len(data["notifications"]) >= 1
    assert "number 3" in data["notifications"][0]["message"]


def test_notification_single_deletion_and_read_toggle(client: TestClient):
    """DELETE /api/notifications/{id} and PATCH /api/notifications/{id}/read."""
    with db_session() as session:
        n = IngestionNotification(
            task_id="test_single_del",
            message="Single deletion target",
            stage="fetch",
            status="info",
            created_at=datetime.now().isoformat(),
            read=0,
        )
        session.add(n)
        session.commit()
        session.refresh(n)
        target_id = n.id

    # Toggle read to true
    patch_resp = client.patch(f"/api/notifications/{target_id}/read?is_read=true")
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_read"] is True

    with db_session() as session:
        assert session.query(IngestionNotification).filter_by(id=target_id).first().read == 1

    # Delete single
    del_resp = client.delete(f"/api/notifications/{target_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_id"] == target_id

    with db_session() as session:
        assert session.query(IngestionNotification).filter_by(id=target_id).first() is None


def test_notifications_batch_deletion(client: TestClient):
    """Batch deleting notifications by ID list and read_only flag."""
    with db_session() as session:
        session.query(IngestionNotification).delete()
        session.commit()
        created = _create_sample_notifications(session, count=8)
        ids_to_del = [created[0].id, created[1].id]

    # Delete by JSON payload ids
    del_resp = client.request("DELETE", "/api/notifications", json={"ids": ids_to_del})
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_count"] == 2

    with db_session() as session:
        for did in ids_to_del:
            assert session.query(IngestionNotification).filter_by(id=did).first() is None

    # Delete read-only
    del_read_resp = client.delete("/api/notifications?read_only=true")
    assert del_read_resp.status_code == 200
    with db_session() as session:
        assert session.query(IngestionNotification).filter_by(read=1).count() == 0
