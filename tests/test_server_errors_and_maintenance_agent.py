"""
Unit tests for Persistent Server Error Logging and Maintenance Agent Sidecar.
"""

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from kb_web.base import db_session, COOKIE_NAME, generate_session_token
from kb_web.models_orm import ServerErrorLog, TaxonomyItem, ensure_views_and_indexes
from kb_web.base import get_engine
from kb_web.server import app, config as server_config
from kb_web.maintenance_agent import (
    format_error_prompt,
    tool_search_source_code,
    tool_view_artifacts,
    tool_search_errors,
    analyze_error_with_agent,
)
from kb_web.gotify import record_server_error
import time


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {server_config.api_key}"}


def test_ensure_taxonomy_item_class_and_views():
    """Verifies that ensure_views_and_indexes runs cleanly and ensures item_class column exists."""
    engine = get_engine()
    ensure_views_and_indexes(engine)
    # Query TaxonomyItem to verify item_class column is present and selectable
    with db_session() as session:
        count = session.query(TaxonomyItem).count()
        assert count >= 0



def test_format_error_prompt_3000_char_limit():
    """Verifies that the Maintenance Agent error prompt strictly enforces the 3000-char limit."""
    huge_stack_trace = "Traceback (most recent call last):\n" + ("  File 'foo.py', line 1, in bar\n" * 200)
    error_dict = {
        "id": 42,
        "timestamp": "2026-10-05T12:00:00",
        "error_type": "HugeCrashError",
        "error_message": "Something went horribly wrong",
        "stack_trace": huge_stack_trace,
        "request_method": "GET",
        "request_url": "/api/broken-endpoint",
        "client_ip": "127.0.0.1",
    }

    prompt = format_error_prompt(error_dict)
    assert len(prompt) <= 3000
    assert "[TRUNCATED TO 3000 CHARS]" in prompt
    assert "HugeCrashError" in prompt


def test_record_server_error_and_persistence(tmp_path, monkeypatch):
    """Verifies that an uncaught error is inserted into the database and JSONL log."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    fake_exc = RuntimeError("Test simulated database explosion")
    fake_tb = "Traceback (most recent call last):\n  File 'test.py', line 10, in <module>\nRuntimeError: Test simulated database explosion"

    from kb_web.config import Config
    cfg = Config()

    error_id = record_server_error(cfg, fake_exc, fake_tb, request=None)
    assert error_id is not None

    # Check database record
    with db_session() as session:
        record = session.query(ServerErrorLog).filter_by(id=error_id).first()
        assert record is not None
        assert record.error_type == "RuntimeError"
        assert "Test simulated database explosion" in record.error_message
        assert record.status == "open"

    # Check JSONL log file
    jsonl_path = tmp_path / ".kb" / "logs" / "server_errors.jsonl"
    assert jsonl_path.exists()
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    last_entry = json.loads(lines[-1])
    assert last_entry["id"] == error_id
    assert last_entry["error_type"] == "RuntimeError"


def test_tool_search_source_code():
    """Verifies that tool_search_source_code searches repository code and returns matches."""
    res = tool_search_source_code("ensure_views_and_indexes", max_results=5)
    assert "matches" in res
    assert res["total"] > 0
    matched_files = [m["file"] for m in res["matches"]]
    assert any("models_orm.py" in f for f in matched_files)


def test_tool_view_artifacts():
    """Verifies that tool_view_artifacts lists available artifacts and reads markdown files."""
    # List artifacts
    res_list = tool_view_artifacts()
    assert "available_artifacts" in res_list
    assert res_list["total"] > 0

    # Read specific artifact
    first_artifact = res_list["available_artifacts"][0]
    res_read = tool_view_artifacts(artifact_path=first_artifact)
    assert "content" in res_read
    assert len(res_read["content"]) > 0


def test_tool_search_errors():
    """Verifies that tool_search_errors queries historical server error logs."""
    with db_session() as session:
        err = ServerErrorLog(
            timestamp="2026-10-05T15:00:00",
            error_type="UniqueTestErrorXYZ",
            error_message="Unique token 987654321",
            stack_trace="Traceback...",
            request_method="POST",
            request_url="/api/test-search",
            status="open",
        )
        session.add(err)
        session.commit()

    res = tool_search_errors("UniqueTestErrorXYZ")
    assert "matches" in res
    assert res["count"] >= 1
    assert any(m["error_type"] == "UniqueTestErrorXYZ" for m in res["matches"])


def test_analyze_error_with_agent_and_feedback():
    """Verifies that analyze_error_with_agent populates agent_feedback and updates status."""
    with db_session() as session:
        err = ServerErrorLog(
            timestamp="2026-10-05T15:10:00",
            error_type="UndefinedColumn",
            error_message="column taxonomy_items.item_class does not exist",
            stack_trace="Traceback (most recent call last):\n  File 'test.py'...",
            request_method="GET",
            request_url="/taxonomy",
            status="open",
        )
        session.add(err)
        session.commit()
        error_id = err.id

    diagnosis = analyze_error_with_agent(error_id, send_gotify=False)
    assert len(diagnosis) > 0
    assert "Root Cause" in diagnosis

    # Check updated status in DB
    with db_session() as session:
        updated = session.query(ServerErrorLog).filter_by(id=error_id).first()
        assert updated.status == "analyzed"
        assert updated.agent_feedback == diagnosis


def test_api_error_routes(client, auth_headers):
    """Verifies REST API endpoints for error inspection and manual re-analysis."""
    with db_session() as session:
        err = ServerErrorLog(
            timestamp="2026-10-05T15:15:00",
            error_type="APIEndpointTestError",
            error_message="Testing REST API error retrieval",
            stack_trace="Traceback...",
            request_method="GET",
            request_url="/api/test-endpoint",
            status="open",
        )
        session.add(err)
        session.commit()
        error_id = err.id

    # 1. GET /api/errors
    res_list = client.get("/api/errors", headers=auth_headers)
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert "items" in data_list
    assert any(it["id"] == error_id for it in data_list["items"])

    # 2. GET /api/errors/{id}
    res_detail = client.get(f"/api/errors/{error_id}", headers=auth_headers)
    assert res_detail.status_code == 200
    detail_data = res_detail.json()
    assert detail_data["id"] == error_id
    assert detail_data["error_type"] == "APIEndpointTestError"

    # 3. GET /api/errors/search?q=APIEndpointTestError
    res_search = client.get("/api/errors/search?q=APIEndpointTestError", headers=auth_headers)
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["count"] >= 1

    # 4. POST /api/errors/{id}/analyze
    res_analyze = client.post(f"/api/errors/{error_id}/analyze", headers=auth_headers)
    assert res_analyze.status_code == 200
    analyze_data = res_analyze.json()
    assert analyze_data["status"] == "analyzed"
    assert "agent_feedback" in analyze_data
