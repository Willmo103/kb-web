"""Test suite for facts display on Article Profile and 7-tier biological taxonomy population."""

import json
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import COOKIE_NAME, generate_session_token, db_session
from kb_web.models_orm import FetchedPage, Note, ContextStatementORM, TaxonomyEntityORM
from kb_web.taxonomy.engine import TaxonomyEngine
from kb_web.context_mesh.store import ContextStore
from kb_web.context_mesh.models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def seed_test_data():
    """Seed test article, note, taxonomy entity, and context statements."""
    with db_session() as session:
        # Seed FetchedPage
        page = session.query(FetchedPage).filter_by(url="https://example.com/test-facts-article").first()
        if not page:
            page = FetchedPage(
                url="https://example.com/test-facts-article",
                title="Test Facts & Taxonomy Article",
                description="AI Wiki summary for test article.",
                md_content="# Test Facts Article\n\nThis article contains vital facts for testing.",
                tags=json.dumps(["python", "architecture", "database"]),
                fetched_at="2026-10-22T08:00:00Z",
            )
            session.add(page)

        # Seed Note
        note = session.query(Note).filter_by(title="Test Taxonomy Note").first()
        if not note:
            note = Note(
                title="Test Taxonomy Note",
                content="Sample note markdown content.",
                vault_name="TestVault",
                url="note://TestVault/Test Taxonomy Note",
                tags=json.dumps(["testing", "notes"]),
                created_at="2026-10-22T08:00:00Z",
            )
            session.add(note)

        session.commit()

        # Register Taxonomy Entity
        from kb_web.taxonomy.engine import TaxonomyClassifier
        tax = TaxonomyClassifier.classify_article(url=page.url, title=page.title, tags=["python", "architecture", "database"])
        TaxonomyEngine().register_entity(
            taxonomy=tax,
            physical_location=page.url,
            attributes={"title": page.title, "tags": ["python", "architecture", "database"], "source_type": "article"},
        )

        # Seed ContextStatement
        stmt_id = "stmt_test_unit_123"
        stmt = session.query(ContextStatementORM).filter_by(id=stmt_id).first()
        if not stmt:
            stmt = ContextStatementORM(
                id=stmt_id,
                statement="PostgreSQL is the designated long-term persistent datastore for kb-web.",
                statement_type=StatementType.FACT.value,
                canonical_path="knowledge/text/human_read/kb-web/architecture/ArticleWiki/database",
                layer_level=TaxonomicLayer.SPECIES.value,
                kingdom="knowledge",
                phylum="text",
                class_name="human_read",
                order_name="kb-web",
                family="architecture",
                genus="ArticleWiki",
                species="database",
                source_uri="https://example.com/test-facts-article",
                source_title="Test Facts & Taxonomy Article",
                confidence=1.0,
                score_rank=3.5,
                eval_status="unreviewed",
                created_at="2026-10-22T08:00:00Z",
                updated_at="2026-10-22T08:00:00Z",
            )
            session.add(stmt)

        session.commit()

    yield

    # Clean up test statement and entity
    with db_session() as session:
        session.query(ContextStatementORM).filter_by(id="stmt_test_unit_123").delete()
        session.commit()


def test_sync_taxonomy_entities_and_tree_generation(client: TestClient, seed_test_data):
    """Test sync-entities endpoint and get_7tier_tree hierarchical structure."""
    resp = client.post("/api/taxonomy/sync-entities?limit=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total_synced"] >= 2  # at least the seeded page and note

    # Test GET /api/taxonomy/7tier/tree
    resp_tree = client.get("/api/taxonomy/7tier/tree")
    assert resp_tree.status_code == 200
    tree_data = resp_tree.json()
    assert tree_data["total_entities"] >= 2
    assert "knowledge" in tree_data["tree"]
    k_node = tree_data["tree"]["knowledge"]
    assert k_node["level"] == "kingdom"
    assert k_node["entity_count"] >= 2


def test_context_mesh_statements_api(client: TestClient, seed_test_data):
    """Test GET /api/context-mesh/statements with various filters."""
    # Query all
    resp = client.get("/api/context-mesh/statements?limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total"] >= 1
    assert any(s["id"] == "stmt_test_unit_123" for s in data["statements"])

    # Query with url filter
    resp_url = client.get("/api/context-mesh/statements?url=https://example.com/test-facts-article")
    assert resp_url.status_code == 200
    data_url = resp_url.json()
    assert all(s["source_uri"] == "https://example.com/test-facts-article" for s in data_url["statements"])

    # Query with statement_type filter
    resp_type = client.get("/api/context-mesh/statements?statement_type=fact")
    assert resp_type.status_code == 200
    data_type = resp_type.json()
    assert all(s["statement_type"] == "fact" for s in data_type["statements"])

    # Query with search keyword
    resp_q = client.get("/api/context-mesh/statements?query=PostgreSQL")
    assert resp_q.status_code == 200
    data_q = resp_q.json()
    assert any("PostgreSQL" in s["statement"] for s in data_q["statements"])


def test_context_mesh_statement_evaluation(client: TestClient, seed_test_data):
    """Test POST /api/context-mesh/statements/{id}/evaluate."""
    stmt_id = "stmt_test_unit_123"

    # Evaluate as approved
    eval_resp = client.post(
        f"/api/context-mesh/statements/{stmt_id}/evaluate",
        json={"eval_status": "approved", "score_rank": 5.0, "eval_feedback": "Verified true"},
    )
    assert eval_resp.status_code == 200
    data = eval_resp.json()
    assert data["status"] == "success"
    assert data["statement"]["eval_status"] == "approved"
    assert data["statement"]["score_rank"] == 5.0
    assert data["statement"]["eval_feedback"] == "Verified true"

    # Verify updated in store
    store = ContextStore()
    stmt = store.get_by_id(stmt_id)
    assert stmt is not None
    assert stmt.eval_status == EvalStatus.APPROVED
    assert stmt.score_rank == 5.0


def test_article_view_renders_facts_and_taxonomy(client: TestClient, seed_test_data):
    """Test /view/page renders facts card, taxonomy coordinates, and evaluation controls."""
    url = "https://example.com/test-facts-article"
    resp = client.get(f"/view/page?url={url}")
    assert resp.status_code == 200
    html = resp.text

    # Assert facts section exists
    assert "facts-context-mesh-card" in html
    assert "Extracted Facts & Intent Mesh" in html
    assert "statement_test_unit_123" not in html or "PostgreSQL is the designated long-term" in html
    assert "7-Tier Taxonomy:" in html
    assert "knowledge" in html
    assert "Extract Facts Now" in html


def test_taxonomy_page_renders_7tier_and_facts_mesh(client: TestClient, seed_test_data):
    """Test /taxonomy renders 7-tier biological hierarchy and facts mesh tab."""
    resp = client.get("/taxonomy")
    assert resp.status_code == 200
    html = resp.text

    # Assert 7-tier biological view exists
    assert "Autonomous Knowledge Taxonomy & Living Facts" in html
    assert "7-Tier Biological Ontology & Living Facts" in html
    assert "Autonomous Category Clusters (Legacy)" in html
    assert "Sync Taxonomy from Library" in html
    assert "Biological Coordinates" in html
    assert "tree-7tier-container" in html
