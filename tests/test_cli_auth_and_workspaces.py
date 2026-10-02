"""
Unit and integration tests for:
- Health check route (/api/health)
- Power loss setting cache resilience
- CLI API Key authentication and /system/restart
- Workspace coding agent tools (create_file, read_file, edit_file)
- Workspace snapshots, version history, restore, and freeze-to-article
- tev1 decision gating integration
- CLI workspace commands
"""

import json
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kb_web.server import app
from kb_web.base import db_session, config
from kb_web.models_orm import (
    CliApiKey,
    Workspace,
    WorkspaceFile,
    WorkspaceSnapshot,
    FetchedPage,
)
from kb_web.agent_tools import tool_create_file, tool_read_file, tool_edit_file
from kb_web.workspace_agent import run_tev1_gating, execute_agent_step
import sys
from pathlib import Path

cli_src = Path(__file__).resolve().parent.parent / "kb-web-cli" / "src"
if str(cli_src) not in sys.path:
    sys.path.insert(0, str(cli_src))

from kb_web_cli.main import app as cli_app

runner = CliRunner()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client():
    import time
    from kb_web.base import COOKIE_NAME, generate_session_token
    c = TestClient(app)
    token = generate_session_token(time.time() + 3600)
    c.cookies.set(COOKIE_NAME, token)
    return c


def test_api_health_endpoint(client):
    """Verifies that /api/health is accessible publicly without authentication."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "ok"
    assert data.get("app") == "kb-web"


def test_cli_api_key_auth_and_restart(client, monkeypatch):
    """Verifies that registered database CLI API keys authenticate requests and allow system restart."""
    import os
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    test_key = "cli-test-token-powerloss-123"
    with db_session() as session:
        if not session.query(CliApiKey).filter_by(key=test_key).first():
            session.add(
                CliApiKey(
                    key=test_key,
                    name="Unit Test Laptop",
                    created_at="2026-10-02T12:00:00",
                )
            )
            session.commit()

    # 1. Unauthenticated request to protected CLI API
    unauth = client.get("/api/cli/logs")
    assert unauth.status_code == 401

    # 2. Authenticated request using CLI API key
    auth_res = client.get("/api/cli/logs", headers={"X-API-Key": test_key})
    assert auth_res.status_code == 200

    # 3. Request system restart via CLI endpoint
    restart_res = client.post(
        "/api/cli/system/restart", headers={"X-API-Key": test_key}
    )
    assert restart_res.status_code == 200
    assert restart_res.json().get("status") == "restarting"


def test_config_disk_settings_cache(tmp_path, monkeypatch):
    """Verifies that persistent disk cache protects credentials and settings across restarts."""
    monkeypatch.setattr(config, "configs_dir", tmp_path)

    # Write setting to cache
    config._write_cached_setting("settings_external", "admin_password", "super_secret_pw")
    read_back = config._read_cached_setting("settings_external", "admin_password")
    assert read_back == "super_secret_pw"

    # Simulate database offline during _read_db_setting
    def failing_read(*args, **kwargs):
        raise ConnectionError("PostgreSQL starting up after power outage...")

    with monkeypatch.context() as m:
        m.setattr(config, "database_url", "postgresql://localhost:5432/kb")
        m.setattr("kb_web.base.db_session", failing_read)

        val = config._read_db_setting("settings_external", "admin_password", "admin123")
        assert val == "super_secret_pw"  # Restored from disk cache instead of falling back to admin123!


def test_agent_tools_primitives():
    """Verifies create_file, read_file, and edit_file tools."""
    with db_session() as session:
        ws = Workspace(name="Tools Test WS", template="blank")
        session.add(ws)
        session.commit()
        ws_id = ws.id

        # 1. Test create_file
        create_res = tool_create_file(
            session=session,
            workspace_id=ws_id,
            file_path="src/main.py",
            content="print('Hello')\nname = 'Alice'\nprint(f'Hi {name}')\n",
            annotation="Initial script",
        )
        assert create_res["success"] is True
        assert create_res["action"] == "created"

        # 2. Test read_file full and slice
        full_read = tool_read_file(session, ws_id, "src/main.py")
        assert full_read["success"] is True
        assert full_read["total_lines"] == 3

        slice_read = tool_read_file(session, ws_id, "src/main.py", start_line=2, end_line=2)
        assert slice_read["success"] is True
        assert slice_read["content"] == "name = 'Alice'\n"

        # 3. Test edit_file
        edit_res = tool_edit_file(
            session=session,
            workspace_id=ws_id,
            file_path="src/main.py",
            target_content="Alice",
            replacement_content="Bob",
        )
        assert edit_res["success"] is True

        # Verify edited content
        verify_read = tool_read_file(session, ws_id, "src/main.py")
        assert "Bob" in verify_read["content"]
        assert "Alice" not in verify_read["content"]


def test_workspace_snapshots_and_freeze_to_article(auth_client):
    """Verifies workspace snapshotting, version history, restore, and freeze to Knowledge Base article."""
    with db_session() as session:
        ws = Workspace(name="Snapshot Demo", template="web-game")
        session.add(ws)
        session.commit()
        ws_id = ws.id

        session.add(
            WorkspaceFile(
                workspace_id=ws_id,
                file_path="index.html",
                content="<h1>Initial Version</h1>",
                language="html",
            )
        )
        session.commit()

    # 1. Create snapshot v1.0.0
    snap_res = auth_client.post(
        f"/api/workspaces/{ws_id}/snapshots",
        json={"version_tag": "v1.0.0", "description": "Release 1.0 baseline"},
    )
    assert snap_res.status_code == 200
    snap_id = snap_res.json()["snapshot_id"]

    # 2. List snapshots
    list_res = auth_client.get(f"/api/workspaces/{ws_id}/snapshots")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1
    assert list_res.json()[0]["version_tag"] == "v1.0.0"

    # 3. Modify workspace file
    auth_client.post(
        f"/api/workspaces/{ws_id}/files",
        json={"path": "index.html", "content": "<h1>Modified Version</h1>", "language": "html"},
    )

    # 4. Restore from snapshot v1.0.0
    restore_res = auth_client.post(f"/api/workspaces/{ws_id}/snapshots/{snap_id}/restore")
    assert restore_res.status_code == 200

    ws_check = auth_client.get(f"/api/workspaces/{ws_id}")
    assert ws_check.json()["files"]["index.html"]["content"] == "<h1>Initial Version</h1>"

    # 5. Freeze snapshot to Knowledge Base article
    freeze_res = auth_client.post(f"/api/workspaces/{ws_id}/snapshots/{snap_id}/freeze-article")
    assert freeze_res.status_code == 200
    data = freeze_res.json()
    assert data["status"] == "published"
    assert "workspace://" in data["article_url"]

    # Verify article is present in database
    with db_session() as session:
        page = session.query(FetchedPage).filter_by(url=data["article_url"]).first()
        assert page is not None
        assert "Initial Version" in page.md_content
        assert page.exclude_from_general == 0


def test_tev1_decision_gating_mock():
    """Verifies tev1 gating parsing and fallbacks."""
    mock_client = MagicMock()
    mock_answer = MagicMock()
    mock_answer.answers = {
        "intent": MagicMock(choice="create_file"),
        "target_file": MagicMock(choice="test.py"),
        "needs_reading": MagicMock(noul=0.1),
    }
    mock_client.systemone.return_value = mock_answer

    decision = run_tev1_gating(
        client=mock_client,
        workspace_files=["app.py", "test.py"],
        user_prompt="Create a new test file test.py",
        active_file=None,
    )
    assert decision["success"] is True
    assert decision["intent"] == "create_file"
    assert decision["target_file"] == "test.py"
    assert decision["needs_reading"] is False


def test_cli_workspace_subcommands(monkeypatch, tmp_path):
    """Verifies CLI commands for snapshots and restart."""
    test_config = {
        "server_url": "http://127.0.0.1:8050",
        "api_key": "test-cli-key",
        "computer_name": "TestRunner",
    }
    config_dir = tmp_path / ".kb"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "cli-config.json"
    with open(config_file, "w") as f:
        json.dump(test_config, f)

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Test help commands
    res_help = runner.invoke(cli_app, ["workspace", "--help"])
    assert res_help.exit_code == 0
    assert "snapshots" in res_help.stdout
    assert "snapshot" in res_help.stdout
    assert "freeze" in res_help.stdout
    assert "agent" in res_help.stdout

    res_restart_help = runner.invoke(cli_app, ["restart", "--help"])
    assert res_restart_help.exit_code == 0
    assert "remote restart" in res_restart_help.stdout.lower()
