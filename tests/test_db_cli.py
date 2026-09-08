"""
Tests for kb-web database CLI commands, SQLite migration utilities,
video media indexing and backup zip retention, and admin backup API routes.
"""

import os
import json
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kb_web.config import Config
from kb_web.models_orm import SafeVector, Base, YouTubeVideo, FetchedPage
from kb_web.base import get_engine, db_session
from kb_web.server import app, config as server_config
from kb_web.cli import app as cli_app
import kb_web.video_manager as vm


@pytest.fixture(autouse=True)
def mock_gotify(monkeypatch):
    """Mocks Gotify globally during tests to prevent real notifications."""
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
def client() -> TestClient:
    """Fixture providing TestClient for FastAPI app."""
    return TestClient(app)


def test_safe_vector_type():
    """Validates SafeVector parses stringified JSON vectors and preserves lists and None."""
    vec = SafeVector()
    assert vec.process_bind_param(None, None) is None
    assert vec.process_bind_param([0.1, 0.2, 0.3], None) == "[0.1, 0.2, 0.3]"
    assert vec.process_bind_param("[0.4, 0.5, 0.6]", None) == "[0.4, 0.5, 0.6]"
    assert vec.process_bind_param("not-json", None) == "not-json"

    # PostgreSQL dialect simulation
    class MockPgDialect:
        name = "postgresql"

    pg_dialect = MockPgDialect()
    assert vec.process_bind_param("[0.1, 0.2, 0.3]", pg_dialect) == [0.1, 0.2, 0.3]
    assert vec.process_bind_param([0.4, 0.5], pg_dialect) == [0.4, 0.5]

    # Result value handling
    assert vec.process_result_value(None, None) is None
    assert vec.process_result_value("[0.1, 0.2]", None) == [0.1, 0.2]
    assert vec.process_result_value([0.3, 0.4], None) == [0.3, 0.4]


def test_video_manager_indexing(tmp_path, monkeypatch):
    """Ensures local video indexing discovers video files and updates database records."""
    cfg = Config()
    cfg.data_root = tmp_path
    cfg.configs_dir = tmp_path / "configs"
    cfg.database_url = ""
    cfg.db_path = tmp_path / "test_vid.db"

    # Create dummy video directory and files
    videos_dir = tmp_path / "media" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    vid1_path = videos_dir / "dQw4w9WgXcQ.mp4"
    vid1_path.write_bytes(b"dummy video content 1")
    sub_dir = videos_dir / "channel_a"
    sub_dir.mkdir(parents=True, exist_ok=True)
    vid2_path = sub_dir / "review_abc12345678.webm"
    vid2_path.write_bytes(b"dummy video content 2")

    # Set up engine & table
    import kb_web.base
    kb_web.base._engine = None
    kb_web.base._SessionFactory = None
    monkeypatch.setattr(kb_web.base, "config", cfg)

    engine = get_engine()
    Base.metadata.create_all(engine)

    with db_session() as session:
        # Seed parent pages and youtube video records
        session.add(FetchedPage(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Vid 1", fetched_at="2026-09-08"))
        session.add(FetchedPage(url="https://www.youtube.com/watch?v=abc12345678", title="Vid 2", fetched_at="2026-09-08"))
        session.add(YouTubeVideo(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", video_id="dQw4w9WgXcQ"))
        session.add(YouTubeVideo(url="https://www.youtube.com/watch?v=abc12345678", video_id="abc12345678"))

    res = vm.index_local_videos(config=cfg)
    assert res["total_files"] == 2
    assert res["indexed_count"] == 2

    # Verify rows updated in DB
    with db_session() as session:
        v1 = session.query(YouTubeVideo).filter_by(video_id="dQw4w9WgXcQ").first()
        assert v1 is not None
        assert v1.local_path == "dQw4w9WgXcQ.mp4"

        v2 = session.query(YouTubeVideo).filter_by(video_id="abc12345678").first()
        assert v2 is not None
        assert "abc12345678.webm" in v2.local_path.replace("\\", "/")


def test_video_backup_max_two_retention(tmp_path):
    """Enforces strict maximum 2 video backup retention policy."""
    cfg = Config()
    cfg.data_root = tmp_path
    cfg.configs_dir = tmp_path / "configs"
    cfg.backups_dir = tmp_path / "backups"
    videos_dir = tmp_path / "media" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "test_video.mp4").write_bytes(b"sample video bytes")

    # 1. Create first backup
    b1 = vm.create_video_backup_zip(config=cfg)
    time.sleep(1.1)  # Ensure distinct timestamp in filename
    assert b1.exists()
    assert len(vm.list_video_backups(config=cfg)) == 1

    # 2. Create second backup
    b2 = vm.create_video_backup_zip(config=cfg)
    time.sleep(1.1)
    assert b2.exists()
    assert len(vm.list_video_backups(config=cfg)) == 2

    # 3. Create third backup - should prune b1, keeping only 2
    b3 = vm.create_video_backup_zip(config=cfg)
    assert b3.exists()

    remaining = vm.list_video_backups(config=cfg)
    assert len(remaining) == 2
    remaining_names = [r["filename"] for r in remaining]
    assert b1.name not in remaining_names
    assert b2.name in remaining_names
    assert b3.name in remaining_names


def test_video_backup_restore_and_delete(tmp_path):
    """Verifies restoring video files from backup ZIP and deleting backup archive."""
    cfg = Config()
    cfg.data_root = tmp_path
    cfg.configs_dir = tmp_path / "configs"
    cfg.backups_dir = tmp_path / "backups"
    videos_dir = tmp_path / "media" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    test_vid = videos_dir / "vid_xyz.mp4"
    test_vid.write_bytes(b"payload 12345")

    # Create backup
    zip_path = vm.create_video_backup_zip(config=cfg)
    assert zip_path.exists()

    # Delete video file
    test_vid.unlink()
    assert not test_vid.exists()

    # Restore from backup
    restored_count = vm.restore_video_backup_zip(zip_path, config=cfg)
    assert restored_count >= 1
    assert test_vid.exists()
    assert test_vid.read_bytes() == b"payload 12345"

    # Delete backup archive
    assert vm.delete_video_backup_zip(zip_path.name, config=cfg) is True
    assert not zip_path.exists()


def test_db_cli_help():
    """Ensures kb-web db CLI commands and options are properly registered."""
    runner = CliRunner()
    result = runner.invoke(cli_app, ["db", "--help"])
    assert result.exit_code == 0
    assert "migrate-sqlite" in result.stdout
    assert "deploy" in result.stdout
    assert "snapshot" in result.stdout
    assert "sync-snapshot" in result.stdout
    assert "replication-setup" in result.stdout
    assert "replication-status" in result.stdout
    assert "backup-videos" in result.stdout
    assert "restore-videos" in result.stdout
    assert "reindex-videos" in result.stdout


def test_db_cli_reindex_and_backup_execution(tmp_path, monkeypatch):
    """Verifies kb-web db reindex-videos and backup-videos CLI subcommands."""
    cfg = Config()
    cfg.data_root = tmp_path
    cfg.configs_dir = tmp_path / "configs"
    cfg.backups_dir = tmp_path / "backups"
    videos_dir = tmp_path / "media" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "dummy_vid.mp4").write_bytes(b"content")

    monkeypatch.setattr(vm, "default_config", cfg)

    runner = CliRunner()
    # Test backup-videos command
    b_res = runner.invoke(cli_app, ["db", "backup-videos"])
    assert b_res.exit_code == 0
    assert "Video backup created successfully" in b_res.stdout

    # Test reindex-videos command
    r_res = runner.invoke(cli_app, ["db", "reindex-videos"])
    assert r_res.exit_code == 0
    assert "Indexed" in r_res.stdout


def test_admin_backups_and_diagnostic_routes(client: TestClient, tmp_path, monkeypatch):
    """Verifies Admin routes for backup creation, download, deletion, restoration, and WS fallback."""
    # 1. Test WebSocket diagnostic HTTP fallback
    ws_fallback_resp = client.get("/admin/ws/import")
    assert ws_fallback_resp.status_code == 200
    assert "WebSocket Import Endpoint Notice" in ws_fallback_resp.text

    # 2. Authenticate admin
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    cookie = {"kb_session": login_resp.cookies.get("kb_session")}

    # Configure backups_dir
    server_config.backups_dir = tmp_path / "admin_backups"
    server_config.backups_dir.mkdir(parents=True, exist_ok=True)

    # 3. Create local database backup via POST /admin/backups/create
    create_resp = client.post("/admin/backups/create", cookies=cookie, follow_redirects=False)
    assert create_resp.status_code == 303
    backups = list(server_config.backups_dir.glob("kb_backup_*.json"))
    assert len(backups) >= 1
    created_name = backups[0].name

    # 4. Download backup via GET /admin/backups/download/{filename}
    dl_resp = client.get(f"/admin/backups/download/{created_name}", cookies=cookie)
    assert dl_resp.status_code == 200
    data = dl_resp.json()
    assert isinstance(data, dict)

    # 5. Restore database backup via POST /admin/backups/restore
    restore_resp = client.post(
        "/admin/backups/restore",
        data={"filename": created_name},
        cookies=cookie,
        follow_redirects=False,
    )
    assert restore_resp.status_code == 303

    # 6. Delete database backup via POST /admin/backups/delete/{filename}
    del_resp = client.post(f"/admin/backups/delete/{created_name}", cookies=cookie, follow_redirects=False)
    assert del_resp.status_code == 303
    assert not (server_config.backups_dir / created_name).exists()

    # 7. Video backup creation via POST /admin/backups/videos/create
    vid_create_resp = client.post("/admin/backups/videos/create", cookies=cookie, follow_redirects=False)
    assert vid_create_resp.status_code == 303
    vid_zips = list(server_config.backups_dir.glob("kb_videos_backup_*.zip"))
    assert len(vid_zips) >= 1
    vid_zip_name = vid_zips[0].name

    # 8. Video backup download via GET /admin/backups/videos/download/{filename}
    vid_dl = client.get(f"/admin/backups/videos/download/{vid_zip_name}", cookies=cookie)
    assert vid_dl.status_code == 200
    assert len(vid_dl.content) > 0

    # 9. Video reindex via POST /admin/backups/videos/reindex
    reindex_resp = client.post("/admin/backups/videos/reindex", cookies=cookie, follow_redirects=False)
    assert reindex_resp.status_code == 303

    # 10. Video backup deletion via POST /admin/backups/videos/delete/{filename}
    vid_del = client.post(f"/admin/backups/videos/delete/{vid_zip_name}", cookies=cookie, follow_redirects=False)
    assert vid_del.status_code == 303
    assert not (server_config.backups_dir / vid_zip_name).exists()
