import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
import uuid
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from kb_web.base import db_session, get_engine
from kb_web.models_orm import Source, ProcessorXref, FetchedPage, ChunkEmbedding, seed_default_processors
from kb_web.queue_processor import (
    resolve_callback,
    enqueue_source,
    IngestionWorker,
    get_worker,
    start_worker,
    stop_worker,
)
from kb_web.server import app


# Test helper callbacks
def _dummy_step_one(source: Source, session):
    source.file_hash = "hash_step_1"


def _dummy_step_two(source: Source, session):
    source.file_hash = "hash_step_2"


def _dummy_fail_step(source: Source, session):
    raise RuntimeError("Intentional processor failure")


@pytest.fixture(autouse=True)
def ensure_schema_and_processors(monkeypatch):
    """Ensures database schema and default processors exist before test runs, and disables Gotify."""
    monkeypatch.setattr("kb_web.queue_processor.post_error_to_gotify", MagicMock())
    seed_default_processors(get_engine())


def test_default_processors_seeded():
    """Verify that default pipeline processors are seeded with correct stages and chains."""
    with db_session() as session:
        fetcher = session.query(ProcessorXref).filter_by(service_name="fetcher").first()
        summary = session.query(ProcessorXref).filter_by(service_name="wiki_summary").first()
        tagger = session.query(ProcessorXref).filter_by(service_name="tagger").first()
        embeddings = session.query(ProcessorXref).filter_by(service_name="embeddings").first()

        assert fetcher is not None
        assert fetcher.stage == "pre"
        assert fetcher.next_processor_id == summary.id

        assert summary is not None
        assert summary.stage == "process"
        assert summary.next_processor_id == tagger.id

        assert tagger is not None
        assert tagger.stage == "process"
        assert tagger.next_processor_id == embeddings.id

        assert embeddings is not None
        assert embeddings.stage == "post"
        assert embeddings.next_processor_id is None


def test_resolve_callback():
    """Verify dynamic callback resolver for module:func and invalid paths."""
    func = resolve_callback("kb_web.queue_processor:resolve_callback")
    assert func is resolve_callback

    with pytest.raises(ValueError):
        resolve_callback("invalid_path_without_separator")

    with pytest.raises(AttributeError):
        resolve_callback("kb_web.queue_processor:non_existent_function_12345")


def test_enqueue_source_defaults():
    """Verify enqueue_source correctly initializes Source record with defaults."""
    # HTML default processor
    s1_id = enqueue_source("https://example.com/test-queue-1", source_type="html", collection_id=2)
    with db_session() as session:
        s1 = session.query(Source).filter_by(id=s1_id).first()
        assert s1 is not None
        assert s1.url == "https://example.com/test-queue-1"
        assert s1.processor_id == 1  # fetcher
        assert s1.status == "pending"
        assert s1.retry_count == 0
        meta = json.loads(s1.metadata_json)
        assert meta["collection_id"] == 2

    # YouTube default processor
    s2_id = enqueue_source("https://www.youtube.com/watch?v=dQw4w9WgXcQ", source_type="youtube")
    with db_session() as session:
        s2 = session.query(Source).filter_by(id=s2_id).first()
        assert s2 is not None
        assert s2.processor_id == 5  # youtube_metadata

    # File default processor
    s3_id = enqueue_source("/path/to/doc.pdf", source_type="docling", custom_instructions="Focus on architecture")
    with db_session() as session:
        s3 = session.query(Source).filter_by(id=s3_id).first()
        assert s3 is not None
        assert s3.processor_id == 7  # docling_parser
        assert s3.path == "/path/to/doc.pdf"
        meta = json.loads(s3.metadata_json)
        assert meta["custom_instructions"] == "Focus on architecture"


def test_worker_pipeline_progression():
    """Verify IngestionWorker advances stages sequentially to completion."""
    with db_session() as session:
        # Create 2 custom test processors
        p2 = ProcessorXref(
            service_name=f"test_proc_2_{uuid.uuid4().hex[:6]}",
            callback_path="tests.test_queue_processor:_dummy_step_two",
            stage="process",
            next_processor_id=None,
            is_active=True,
        )
        session.add(p2)
        session.flush()
        p2_id = p2.id

        p1 = ProcessorXref(
            service_name=f"test_proc_1_{uuid.uuid4().hex[:6]}",
            callback_path="tests.test_queue_processor:_dummy_step_one",
            stage="pre",
            next_processor_id=p2_id,
            is_active=True,
        )
        session.add(p1)
        session.flush()
        p1_id = p1.id
        session.commit()

        # Enqueue job pointing to p1
        test_source_id = str(uuid.uuid4())
        src = Source(
            id=test_source_id,
            url="https://example.com/worker-test",
            type="html",
            processor_id=p1_id,
            status="pending",
        )
        session.add(src)
        session.commit()

    worker = IngestionWorker(poll_interval=0.1, max_retries=3)

    # Step 1 execution
    did_work = worker.process_next_job(source_id=test_source_id)
    assert did_work is True

    with db_session() as session:
        src = session.query(Source).filter_by(id=test_source_id).first()
        assert src.processor_id == p2_id
        assert src.status == "pending"
        assert src.file_hash == "hash_step_1"

    # Step 2 execution
    did_work = worker.process_next_job(source_id=test_source_id)
    assert did_work is True

    with db_session() as session:
        src = session.query(Source).filter_by(id=test_source_id).first()
        assert src.status == "completed"
        assert src.file_hash == "hash_step_2"
        assert src.error_log is None


def test_worker_retry_and_failure():
    """Verify worker increments retries on exception and marks failed on max_retries."""
    with db_session() as session:
        p_fail = ProcessorXref(
            service_name=f"test_proc_fail_{uuid.uuid4().hex[:6]}",
            callback_path="tests.test_queue_processor:_dummy_fail_step",
            stage="pre",
            next_processor_id=None,
            is_active=True,
        )
        session.add(p_fail)
        session.flush()
        p_fail_id = p_fail.id
        session.commit()

        fail_source_id = str(uuid.uuid4())
        src = Source(
            id=fail_source_id,
            url="https://example.com/failure-test",
            type="html",
            processor_id=p_fail_id,
            status="pending",
            retry_count=0,
        )
        session.add(src)
        session.commit()

    worker = IngestionWorker(poll_interval=0.1, max_retries=2)

    # Attempt 1 -> retry_count becomes 1, status pending
    worker.process_next_job(source_id=fail_source_id)
    with db_session() as session:
        src = session.query(Source).filter_by(id=fail_source_id).first()
        assert src.retry_count == 1
        assert src.status == "pending"
        assert "Intentional processor failure" in (src.error_log or "")

    # Attempt 2 -> retry_count becomes 2, reaches max_retries=2 -> status failed
    worker.process_next_job(source_id=fail_source_id)
    with db_session() as session:
        src = session.query(Source).filter_by(id=fail_source_id).first()
        assert src.retry_count == 2
        assert src.status == "failed"


def test_worker_thread_lifecycle():
    """Verify worker daemon thread starts, runs, and stops cleanly."""
    worker = IngestionWorker(poll_interval=0.05)
    assert not worker.is_running
    worker.start()
    assert worker.is_running
    worker.stop(timeout=1.0)
    assert not worker.is_running


def test_rest_api_queue_endpoints():
    """Verify /api/queue/jobs and /api/queue/enqueue REST endpoints."""
    client = TestClient(app)

    # Test enqueue endpoint
    enqueue_payload = {
        "url_or_path": "https://example.com/api-enqueued-page",
        "source_type": "html",
        "collection_id": 1,
        "custom_instructions": "Extract table summary",
    }
    resp = client.post("/api/queue/enqueue", json=enqueue_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    source_id = data["source_id"]
    assert source_id

    # Test list jobs endpoint
    resp_list = client.get(f"/api/queue/jobs?status=pending&limit=10")
    assert resp_list.status_code == 200
    jobs_data = resp_list.json()
    assert "items" in jobs_data
    assert any(item["id"] == source_id for item in jobs_data["items"])
    matching = next(item for item in jobs_data["items"] if item["id"] == source_id)
    assert matching["url"] == "https://example.com/api-enqueued-page"
    assert matching["processor_name"] == "fetcher"
