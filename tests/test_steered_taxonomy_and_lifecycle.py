"""Unit and integration tests for steered taxonomy tree, gating questions,
lifecycle automation, taxonomy reset/nuke, worker pause controls, and personal VK layer.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_

from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.context_mesh.injector import SubconsciousContextInjector, get_subconscious_injector
from kb_web.context_mesh.personal_vk import (
    PersonalVKManager,
    get_default_personal_vk,
    get_personal_vk_manager,
)
from kb_web.models_orm import FetchedPage, TaxonomyEntityORM, TaxonomyItem, TopicGovernanceORM
from kb_web.server import app
from kb_web.taxonomy.engine import (
    assign_topic_and_subtopic,
    classify_steered_hierarchical,
    nuke_all_taxonomy,
)
from kb_web.taxonomy.steered_tree import (
    SteeredTaxonomyNode,
    SteeredTaxonomyTreeManager,
    get_default_steered_tree,
    get_steered_tree_manager,
)
from kb_web.worker import AutonomousWorker, ServerJob, autonomous_worker


@pytest.fixture(autouse=True)
def clean_db_state():
    """Wipes test state before and after each test."""
    def _do_clean():
        with db_session() as session:
            session.query(TaxonomyEntityORM).filter(
                TaxonomyEntityORM.physical_location.like("https://test-steered-%")
            ).delete(synchronize_session=False)

            session.query(FetchedPage).filter(
                FetchedPage.url.like("https://test-steered-%")
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
# 1. Steered Taxonomy Tree & Governance Tests
# =============================================================================

def test_steered_tree_defaults_and_validation():
    """Verify default steered taxonomy tree nodes and fields."""
    tree = get_default_steered_tree()
    assert len(tree) >= 5

    kingdom_names = [n.name for n in tree]
    assert "Software Documentation" in kingdom_names
    assert "Hobby/Leisure" in kingdom_names
    assert "News" in kingdom_names

    # Check node fields
    sw_node = next(n for n in tree if n.name == "Software Documentation")
    assert sw_node.is_frozen is True
    assert len(sw_node.gating_questions) > 0
    assert "tiktok.com" in sw_node.blacklisted_domains
    assert sw_node.is_domain_blacklisted("https://www.tiktok.com/@coder") is True
    assert sw_node.is_domain_blacklisted("https://docs.python.org/3/") is False


def test_tree_manager_persistence_and_lookup(tmp_path):
    """Test saving, loading, and searching steered tree nodes."""
    mgr = SteeredTaxonomyTreeManager()
    tree = mgr.get_tree()
    assert len(tree) > 0

    found = mgr.find_node("Software Documentation")
    assert found is not None
    assert found.name == "Software Documentation"

    # Child lookup
    valid_children = mgr.get_valid_children(found, "https://docs.python.org")
    assert len(valid_children) > 0


def test_domain_blacklist_filtering():
    """Verify blacklisted domains are rejected or filtered out."""
    node = SteeredTaxonomyNode(
        id="test_node",
        name="Test Node",
        blacklisted_domains=["youtube.com", "reddit.com"],
    )
    assert node.is_domain_blacklisted("https://youtube.com/watch?v=123") is True
    assert node.is_domain_blacklisted("https://m.reddit.com/r/python") is True
    assert node.is_domain_blacklisted("https://github.com/fastapi/fastapi") is False


# =============================================================================
# 2. Hierarchical Guided Decision Classification & Gating
# =============================================================================

def test_classify_steered_hierarchical_python_docs():
    """Verify layer-by-layer classification for python documentation."""
    url = "https://test-steered-docs.python.org/3/library/asyncio.html"
    title = "asyncio — Asynchronous I/O"
    md_content = "This library provides infrastructure for writing single-threaded concurrent code using coroutines."
    tags = ["python", "asyncio", "documentation"]

    with db_session() as session:
        fp = FetchedPage(
            url=url,
            title=title,
            md_content=md_content,
            tags=json.dumps(tags),
            topic_status="unassigned",
        )
        session.add(fp)
        session.commit()

    # Run steered classification with mocked Ollama client selecting python ecosystem
    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": '{"selected_id": "kingdom_software_docs", "rationale": "Matches tech docs"}'}
    }

    result = classify_steered_hierarchical(
        url=url,
        title=title,
        md_content=md_content,
        tags=tags,
        client=mock_client,
    )

    assert result["status"] == "success"
    assert result["topic"] == "Software Documentation"
    assert "taxonomy_path" in result
    assert result["lifecycle_action"] in ("none", "refetch", "freeze")

    # Verify FetchedPage was updated
    with db_session() as session:
        fp = session.query(FetchedPage).filter_by(url=url).first()
        assert fp.topic == "Software Documentation"
        assert fp.topic_status == "approved"


def test_classify_steered_lifecycle_freeze():
    """Verify nodes with lifecycle_action 'freeze' set is_frozen=1 on FetchedPage."""
    url = "https://test-steered-example.org/dam-removal-activism"
    title = "Dam Removal and Ecological Restoration"
    md_content = "Community activism and removal efforts restoring salmon passages."
    tags = ["activism", "restoration"]

    with db_session() as session:
        fp = FetchedPage(
            url=url,
            title=title,
            md_content=md_content,
            tags=json.dumps(tags),
            is_frozen=0,
        )
        session.add(fp)
        session.commit()

    mock_client = MagicMock()
    mock_client.chat.side_effect = [
        {"message": {"content": '{"selected_id": "kingdom_news"}'}},
        {"message": {"content": '{"selected_id": "phylum_activism"}'}},
        {"message": {"content": '{"selected_id": "class_removal_efforts"}'}},
    ]

    result = classify_steered_hierarchical(
        url=url,
        title=title,
        md_content=md_content,
        tags=tags,
        client=mock_client,
    )

    assert result["status"] == "success"
    assert result["lifecycle_action"] == "freeze"

    with db_session() as session:
        fp = session.query(FetchedPage).filter_by(url=url).first()
        assert fp.is_frozen == 1


# =============================================================================
# 3. Taxonomy Nuke / Reset Operations
# =============================================================================

def test_nuke_all_taxonomy_requires_confirm():
    """Nuke fails without explicit confirm=True."""
    res = nuke_all_taxonomy(confirm=False)
    assert res["status"] == "error"
    assert "confirm=True" in res["message"]


def test_nuke_all_taxonomy_execution():
    """Verify nuke removes all taxonomy records and resets FetchedPage topics."""
    with db_session() as session:
        p1 = FetchedPage(
            url="https://test-steered-site1.com",
            title="Site 1",
            topic="Software Documentation",
            sub_topic="Official-Documentation/Python",
            topic_status="approved",
        )
        p2 = FetchedPage(
            url="https://test-steered-site2.com",
            title="Site 2",
            topic="Hobby/Leisure",
            sub_topic="Fishing/Ultralight",
            topic_status="approved",
        )
        ent1 = TaxonomyEntityORM(
            canonical_id="tax_test_steered_1",
            taxonomy_path="Software Documentation/Official-Documentation/Python/site1/general/art1/sp1",
            physical_location="https://test-steered-site1.com",
            updated_at="2026-11-02T00:00:00Z",
        )
        session.add_all([p1, p2, ent1])
        session.commit()

    nuke_res = nuke_all_taxonomy(confirm=True)
    assert nuke_res["status"] == "success"
    assert nuke_res["deleted_entities_count"] >= 1
    assert nuke_res["reset_pages_count"] >= 2

    with db_session() as session:
        pages = session.query(FetchedPage).filter(FetchedPage.url.like("https://test-steered-%")).all()
        for p in pages:
            assert p.topic is None
            assert p.sub_topic is None
            assert p.topic_status == "unassigned"


def test_api_nuke_taxonomy_endpoint(auth_client: TestClient):
    """Test POST /api/taxonomy/nuke."""
    # Without confirm
    res_bad = auth_client.post("/api/taxonomy/nuke", json={"confirm": False})
    assert res_bad.status_code == 400

    # With confirm
    res_ok = auth_client.post("/api/taxonomy/nuke", json={"confirm": True})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["status"] == "success"
    assert data["action"] == "taxonomy_nuked"


# =============================================================================
# 4. Worker Pausing Controls ("Core Only" Mode)
# =============================================================================

def test_worker_pause_non_core_and_resume():
    """Verify pausing non-core jobs preserves wiki_curation and tag_curation."""
    worker = AutonomousWorker()

    for job in worker.jobs.values():
        job.enabled = True

    pause_res = worker.pause_non_core_jobs()
    assert pause_res["status"] == "success"
    assert pause_res["mode"] == "core_only"

    # Core jobs MUST remain enabled
    assert worker.jobs["wiki_curation"].enabled is True
    assert worker.jobs["tag_curation"].enabled is True

    # Secondary jobs MUST be disabled
    assert worker.jobs["topic_assignment"].enabled is False
    assert worker.jobs["embedding_refresh"].enabled is False
    assert worker.jobs["synthetic_qa"].enabled is False
    assert worker.jobs["fact_extraction"].enabled is False
    assert worker.is_core_only_mode() is True

    # Resume all
    resume_res = worker.resume_all_jobs()
    assert resume_res["status"] == "success"
    assert worker.jobs["topic_assignment"].enabled is True
    assert worker.jobs["synthetic_qa"].enabled is True
    assert worker.is_core_only_mode() is False


def test_api_worker_pause_and_resume_endpoints(auth_client: TestClient):
    """Test REST endpoints for pausing and resuming jobs."""
    p_res = auth_client.post("/api/jobs/pause-non-core")
    assert p_res.status_code == 200
    assert p_res.json()["mode"] == "core_only"

    m_res = auth_client.get("/api/jobs/mode")
    assert m_res.status_code == 200
    assert m_res.json()["core_only_mode"] is True

    r_res = auth_client.post("/api/jobs/resume-all")
    assert r_res.status_code == 200
    assert r_res.json()["mode"] == "all_active"


# =============================================================================
# 5. Personal VK (Value-Knowledge) Context Layer Tests
# =============================================================================

def test_personal_vk_manager_get_and_save():
    """Test personal VK context loading, modifying, and saving."""
    vk_mgr = get_personal_vk_manager()
    ctx = vk_mgr.get_context()
    assert "interests" in ctx
    assert "values" in ctx

    # Test update
    ctx["interests"]["custom_interest"] = ["Test Item 1", "Test Item 2"]
    saved = vk_mgr.save_context(ctx)
    assert "custom_interest" in saved["interests"]

    prompt_xml = vk_mgr.format_for_prompt()
    assert "<personal_values_context>" in prompt_xml
    assert "custom_interest" in prompt_xml


def test_subconscious_context_injector_with_personal_vk():
    """Verify SubconsciousContextInjector includes <personal_values_context>."""
    injector = SubconsciousContextInjector()
    base_prompt = "You are a helpful coding assistant."
    injected, _ = injector.inject_subconscious_context(
        prompt=base_prompt,
        user_query="How do I configure FastAPI?",
        include_personal_vk=True,
    )
    assert "<personal_values_context>" in injected
    assert "You are a helpful coding assistant." in injected


def test_api_personal_vk_endpoints(auth_client: TestClient):
    """Test GET and PUT /api/context-mesh/personal-vk."""
    get_res = auth_client.get("/api/context-mesh/personal-vk")
    assert get_res.status_code == 200
    data = get_res.json()
    assert "interests" in data

    # Update
    data["values"]["operational"].append("Strict deterministic test verification")
    put_res = auth_client.put("/api/context-mesh/personal-vk", json=data)
    assert put_res.status_code == 200
    assert put_res.json()["status"] == "success"
    assert "Strict deterministic test verification" in put_res.json()["personal_vk"]["values"]["operational"]
