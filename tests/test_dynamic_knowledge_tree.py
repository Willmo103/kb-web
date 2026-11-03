"""Unit and integration tests for dynamic knowledge tree, direct topic/sub-topic deletion,
arbitrary folder creation, and bulk relocation for items and context facts.
"""

import json
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_

from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.context_mesh.models import ContextStatement, EvalStatus, StatementType, TaxonomicLayer
from kb_web.models_orm import ContextStatementORM, FetchedPage, TaxonomyEntityORM, TopicGovernanceORM
from kb_web.server import app
from kb_web.taxonomy.engine import (
    bulk_move_facts,
    bulk_move_items,
    delete_topic_or_subtopic,
)
from kb_web.taxonomy.steered_tree import (
    SteeredTaxonomyNode,
    SteeredTaxonomyTreeManager,
    get_steered_tree_manager,
)


@pytest.fixture(autouse=True)
def clean_db_state():
    """Cleans up dynamic tree test artifacts before and after runs."""
    def _do_clean():
        with db_session() as session:
            session.query(TaxonomyEntityORM).filter(
                TaxonomyEntityORM.physical_location.like("https://test-dyn-%")
            ).delete(synchronize_session=False)

            session.query(FetchedPage).filter(
                FetchedPage.url.like("https://test-dyn-%")
            ).delete(synchronize_session=False)

            session.query(TopicGovernanceORM).filter(
                TopicGovernanceORM.name.like("DynTestTopic%")
                | TopicGovernanceORM.name.like("DynChild%")
                | TopicGovernanceORM.name.like("TargetFolder%")
            ).delete(synchronize_session=False)

            session.query(ContextStatementORM).filter(
                ContextStatementORM.id.like("stmt_test_dyn_%")
            ).delete(synchronize_session=False)

            session.commit()

    _do_clean()
    yield
    _do_clean()


@pytest.fixture
def auth_client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


# =============================================================================
# 1. Direct Topic & Sub-Topic Deletion Tests
# =============================================================================

def test_delete_topic_and_cascade():
    """Verify delete_topic_or_subtopic permanently deletes topic and cascades to children and pages."""
    now_iso = "2026-11-02T00:00:00Z"
    with db_session() as session:
        t1 = TopicGovernanceORM(name="DynTestTopic", level="topic", status="allowed", created_at=now_iso)
        st1 = TopicGovernanceORM(name="DynChildSub", level="sub_topic", parent_topic="DynTestTopic", status="allowed", created_at=now_iso)
        p1 = FetchedPage(url="https://test-dyn-page1.com", title="Page 1", topic="DynTestTopic", sub_topic="DynChildSub", topic_status="approved")
        session.add_all([t1, st1, p1])
        session.commit()

    # Add to steered tree
    tree_mgr = get_steered_tree_manager()
    tree_mgr.add_node(name="DynTestTopic", parent_id=None, level="kingdom")

    # Delete topic
    res = delete_topic_or_subtopic(name="DynTestTopic", level="topic")
    assert res["status"] == "success"
    assert res["action"] == "deleted"
    assert res["deleted_count"] >= 1

    # Verify database state
    with db_session() as session:
        assert session.query(TopicGovernanceORM).filter_by(name="DynTestTopic").first() is None
        assert session.query(TopicGovernanceORM).filter_by(name="DynChildSub").first() is None
        p = session.query(FetchedPage).filter_by(url="https://test-dyn-page1.com").first()
        assert p.topic is None
        assert p.sub_topic is None
        assert p.topic_status == "unassigned"


def test_delete_topic_with_reassign():
    """Verify delete_topic_or_subtopic reassigns affected pages when reassign_to is provided."""
    now_iso = "2026-11-02T00:00:00Z"
    with db_session() as session:
        t1 = TopicGovernanceORM(name="DynTestTopicOld", level="topic", status="allowed", created_at=now_iso)
        p1 = FetchedPage(url="https://test-dyn-page2.com", title="Page 2", topic="DynTestTopicOld", topic_status="approved")
        session.add_all([t1, p1])
        session.commit()

    res = delete_topic_or_subtopic(name="DynTestTopicOld", level="topic", reassign_to="TargetFolder")
    assert res["status"] == "success"
    assert res["reassigned_to"] == "TargetFolder"

    with db_session() as session:
        p = session.query(FetchedPage).filter_by(url="https://test-dyn-page2.com").first()
        assert p.topic == "TargetFolder"
        assert p.topic_status == "approved"


# =============================================================================
# 2. Bulk Relocation Engine Tests
# =============================================================================

def test_bulk_move_items():
    """Verify bulk_move_items updates FetchedPage, TaxonomyEntityORM, and ContextStatements."""
    now_iso = "2026-11-02T00:00:00Z"
    u1 = "https://test-dyn-move1.com"
    u2 = "https://test-dyn-move2.com"

    with db_session() as session:
        p1 = FetchedPage(url=u1, title="Move 1", topic="OldFolder", sub_topic="OldSub", topic_status="approved")
        p2 = FetchedPage(url=u2, title="Move 2", topic="OldFolder", sub_topic="OldSub", topic_status="approved")
        ent1 = TaxonomyEntityORM(
            canonical_id="tax_dyn_1",
            taxonomy_path="OldFolder/OldSub/Overview/site/gen/art1/sp1",
            physical_location=u1,
            updated_at=now_iso,
        )
        stmt1 = ContextStatementORM(
            id="stmt_test_dyn_1",
            statement="Test statement from dyn move",
            statement_type="fact",
            canonical_path="OldFolder/OldSub/site/gen",
            layer_level="species",
            source_uri=u1,
            source_title="Move 1",
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add_all([p1, p2, ent1, stmt1])
        session.commit()

    # Execute bulk move to TargetFolder / NewSubFolder
    res = bulk_move_items(
        urls=[u1, u2],
        target_topic="TargetFolder",
        target_sub_topic="NewSubFolder",
    )
    assert res["status"] == "success"
    assert res["moved_count"] == 2
    assert res["target_topic"] == "TargetFolder"
    assert res["target_sub_topic"] == "NewSubFolder"

    with db_session() as session:
        pages = session.query(FetchedPage).filter(FetchedPage.url.in_([u1, u2])).all()
        for p in pages:
            assert p.topic == "TargetFolder"
            assert p.sub_topic == "NewSubFolder"
            assert p.topic_status == "approved"

        # Check entity
        e = session.query(TaxonomyEntityORM).filter_by(physical_location=u1).first()
        assert e.kingdom == "TargetFolder"
        assert e.phylum == "NewSubFolder"
        assert e.taxonomy_path.startswith("TargetFolder/NewSubFolder")

        # Check statement
        s = session.query(ContextStatementORM).filter_by(id="stmt_test_dyn_1").first()
        assert s.kingdom == "TargetFolder"
        assert s.phylum == "NewSubFolder"
        assert s.canonical_path.startswith("TargetFolder/NewSubFolder")


def test_bulk_move_facts():
    """Verify bulk_move_facts updates context statements in batch."""
    now_iso = "2026-11-02T00:00:00Z"
    with db_session() as session:
        s1 = ContextStatementORM(
            id="stmt_test_dyn_f1",
            statement="Fact 1",
            statement_type="fact",
            canonical_path="OldTopic/OldSub/test",
            layer_level="species",
            source_uri="https://test-dyn-f1.com",
            source_title="F1",
            created_at=now_iso,
            updated_at=now_iso,
        )
        s2 = ContextStatementORM(
            id="stmt_test_dyn_f2",
            statement="Fact 2",
            statement_type="fact",
            canonical_path="OldTopic/OldSub/test",
            layer_level="species",
            source_uri="https://test-dyn-f2.com",
            source_title="F2",
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add_all([s1, s2])
        session.commit()

    res = bulk_move_facts(
        statement_ids=["stmt_test_dyn_f1", "stmt_test_dyn_f2"],
        target_canonical_path="NewTopic/NewSub/NewClass",
        target_kingdom="NewTopic",
        target_phylum="NewSub",
        target_class="NewClass",
    )
    assert res["status"] == "success"
    assert res["moved_count"] == 2

    with db_session() as session:
        stmts = session.query(ContextStatementORM).filter(ContextStatementORM.id.in_(["stmt_test_dyn_f1", "stmt_test_dyn_f2"])).all()
        for s in stmts:
            assert s.canonical_path == "NewTopic/NewSub/NewClass"
            assert s.kingdom == "NewTopic"
            assert s.phylum == "NewSub"


# =============================================================================
# 3. Dynamic Folder Tree Management Tests
# =============================================================================

def test_dynamic_tree_add_and_delete_node():
    """Verify adding and removing folders in the knowledge tree."""
    mgr = SteeredTaxonomyTreeManager()

    # Add top-level folder
    root_node = mgr.add_node(name="DevOps Architecture", parent_id=None, level="kingdom")
    assert root_node is not None
    assert root_node.name == "DevOps Architecture"
    assert root_node.level == "kingdom"

    # Add nested child folder
    child_node = mgr.add_node(name="Kubernetes Clusters", parent_id=root_node.id, level="phylum")
    assert child_node is not None
    assert child_node.name == "Kubernetes Clusters"

    # Verify lookup
    found_root = mgr.find_node(root_node.id)
    assert found_root is not None
    assert any(c.id == child_node.id for c in found_root.children)

    # Delete child
    assert mgr.delete_node(child_node.id) is True
    assert mgr.find_node(child_node.id) is None

    # Delete root
    assert mgr.delete_node(root_node.id) is True
    assert mgr.find_node(root_node.id) is None


# =============================================================================
# 4. REST Endpoints Verification
# =============================================================================

def test_api_delete_topic_endpoint(auth_client: TestClient):
    """Test POST /api/taxonomy/topics/delete."""
    with db_session() as session:
        t = TopicGovernanceORM(name="DynTestTopicApi", level="topic", status="allowed")
        session.add(t)
        session.commit()

    res = auth_client.post(
        "/api/taxonomy/topics/delete",
        json={"name": "DynTestTopicApi", "level": "topic"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["action"] == "deleted"


def test_api_bulk_move_items_endpoint(auth_client: TestClient):
    """Test POST /api/taxonomy/items/bulk-move."""
    u = "https://test-dyn-api-move.com"
    with db_session() as session:
        p = FetchedPage(url=u, title="API Move Page", topic="OldFolder", topic_status="approved")
        session.add(p)
        session.commit()

    res = auth_client.post(
        "/api/taxonomy/items/bulk-move",
        json={"urls": [u], "target_topic": "TargetFolder", "target_sub_topic": "SubCategory"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["moved_count"] == 1


def test_api_tree_add_and_delete_node(auth_client: TestClient):
    """Test POST /api/taxonomy/tree/add-node and /api/taxonomy/tree/delete-node."""
    add_res = auth_client.post(
        "/api/taxonomy/tree/add-node",
        json={"name": "API Created Folder", "description": "Test folder"},
    )
    assert add_res.status_code == 200
    node = add_res.json()["node"]
    node_id = node["id"]
    assert node["name"] == "API Created Folder"

    del_res = auth_client.post(
        "/api/taxonomy/tree/delete-node",
        json={"node_id": node_id},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"
    assert del_res.json()["deleted_id"] == node_id

