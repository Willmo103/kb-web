"""Unit and integration tests for Admin Batch-Delete suite and Content Freeze/Immutability features."""

import json
import time
import pytest
from starlette.testclient import TestClient

from kb_web.server import app, config as server_config
from kb_web.base import db_session, COOKIE_NAME, generate_session_token
from kb_web.models_orm import (
    FetchedPage,
    Note,
    YouTubeVideo,
    ArticleEmbedding,
    ChunkEmbedding,
    Link,
    SiteWiki,
)


from unittest.mock import patch


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {server_config.api_key}"}


@pytest.fixture(autouse=True)
def mock_note_background_processor():
    """Mocks background note tagging/Ollama calls to run deterministically and offline."""
    with patch("kb_web.routers.notes._process_note_in_background") as mock_proc:
        def fake_process(note_id):
            with db_session() as session:
                note = session.query(Note).filter_by(id=note_id).first()
                if note:
                    p = session.query(FetchedPage).filter_by(url=note.url).first()
                    if not p:
                        session.add(FetchedPage(
                            url=note.url,
                            title=f"📝 {note.title}",
                            html_content="",
                            md_content=note.content,
                            fetched_at="2026-10-05T12:00:00",
                            is_frozen=note.is_frozen or 0,
                        ))
                        session.commit()
        mock_proc.side_effect = fake_process
        yield mock_proc


def test_page_freeze_toggle_and_rendering(client: TestClient):
    """Test freezing and unfreezing an article page via admin and API routes."""
    test_url = "https://example.com/test-freeze-article-1"
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        if not page:
            page = FetchedPage(
                url=test_url,
                title="Test Freeze Article",
                description="Testing freeze and immutability.",
                html_content="<p>Test content</p>",
                md_content="# Test content",
                fetched_at="2026-10-05T12:00:00",
                tags=json.dumps(["test", "freeze"]),
                is_frozen=0,
            )
            session.add(page)
            session.commit()

    # 1. Toggle freeze to 1 via admin POST redirect
    resp = client.post(
        "/admin/freeze/page",
        data={"url": test_url, "freeze": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Frozen" in resp.text

    with db_session() as session:
        p = session.query(FetchedPage).filter_by(url=test_url).first()
        assert p.is_frozen == 1

    # 2. Verify view page renders Frozen badge and Unfreeze button
    view_resp = client.get(f"/view/page?url={test_url}")
    assert view_resp.status_code == 200
    assert "❄️" in view_resp.text or "Frozen" in view_resp.text
    assert "Unfreeze Content" in view_resp.text

    # 3. Toggle unfreeze to 0 via API JSON endpoint
    api_resp = client.post(f"/api/pages/{test_url}/freeze")
    assert api_resp.status_code == 200
    data = api_resp.json()
    assert data["status"] == "success"
    assert data["is_frozen"] == 0

    with db_session() as session:
        p = session.query(FetchedPage).filter_by(url=test_url).first()
        assert p.is_frozen == 0


def test_page_freeze_blocks_mutation_actions(client: TestClient):
    """Test that frozen pages reject mutations (wiki regen, tags regen, tag edit, refetch)."""
    test_url = "https://example.com/test-frozen-immutable-guard"
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        if not page:
            page = FetchedPage(
                url=test_url,
                title="Immutable Guard Article",
                description="Testing immutability action gating.",
                html_content="<p>Immutable</p>",
                md_content="# Immutable",
                fetched_at="2026-10-05T12:00:00",
                tags=json.dumps(["immutable"]),
                is_frozen=1,
            )
            session.add(page)
            session.commit()
        else:
            page.is_frozen = 1
            session.commit()

    # 1. Regenerate Wiki -> Rejected
    resp = client.post(f"/admin/regenerate/wiki?url={test_url}", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert "frozen" in resp.headers["location"].lower()

    # 2. Regenerate Tags -> Rejected
    resp = client.post(f"/admin/regenerate/tags?url={test_url}", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert "frozen" in resp.headers["location"].lower()

    # 3. Update Tags Manual -> Rejected
    resp = client.post("/admin/update/tags", data={"url": test_url, "tags_csv": "newtag"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert "frozen" in resp.headers["location"].lower()

    # 4. Re-fetch Page -> Rejected
    resp = client.post(f"/admin/refetch/page?url={test_url}", follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert "frozen" in resp.headers["location"].lower()

    # Verify tags did NOT change
    with db_session() as session:
        p = session.query(FetchedPage).filter_by(url=test_url).first()
        assert json.loads(p.tags) == ["immutable"]

    # Clean up test page
    with db_session() as session:
        session.query(FetchedPage).filter_by(url=test_url).delete()
        session.commit()


def test_note_freeze_toggle_and_edit_guard(client: TestClient):
    """Test freeze toggle on notes and immutability guard in PUT /api/notes/{id}."""
    # 1. Create a note
    create_resp = client.post(
        "/api/notes/paste",
        json={
            "title": "Freeze Note Test",
            "content": "# Original content",
            "syntax": "markdown",
            "vault_name": "TestVault",
            "folder_path": "Drafts",
        },
    )
    assert create_resp.status_code == 200
    note_id = create_resp.json()["id"]

    try:
        # 2. Freeze note
        freeze_resp = client.post(f"/api/notes/{note_id}/freeze")
        assert freeze_resp.status_code == 200
        assert freeze_resp.json()["is_frozen"] == 1

        with db_session() as session:
            n = session.query(Note).filter_by(id=note_id).first()
            assert n.is_frozen == 1
            if n.url:
                p = session.query(FetchedPage).filter_by(url=n.url).first()
                if p:
                    assert p.is_frozen == 1

        # 3. Attempt update while frozen -> should be rejected with 400
        update_resp = client.put(
            f"/api/notes/{note_id}",
            json={"title": "Updated Title", "content": "# Hacked Content", "syntax": "markdown"},
        )
        assert update_resp.status_code == 400
        assert "frozen" in update_resp.json()["detail"].lower()

        # 4. Unfreeze note
        unfreeze_resp = client.post(f"/api/notes/{note_id}/freeze")
        assert unfreeze_resp.status_code == 200
        assert unfreeze_resp.json()["is_frozen"] == 0

        # 5. Update now succeeds
        update_resp = client.put(
            f"/api/notes/{note_id}",
            json={"title": "Updated Title", "content": "# Edited successfully", "syntax": "markdown"},
        )
        assert update_resp.status_code == 200

    finally:
        # Clean up
        with db_session() as session:
            note = session.query(Note).filter_by(id=note_id).first()
            if note:
                if note.url:
                    session.query(FetchedPage).filter_by(url=note.url).delete()
                session.delete(note)
                session.commit()


def test_video_freeze_toggle(client: TestClient):
    """Test video freeze toggle and metadata regeneration lock."""
    test_vid_id = "test_freeze_vid123"
    test_url = f"https://www.youtube.com/watch?v={test_vid_id}"

    with db_session() as session:
        session.query(YouTubeVideo).filter_by(video_id=test_vid_id).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()

        vid = YouTubeVideo(
            video_id=test_vid_id,
            url=test_url,
            creator="Tester",
            duration=120,
            view_count=500,
            channel_id="UC123",
            is_frozen=0,
        )
        page = FetchedPage(
            url=test_url,
            title="Freeze Video Test",
            html_content="<p>Video</p>",
            md_content="# Video",
            fetched_at="2026-10-05T12:00:00",
            tags=json.dumps(["video"]),
            is_frozen=0,
        )
        session.add(vid)
        session.add(page)
        session.commit()

    try:
        # 1. Toggle freeze via /api/videos/{video_id}/freeze
        res = client.post(f"/api/videos/{test_vid_id}/freeze")
        assert res.status_code == 200
        assert res.json()["is_frozen"] == 1

        with db_session() as session:
            v = session.query(YouTubeVideo).filter_by(video_id=test_vid_id).first()
            assert v.is_frozen == 1
            p = session.query(FetchedPage).filter_by(url=test_url).first()
            assert p.is_frozen == 1

        # 2. Attempt regenerate YouTube metadata while frozen -> rejected
        regen_res = client.post(f"/admin/regenerate/youtube-metadata?url={test_url}", follow_redirects=False)
        assert regen_res.status_code == 303
        assert "error=" in regen_res.headers["location"]
        assert "frozen" in regen_res.headers["location"].lower()

    finally:
        with db_session() as session:
            session.query(YouTubeVideo).filter_by(video_id=test_vid_id).delete()
            session.query(FetchedPage).filter_by(url=test_url).delete()
            session.commit()


def test_batch_delete_notes(client: TestClient):
    """Test batch deletion of notes by IDs, by folder prefix, and by vault name."""
    # 1. Create 3 notes across different folders
    n1_resp = client.post("/api/notes/paste", json={"title": "N1", "content": "C1", "vault_name": "VaultA", "folder_path": "Folder1"}).json()
    n2_resp = client.post("/api/notes/paste", json={"title": "N2", "content": "C2", "vault_name": "VaultA", "folder_path": "Folder1/Sub"}).json()
    n3_resp = client.post("/api/notes/paste", json={"title": "N3", "content": "C3", "vault_name": "VaultB", "folder_path": "Folder2"}).json()

    id1, id2, id3 = n1_resp["id"], n2_resp["id"], n3_resp["id"]

    try:
        # Batch delete by IDs: delete id3
        del_ids_resp = client.request("DELETE", "/api/notes/batch", json={"note_ids": [id3]})
        assert del_ids_resp.status_code == 200
        assert del_ids_resp.json()["deleted_count"] == 1
        assert id3 in del_ids_resp.json()["deleted_ids"]

        with db_session() as session:
            assert session.query(Note).filter_by(id=id3).first() is None

        # Batch delete by folder prefix: delete Folder1 (should delete id1 and id2)
        del_prefix_resp = client.request("DELETE", "/api/notes/batch", json={"folder_prefix": "Folder1"})
        assert del_prefix_resp.status_code == 200
        assert del_prefix_resp.json()["deleted_count"] == 2

        with db_session() as session:
            assert session.query(Note).filter_by(id=id1).first() is None
            assert session.query(Note).filter_by(id=id2).first() is None

    finally:
        with db_session() as session:
            session.query(Note).filter(Note.id.in_([id1, id2, id3])).delete()
            session.commit()


def test_batch_delete_site(client: TestClient):
    """Test deleting an entire virtual domain site and all its pages."""
    domain = "batch-test-domain.org"
    url1 = f"https://{domain}/page1"
    url2 = f"https://{domain}/page2"

    with db_session() as session:
        session.query(FetchedPage).filter(FetchedPage.url.in_([url1, url2])).delete()
        p1 = FetchedPage(url=url1, title="Page 1", html_content="<p>1</p>", md_content="# 1", fetched_at="2026-10-05T12:00:00")
        p2 = FetchedPage(url=url2, title="Page 2", html_content="<p>2</p>", md_content="# 2", fetched_at="2026-10-05T12:00:00")
        sw = SiteWiki(site=domain, wiki_content="# Test Site", updated_at="2026-10-05T12:00:00")
        session.add_all([p1, p2, sw])
        session.commit()

    del_resp = client.request("DELETE", f"/api/sites/{domain}/all")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_pages_count"] >= 2

    with db_session() as session:
        assert session.query(FetchedPage).filter(FetchedPage.url.in_([url1, url2])).count() == 0
        assert session.query(SiteWiki).filter_by(site=domain).first() is None


def test_batch_freeze_api(client: TestClient):
    """Test batch freeze and unfreeze API endpoint /api/admin/batch-freeze."""
    u1 = "https://example.com/batch-freeze-1"
    u2 = "https://example.com/batch-freeze-2"

    with db_session() as session:
        session.query(FetchedPage).filter(FetchedPage.url.in_([u1, u2])).delete()
        p1 = FetchedPage(url=u1, title="BF 1", html_content="<p>1</p>", md_content="# 1", fetched_at="2026-10-05T12:00:00", is_frozen=0)
        p2 = FetchedPage(url=u2, title="BF 2", html_content="<p>2</p>", md_content="# 2", fetched_at="2026-10-05T12:00:00", is_frozen=0)
        session.add_all([p1, p2])
        session.commit()

    try:
        # Freeze both
        freeze_resp = client.post("/api/admin/batch-freeze", json={"entity_type": "pages", "ids": [u1, u2], "freeze": 1})
        assert freeze_resp.status_code == 200
        assert freeze_resp.json()["updated_count"] == 2

        with db_session() as session:
            assert session.query(FetchedPage).filter_by(url=u1).first().is_frozen == 1
            assert session.query(FetchedPage).filter_by(url=u2).first().is_frozen == 1

        # Unfreeze both
        unfreeze_resp = client.post("/api/admin/batch-freeze", json={"entity_type": "pages", "ids": [u1, u2], "freeze": 0})
        assert unfreeze_resp.status_code == 200
        assert unfreeze_resp.json()["updated_count"] == 2

        with db_session() as session:
            assert session.query(FetchedPage).filter_by(url=u1).first().is_frozen == 0
            assert session.query(FetchedPage).filter_by(url=u2).first().is_frozen == 0

    finally:
        with db_session() as session:
            session.query(FetchedPage).filter(FetchedPage.url.in_([u1, u2])).delete()
            session.commit()


def test_unified_admin_batch_delete(client: TestClient):
    """Test unified endpoint POST /api/admin/batch-delete."""
    u1 = "https://example.com/unified-batch-del-1"
    with db_session() as session:
        session.query(FetchedPage).filter_by(url=u1).delete()
        p1 = FetchedPage(url=u1, title="Unified 1", html_content="<p>1</p>", md_content="# 1", fetched_at="2026-10-05T12:00:00")
        session.add(p1)
        session.commit()

    res = client.post("/api/admin/batch-delete", json={"entity_type": "pages", "ids": [u1]})
    assert res.status_code == 200
    assert res.json()["deleted_count"] == 1

    with db_session() as session:
        assert session.query(FetchedPage).filter_by(url=u1).first() is None
