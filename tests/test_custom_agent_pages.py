"""
Unit and integration tests for Custom Autonomous Topic Agents:
- TopicWikiPage (/wiki/{agent_id}/{path})
- AgentPage raw vs themed modes (/pages/agent/{hash_id})
- HITL Python code approval and execution flow
- Topic grounding and autonomous deliberation engine
"""

from datetime import datetime, timezone
import json
import time
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from kb_web.server import app
from kb_web.base import COOKIE_NAME, db_session, generate_session_token
from kb_web.models_orm import (
    AgentObservation,
    AgentPage,
    AgentPythonApproval,
    AgentSelfTask,
    CustomAgent,
    FetchedPage,
    TopicWikiPage,
)
from kb_web.python_kernel import (
    execute_approved_code,
    propose_python_execution,
    reject_code_execution,
)
from kb_web.custom_agent_engine import (
    deliberate_agent,
    steer_topic_grounding,
)


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def sample_agent():
    agent_id = f"test_agent_{int(time.time()*1000)}"
    now_iso = datetime.now(timezone.utc).isoformat()
    with db_session() as session:
        agent = CustomAgent(
            id=agent_id,
            name=f"Agent-{agent_id}",
            topic_domain="Distributed Databases Raft Consensus",
            system_prompt="You are an autonomous topic specialist.",
            status="idle",
            created_at=now_iso,
            updated_at=now_iso,
        )
        session.add(agent)
        session.commit()
    return agent_id


def test_topic_wiki_page_rendering(client: TestClient, sample_agent: str):
    """Test /wiki/{agent_id}/{path} rendering with navigation tree, citations, and markdown."""
    test_url = f"https://raft.github.io/raft_{time.time_ns()}.pdf"
    with db_session() as session:
        # Create a sample fetched page for reference
        fetched = FetchedPage(
            url=test_url,
            title="In Search of an Understandable Consensus Algorithm",
            md_content="# Raft Paper\nDetails of Raft...",
        )
        session.add(fetched)
        session.commit()
        ref_url = fetched.url

        # Create topic wiki pages
        p1 = TopicWikiPage(
            agent_id=sample_agent,
            logical_path="index",
            title="Overview of Raft",
            body_markdown="## Introduction\nRaft is a consensus algorithm.\n\nSee [Leader Election](/wiki/" + sample_agent + "/leader-election).",
            references_json=json.dumps([{"url": ref_url, "title": "Raft Paper"}]),
            links_json=json.dumps([{"title": "Leader Election", "path": "leader-election"}]),
        )
        p2 = TopicWikiPage(
            agent_id=sample_agent,
            logical_path="leader-election",
            title="Leader Election Mechanism",
            body_markdown="## Election Safety\nHeartbeats and election timeouts prevent split votes.",
        )
        session.add_all([p1, p2])
        session.commit()

    # Request index page
    resp = client.get(f"/wiki/{sample_agent}")
    assert resp.status_code == 200
    assert "Overview of Raft" in resp.text
    assert "Raft is a consensus algorithm" in resp.text
    assert "Raft Paper" in resp.text
    assert "Leader Election Mechanism" in resp.text  # Tree navigation sidebar

    # Request subpage
    resp_sub = client.get(f"/wiki/{sample_agent}/leader-election")
    assert resp_sub.status_code == 200
    assert "Leader Election Mechanism" in resp_sub.text
    assert "Heartbeats and election timeouts" in resp_sub.text


def test_agent_page_raw_mode(client: TestClient, sample_agent: str):
    """Test AgentPage with render_mode='raw' returns pure unstyled HTML without base chrome."""
    raw_html = "<!DOCTYPE html><html><head><title>Raw Canvas</title></head><body><h1>Unadorned Dashboard</h1></body></html>"
    hash_id = f"raw_{int(time.time()*1000)}"

    with db_session() as session:
        page = AgentPage(
            agent_id=sample_agent,
            hash_id=hash_id,
            title="Raw Canvas Test",
            render_mode="raw",
            body_content=raw_html,
        )
        session.add(page)
        session.commit()

    resp = client.get(f"/pages/agent/{hash_id}")
    assert resp.status_code == 200
    assert resp.text == raw_html
    assert "<nav" not in resp.text
    assert "Unadorned Dashboard" in resp.text


def test_agent_page_themed_mode_and_interactive_form(client: TestClient, sample_agent: str):
    """Test AgentPage with render_mode='themed' renders with base template and supports form submission."""
    hash_id = f"themed_{int(time.time()*1000)}"
    form_schema = {
        "title": "Feedback on Raft Research",
        "description": "Please provide guidance on which consensus edge cases to prioritize.",
        "fields": [
            {"name": "priority", "label": "Target Priority", "type": "select", "options": ["Log Compaction", "Membership Changes"]},
            {"name": "comments", "label": "Additional Directives", "type": "textarea"},
        ],
    }

    with db_session() as session:
        page = AgentPage(
            agent_id=sample_agent,
            hash_id=hash_id,
            title="Topic Directives Request",
            render_mode="themed",
            body_content="### Needs Direction\nI have completed the core election analysis. Where should I focus next?",
            form_schema_json=json.dumps(form_schema),
        )
        session.add(page)
        session.commit()

    # View page
    resp = client.get(f"/pages/agent/{hash_id}")
    assert resp.status_code == 200
    assert "Topic Directives Request" in resp.text
    assert "Feedback on Raft Research" in resp.text
    assert "Log Compaction" in resp.text

    # Submit interactive form JSON
    submit_resp = client.post(
        f"/api/pages/agent/{hash_id}/submit",
        json={"priority": "Log Compaction", "comments": "Analyze snapshot installation RPC."},
    )
    assert submit_resp.status_code == 200
    submit_json = submit_resp.json()
    assert submit_json["status"] == "success"

    # Verify response saved in DB
    with db_session() as session:
        updated = session.query(AgentPage).filter_by(hash_id=hash_id).first()
        assert updated.user_response_json is not None
        user_res = json.loads(updated.user_response_json)
        assert user_res["data"]["priority"] == "Log Compaction"


def test_hitl_python_approval_and_execution_flow(client: TestClient, sample_agent: str):
    """Test the strict Human-In-The-Loop Python execution workflow: propose -> approve -> execute."""
    python_code = "print(f'Consensus calculation result: {21 * 2}')"

    with db_session() as session:
        res = propose_python_execution(
            agent_id=sample_agent,
            code=python_code,
            purpose="Calculate cluster quorum threshold",
            session=session,
        )
        session.commit()
        approval_id = res["approval_id"]
        hash_id = res["hash_id"]

    # 1. Verify approval was created in pending state
    with db_session() as session:
        appr = session.query(AgentPythonApproval).filter_by(id=approval_id).first()
        assert appr.status == "pending"
        assert appr.executed_at is None

    # 2. View approval page in browser
    resp = client.get(f"/pages/agent/{hash_id}")
    assert resp.status_code == 200
    assert "Consensus calculation result" in resp.text
    assert "Human-In-The-Loop Python Execution Request" in resp.text

    # 3. Submit approval decision via API
    submit_resp = client.post(
        f"/api/pages/agent/{hash_id}/submit",
        json={"decision": "approve"},
    )
    assert submit_resp.status_code == 200
    result = submit_resp.json()
    assert result["status"] == "success"
    exec_result = result["execution_result"]
    assert exec_result["status"] == "executed"
    assert "Consensus calculation result: 42" in exec_result["output"]

    # 4. Verify in DB
    with db_session() as session:
        appr_after = session.query(AgentPythonApproval).filter_by(id=approval_id).first()
        assert appr_after.status == "executed"
        assert "42" in appr_after.output


def test_hitl_python_rejection_flow(client: TestClient, sample_agent: str):
    """Test rejecting untrusted Python code proposals."""
    untrusted_code = "import os; print(os.environ)"

    with db_session() as session:
        res = propose_python_execution(
            agent_id=sample_agent,
            code=untrusted_code,
            purpose="Inspect environment secrets",
            session=session,
        )
        session.commit()
        approval_id = res["approval_id"]
        hash_id = res["hash_id"]

    # Reject via form submit
    submit_resp = client.post(
        f"/api/pages/agent/{hash_id}/submit",
        json={"decision": "reject", "feedback": "Environment inspection not permitted"},
    )
    assert submit_resp.status_code == 200
    result = submit_resp.json()
    assert result["status"] == "success"
    assert result["execution_result"]["status"] == "rejected"

    with db_session() as session:
        appr_after = session.query(AgentPythonApproval).filter_by(id=approval_id).first()
        assert appr_after.status == "rejected"
        assert "not permitted" in (appr_after.output or "")


def test_steer_topic_grounding(sample_agent: str):
    """Verify topic grounding searches and links already-imported library items."""
    u1 = f"https://dist-sys.org/raft_{time.time_ns()}"
    u2 = f"https://recipes.com/soup_{time.time_ns()}"
    with db_session() as session:
        f1 = FetchedPage(
            url=u1,
            title="Raft Distributed Consensus Architecture",
            md_content="Raft algorithm guarantees state machine replication across server quorums.",
            tags="consensus,raft,database",
        )
        f2 = FetchedPage(
            url=u2,
            title="Tomato Soup Recipe",
            md_content="How to make hot tomato soup in winter.",
            tags="cooking,soup",
        )
        session.add_all([f1, f2])
        session.commit()

        # Run topic grounding
        res = steer_topic_grounding(sample_agent, session)
        assert res["status"] == "success"
        assert res["new_observations"] >= 1

        # Verify an observation was recorded in agent's working memory
        obs = (
            session.query(AgentObservation)
            .filter_by(agent_id=sample_agent)
            .order_by(AgentObservation.id.desc())
            .first()
        )
        assert obs is not None
        assert "Raft Distributed Consensus Architecture" in obs.content


@patch("kb_web.custom_agent_engine._get_ollama_client")
def test_deliberate_agent(mock_get_client, sample_agent: str):
    """Verify agent self-task generation and topic wiki compilation during autonomous deliberation."""
    mock_cli = MagicMock()
    # Mock LLM deliberation response
    mock_chat_res = MagicMock()
    mock_chat_res.message.content = """# Distributed Consensus Architecture

## Executive Summary
Raft achieves consensus via leader election and replicated log management.

## Architecture
Leader, Follower, and Candidate states define node lifecycles.
"""
    mock_cli.chat.return_value = mock_chat_res
    mock_get_client.return_value = mock_cli

    unique_src = f"https://dist-sys.org/raft_{time.time_ns()}"
    with db_session() as session:
        # Prepopulate an observation so agent has context
        session.add(AgentObservation(
            agent_id=sample_agent,
            content="Discovered cluster compaction requirements.",
            source_url=unique_src,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))
        session.commit()

        res = deliberate_agent(sample_agent, session)
        assert res["status"] == "success"
        assert "index" in res["wiki_path"]

        # Check TopicWikiPage was compiled
        wiki_page = session.query(TopicWikiPage).filter_by(agent_id=sample_agent, logical_path="index").first()
        assert wiki_page is not None
        assert "Overview" in wiki_page.title
        assert "Raft achieves consensus" in wiki_page.body_markdown

        # Check self tasks were recorded and completed
        tasks = session.query(AgentSelfTask).filter_by(agent_id=sample_agent).all()
        assert len(tasks) >= 1
        assert any(t.status == "completed" for t in tasks)
