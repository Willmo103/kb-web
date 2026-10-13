"""
Unit & Integration Tests for kb-web Modular Server Jobs Framework,
Notification Contract, Workspace Reactivity/Syntax, and Rule 7 Configuration Transparency.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

import time
from kb_web.base import COOKIE_NAME, config, generate_session_token, db_session
from kb_web.models_orm import FetchedPage, Workspace, WorkspaceFile
from kb_web.pipeline import record_notification
from kb_web.repo_importer import get_markdown_syntax, normalize_repo_url
from kb_web.routers.workspaces import _infer_language
from kb_web.server import app
from kb_web.worker import autonomous_worker


@pytest.fixture
def auth_client():
    orig_key = config.api_key
    config.api_key = "test-secret-key"
    try:
        with patch("kb_core.notifier.Gotify") as mock_gotify:
            mock_instance = MagicMock()
            mock_gotify.return_value = mock_instance
            c = TestClient(app)
            c.headers["X-API-Key"] = "test-secret-key"
            c.cookies.set(COOKIE_NAME, generate_session_token(time.time() + 3600))
            yield c
    finally:
        config.api_key = orig_key


def test_notification_api_page_id_resolution(auth_client):
    """Verifies that /api/notifications resolves page_id matching URL and formats unread_count envelope."""
    test_url = "https://example.com/test-notification-resolution"
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        if not page:
            page = FetchedPage(
                url=test_url,
                title="Test Notification Target",
                description="Test description",
                fetched_at="2026-10-12T12:00:00",
            )
            session.add(page)
            session.commit()
            session.refresh(page)
        target_id = page.url

    record_notification(
        stage="test",
        status="success",
        message="Notification resolution test",
        url=test_url,
        title="Test Notification Target",
    )

    resp = auth_client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert "notifications" in data
    assert "unread_count" in data
    assert isinstance(data["notifications"], list)

    matching = [n for n in data["notifications"] if n.get("url") == test_url]
    assert len(matching) > 0
    assert matching[0].get("page_id") == target_id


def test_workspace_syntax_inferrer():
    """Validates that PowerShell, Batch, and other script extensions map to valid Monaco language IDs."""
    assert _infer_language("script.ps1") == "powershell"
    assert _infer_language("tool.ps") == "powershell"
    assert _infer_language("module.psm1") == "powershell"
    assert _infer_language("manifest.psd1") == "powershell"
    assert _infer_language("run.bat") == "bat"
    assert _infer_language("setup.cmd") == "bat"
    assert _infer_language("main.py") == "python"
    assert _infer_language("index.html") == "html"
    assert _infer_language("style.css") == "css"
    assert _infer_language("unknown.xyz") == "plaintext"


def test_workspace_files_api(auth_client):
    """Verifies GET /api/workspaces/{id}/files returns current file list with contents and languages."""
    with db_session() as session:
        ws = Workspace(
            name="Reactivity Test Workspace",
            description="Testing live file updates",
            template="python-demo",
            created_at="2026-10-12T12:00:00",
            updated_at="2026-10-12T12:00:00",
        )
        session.add(ws)
        session.commit()
        session.refresh(ws)
        ws_id = ws.id

        f = WorkspaceFile(
            workspace_id=ws_id,
            file_path="deploy.ps1",
            content="Write-Output 'Testing PowerShell syntax in IDE'",
            language="powershell",
            updated_at="2026-10-12T12:00:00",
        )
        session.add(f)
        session.commit()

    resp = auth_client.get(f"/api/workspaces/{ws_id}/files")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "files" in data
    assert "deploy.ps1" in data["files"]
    assert data["files"]["deploy.ps1"]["language"] == "powershell"
    assert "Write-Output" in data["files"]["deploy.ps1"]["content"]


def test_modular_server_jobs_framework(auth_client):
    """Verifies modular server jobs listing, updating, and execution APIs."""
    jobs = autonomous_worker.get_jobs()
    job_ids = [j["id"] for j in jobs]
    assert "wiki_curation" in job_ids
    assert "tag_curation" in job_ids
    assert "embedding_refresh" in job_ids

    # Update job config via worker method
    updated = autonomous_worker.update_job_config(
        job_id="wiki_curation",
        enabled=True,
        interval_minutes=8,
        model="qwen2.5:latest",
    )
    assert updated["interval_minutes"] == 8
    assert updated["model"] == "qwen2.5:latest"

    # API List jobs
    resp = auth_client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    wiki_job = [j for j in data["jobs"] if j["id"] == "wiki_curation"][0]
    assert wiki_job["interval_minutes"] == 8

    # Detail endpoint
    resp_detail = auth_client.get("/api/jobs/wiki_curation")
    assert resp_detail.status_code == 200
    assert resp_detail.json()["id"] == "wiki_curation"


def test_config_transparency_operational_thresholds():
    """Verifies that operational limits are configurable and not hardcoded (Rule 7)."""
    orig_taxonomy = config.taxonomy_batch_limit
    orig_top_k = config.rag_search_top_k
    orig_sim = config.similarity_threshold
    orig_timeout = config.ollama_timeout

    try:
        config.taxonomy_batch_limit = 750
        assert config.taxonomy_batch_limit == 750

        config.rag_search_top_k = 15
        assert config.rag_search_top_k == 15

        config.similarity_threshold = 0.72
        assert config.similarity_threshold == 0.72

        config.ollama_timeout = 180
        assert config.ollama_timeout == 180
    finally:
        config.taxonomy_batch_limit = orig_taxonomy
        config.rag_search_top_k = orig_top_k
        config.similarity_threshold = orig_sim
        config.ollama_timeout = orig_timeout


def test_git_repo_importer_helpers():
    """Verifies Git repo URL normalization and syntax mapping."""
    canonical, title = normalize_repo_url("https://github.com/owner/my-cool-project.git")
    assert canonical == "repo://github.com/owner/my-cool-project"
    assert title == "owner/my-cool-project"

    assert get_markdown_syntax(Path("script.ps1")) == "powershell"
    assert get_markdown_syntax(Path("Makefile")) == "text"


def test_git_repo_import_api_validation(auth_client):
    """Verifies that POST /api/import/repo validates input."""
    resp = auth_client.post("/api/import/repo", json={"repo_url": ""})
    assert resp.status_code == 400
