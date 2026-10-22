"""Unit and integration test suite for autonomous worker target execution tracking & deduplication."""

from datetime import datetime, timezone
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, config, db_session, generate_session_token
from kb_web.context_mesh.models import ContextStatement, StatementType, TaxonomicLayer
from kb_web.models_orm import FetchedPage, WorkerJobExecution
from kb_web.server import app
from kb_web.worker import AutonomousWorker


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


def test_worker_job_execution_model_persistence():
    """Verify WorkerJobExecution model persists and retrieves correctly."""
    target_id = f"test://example.com/target-{int(time.time())}"
    with db_session() as session:
        exec_record = WorkerJobExecution(
            job_id="fact_extraction",
            target_id=target_id,
            status="success",
            items_count=4,
            error_message=None,
            executed_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(exec_record)
        session.commit()

        queried = (
            session.query(WorkerJobExecution)
            .filter_by(job_id="fact_extraction", target_id=target_id)
            .first()
        )
        assert queried is not None
        assert queried.status == "success"
        assert queried.items_count == 4
        assert queried.error_message is None
        assert queried.executed_at is not None

        # Clean up
        session.delete(queried)
        session.commit()


def test_autonomous_worker_execution_helpers():
    """Verify AutonomousWorker helper methods for tracking, querying, and clearing target executions."""
    worker = AutonomousWorker()
    job_id = "test_job_helpers"
    t1 = "https://example.com/page1"
    t2 = "https://example.com/page2"

    worker.clear_target_executions(job_id)

    worker.log_target_execution(job_id, t1, status="success", items_count=5)
    worker.log_target_execution(job_id, t2, status="skipped", items_count=0)

    executed = worker.get_executed_targets(job_id)
    assert t1 in executed
    assert t2 in executed

    success_only = worker.get_executed_targets(job_id, statuses=["success"])
    assert t1 in success_only

    recent_logs = worker.get_target_executions(job_id)
    assert len(recent_logs) >= 2
    assert any(log["target_id"] == t1 and log["status"] == "success" for log in recent_logs)
    assert any(log["target_id"] == t2 and log["status"] == "skipped" for log in recent_logs)

    cleared = worker.clear_target_executions(job_id)
    assert cleared >= 2
    assert len(worker.get_executed_targets(job_id)) == 0


@pytest.mark.anyio
async def test_fact_extraction_deduplication_and_no_loop():
    """Verify AutonomousWorker._run_fact_extraction processes pages sequentially without looping."""
    worker = AutonomousWorker()
    worker.clear_target_executions("fact_extraction")

    ts = int(time.time())
    url_a = f"https://test.local/ssd1306_{ts}.py"
    url_b = f"https://test.local/display_{ts}.py"

    try:
        with db_session() as session:
            session.add_all([
                FetchedPage(
                    url=url_a,
                    title="ssd1306.py",
                    description="OLED driver script",
                    md_content="def init_display(): pass",
                    fetched_at="2099-01-01T01:00:00",
                ),
                FetchedPage(
                    url=url_b,
                    title="display.py",
                    description="Display driver wrapper",
                    md_content="import ssd1306",
                    fetched_at="2099-01-01T01:05:00",
                ),
            ])
            session.commit()

        mock_statements = [
            ContextStatement(
                statement="SSD1306 drives 128x64 I2C displays.",
                statement_type=StatementType.FACT,
                canonical_path="hardware/electronics/display/ssd1306",
                layer_level=TaxonomicLayer.SPECIES,
                source_uri=url_a,
                source_title="ssd1306.py",
            )
        ]

        with patch(
            "kb_web.context_mesh.pipeline.FactExtractionPipeline.extract_from_page",
            return_value=mock_statements,
        ):
            job = worker.jobs["fact_extraction"]

            # Run 1: Should pick url_b (latest fetched_at 01:05:00)
            res1 = await worker._run_fact_extraction(job, "cycle_1")
            assert res1["status"] == "success"
            first_url = res1["url"]

            # Run 2: Should pick url_a (older), NOT repeat the first url
            res2 = await worker._run_fact_extraction(job, "cycle_2")
            assert res2["status"] == "success"
            second_url = res2["url"]
            assert first_url != second_url

            # Run 3: Neither url_a nor url_b must EVER be picked again!
            res3 = await worker._run_fact_extraction(job, "cycle_3")
            if res3["status"] == "success":
                assert res3["url"] not in (url_a, url_b)
            else:
                assert res3["status"] in ("noop", "skipped")
    finally:
        with db_session() as session:
            session.query(FetchedPage).filter(FetchedPage.url.in_([url_a, url_b])).delete()
            session.commit()
        worker.clear_target_executions("fact_extraction")


@pytest.mark.anyio
async def test_fact_extraction_zero_statements_logged_as_skipped():
    """Verify that pages yielding 0 context statements are marked as skipped and never loop."""
    worker = AutonomousWorker()
    worker.clear_target_executions("fact_extraction")

    ts = int(time.time())
    url_zero = f"https://test.local/empty_facts_{ts}.py"

    try:
        with db_session() as session:
            session.add(
                FetchedPage(
                    url=url_zero,
                    title="empty_facts.py",
                    description="Empty code file",
                    md_content="# pass",
                    fetched_at="2099-01-01T02:00:00",
                )
            )
            session.commit()

        with patch(
            "kb_web.context_mesh.pipeline.FactExtractionPipeline.extract_from_page",
            return_value=[],
        ):
            job = worker.jobs["fact_extraction"]

            # Run 1: Returns 0 statements -> marks status="skipped"
            res1 = await worker._run_fact_extraction(job, "cycle_zero_1")
            assert res1["status"] == "skipped"
            assert res1["url"] == url_zero

            # Run 2: Since it was logged as skipped, it must NOT be selected again!
            res2 = await worker._run_fact_extraction(job, "cycle_zero_2")
            assert res2.get("url") != url_zero

        # Verify execution record has status="skipped"
        with db_session() as session:
            rec = (
                session.query(WorkerJobExecution)
                .filter_by(job_id="fact_extraction", target_id=url_zero)
                .first()
            )
            assert rec is not None
            assert rec.status == "skipped"
            assert rec.items_count == 0
    finally:
        with db_session() as session:
            session.query(WorkerJobExecution).filter_by(job_id="fact_extraction", target_id=url_zero).delete()
            session.query(FetchedPage).filter_by(url=url_zero).delete()
            session.commit()
        worker.clear_target_executions("fact_extraction")


def test_job_execution_api_endpoints(auth_client):
    """Verify GET and POST API endpoints for job target executions."""
    from kb_web.worker import autonomous_worker

    job_id = "wiki_curation"
    autonomous_worker.clear_target_executions(job_id)

    # Log two sample executions
    autonomous_worker.log_target_execution(job_id, "https://api.test/page1", "success", 1)
    autonomous_worker.log_target_execution(job_id, "https://api.test/page2", "failed", 0, "Test error")

    # 1. GET /api/jobs/{job_id}/executions
    resp = auth_client.get(f"/api/jobs/{job_id}/executions?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["count"] >= 2
    assert any(e["target_id"] == "https://api.test/page1" and e["status"] == "success" for e in data["executions"])
    assert any(e["target_id"] == "https://api.test/page2" and e["status"] == "failed" for e in data["executions"])

    # 2. POST /api/jobs/{job_id}/executions/clear
    resp_clear = auth_client.post(f"/api/jobs/{job_id}/executions/clear")
    assert resp_clear.status_code == 200
    clear_data = resp_clear.json()
    assert clear_data["status"] == "success"
    assert clear_data["cleared_count"] >= 2

    # 3. Verify GET now returns empty
    resp_empty = auth_client.get(f"/api/jobs/{job_id}/executions")
    assert resp_empty.status_code == 200
    assert resp_empty.json()["count"] == 0
