import json
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import db_session
from kb_web.models_orm import FetchedPage, YouTubeVideo, Collection, CollectionItem, PageVersion


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
def client():
    return TestClient(app)


def test_list_articles_and_pagination(client: TestClient):
    with db_session() as session:
        # Seed test pages
        for i in range(1, 6):
            url = f"https://example.com/test-article-{i}"
            existing = session.query(FetchedPage).filter_by(url=url).first()
            if not existing:
                session.add(
                    FetchedPage(
                        url=url,
                        title=f"Test Article {i}",
                        description=f"Summary for test article {i}",
                        html_content="<p>Full HTML content</p>",
                        md_content=f"# Test Article {i}\n\nContent...",
                        tags=json.dumps(["python", f"tag{i}"]),
                        fetched_at=f"2026-09-12T10:0{i}:00",
                    )
                )

    # 1. Test pagination: page 1 with limit 2
    res = client.get("/api/articles?page=1&limit=2")
    assert res.status_code == 200
    data = res.json()
    assert data["page"] == 1
    assert data["limit"] == 2
    assert len(data["items"]) == 2
    assert data["total"] >= 5
    assert data["has_next"] is True
    assert data["has_prev"] is False

    # 2. Test pagination: page 2
    res_p2 = client.get("/api/articles?page=2&limit=2")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert data_p2["page"] == 2
    assert data_p2["has_prev"] is True
    # Verify different items
    assert data_p2["items"][0]["url"] != data["items"][0]["url"]

    # 3. Test search query
    res_search = client.get("/api/articles?q=Article+3")
    assert res_search.status_code == 200
    data_search = res_search.json()
    assert any("Article 3" in item["title"] for item in data_search["items"])

    # 4. Test tag filter
    res_tag = client.get("/api/articles?tag=tag4")
    assert res_tag.status_code == 200
    data_tag = res_tag.json()
    assert len(data_tag["items"]) >= 1
    assert "tag4" in data_tag["items"][0]["tags"]


def test_article_detail_endpoint(client: TestClient):
    url = "https://example.com/detail-test-page"
    with db_session() as session:
        existing = session.query(FetchedPage).filter_by(url=url).first()
        if not existing:
            session.add(
                FetchedPage(
                    url=url,
                    title="Detail Page Title",
                    description="Detailed wiki description summary",
                    html_content="<h1>Detail</h1><p>Body</p>",
                    md_content="# Detail Page Title\n\nFull markdown body text.",
                    tags=json.dumps(["detail", "fastapi"]),
                    links=json.dumps(["https://example.com/other-page"]),
                    keywords=json.dumps(["test", "wiki"]),
                    fetched_at="2026-09-12T12:00:00",
                )
            )

    # Fetch existing detail
    res = client.get(f"/api/articles/detail?url={url}")
    assert res.status_code == 200
    data = res.json()
    assert data["url"] == url
    assert data["title"] == "Detail Page Title"
    assert data["description"] == "Detailed wiki description summary"
    assert "Full markdown body text" in data["md_content"]
    assert "detail" in data["tags"]
    assert "https://example.com/other-page" in data["links"]

    # Fetch nonexistent detail
    res_404 = client.get("/api/articles/detail?url=https://example.com/does-not-exist")
    assert res_404.status_code == 404


def test_video_endpoints_and_transcript_extraction(client: TestClient):
    video_id = "rick_astley_rest_api"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    transcript_text = (
        "[00:05] We're no strangers to love\n"
        "[00:10] You know the rules and so do I\n"
        "[01:23] A full commitment's what I'm thinking of\n"
    )

    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=video_url).first()
        if not page:
            page = FetchedPage(url=video_url)
            session.add(page)
        page.title = "Never Gonna Give You Up"
        page.description = "Official music video by Rick Astley."
        page.html_content = "<p>Video</p>"
        page.md_content = f"# Never Gonna Give You Up\n\n## Description\nSong description\n\n## Transcript\n{transcript_text}"
        page.tags = json.dumps(["music", "80s"])
        page.fetched_at = "2026-09-12T11:00:00"

        yt = session.query(YouTubeVideo).filter_by(url=video_url).first()
        if not yt:
            yt = YouTubeVideo(url=video_url, video_id=video_id)
            session.add(yt)
        yt.creator = "Rick Astley"
        yt.duration = 213
        yt.view_count = 1500000000
        yt.thumbnail_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    # 1. Test GET /api/videos
    res = client.get("/api/videos?creator=Rick+Astley")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["video_id"] == video_id
    assert data["items"][0]["creator"] == "Rick Astley"
    assert any(c["name"] == "Rick Astley" for c in data["creators"])

    # 2. Test GET /api/videos/transcript by video_id
    res_t = client.get(f"/api/videos/transcript?video_id={video_id}")
    assert res_t.status_code == 200
    t_data = res_t.json()
    assert t_data["video_id"] == video_id
    assert t_data["creator"] == "Rick Astley"
    assert len(t_data["segments"]) == 3
    assert t_data["segments"][0]["timestamp"] == "00:05"
    assert t_data["segments"][0]["seconds"] == 5
    assert "strangers to love" in t_data["segments"][0]["text"]
    assert t_data["segments"][2]["timestamp"] == "01:23"
    assert t_data["segments"][2]["seconds"] == 83


def test_sites_and_tags_endpoints(client: TestClient):
    # Test GET /api/sites
    res_sites = client.get("/api/sites")
    assert res_sites.status_code == 200
    sites_data = res_sites.json()
    assert "items" in sites_data
    assert sites_data["total"] >= 1
    assert any(s["name"] == "example.com" for s in sites_data["items"])

    # Test GET /api/tags
    res_tags = client.get("/api/tags")
    assert res_tags.status_code == 200
    tags_data = res_tags.json()
    assert "tags" in tags_data
    assert tags_data["total"] >= 1
    assert any(t["tag"] == "python" for t in tags_data["tags"])


def test_main_page_html_response_and_pagination(client: TestClient):
    # Test GET /
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "Wiki Index Dashboard" in res_root.text or "Knowledge Library" in res_root.text
    assert "search-input" in res_root.text
    assert "articles-grid-container" in res_root.text

    # Test GET /pages with pagination parameters
    res_pages = client.get("/pages?page=1&limit=2")
    assert res_pages.status_code == 200
    assert "articles-grid-container" in res_pages.text
