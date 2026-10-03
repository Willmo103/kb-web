"""
Unit and integration tests for:
- Notes ingestion pipeline: valid URL extraction filtering, automatic titling, tagging, and wiki generation skipping
- Autonomous Category Taxonomy State Machine:
  - Cold start inaugural category creation
  - Tree hierarchy formatting
  - tev1 decision gating and LLM category synthesis
  - Living category wiki doc updating
  - 10-item partitioning inner loop into >=2 child sub-categories
- Agent Memory & Cross-Agent Message Board:
  - post_agent_memory, read_agent_memory, get_agent_board_summary
  - REST endpoints /api/agent-memory, /api/agent-memory/summary
  - UI page /agents/board
- Taxonomy REST endpoints (/api/taxonomy/tree, /categories/{id}, /crawl, /status) and UI /taxonomy
- CLI taxonomy and board commands
"""

import json
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kb_web.server import app
from kb_web.base import db_session, config, COOKIE_NAME, generate_session_token
from kb_web.models_orm import (
    Note,
    FetchedPage,
    TaxonomyCategory,
    TaxonomyItem,
    AgentMessage,
    Workspace,
    WorkspaceFile,
)
from kb_web.utils import extract_valid_urls, generate_note_title
from kb_web.agent_memory import (
    post_agent_memory,
    read_agent_memory,
    get_agent_board_summary,
)
from kb_web.taxonomy_state_machine import (
    format_category_tree_for_prompt,
    get_category_tree_data,
    classify_item,
    partition_category,
    crawl_and_classify_all,
    is_partitioning_paused,
)
from kb_web.cli import app as cli_app

runner = CliRunner()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_client():
    c = TestClient(app)
    token = generate_session_token(time.time() + 3600)
    c.cookies.set(COOKIE_NAME, token)
    return c


# ==============================================================================
# 1. URL EXTRACTION & NOTE PIPELINE TESTS
# ==============================================================================

def test_extract_valid_urls_filtering():
    """Validates that extract_valid_urls strictly keeps valid http(s) URLs and rejects garbage."""
    sample_text = """
    Check out the docs at https://fastapi.tiangolo.com/tutorial/ and also http://example.com/api?v=1.
    Do not include relative links like /local/path or fragments like #section-1.
    Skip invalid schemes: file:///C:/path/file.txt, mailto:test@example.com, javascript:alert(1).
    Trailing punctuation must be stripped: https://docs.python.org/3/library/re.html), and https://github.com/!
    Markdown links: [Search](https://duckduckgo.com/?q=test).
    Duplicate link: https://fastapi.tiangolo.com/tutorial/
    """
    urls = extract_valid_urls(sample_text)

    assert "https://fastapi.tiangolo.com/tutorial/" in urls
    assert "http://example.com/api?v=1" in urls
    assert "https://docs.python.org/3/library/re.html" in urls
    assert "https://github.com/" in urls
    assert "https://duckduckgo.com/?q=test" in urls

    # Rejection checks
    assert not any(u.startswith("/local") for u in urls)
    assert not any(u.startswith("file:") for u in urls)
    assert not any(u.startswith("mailto:") for u in urls)
    assert not any(u.startswith("javascript:") for u in urls)
    assert not any(u.endswith(")") for u in urls)
    assert not any(u.endswith("!") for u in urls)

    # Deduplication check
    assert urls.count("https://fastapi.tiangolo.com/tutorial/") == 1


def test_generate_note_title_from_heading_or_content():
    """Validates note titling from markdown heading or fallback content."""
    content_with_h1 = "# Microservices Architecture Design\n\nDiscussion on service mesh..."
    title = generate_note_title(content_with_h1)
    assert title == "Microservices Architecture Design"

    content_plain = "Distributed event queues using Kafka and RabbitMQ for decoupling."
    title_plain = generate_note_title(content_plain)
    assert len(title_plain) > 5


def test_note_ingestion_pipeline_skips_wiki_and_extracts_links():
    """Validates that background note processing extracts URLs and tags, but skips wiki summary."""
    test_note_url = f"note://Personal/test_pipeline_note_{int(time.time() * 1000)}"
    with db_session() as session:
        note = Note(
            url=test_note_url,
            title="Untitled Note",
            content="# Kubernetes Cluster Guide\n\nRefer to https://kubernetes.io/docs/home/ for setup.\nAlso see https://helm.sh/docs/.",
            syntax="markdown",
            vault_name="Personal",
            folder_path="",
            created_at="2026-10-01T00:00:00",
            updated_at="2026-10-01T00:00:00",
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

    from kb_web.routers.notes import _process_note_in_background

    # Mock Ollama tag extractor
    with patch("kb_web.routers.notes.extract_tags_content", return_value=["kubernetes", "devops", "cloud"]):
        _process_note_in_background(note_id)

    with db_session() as session:
        updated = session.query(Note).filter_by(id=note_id).first()
        assert updated is not None
        # Titling check: updated from "Untitled Note" to heading
        assert updated.title == "Kubernetes Cluster Guide"

        # Links check: valid URLs extracted
        assert updated.links is not None
        links = json.loads(updated.links)
        assert "https://kubernetes.io/docs/home/" in links
        assert "https://helm.sh/docs/" in links

        # Tags check:
        tags = json.loads(updated.tags or "[]")
        assert "kubernetes" in tags

        # Wiki generation MUST be skipped
        assert not updated.wiki_summary

        # Mirroring into FetchedPage check
        page = session.query(FetchedPage).filter_by(url=updated.url).first()
        assert page is not None
        assert "https://kubernetes.io/docs/home/" in page.links
        assert "kubernetes" in page.tags


# ==============================================================================
# 2. AGENT MEMORY & MESSAGE BOARD TESTS
# ==============================================================================

def test_agent_memory_crud_and_summary():
    """Validates posting, reading, filtering, and summary metrics on the Agent Message Board."""
    with db_session() as session:
        # Post test entries
        msg1 = post_agent_memory(
            session=session,
            agent_name="TaxonomyAgent",
            channel="taxonomy",
            topic="test_topic",
            content="Created cold start category",
            memory_type="lifecycle",
            metadata={"test_key": "val1"},
        )
        msg2 = post_agent_memory(
            session=session,
            agent_name="NotesIngestionAgent",
            channel="ingestion",
            topic="notes",
            content="Enriched note with 2 URLs",
            memory_type="observation",
        )

        assert msg1["id"] is not None
        assert msg2["id"] is not None

        # Filter by channel
        tax_msgs = read_agent_memory(session=session, channel="taxonomy")
        assert any(m["topic"] == "test_topic" for m in tax_msgs)
        assert not any(m["channel"] == "ingestion" for m in tax_msgs)

        # Filter by agent
        notes_msgs = read_agent_memory(session=session, agent_name="NotesIngestionAgent")
        assert len(notes_msgs) >= 1
        assert notes_msgs[0]["agent_name"] == "NotesIngestionAgent"

        # Summary
        summary = get_agent_board_summary(session=session)
        assert summary["total_messages"] >= 2
        assert "taxonomy" in summary["channels"]
        assert "ingestion" in summary["channels"]
        assert "TaxonomyAgent" in summary["agents"]


def test_agent_memory_api_and_ui(client, auth_client):
    """Tests /api/agent-memory REST endpoints and /agents/board UI."""
    # Unauthenticated request should be rejected with 401
    unauth_res = client.get("/api/agent-memory")
    assert unauth_res.status_code == 401

    # Test POST /api/agent-memory
    post_res = auth_client.post(
        "/api/agent-memory",
        json={
            "agent_name": "TestBot",
            "channel": "testing",
            "topic": "ping",
            "content": "Automated system test event",
            "memory_type": "observation",
            "metadata": {"test": True},
        },
    )
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["status"] == "created"

    # Test GET /api/agent-memory
    get_res = auth_client.get("/api/agent-memory?channel=testing")
    assert get_res.status_code == 200
    msgs = get_res.json()["messages"]
    assert any(m["content"] == "Automated system test event" for m in msgs)

    # Test GET /api/agent-memory/summary
    sum_res = auth_client.get("/api/agent-memory/summary")
    assert sum_res.status_code == 200
    assert "testing" in sum_res.json()["channels"]

    # Test UI /agents/board
    ui_res = auth_client.get("/agents/board")
    assert ui_res.status_code == 200
    assert "Agent Memory &amp; Message Board" in ui_res.text or "Agent Memory" in ui_res.text


# ==============================================================================
# 3. AUTONOMOUS TAXONOMY STATE MACHINE TESTS
# ==============================================================================

def test_format_category_tree_for_prompt():
    """Validates the tree formatting for LLMs and decision gates."""
    cat1 = TaxonomyCategory(id=1, name="Software Engineering", slug="software-eng", parent_id=None, doc="Dev docs", item_count=0, depth=0, is_container=1)
    cat2 = TaxonomyCategory(id=2, name="Backend APIs", slug="backend-apis", parent_id=1, doc="FastAPI REST", item_count=4, depth=1, is_container=0)
    cat3 = TaxonomyCategory(id=3, name="Data Science", slug="data-science", parent_id=None, doc="ML and statistics", item_count=2, depth=0, is_container=0)

    tree_str = format_category_tree_for_prompt([cat1, cat2, cat3])
    assert "- [cat_1] Software Engineering [Container Branch]" in tree_str
    assert "  - [cat_2] Backend APIs (4 items)" in tree_str
    assert "- [cat_3] Data Science (2 items)" in tree_str


def test_taxonomy_cold_start_and_subsequent_classification():
    """Tests the state machine from 0 categories (cold start) to assignment and new category synthesis."""
    with db_session() as session:
        # Clean taxonomy tables for isolated state machine test
        session.query(TaxonomyItem).delete()
        session.query(TaxonomyCategory).delete()
        session.commit()

        # Mock LLM and Client
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {
                "content": json.dumps({
                    "category_name": "Artificial Intelligence",
                    "category_doc": "# Artificial Intelligence\n\nCovers machine learning, neural networks, and agents.",
                })
            }
        }

        # Step 1: Cold start first item
        res1 = classify_item(
            session=session,
            item_type="article",
            item_id="https://ai.example.com/transformers",
            item_title="Attention Is All You Need",
            item_content="The Transformer model architecture relying entirely on attention mechanisms.",
            item_tags=["transformers", "attention", "nlp"],
            client=mock_client,
        )
        assert res1["status"] == "cold_start_created"
        cat1_id = res1["category_id"]

        cat1 = session.query(TaxonomyCategory).filter_by(id=cat1_id).first()
        assert cat1 is not None
        assert cat1.name == "Artificial Intelligence"
        assert cat1.item_count == 1

        # Step 2: Second item that fits via tev1 decision gate
        mock_tev1_resp = MagicMock()
        mock_tev1_resp.answers = {
            "category_choice": MagicMock(choice=f"cat_{cat1_id}"),
            "fit_confidence": MagicMock(noul=True),
        }
        mock_client.systemone.return_value = mock_tev1_resp
        mock_client.chat.return_value = {
            "message": {"content": "# Artificial Intelligence\n\nUpdated wiki doc incorporating LLM reasoning."}
        }

        res2 = classify_item(
            session=session,
            item_type="article",
            item_id="https://ai.example.com/gpt4",
            item_title="GPT-4 Technical Report",
            item_content="Large multimodal model capable of processing image and text inputs.",
            item_tags=["llm", "multimodal"],
            client=mock_client,
        )
        assert res2["status"] == "assigned"
        assert res2["category_id"] == cat1_id

        session.refresh(cat1)
        assert cat1.item_count == 2
        assert "incorporating LLM reasoning" in cat1.doc

        # Step 3: Third item that DOES NOT fit -> Triggers new category synthesis
        mock_tev1_resp_new = MagicMock()
        mock_tev1_resp_new.answers = {
            "category_choice": MagicMock(choice="new_category"),
            "fit_confidence": MagicMock(noul=False),
        }
        mock_client.systemone.return_value = mock_tev1_resp_new
        mock_client.chat.return_value = {
            "message": {
                "content": json.dumps({
                    "category_name": "Culinary Arts",
                    "category_doc": "# Culinary Arts\n\nRecipes, gastronomy, and kitchen techniques.",
                })
            }
        }

        res3 = classify_item(
            session=session,
            item_type="article",
            item_id="https://cooking.example.com/sourdough",
            item_title="Artisan Sourdough Bread Mastery",
            item_content="Step by step wild fermentation baking guide.",
            item_tags=["baking", "sourdough"],
            client=mock_client,
        )
        assert res3["status"] == "new_category_created"
        cat2 = session.query(TaxonomyCategory).filter_by(id=res3["category_id"]).first()
        assert cat2.name == "Culinary Arts"
        assert cat2.item_count == 1


def test_10_item_threshold_partitioning_loop():
    """Validates the 10-item limit: when 10th item is reached, global additions pause,

    items are partitioned into >=2 child sub-categories, and parent becomes a group container.
    """
    with db_session() as session:
        session.query(TaxonomyItem).delete()
        session.query(TaxonomyCategory).delete()
        session.commit()

        # Create parent category with 10 items
        parent = TaxonomyCategory(
            name="Cloud Infrastructure",
            slug="cloud-infra",
            parent_id=None,
            doc="# Cloud Infrastructure\n\nGeneral cloud topics.",
            item_count=10,
            depth=0,
            is_container=0,
            created_at="2026-10-01T00:00:00",
            updated_at="2026-10-01T00:00:00",
        )
        session.add(parent)
        session.commit()
        session.refresh(parent)

        # Add 10 items
        for i in range(10):
            item = TaxonomyItem(
                category_id=parent.id,
                item_type="article",
                item_id=f"https://cloud.com/item_{i}",
                item_title=f"Cloud Resource {i}",
                fit_score=1.0,
                assigned_at="2026-10-01T00:00:00",
            )
            session.add(item)
        session.commit()

        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "message": {
                "content": json.dumps({
                    "sub_categories": [
                        {
                            "name": "Cloud Storage & Databases",
                            "doc": "# Cloud Storage & Databases\n\nS3, RDS, and storage primitives.",
                            "item_indices": [0, 1, 2, 3, 4],
                        },
                        {
                            "name": "Serverless & Compute",
                            "doc": "# Serverless & Compute\n\nLambda, containers, and VMs.",
                            "item_indices": [5, 6, 7, 8, 9],
                        },
                    ]
                })
            }
        }

        # Run partitioning
        partition_category(session=session, category_id=parent.id, client=mock_client, config=config)

        # Verify state after partitioning:
        session.refresh(parent)
        assert parent.is_container == 1
        assert parent.item_count == 0  # direct items now 0; parent is container
        assert "(Container)" in parent.doc

        # Verify child sub-categories created
        children = session.query(TaxonomyCategory).filter_by(parent_id=parent.id).all()
        assert len(children) == 2
        child_names = {c.name for c in children}
        assert "Cloud Storage & Databases" in child_names
        assert "Serverless & Compute" in child_names

        for c in children:
            assert c.depth == 1
            assert c.item_count == 5
            assert c.is_container == 0

        # Verify items were reassigned to child categories
        child_ids = {c.id for c in children}
        reassigned_items = session.query(TaxonomyItem).filter(TaxonomyItem.category_id.in_(child_ids)).all()
        assert len(reassigned_items) == 10

        # Verify global pause was released
        assert not is_partitioning_paused()


def test_taxonomy_api_and_ui(client, auth_client):
    """Tests taxonomy API endpoints and UI view."""
    # Unauthenticated request returns 401
    unauth_tree = client.get("/api/taxonomy/tree")
    assert unauth_tree.status_code == 401

    # GET /api/taxonomy/tree with auth
    res_tree = auth_client.get("/api/taxonomy/tree")
    assert res_tree.status_code == 200
    assert "tree" in res_tree.json()

    # GET /api/taxonomy/status with auth
    res_status = auth_client.get("/api/taxonomy/status")
    assert res_status.status_code == 200
    assert "is_partitioning_paused" in res_status.json()

    # GET /taxonomy UI
    res_ui = auth_client.get("/taxonomy")
    assert res_ui.status_code == 200
    assert "Autonomous Knowledge Taxonomy" in res_ui.text


# ==============================================================================
# 4. CLI COMMANDS TEST
# ==============================================================================

def test_cli_taxonomy_and_board_commands():
    """Tests kb-web-cli taxonomy tree and board list commands."""
    res_tree = runner.invoke(cli_app, ["taxonomy", "tree"])
    assert res_tree.exit_code == 0

    res_board = runner.invoke(cli_app, ["board", "list", "--limit", "5"])
    assert res_board.exit_code == 0
