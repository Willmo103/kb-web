"""Tests for YouTube audio-only downloading and in-browser playback."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, config, db_session, generate_session_token
from kb_web.models_orm import FetchedPage, YouTubeVideo
from kb_web.server import app
from kb_web.utils import download_youtube_audio


@pytest.fixture
def auth_client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture(autouse=True)
def cleanup_audio_test_files():
    from sqlalchemy import inspect, text
    from kb_web.base import get_engine

    eng = get_engine()
    insp = inspect(eng)
    if "youtube_videos" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("youtube_videos")}
        with eng.begin() as conn:
            if "local_path" not in cols:
                conn.execute(text("ALTER TABLE youtube_videos ADD COLUMN local_path VARCHAR;"))
            if "audio_path" not in cols:
                conn.execute(text("ALTER TABLE youtube_videos ADD COLUMN audio_path VARCHAR;"))
    yield
    audio_dir = config.configs_dir.parent / "media" / "audio"
    for vid in ("audTest1111", "audSolo2222"):
        if audio_dir.exists():
            for f in audio_dir.glob(f"*{vid}*"):
                if f.is_file():
                    f.unlink()
    with db_session() as session:
        urls = [
            "https://www.youtube.com/watch?v=audTest1111",
            "https://www.youtube.com/watch?v=audSolo2222",
        ]
        session.query(YouTubeVideo).filter(YouTubeVideo.url.in_(urls)).delete(
            synchronize_session=False
        )
        session.query(FetchedPage).filter(FetchedPage.url.in_(urls)).delete(
            synchronize_session=False
        )
        session.commit()


def test_download_youtube_audio_uses_audio_only_format():
    """Verifies download_youtube_audio requests audio-only format without downloading video."""
    audio_dir = config.configs_dir.parent / "media" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    captured_opts = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            captured_opts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download=False):
            return {"title": "Audio Only Test", "uploader": "TestChannel"}

        def download(self, urls):
            out = audio_dir / "[TestChannel] - Audio Only Test [audTest1111].m4a"
            out.write_bytes(b"FAKE_M4A_AUDIO_BYTES")

    with patch("yt_dlp.YoutubeDL", FakeYDL):
        result_path = download_youtube_audio("audTest1111", config)

    assert Path(result_path).exists()
    assert Path(result_path).suffix == ".m4a"
    # Second call returns cached file immediately
    assert download_youtube_audio("audTest1111", config) == result_path
    # Verify download call used audio-only format selector (no bv*/video)
    dl_opts = [o for o in captured_opts if "outtmpl" in o][0]
    assert "bv" not in dl_opts["format"]
    assert "ba" in dl_opts["format"]


def test_api_youtube_download_audio_db_and_standalone(auth_client):
    """Verifies /api/youtube/download-audio works for DB videos and standalone URLs."""
    db_url = "https://www.youtube.com/watch?v=audTest1111"
    solo_url = "https://youtu.be/audSolo2222"

    with db_session() as session:
        session.add(
            FetchedPage(
                url=db_url,
                title="DB Video Audio Test",
                md_content="Transcript",
                fetched_at="2026-11-17T00:00:00Z",
            )
        )
        session.add(
            YouTubeVideo(
                url=db_url,
                video_id="audTest1111",
                creator="TestCreator",
            )
        )
        session.commit()

    audio_dir = config.configs_dir.parent / "media" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    db_audio_file = audio_dir / "[TestCreator] - DB Video Audio Test [audTest1111].m4a"
    solo_audio_file = audio_dir / "audSolo2222.m4a"

    def fake_dl(video_id, cfg=None):
        if video_id == "audTest1111":
            db_audio_file.write_bytes(b"DB_AUDIO")
            return str(db_audio_file)
        solo_audio_file.write_bytes(b"SOLO_AUDIO")
        return str(solo_audio_file)

    with patch("kb_web.routers.pages.download_youtube_audio", side_effect=fake_dl):
        # 1. DB video audio download
        r1 = auth_client.post("/api/youtube/download-audio", json={"url": db_url})
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["status"] == "success"
        assert d1["video_id"] == "audTest1111"
        assert d1["audio_url"].startswith("/media/audio/")

        # 2. Standalone YouTube URL not in DB
        r2 = auth_client.post("/api/youtube/download-audio", json={"url": solo_url})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["status"] == "success"
        assert d2["video_id"] == "audSolo2222"
        assert d2["audio_url"] == "/media/audio/audSolo2222.m4a"

    # 3. Verify DB row updated and view_page renders audio player
    with db_session() as session:
        yt = session.query(YouTubeVideo).filter_by(url=db_url).first()
        assert yt.audio_path == str(db_audio_file)

    from urllib.parse import quote_plus

    view_resp = auth_client.get(f"/view/page?url={quote_plus(db_url)}")
    assert view_resp.status_code == 200
    assert 'id="yt-audio-player"' in view_resp.text
    assert "/media/audio/" in view_resp.text

    # 4. Verify audio-list endpoint returns both tracks
    list_resp = auth_client.get("/api/youtube/audio-list")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    vids = {i["video_id"] for i in items}
    assert "audTest1111" in vids
    assert "audSolo2222" in vids
