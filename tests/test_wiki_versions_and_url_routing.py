"""Unit and integration tests for Wiki Versioning, Model Steering, and Internal URL Routing."""

from datetime import datetime, timezone
import time
from urllib.parse import quote_plus
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient

from kb_web.server import app, config as server_config
from kb_web.base import (
    db_session,
    COOKIE_NAME,
    generate_session_token,
    resolve_entity_url,
)
from kb_web.models_orm import (
    FetchedPage,
    WikiVersion,
    Note,
)
from kb_web.routers.notes import _cascade_delete_notes
from kb_web.routers.admin_batch import _cascade_delete_page_urls


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {server_config.api_key}"}


def test_wiki_version_orm_and_cascade_delete():
    """Verifies WikiVersion ORM model creation and cascade deletion with parent FetchedPage."""
    test_url = "https://example.com/test-wiki-version-cascade"
    now_str = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        # Clean any preexisting
        session.query(WikiVersion).filter_by(url=test_url).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()

        page = FetchedPage(
            url=test_url,
            title="Initial Title",
            description="Initial Wiki Content",
            wiki_model="gemma4:latest",
            fetched_at=now_str,
        )
        session.add(page)
        session.flush()

        wv1 = WikiVersion(
            url=test_url,
            title="Initial Title",
            wiki_content="Initial Wiki Content",
            model_name="gemma4:latest",
            steering_instructions="Initial prompt",
            created_at=now_str,
        )
        session.add(wv1)

    with db_session() as session:
        stored = session.query(WikiVersion).filter_by(url=test_url).first()
        assert stored is not None
        assert stored.wiki_content == "Initial Wiki Content"
        assert stored.model_name == "gemma4:latest"
        assert stored.steering_instructions == "Initial prompt"

        # Delete parent FetchedPage
        session.query(FetchedPage).filter_by(url=test_url).delete()

    with db_session() as session:
        remaining = session.query(WikiVersion).filter_by(url=test_url).all()
        assert len(remaining) == 0


def test_resolve_entity_url_utility():
    """Verifies resolve_entity_url correctly classifies and dispatches internal vs external schemes."""
    # 1. note:// scheme
    note_url = "note://personal-vault/projects/design-system"
    res_note = resolve_entity_url(note_url)
    assert res_note["is_internal"] is True
    assert res_note["clickable"] is True
    assert res_note["scheme"] == "note"
    assert res_note["target_url"] == f"/notes/edit?url={quote_plus(note_url)}"
    assert res_note["icon"] == "📝"

    # 2. workspace:// scheme
    ws_url = "workspace://workspace-abc-123/snapshot/v2"
    res_ws = resolve_entity_url(ws_url)
    assert res_ws["is_internal"] is True
    assert res_ws["clickable"] is True
    assert res_ws["scheme"] == "workspace"
    assert res_ws["target_url"] == "/workspaces/workspace-abc-123"
    assert res_ws["icon"] == "💻"

    # 3. workspace:// root
    res_ws_root = resolve_entity_url("workspace://")
    assert res_ws_root["clickable"] is False
    assert res_ws_root["target_url"] == "/workspaces"

    # 4. http/https external links
    ext_url = "https://docs.pytest.org/en/latest/"
    res_ext = resolve_entity_url(ext_url)
    assert res_ext["is_internal"] is False
    assert res_ext["clickable"] is True
    assert res_ext["target_url"] == ext_url
    assert res_ext["target"] == "_blank"
    assert res_ext["icon"] == "🌐"

    # 5. Unknown pseudo-scheme
    unknown_url = "foobar://something/internal"
    res_unk = resolve_entity_url(unknown_url)
    assert res_unk["is_internal"] is True
    assert res_unk["clickable"] is False
    assert res_unk["target_url"] == "#"

    # 6. None or empty
    assert resolve_entity_url(None)["clickable"] is False
    assert resolve_entity_url("")["clickable"] is False


def test_open_dispatcher_endpoint(client: TestClient):
    """Verifies GET /open redirects correctly for note://, workspace://, and external schemes."""
    # note:// redirect
    note_url = "note://my-vault/my-note"
    resp = client.get(f"/open?url={quote_plus(note_url)}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/notes/edit?url={quote_plus(note_url)}"

    # workspace:// redirect
    ws_url = "workspace://ws-uuid-999/snapshot/tag"
    resp = client.get(f"/open?url={quote_plus(ws_url)}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/workspaces/ws-uuid-999"

    # external https redirect
    ext_url = "https://example.com/test-redirect"
    resp = client.get(f"/open?url={quote_plus(ext_url)}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == ext_url


def test_regenerate_wiki_archives_old_and_records_model(client: TestClient):
    """Verifies that regenerating a wiki archives the prior wiki to WikiVersion and records the selected model."""
    test_url = "https://example.com/test-regenerate-model-steering"
    now_str = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        session.query(WikiVersion).filter_by(url=test_url).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()

        page = FetchedPage(
            url=test_url,
            title="Initial Title",
            description="# Old Wiki\n\nThis is the old summary.",
            wiki_model="qwen2.5:latest",
            md_content="# Raw Content\n\nSome raw article text here.",
            fetched_at=now_str,
        )
        session.add(page)

    new_wiki_text = "# New Steered Wiki\n\nThis is newly generated content."
    with patch("kb_web.routers.admin.extract_wiki_content", return_value=new_wiki_text) as mock_extract, \
         patch("kb_web.routers.admin.update_article_embedding"):
        resp = client.post(
            "/admin/regenerate/wiki",
            data={
                "url": test_url,
                "model": "deepseek-r1:latest",
                "steering_instructions": "Focus strictly on technical implementation.",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert kwargs["model"] == "deepseek-r1:latest"
        assert kwargs["steering_instructions"] == "Focus strictly on technical implementation."

    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        assert page.description == new_wiki_text
        assert page.wiki_model == "deepseek-r1:latest"
        assert page.title == "New Steered Wiki"

        # Check that previous wiki was archived
        versions = session.query(WikiVersion).filter_by(url=test_url).all()
        assert len(versions) == 1
        assert versions[0].wiki_content == "# Old Wiki\n\nThis is the old summary."
        assert versions[0].model_name == "qwen2.5:latest"


def test_restore_wiki_endpoint(client: TestClient):
    """Verifies restoring a historical wiki version archives current and updates wiki_model."""
    test_url = "https://example.com/test-restore-wiki"
    now_str = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        session.query(WikiVersion).filter_by(url=test_url).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()

        page = FetchedPage(
            url=test_url,
            title="Active V2 Title",
            description="Active V2 Wiki Content",
            wiki_model="llama3.1:latest",
            fetched_at=now_str,
        )
        session.add(page)
        session.flush()

        v1 = WikiVersion(
            url=test_url,
            title="Archived V1 Title",
            wiki_content="Archived V1 Wiki Content",
            model_name="mistral:latest",
            steering_instructions=None,
            created_at=now_str,
        )
        session.add(v1)
        session.flush()
        v1_id = v1.id

    with patch("kb_web.routers.admin.update_article_embedding"):
        resp = client.post(
            "/admin/wiki/restore",
            data={"url": test_url, "version_id": v1_id},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        # Active page should now have v1 content and model
        assert page.description == "Archived V1 Wiki Content"
        assert page.title == "Archived V1 Title"
        assert page.wiki_model == "mistral:latest"

        # And v2 should now be saved in wiki_versions
        versions = session.query(WikiVersion).filter_by(url=test_url).all()
        assert len(versions) == 2
        archived_v2 = [v for v in versions if v.id != v1_id][0]
        assert archived_v2.wiki_content == "Active V2 Wiki Content"
        assert archived_v2.model_name == "llama3.1:latest"


def test_batch_and_notes_cascade_deletes_wiki_versions():
    """Verifies batch cascade deletion and note cascade deletion clean up WikiVersion."""
    test_url = "note://test-vault/test-note-cascade"
    now_str = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        session.query(WikiVersion).filter_by(url=test_url).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()
        session.query(Note).filter_by(url=test_url).delete()

        note = Note(
            vault_name="test-vault",
            folder_path="",
            url=test_url,
            title="Test Note Cascade",
            content="# Hello",
            created_at=now_str,
            updated_at=now_str,
        )
        page = FetchedPage(
            url=test_url,
            title="Test Note Cascade",
            description="Wiki for Note",
            wiki_model="gemma4:latest",
            fetched_at=now_str,
        )
        wv = WikiVersion(
            url=test_url,
            title="Test Note Cascade",
            wiki_content="Old Wiki for Note",
            model_name="gemma4:latest",
            created_at=now_str,
        )
        session.add(note)
        session.add(page)
        session.add(wv)
        session.flush()
        note_id = note.id

    # Test _cascade_delete_notes
    with db_session() as session:
        _cascade_delete_notes(session, [note_id])

    with db_session() as session:
        assert session.query(WikiVersion).filter_by(url=test_url).count() == 0

    # Test _cascade_delete_page_urls
    page_url = "https://example.com/test-batch-cascade"
    with db_session() as session:
        p = FetchedPage(url=page_url, title="P", description="D", fetched_at=now_str)
        wv = WikiVersion(url=page_url, title="P", wiki_content="W", created_at=now_str)
        session.add(p)
        session.add(wv)

    with db_session() as session:
        _cascade_delete_page_urls(session, [page_url])

    with db_session() as session:
        assert session.query(WikiVersion).filter_by(url=page_url).count() == 0


def test_view_page_renders_wiki_versions_and_model(client: TestClient):
    """Verifies that /view/page renders model attribution and historical version badges."""
    test_url = "https://example.com/test-view-page-versions"
    now_str = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        session.query(WikiVersion).filter_by(url=test_url).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()

        page = FetchedPage(
            url=test_url,
            title="Test Page Title",
            description="Active Wiki Content",
            wiki_model="qwen-coder:7b",
            fetched_at=now_str,
        )
        session.add(page)
        session.flush()

        wv = WikiVersion(
            url=test_url,
            title="Old Title",
            wiki_content="Old Wiki Content",
            model_name="deepseek:latest",
            created_at=now_str,
        )
        session.add(wv)
        session.flush()
        wv_id = wv.id

    # 1. View current page
    resp = client.get(f"/view/page?url={quote_plus(test_url)}")
    assert resp.status_code == 200
    assert "qwen-coder:7b" in resp.text
    assert "Active Wiki Content" in resp.text
    assert "Regenerate AI Wiki" in resp.text

    # 2. View historical wiki version
    resp_hist = client.get(f"/view/page?url={quote_plus(test_url)}&wiki_version_id={wv_id}")
    assert resp_hist.status_code == 200
    assert "deepseek:latest" in resp_hist.text
    assert "Old Wiki Content" in resp_hist.text
    assert "Restore Version" in resp_hist.text
