"""
Unit tests for Raw SQL Reporting with Decision Model Gating and Admin Server Restart.
"""

import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import COOKIE_NAME, generate_session_token
from kb_web.routers.reports import (
    split_sql_statements,
    check_static_sql_safety,
    evaluate_sql_safety,
)


@pytest.fixture
def auth_client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def test_split_sql_statements():
    """Verify robust multi-statement splitting with quotes and comments handled properly."""
    # Simple single statement
    s1 = "SELECT * FROM fetched_pages"
    assert split_sql_statements(s1) == ["SELECT * FROM fetched_pages"]

    # Multiple statements
    s2 = "SELECT 1; SELECT 2; SELECT 3;"
    assert split_sql_statements(s2) == ["SELECT 1", "SELECT 2", "SELECT 3"]

    # Semicolons inside string literals
    s3 = "SELECT 'hello; world' AS greeting; SELECT 42;"
    assert split_sql_statements(s3) == ["SELECT 'hello; world' AS greeting", "SELECT 42"]

    # Semicolons inside comments
    s4 = "-- Comment with ; semicolon\nSELECT 1; /* Block ; comment */ SELECT 2;"
    res4 = split_sql_statements(s4)
    assert len(res4) == 2


def test_static_sql_safety_allowed():
    """Verify non-destructive read queries and temporary table operations are permitted."""
    safe_queries = [
        "SELECT url, title FROM fetched_pages LIMIT 10;",
        "WITH cte AS (SELECT domain, count(*) cnt FROM fetched_pages GROUP BY domain) SELECT * FROM cte;",
        "CREATE TEMP TABLE temp_summary AS SELECT domain, count(*) FROM fetched_pages GROUP BY domain;",
        "CREATE TEMPORARY TABLE IF NOT EXISTS tmp_calc (val int);",
        "CREATE TABLE #tsql_temp (id int);",
        "DROP TABLE IF EXISTS temp_summary;",
        "DROP TABLE IF EXISTS #tsql_temp;",
        "DROP TEMPORARY TABLE tmp_calc;",
        """
        CREATE TEMP TABLE temp_counts (cnt int);
        INSERT INTO temp_counts VALUES (10);
        SELECT * FROM temp_counts;
        DROP TABLE temp_counts;
        """,
    ]
    for q in safe_queries:
        is_safe, reason, _ = check_static_sql_safety(q)
        assert is_safe is True, f"Expected safe for query: {q}, but got: {reason}"


def test_static_sql_safety_destructive_rejected():
    """Verify destructive operations against persistent entities are caught and rejected."""
    destructive_queries = [
        ("DROP TABLE public.audit_logs CASCADE;", "Cannot drop persistent table"),
        ("DROP TABLE fetched_pages;", "Cannot drop persistent table"),
        ("TRUNCATE notes;", "TRUNCATE command is prohibited"),
        ("ALTER TABLE fetched_pages ADD COLUMN test_col int;", "ALTER TABLE is prohibited"),
        ("DELETE FROM notes WHERE id = 1;", "DML statement target 'notes' is not a temporary table"),
        ("UPDATE fetched_pages SET title = 'hacked';", "DML statement target 'fetched_pages' is not a temporary table"),
        ("DROP DATABASE postgres;", "Prohibited destructive DDL"),
        ("DROP SCHEMA public;", "Prohibited destructive DDL"),
        ("GRANT ALL ON fetched_pages TO public;", "Privilege management commands are prohibited"),
        ("ATTACH DATABASE 'test.db' AS test;", "Database maintenance command prohibited"),
    ]
    for q, expected_phrase in destructive_queries:
        is_safe, reason, _ = check_static_sql_safety(q)
        assert is_safe is False, f"Expected rejection for query: {q}"
        assert expected_phrase.lower() in reason.lower(), f"Expected '{expected_phrase}' in '{reason}'"


def test_evaluate_sql_safety_decision_model_gate():
    """Verify systemone decision gating properly honors non-destructive threshold (nd_01 >= 0.5)."""
    # 1. SystemOne returns high non-destructive score
    with patch("kb_web.routers.reports._get_ollama_client") as mock_get_client:
        mock_cli = MagicMock()
        mock_cli.systemone.return_value = {
            "answers": {
                "statement_dialect": {"choice": "PostgreSQL"},
                "d_01_compliance": {"noul": 0.98},
                "nd_01_compliance": {"noul": 0.95},
            }
        }
        mock_get_client.return_value = mock_cli

        res = evaluate_sql_safety("SELECT 1 AS val;", dialect="PostgreSQL")
        assert res["allowed"] is True
        assert res["decision_gate"]["nd_01_score"] == 0.95

    # 2. SystemOne returns low non-destructive score (< 0.5)
    with patch("kb_web.routers.reports._get_ollama_client") as mock_get_client:
        mock_cli = MagicMock()
        mock_cli.systemone.return_value = {
            "answers": {
                "statement_dialect": {"choice": "PostgreSQL"},
                "d_01_compliance": {"noul": 0.90},
                "nd_01_compliance": {"noul": 0.20},
            }
        }
        mock_get_client.return_value = mock_cli

        res = evaluate_sql_safety("SELECT 1 AS val;", dialect="PostgreSQL")
        assert res["allowed"] is False
        assert "classified query as destructive" in res["reason"]

    # 3. SystemOne raises exception -> Graceful fallback to static validation
    with patch("kb_web.routers.reports._get_ollama_client") as mock_get_client:
        mock_cli = MagicMock()
        mock_cli.systemone.side_effect = RuntimeError("Ollama offline")
        mock_get_client.return_value = mock_cli

        res = evaluate_sql_safety("SELECT 1 AS val;", dialect="PostgreSQL")
        assert res["allowed"] is True
        assert "systemone_fallback" in res["decision_gate"]


def test_api_raw_sql_endpoint_success(auth_client):
    """Test successful raw SQL query execution via POST /api/reports/raw-sql."""
    # Simple query
    payload = {
        "query": "SELECT 123 AS num, 'kb-web-test' AS label;",
        "limit": 10,
    }
    resp = auth_client.post("/api/reports/raw-sql", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert "num" in data["columns"]
    assert "label" in data["columns"]
    assert len(data["rows"]) == 1
    assert data["rows"][0]["num"] == 123
    assert data["rows"][0]["label"] == "kb-web-test"


def test_api_raw_sql_endpoint_temp_table_excused(auth_client):
    """Test multi-statement raw SQL using an excused temporary table."""
    query = """
    CREATE TEMP TABLE temp_unit_test (id int, val text);
    INSERT INTO temp_unit_test VALUES (1, 'Alpha'), (2, 'Beta');
    SELECT * FROM temp_unit_test ORDER BY id ASC;
    DROP TABLE IF EXISTS temp_unit_test;
    """
    payload = {"query": query, "limit": 100}
    resp = auth_client.post("/api/reports/raw-sql", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["columns"] == ["id", "val"]
    assert len(data["rows"]) == 2
    assert data["rows"][0]["val"] == "Alpha"
    assert data["rows"][1]["val"] == "Beta"
    assert "temp_unit_test" in data["decision_gate"]["temporary_tables"]


def test_api_raw_sql_endpoint_destructive_rejected(auth_client):
    """Test rejection of destructive statements via POST /api/reports/raw-sql."""
    payload = {"query": "DROP TABLE IF EXISTS public.audit_logs CASCADE;"}
    resp = auth_client.post("/api/reports/raw-sql", json=payload)
    assert resp.status_code == 400
    err = resp.json()
    assert "Cannot drop persistent table" in str(err)


def test_api_raw_sql_export_csv_and_json(auth_client):
    """Test exporting raw SQL queries to CSV and JSON."""
    # CSV export
    resp_csv = auth_client.post(
        "/api/reports/raw-sql/export",
        json={"query": "SELECT 1 AS a, 2 AS b;", "format": "csv"},
    )
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert "a,b" in resp_csv.text

    # JSON export
    resp_json = auth_client.post(
        "/api/reports/raw-sql/export",
        json={"query": "SELECT 1 AS a, 2 AS b;", "format": "json"},
    )
    assert resp_json.status_code == 200
    assert "application/json" in resp_json.headers["content-type"]
    exported_data = resp_json.json()
    assert isinstance(exported_data, list)
    assert exported_data[0]["a"] == 1


def test_admin_server_restart_auth_required():
    """Verify POST /admin/server/restart requires authentication."""
    anon_client = TestClient(app)
    resp = anon_client.post(
        "/admin/server/restart", json={"pull_git": False}, follow_redirects=False
    )
    # FastApi Depends(verify_auth) redirects to /login or returns 401/403
    assert resp.status_code in (302, 303, 307, 401, 403)


def test_admin_server_restart_endpoint_simulation(auth_client):
    """Verify authenticated POST /admin/server/restart works smoothly."""
    # Simulated restart without pull_git
    resp = auth_client.post("/admin/server/restart", json={"pull_git": False})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["pull_git"] is False

    # Simulated restart with pull_git (mocking subprocess to avoid git network operations)
    with patch("subprocess.run") as mock_sub:
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "Already up to date."
        mock_res.stderr = ""
        mock_sub.return_value = mock_res

        resp_git = auth_client.post("/admin/server/restart", json={"pull_git": True})
        assert resp_git.status_code == 200, resp_git.text
        data_git = resp_git.json()
        assert data_git["status"] == "success"
        assert data_git["pull_git"] is True
        assert any("git pull" in log for log in data_git["logs"])
