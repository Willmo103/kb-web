"""Tests for Obsidian Vault ZIP Export and Database-Backed Image Caching."""

import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.image_cache import (
    STATIC_CACHED_IMAGES_DIR,
    cache_and_rewrite_markdown_images,
    sync_cached_images_to_disk,
)
from kb_web.models_orm import (
    ArticleEmbedding,
    CachedImage,
    Collection,
    CollectionItem,
    FetchedPage,
    PageVersion,
    WikiVersion,
)
from kb_web.obsidian_export import build_obsidian_vault_zip, format_source_filename
from kb_web.server import app


@pytest.fixture
def auth_client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture(autouse=True)
def cleanup_export_and_image_test_data():
    yield
    test_urls = [
        "https://obsidian-test.example.com/docs/guide/intro",
        "https://obsidian-test.example.com/docs/guide/advanced",
        "https://www.youtube.com/watch?v=obsTest1234",
        "note://obsidian-test-note",
        "https://img-test.example.com/article",
    ]
    with db_session() as session:
        session.query(ArticleEmbedding).filter(ArticleEmbedding.url.in_(test_urls)).delete(
            synchronize_session=False
        )
        session.query(WikiVersion).filter(WikiVersion.url.in_(test_urls)).delete(
            synchronize_session=False
        )
        session.query(PageVersion).filter(PageVersion.url.in_(test_urls)).delete(
            synchronize_session=False
        )
        session.query(CollectionItem).filter(CollectionItem.source_id.in_(test_urls)).delete(
            synchronize_session=False
        )
        session.query(FetchedPage).filter(FetchedPage.url.in_(test_urls)).delete(
            synchronize_session=False
        )
        session.query(Collection).filter(Collection.title == "ObsidianTestCol").delete(
            synchronize_session=False
        )
        session.query(CachedImage).filter(
            CachedImage.original_url.like("https://img-test.example.com/%")
        ).delete(synchronize_session=False)
        session.commit()


def test_format_source_filename():
    assert format_source_filename("https://example.com/docs/guide/intro") == "docs.guide.intro.md"
    assert format_source_filename("https://example.com/") == "index.md"
    assert format_source_filename("https://www.youtube.com/watch?v=abc12345678") == "watch.abc12345678.md"


def test_obsidian_vault_zip_export_structure_and_backlinks(auth_client):
    u1 = "https://obsidian-test.example.com/docs/guide/intro"
    u2 = "https://obsidian-test.example.com/docs/guide/advanced"
    u_yt = "https://www.youtube.com/watch?v=obsTest1234"
    u_note = "note://obsidian-test-note"

    with db_session() as session:
        col = Collection(title="ObsidianTestCol", visibility="private", created_at="2026-11-17T00:00:00Z")
        session.add(col)
        session.flush()

        p1 = FetchedPage(
            url=u1,
            title="Duplicate Guide Title",
            md_content="Raw intro markdown content.",
            fetched_at="2026-11-17T01:00:00Z",
            tags=json.dumps(["python", "knowledge base"]),
            collection_id=col.id,
            wiki_model="gemma4:latest",
        )
        p2 = FetchedPage(
            url=u2,
            title="Duplicate Guide Title",  # Intentional conflict
            md_content="Raw advanced markdown content.",
            fetched_at="2026-11-17T02:00:00Z",
            tags=json.dumps(["python", "vectors"]),
            collection_id=col.id,
            wiki_model="gemma4:latest",
        )
        p_yt = FetchedPage(
            url=u_yt,
            title="YouTube Transcript Test",
            md_content="[00:01] Hello world transcript.",
            fetched_at="2026-11-17T03:00:00Z",
            tags=json.dumps(["video"]),
        )
        p_note = FetchedPage(
            url=u_note,
            title="Personal Note Excluded",
            md_content="Should never be exported.",
            fetched_at="2026-11-17T04:00:00Z",
        )
        session.add_all([p1, p2, p_yt, p_note])
        session.flush()

        session.add(PageVersion(url=u1, title="Duplicate Guide Title", md_content="v1"))
        session.add(
            WikiVersion(
                url=u1,
                title="Duplicate Guide Title",
                wiki_content="# Duplicate Guide Title\n\nWiki summary for intro.",
                model_name="gemma4:latest",
                created_at="2026-11-17T01:05:00Z",
            )
        )
        session.add(
            WikiVersion(
                url=u2,
                title="Duplicate Guide Title",
                wiki_content="# Duplicate Guide Title\n\nWiki summary for advanced.",
                model_name="qwen2.5:14b",
                created_at="2026-11-17T02:05:00Z",
            )
        )
        session.add(
            WikiVersion(
                url=u_yt,
                title="YouTube Transcript Test",
                wiki_content="Video wiki content.",
                model_name="gemma4:latest",
                created_at="2026-11-17T03:05:00Z",
            )
        )

        # Add embeddings so u1 and u2 are nearest neighbors (and p_note is ignored)
        session.add(ArticleEmbedding(url=u1, embedding=json.dumps([1.0, 0.0, 0.0])))
        session.add(ArticleEmbedding(url=u2, embedding=json.dumps([0.95, 0.05, 0.0])))
        session.add(ArticleEmbedding(url=u_note, embedding=json.dumps([1.0, 0.0, 0.0])))
        session.commit()

    # Mock Ollama client to resolve title conflict
    mock_ollama = MagicMock()
    mock_ollama.chat.return_value = {"message": {"content": "Advanced Guide Deep Dive"}}

    with db_session() as session:
        zip_bytes = build_obsidian_vault_zip(
            session=session,
            ollama_client=mock_ollama,
            neighbor_k=3,
            url_filter=[u1, u2, u_yt, u_note],
        )

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()

        # Verify notes are excluded
        assert not any("obsidian-test-note" in n or "Personal Note Excluded" in n for n in names)

        # Verify _sources structure and naming
        assert "_sources/obsidian-test.example.com/docs.guide.intro.md" in names
        assert "_sources/obsidian-test.example.com/docs.guide.advanced.md" in names
        assert "_sources/www.youtube.com/watch.obsTest1234.md" in names

        src1 = zf.read("_sources/obsidian-test.example.com/docs.guide.intro.md").decode("utf-8")
        assert 'date_scraped: "2026-11-17T01:00:00Z"' in src1
        assert "version: 2" in src1
        assert "Raw intro markdown content." in src1

        # Verify articles structure, conflict resolution, frontmatter, tags, and backlinks
        art1_path = "articles/ObsidianTestCol/obsidian-test.example.com/Duplicate Guide Title.md"
        art2_path = "articles/ObsidianTestCol/obsidian-test.example.com/Advanced Guide Deep Dive.md"
        assert art1_path in names
        assert art2_path in names

        art1 = zf.read(art1_path).decode("utf-8")
        assert 'site: "obsidian-test.example.com"' in art1
        assert 'model_used: "gemma4:latest"' in art1
        assert 'date_scraped: "2026-11-17T01:00:00Z"' in art1
        assert "#python #knowledge-base" in art1
        assert "(/ _sources/" not in art1
        assert "(/_sources/obsidian-test.example.com/docs.guide.intro.md)" in art1
        assert "(/reference/articles/ObsidianTestCol/obsidian-test.example.com/Advanced%20Guide%20Deep%20Dive.md)" in art1

    # Verify HTTP endpoint
    with patch("kb_web.obsidian_export.build_obsidian_vault_zip", return_value=zip_bytes):
        resp = auth_client.get("/admin/export/obsidian")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"


def test_image_caching_and_lazy_backfill(auth_client):
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake_image_bytes_12345"
    expected_hash = hashlib.sha256(fake_png).hexdigest()
    img_url = "https://img-test.example.com/assets/diagram.png"
    page_url = "https://img-test.example.com/article"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = fake_png
    mock_resp.headers = {"content-type": "image/png"}

    with db_session() as session:
        session.add(
            FetchedPage(
                url=page_url,
                title="Image Cache Test",
                md_content=f"Look at this diagram:\n\n![Diagram]({img_url})",
                fetched_at="2026-11-17T01:00:00Z",
            )
        )
        session.commit()

    with patch("kb_web.image_cache.httpx.get", return_value=mock_resp), patch(
        "kb_web.image_cache.validate_target_url", return_value=None
    ):
        resp = auth_client.post("/api/pages/cache-images", json={"url": page_url})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["updated"] is True
        assert data["cached_count"] == 1
        assert f"/static/cached_images/{expected_hash}.png" in data["rendered_html"]

    # Verify DB storage and disk sync
    with db_session() as session:
        cached = session.query(CachedImage).filter_by(image_hash=expected_hash).first()
        assert cached is not None
        assert cached.original_url == img_url
        assert cached.data == fake_png

        disk_file = STATIC_CACHED_IMAGES_DIR / f"{expected_hash}.png"
        assert disk_file.exists()
        assert disk_file.read_bytes() == fake_png

        # Remove disk file and test sync_cached_images_to_disk
        disk_file.unlink()
        assert not disk_file.exists()
        synced = sync_cached_images_to_disk(session)
        assert synced >= 1
        assert disk_file.exists()
        disk_file.unlink()
