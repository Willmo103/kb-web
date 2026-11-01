"""Comprehensive test suite verifying solutions for GitHub Issues #122 through #128.

#122: Taxonomical Fact Management page (/facts) & CRUDS + search API
#123: Fact extraction context awareness & vector similarity deduplication
#124: Decoupled pipeline stages & worker execution (prevents infinite loop on wiki failure)
#125: Auto-deletion of rejected facts from database
#126: 7-tier biological taxonomy pattern (Tier 1 Kingdom = General Topic, Phylum/Class = Sub-Topics)
#127: MAX_FACT_CHAR_COUNT configuration (144) & LLM re-prompt shortening
#128: AI Topic & Sub-Topic assignment pipeline step, governance table, approval & denial
"""

import json
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_

from kb_web.base import COOKIE_NAME, generate_session_token, db_session
from kb_web.config import Config
from kb_web.context_mesh.models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer
from kb_web.context_mesh.pipeline import FactExtractionPipeline
from kb_web.context_mesh.store import ContextStore
from kb_web.models_orm import FetchedPage, TopicGovernanceORM, ContextStatementORM
from kb_web.server import app
from kb_web.taxonomy.engine import TaxonomyClassifier, TaxonomyEngine
from kb_web.worker import AutonomousWorker


@pytest.fixture
def auth_client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture(autouse=True)
def clean_test_entities():
    """Clean test statements, topics, and pages before and after runs."""
    def _do_clean():
        with db_session() as session:
            session.query(ContextStatementORM).filter(
                or_(
                    ContextStatementORM.id.like("test_issue_%"),
                    ContextStatementORM.source_uri.like("https://example.com/test-issue-%"),
                )
            ).delete(synchronize_session=False)
            session.query(TopicGovernanceORM).filter(
                TopicGovernanceORM.name.like("TestTopic%")
            ).delete(synchronize_session=False)
            session.query(FetchedPage).filter(
                FetchedPage.url.like("https://example.com/test-issue-%")
            ).delete(synchronize_session=False)
            session.commit()
    _do_clean()
    yield
    _do_clean()


# =========================================================================
# Issue #122: Taxonomical Fact Management UI & CRUDS API
# =========================================================================

def test_issue_122_facts_management_page_and_cruds_api(auth_client: TestClient):
    """Test /facts UI rendering, CRUDS endpoints, and search API."""
    # 1. Test /facts UI renders
    res = auth_client.get("/facts")
    assert res.status_code == 200
    assert "Taxonomical Fact Management" in res.text
    assert "Search Engine" in res.text

    # Fast mock for embedding during API calls
    with patch.object(FactExtractionPipeline, "_embed_text", return_value=[0.1, 0.2, 0.3, 0.4]):
        # 2. Test POST /api/context-mesh/statements (Create)
        create_payload = {
            "statement": "Antigravity agents operate with strict governance boundaries.",
            "statement_type": "negative_invariant",
            "canonical_path": "Software Documentation/Agents/Governance/Architecture/Fact/rule1",
            "layer_level": "order",
            "source_uri": "https://example.com/test-issue-122",
            "source_title": "Issue 122 Source",
            "confidence": 0.95,
            "tags": ["agents", "governance"],
        }
        create_res = auth_client.post("/api/context-mesh/statements", json=create_payload)
        assert create_res.status_code == 200
        created_data = create_res.json()
        assert created_data["status"] == "success"
        stmt_id = created_data["id"]
        assert stmt_id.startswith("stmt_")

        # 3. Test PUT /api/context-mesh/statements/{id} (Update)
        update_payload = {
            "statement": "Antigravity agents operate with verified strict governance boundaries.",
            "confidence": 0.99,
            "statement_type": "preference",
        }
        update_res = auth_client.put(f"/api/context-mesh/statements/{stmt_id}", json=update_payload)
        assert update_res.status_code == 200
        assert update_res.json()["status"] == "success"

        store = ContextStore()
        updated_stmt = store.get_by_id(stmt_id)
        assert updated_stmt is not None
        assert updated_stmt.statement == update_payload["statement"]
        assert updated_stmt.confidence == 0.99
        assert updated_stmt.statement_type == StatementType.PREFERENCE

    # 4. Test GET /api/context-mesh/search (Search API)
    search_res = auth_client.get("/api/context-mesh/search", params={"q": "governance", "mode": "lexical"})
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] >= 1
    assert any(s["id"] == stmt_id for s in search_data["statements"])

    # 5. Test DELETE /api/context-mesh/statements/{id} (Delete)
    del_res = auth_client.delete(f"/api/context-mesh/statements/{stmt_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"
    assert del_res.json()["deleted"] is True
    assert store.get_by_id(stmt_id) is None

    # 6. Test POST /api/context-mesh/statements/bulk-delete
    s1 = ContextStatement(
        id="test_issue_122_bulk1",
        statement="Bulk test statement 1",
        statement_type=StatementType.FACT,
        canonical_path="Software Documentation/Test/Bulk/Fact1",
        layer_level=TaxonomicLayer.SPECIES,
        source_uri="https://example.com/test-issue-122",
        source_title="Issue 122 Source",
    )
    s2 = ContextStatement(
        id="test_issue_122_bulk2",
        statement="Bulk test statement 2",
        statement_type=StatementType.FACT,
        canonical_path="Software Documentation/Test/Bulk/Fact2",
        layer_level=TaxonomicLayer.SPECIES,
        source_uri="https://example.com/test-issue-122",
        source_title="Issue 122 Source",
    )
    store.upsert(s1)
    store.upsert(s2)
    assert store.get_by_id("test_issue_122_bulk1") is not None
    assert store.get_by_id("test_issue_122_bulk2") is not None

    bulk_res = auth_client.post("/api/context-mesh/statements/bulk-delete", json={"statement_ids": ["test_issue_122_bulk1", "test_issue_122_bulk2"]})
    assert bulk_res.status_code == 200
    assert bulk_res.json()["deleted_count"] == 2
    assert store.get_by_id("test_issue_122_bulk1") is None
    assert store.get_by_id("test_issue_122_bulk2") is None


# =========================================================================
# Issue #123: Context Awareness & Vector Similarity Deduplication Gate
# =========================================================================

def test_issue_123_context_awareness_and_deduplication():
    """Verify prompt includes existing facts and vector similarity gate drops duplicates."""
    store = ContextStore()

    # Seed an existing fact for document
    existing_stmt = ContextStatement(
        id="test_issue_123_exist",
        statement="Postgres view vw_page_cards provides indexed article card retrieval.",
        statement_type=StatementType.FACT,
        canonical_path="Software Documentation/Architecture/Database/Postgres/Fact",
        layer_level=TaxonomicLayer.ORDER,
        source_uri="https://example.com/test-issue-123",
        source_title="Database Architecture",
        embedding=[0.1, 0.2, 0.3, 0.4],
    )
    store.upsert(existing_stmt)

    # Setup pipeline with mock client
    mock_client = MagicMock()
    mock_client.list.return_value = {"models": [{"name": "ornith-1.5:9b"}, {"name": "nomic-embed-text"}]}
    mock_client.chat.return_value = {
        "message": {
            "content": json.dumps([
                {
                    "statement": "vw_page_cards provides fast pre-aggregated indexed article card queries.",
                    "statement_type": "fact",
                    "layer_level": "order",
                },
                {
                    "statement": "Qdrant vector collection handles 1536-dimensional semantic embeddings.",
                    "statement_type": "fact",
                    "layer_level": "class",
                },
            ])
        }
    }

    # Simulate embeddings: first statement is highly similar to existing_stmt ([0.1, 0.2, 0.3, 0.4]) -> cos sim ~ 1.0 >= 0.85
    # Second statement has distinct vector
    mock_client.embeddings.side_effect = lambda model, prompt: {
        "embedding": [0.1, 0.2, 0.3, 0.4] if "vw_page_cards" in prompt else [0.9, 0.8, 0.7, 0.6]
    }

    pipeline = FactExtractionPipeline(store=store, client=mock_client)

    # 1. Verify existing context facts are gathered
    gathered = pipeline._gather_existing_context_facts(
        source_uri="https://example.com/test-issue-123",
        source_title="Database Architecture",
        source_text="Postgres view",
    )
    assert any("vw_page_cards" in g for g in gathered)

    # 2. Extract facts from text
    extracted = pipeline.extract_from_text(
        source_text="Postgres view and Qdrant architecture details.",
        source_uri="https://example.com/test-issue-123",
        source_title="Architecture Details",
        canonical_path="Software Documentation/Architecture/Database/Postgres/Doc",
    )

    # First statement should be dropped as duplicate of test_issue_123_exist
    assert len(extracted) == 1
    assert "Qdrant" in extracted[0].statement


# =========================================================================
# Issue #124: Decoupled Pipeline Stages & Worker Execution
# =========================================================================

def test_issue_124_decoupled_pipeline_stages_and_worker():
    """Verify fact extraction is decoupled from wiki generation and skips if already extracted."""
    store = ContextStore()

    # Seed page with facts already extracted
    page_url = "https://example.com/test-issue-124-done"
    page_title = "Worker Schedule Guide"
    page_md = "# Worker Schedule Guide\nAutonomous worker guide."
    store.upsert(ContextStatement(
        id="test_issue_124_done",
        statement="Autonomous workers process jobs based on interval schedules.",
        statement_type=StatementType.FACT,
        canonical_path="Software Documentation/Worker/Fact",
        layer_level=TaxonomicLayer.FAMILY,
        source_uri=page_url,
        source_title=page_title,
    ))

    with db_session() as session:
        page = FetchedPage(
            url=page_url,
            title=page_title,
            description="",  # Wiki generation failed / missing!
            md_content=page_md,
            tags=json.dumps(["worker", "jobs"]),
        )
        session.add(page)
        session.commit()

    # Fact extraction should detect existing facts and gracefully return without re-extracting
    pipeline = FactExtractionPipeline(store=store)
    mock_extract = MagicMock()
    with patch.object(pipeline, "extract_from_text", mock_extract):
        result = pipeline.extract_from_page(
            url=page_url,
            title=page_title,
            md_content=page_md,
            tags=["worker", "jobs"],
            force=False,
        )
        assert len(result) == 1
        assert result[0].id == "test_issue_124_done"
        mock_extract.assert_not_called()

    # Autonomous worker fact_extraction job registration check
    worker = AutonomousWorker()
    assert "fact_extraction" in worker.jobs
    assert worker.jobs["fact_extraction"].category == "llm"


# =========================================================================
# Issue #125: Auto-Deletion of Rejected Facts
# =========================================================================

def test_issue_125_rejected_facts_auto_deleted():
    """Verify that updating evaluation status to REJECTED permanently deletes the fact."""
    store = ContextStore()
    stmt = ContextStatement(
        id="test_issue_125_reject",
        statement="Use raw SQL string concatenation without binding parameters.",
        statement_type=StatementType.NEGATIVE_INVARIANT,
        canonical_path="Software Documentation/Security/Fact",
        layer_level=TaxonomicLayer.SPECIES,
        source_uri="https://example.com/test-issue-125",
        source_title="Security Guide",
        confidence=0.1,
    )
    store.upsert(stmt)
    assert store.get_by_id("test_issue_125_reject") is not None

    # Evaluate as REJECTED
    evaluated = store.update_evaluation("test_issue_125_reject", score=1.0, status=EvalStatus.REJECTED, feedback="Security risk")
    assert evaluated is not None
    assert evaluated.eval_status == EvalStatus.REJECTED

    # Ensure deleted from ContextStore
    assert store.get_by_id("test_issue_125_reject") is None

    # Ensure deleted from database table directly
    with db_session() as session:
        row = session.query(ContextStatementORM).filter_by(id="test_issue_125_reject").first()
        assert row is None


# =========================================================================
# Issue #126: 7-Tier Biological Taxonomy Pattern
# =========================================================================

def test_issue_126_seven_tier_taxonomy_biological_pattern():
    """Verify 7-tier taxonomy structure where Tier 1 Kingdom = General Topic (not hardcoded knowledge)."""
    # 1. Article with explicit general topic and sub-topic
    tax = TaxonomyClassifier.classify_article(
        url="https://example.com/test-issue-126/article",
        title="Python Asyncio Best Practices",
        tags=["python", "asyncio", "concurrency"],
        topic="Software Documentation",
        sub_topic="Concurrency/AsyncIO",
    )

    # Tier 1: Kingdom is General Topic (never 'knowledge')
    assert tax.kingdom == "Software Documentation"
    assert tax.kingdom != "knowledge"

    # Tier 2 & 3: Phylum & Class are 2-level Sub-Topic
    assert tax.phylum == "Concurrency"
    assert tax.class_ == "AsyncIO"

    # Tier 4 & 5: Order & Family are Domain and Path/Source
    assert tax.order == "example_com"
    assert tax.family == "python"

    # Tier 6 & 7: Genus & Species are unique article identifiers
    assert "article" in tax.genus.lower()
    assert "asyncio" in tax.species.lower()

    # Verify canonical path string
    path_str = tax.to_path_string()
    assert path_str.startswith("Software Documentation/Concurrency/AsyncIO/")


# =========================================================================
# Issue #127: MAX_FACT_CHAR_COUNT Configuration & LLM Shortening
# =========================================================================

def test_issue_127_max_fact_char_count_configuration_and_shortening():
    """Verify max_fact_char_count default is 144 and long statements are shortened."""
    cfg = Config()
    assert cfg.max_fact_char_count == 144

    store = ContextStore()
    pipeline = FactExtractionPipeline(store=store)

    long_statement = (
        "The Knowledge-Base platform incorporates an asynchronous autonomous worker engine that "
        "periodically polls database records to curate missing AI wikis, assign curated taxonomy "
        "tags, and extract atomic architectural facts without causing infinite processing loops."
    )
    assert len(long_statement) > 144

    # Test shorten_fact_statement with mock LLM
    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {
            "content": "Autonomous worker periodically curates wikis, tags, and facts without infinite loops."
        }
    }
    pipeline.client = mock_client

    shortened = pipeline.shorten_fact_statement(long_statement, max_chars=144)
    assert len(shortened) <= 144
    assert "Autonomous worker" in shortened

    # If LLM shortening fails or raises an error, fallback hard truncation with ellipsis/period works
    mock_client.chat.side_effect = Exception("Ollama offline")
    fallback_shortened = pipeline.shorten_fact_statement("A" * 200, max_chars=144)
    assert len(fallback_shortened) <= 144
    assert fallback_shortened.endswith(".")


# =========================================================================
# Issue #128: Topic & Sub-Topic Assignment, Governance & Denial Re-queuing
# =========================================================================

def test_issue_128_topic_governance_and_reassignment(auth_client: TestClient):
    """Verify topic governance endpoints (approve, deny), blocklisting, and clearing assigned articles."""
    store = ContextStore()

    # Create a test page assigned to 'TestTopicPending'
    test_page_url = "https://example.com/test-issue-128-page"
    with db_session() as session:
        page = FetchedPage(
            url=test_page_url,
            title="Governance Test Page",
            topic="TestTopicPending",
            sub_topic="Governance/Rules",
            topic_status="pending",
        )
        session.add(page)
        session.commit()

    # Create governance record for TestTopicPending
    with db_session() as session:
        gov = TopicGovernanceORM(
            name="TestTopicPending",
            level="topic",
            status="pending",
        )
        session.add(gov)
        session.commit()

    # 1. Test GET /api/taxonomy/topics returns summary
    summary_res = auth_client.get("/api/taxonomy/topics")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert "topics" in summary_data
    assert any(t["name"] == "TestTopicPending" for t in summary_data["topics"])

    # 2. Test Approve endpoint: POST /api/taxonomy/topics/approve
    approve_res = auth_client.post("/api/taxonomy/topics/approve", json={"name": "TestTopicPending", "level": "topic"})
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "success"

    with db_session() as session:
        gov_row = session.query(TopicGovernanceORM).filter_by(name="TestTopicPending").first()
        assert gov_row.status == "allowed"
        page_row = session.query(FetchedPage).filter_by(url=test_page_url).first()
        assert page_row.topic_status == "approved"

    # 3. Test Deny endpoint: POST /api/taxonomy/topics/deny
    # Denying should set status='denied', blocklist the topic, clear it from pages, and set page topic_status='unassigned'
    deny_res = auth_client.post("/api/taxonomy/topics/deny", json={"name": "TestTopicPending", "level": "topic"})
    assert deny_res.status_code == 200
    assert deny_res.json()["status"] == "success"
    assert deny_res.json()["requeued_count"] >= 1

    with db_session() as session:
        gov_row = session.query(TopicGovernanceORM).filter_by(name="TestTopicPending").first()
        assert gov_row.status == "denied"
        page_row = session.query(FetchedPage).filter_by(url=test_page_url).first()
        assert page_row.topic is None
        assert page_row.sub_topic is None
        assert page_row.topic_status == "unassigned"  # Re-queued for reassignment!
