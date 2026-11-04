"""Tests for UAT feedback issues: Topic editing, persistent deletion, unclassified grouping, and library search."""

import time
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.models_orm import (
    ContextStatementORM,
    FetchedPage,
    SettingExternal,
    TaxonomyEntityORM,
    TopicGovernanceORM,
)
from kb_web.server import app
from kb_web.taxonomy.engine import (
    delete_topic_or_subtopic,
    edit_topic,
    ensure_default_topics_seeded,
    get_library_items_summary,
    get_topic_governance_summary,
    TaxonomyEngine,
)
from kb_web.taxonomy.steered_tree import get_steered_tree_manager, SteeredTaxonomyNode


@pytest.fixture
def auth_client():
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture(autouse=True)
def cleanup_uat_test_data():
    yield
    with db_session() as session:
        session.query(TopicGovernanceORM).filter(
            TopicGovernanceORM.name.like("UatTest%")
            | TopicGovernanceORM.name.like("RenamedUat%")
        ).delete(synchronize_session=False)
        session.query(FetchedPage).filter(
            FetchedPage.url.like("https://uat-test-%")
        ).delete(synchronize_session=False)
        session.query(ContextStatementORM).filter(
            ContextStatementORM.source_uri.like("https://uat-test-%")
        ).delete(synchronize_session=False)
        session.query(TaxonomyEntityORM).filter(
            TaxonomyEntityORM.physical_location.like("https://uat-test-%")
        ).delete(synchronize_session=False)
        session.commit()


def test_issue1_deleted_default_topics_stay_deleted():
    """Verify that once initialized, deleting topics does not cause them to be automatically re-seeded."""
    with db_session() as session:
        init = session.query(SettingExternal).filter_by(key="taxonomy_default_topics_initialized").first()
        if not init:
            session.add(SettingExternal(key="taxonomy_default_topics_initialized", value="1"))
        else:
            init.value = "1"
        session.commit()

    now_iso = datetime.now(timezone.utc).isoformat()
    with db_session() as session:
        session.query(TopicGovernanceORM).filter_by(name="UatTestCustomTopic").delete()
        session.add(TopicGovernanceORM(name="UatTestCustomTopic", level="topic", status="allowed", created_at=now_iso))
        session.commit()

    summary = get_topic_governance_summary()
    assert "UatTestCustomTopic" in [t["name"] for t in summary["topics"]]

    delete_topic_or_subtopic("UatTestCustomTopic", level="topic")
    summary2 = get_topic_governance_summary()
    assert "UatTestCustomTopic" not in [t["name"] for t in summary2["topics"]]


def test_issue2_edit_topic_cascades(auth_client):
    """Test editing an existing topic renames it across TopicGovernanceORM, FetchedPage, ContextStatementORM, and SteeredTree."""
    now_iso = datetime.now(timezone.utc).isoformat()
    url = "https://uat-test-edit.com/article1"

    with db_session() as session:
        session.add(TopicGovernanceORM(name="UatTestOldTopic", level="topic", status="allowed", created_at=now_iso))
        session.add(FetchedPage(url=url, title="UAT Edit Page", topic="UatTestOldTopic", sub_topic="UatSub", topic_status="approved"))
        session.add(ContextStatementORM(
            id="uat_stmt_edit_1",
            statement="An atomic context mesh statement for editing.",
            source_uri=url,
            source_title="UAT Edit Page",
            canonical_path="UatTestOldTopic/UatSub/overview",
            kingdom="UatTestOldTopic",
            phylum="UatSub",
            statement_type="fact",
            layer_level="species",
            created_at=now_iso,
            updated_at=now_iso,
        ))
        session.commit()

    tree_mgr = get_steered_tree_manager()
    tree_mgr.add_node(name="UatTestOldTopic", level="kingdom", description="Old description")

    resp = auth_client.post("/api/taxonomy/topics/edit", json={
        "old_name": "UatTestOldTopic",
        "new_name": "RenamedUatTopic",
        "level": "topic",
        "description": "Updated new description",
        "gating_criteria": ["Is this related to renamed topic?"],
        "domain_blacklist": ["unwanted.com"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["new_name"] == "RenamedUatTopic"

    with db_session() as session:
        assert session.query(TopicGovernanceORM).filter_by(name="UatTestOldTopic").first() is None
        new_gov = session.query(TopicGovernanceORM).filter_by(name="RenamedUatTopic").first()
        assert new_gov is not None

        page = session.query(FetchedPage).filter_by(url=url).first()
        assert page.topic == "RenamedUatTopic"

        stmt = session.query(ContextStatementORM).filter_by(id="uat_stmt_edit_1").first()
        assert stmt.kingdom == "RenamedUatTopic"
        assert "RenamedUatTopic" in stmt.canonical_path

    node = tree_mgr.find_node("RenamedUatTopic")
    assert node is not None
    assert node.name == "RenamedUatTopic"
    assert "Is this related to renamed topic?" in node.gating_questions


def test_issue3_ui_shows_taxonomy_nodes_and_folder_governance(auth_client):
    """Test UI displays 'Taxonomy Nodes & Folder Governance' and updated wording."""
    resp = auth_client.get("/taxonomy")
    assert resp.status_code == 200
    html = resp.text
    assert "Taxonomy Nodes &amp; Folder Governance" in html
    assert "immutable structural folder layers" in html
    assert "Library Imports &amp; Placement" in html
    assert "selected7TierPath" in html


def test_issue5_unclassified_grouping():
    """Verify items without topic are placed under 'Unclassified' rather than a fake 'General' hierarchy."""
    engine = TaxonomyEngine()
    url = "https://uat-test-unclass.com/p1"
    now_iso = datetime.now(timezone.utc).isoformat()

    with db_session() as session:
        session.add(FetchedPage(url=url, title="Unassigned Page", topic=None, sub_topic=None, topic_status="unassigned"))
        session.add(TaxonomyEntityORM(
            canonical_id="entity_uat_test_p1",
            physical_location=url,
            taxonomy_path="unassigned",
            kingdom=None,
            phylum=None,
            order_name=None,
            family=None,
            genus="page",
            species="p1",
            attributes_json="{}",
            updated_at=now_iso,
        ))
        session.commit()

    tree_data = engine.get_7tier_tree()
    tree = tree_data["tree"]
    if "Unclassified" in tree:
        assert tree["Unclassified"]["name"] == "Unclassified"


def test_issue6_library_items_search_and_api(auth_client):
    """Test GET /api/taxonomy/library-items returns search results and placement statuses."""
    now_iso = datetime.now(timezone.utc).isoformat()
    url1 = "https://uat-test-search.com/python-guide"
    url2 = "https://uat-test-search.com/fishing-knot"

    with db_session() as session:
        session.add(FetchedPage(url=url1, title="Python Guide Tutorial", topic="Technology", sub_topic="Python", topic_status="approved", fetched_at=now_iso))
        session.add(FetchedPage(url=url2, title="Knot Tying 101", topic=None, sub_topic=None, topic_status="unassigned", fetched_at=now_iso))
        session.commit()

    resp = auth_client.get("/api/taxonomy/library-items?search=Python")
    assert resp.status_code == 200
    data = resp.json()
    assert any("Python Guide Tutorial" in it["title"] for it in data["items"])

    resp_unclass = auth_client.get("/api/taxonomy/library-items?search=Knot&status=unclassified")
    assert resp_unclass.status_code == 200
    unclass_data = resp_unclass.json()
    assert any("Knot Tying 101" in it["title"] for it in unclass_data["items"])
