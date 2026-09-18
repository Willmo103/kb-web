"""
Test suite for Sprint 6 features:
- Issue #62: Main page RAG Semantic Chunk Search
- Issue #63: Multi-Model Embedding Reindexing, Model Comparison, and Source Toggle
- Issue #64: Article-level Ollama Chat & Dedicated Conversations Dashboard
- Issue #65: Notes & Code Ingestion, Monaco Editor, and Obsidian Vault Mirroring
- Issue #66: Admin Portal Modernization (Tabbed Navigation)
- Issue #67: Custom Reports & ERP Data Grid Builder with Dynamic Joins and Streaming Exports
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from kb_web.server import app, config as server_config
from kb_web.base import db_session
from kb_web.models_orm import FetchedPage, ChunkEmbedding, Note, ChatConversation, ChatMessage, SavedReportView


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_cookie(client: TestClient):
    """Logs in as admin and returns session cookies."""
    login_resp = client.post(
        "/login",
        data={"password": server_config.admin_password},
        follow_redirects=False,
    )
    return {"kb_session": login_resp.cookies.get("kb_session")}


@pytest.fixture(autouse=True)
def seed_sprint6_test_data():
    """Seeds sample data for testing Sprint 6 endpoints."""
    with db_session() as session:
        # 1. Sample Page
        test_url = "https://example.com/sprint6-test-article"
        page = session.query(FetchedPage).filter_by(url=test_url).first()
        if not page:
            page = FetchedPage(
                url=test_url,
                title="Advanced Quantum Machine Learning Guide",
                description="A detailed overview of quantum state representations and neural networks.",
                html_content="<html><body><h1>Quantum Computing</h1><p>Quantum machine learning blends classical algorithms with quantum information theory.</p></body></html>",
                md_content="# Quantum Computing\n\nQuantum machine learning blends classical algorithms with quantum information theory.",
                fetched_at="2026-09-18T01:00:00",
                tags=json.dumps(["quantum", "machine learning", "physics"]),
            )
            session.add(page)

        # 2. Sample Chunk Embeddings for Multi-Model Testing
        existing_chunks = session.query(ChunkEmbedding).filter_by(source_id=test_url).all()
        if not existing_chunks:
            # Model 1: embeddinggemma
            c1 = ChunkEmbedding(
                source_type="articles",
                source_id=test_url,
                source_title=page.title,
                chunk_number=1,
                chunk_content="Quantum machine learning blends classical algorithms with quantum computing circuits.",
                chunk_vector=[0.1] * 768,
                model_name="embeddinggemma",
                created_at="2026-09-18T01:05:00",
            )
            # Model 2: nomic-embed-text
            c2 = ChunkEmbedding(
                source_type="articles",
                source_id=test_url,
                source_title=page.title,
                chunk_number=1,
                chunk_content="Quantum machine learning blends classical algorithms with quantum computing circuits.",
                chunk_vector=[0.2] * 768,
                model_name="nomic-embed-text",
                created_at="2026-09-18T01:05:00",
            )
            session.add_all([c1, c2])

        # 3. Sample Note
        sample_note_url = "note://vault/algorithms/quicksort.py"
        note = session.query(Note).filter_by(url=sample_note_url).first()
        if not note:
            note = Note(
                url=sample_note_url,
                title="QuickSort Algorithm in Python",
                content="def quicksort(arr):\n    if len(arr) <= 1: return arr\n    pivot = arr[len(arr) // 2]\n    return quicksort([x for x in arr if x < pivot]) + [x for x in arr if x == pivot] + quicksort([x for x in arr if x > pivot])",
                syntax="python",
                folder_path="algorithms",
                vault_name="CodeVault",
                tags=json.dumps(["algorithms", "python", "sorting"]),
                wiki_summary="Standard divide-and-conquer sorting algorithm in Python with O(N log N) average complexity.",
                created_at="2026-09-18T01:10:00",
                updated_at="2026-09-18T01:10:00",
            )
            session.add(note)

        # 4. Sample Conversation
        conv = session.query(ChatConversation).filter_by(source_id=test_url).first()
        if not conv:
            conv = ChatConversation(
                title="Quantum Discussion",
                source_type="article",
                source_id=test_url,
                created_at="2026-09-18T01:15:00",
                updated_at="2026-09-18T01:15:00",
            )
            session.add(conv)
            session.flush()
            msg1 = ChatMessage(
                conversation_id=conv.id,
                role="user",
                content="What is the main premise of quantum machine learning?",
                timestamp="2026-09-18T01:15:05",
                model="llama3:latest",
            )
            msg2 = ChatMessage(
                conversation_id=conv.id,
                role="assistant",
                content="Quantum machine learning leverages superposition and entanglement to speed up matrix operations.",
                timestamp="2026-09-18T01:15:10",
                model="llama3:latest",
            )
            session.add_all([msg1, msg2])

        session.commit()


# -----------------------------------------------------------------------------
# Issue #62: Main Page RAG Semantic Chunk Search Tests
# -----------------------------------------------------------------------------

def test_rag_search_endpoints(client: TestClient):
    """Verifies GET and POST /api/search/rag endpoints return chunks and parent references."""
    with patch("kb_web.utils.generate_gemma_embeddings_for_page", return_value=[0.1] * 768):
        # 1. GET /api/search/rag
        get_resp = client.get("/api/search/rag?q=quantum+machine+learning&limit=5")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert "query" in get_data
        assert "results" in get_data
        assert isinstance(get_data["results"], list)
        if get_data["results"]:
            chunk = get_data["results"][0]
            assert "source_id" in chunk
            assert "chunk_content" in chunk
            assert "similarity" in chunk

        # 2. POST /api/search/rag
        post_resp = client.post(
            "/api/search/rag",
            json={"query": "quantum circuits", "limit": 3, "source_type": "all"},
        )
        assert post_resp.status_code == 200
        post_data = post_resp.json()
        assert post_data["query"] == "quantum circuits"


def test_article_view_chunks_hydration(client: TestClient):
    """Verifies that /view/page renders document chunks with anchor jump links."""
    resp = client.get("/view/page?url=https://example.com/sprint6-test-article")
    assert resp.status_code == 200
    assert "Document Chunks" in resp.text
    assert "chunk-1" in resp.text


# -----------------------------------------------------------------------------
# Issue #63: Multi-Model Embeddings & Comparison Tests
# -----------------------------------------------------------------------------

def test_embedding_models_endpoints(client: TestClient, auth_cookie):
    """Verifies listing embedding models, toggling active model, and comparing similarity."""
    # 1. List supported models
    resp = client.get("/api/embeddings/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "available_models" in data
    assert "embeddinggemma" in data["available_models"]

    # 2. Get and set active model
    active_resp = client.get("/api/embeddings/active-model")
    assert active_resp.status_code == 200
    current_model = active_resp.json()["active_model"]

    set_resp = client.post(
        "/api/embeddings/active-model",
        json={"model": "nomic-embed-text"},
        cookies=auth_cookie,
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["active_model"] == "nomic-embed-text"

    # Reset back
    client.post(
        "/api/embeddings/active-model",
        json={"model": current_model},
        cookies=auth_cookie,
    )

    # 3. Model comparison UI and API
    ui_resp = client.get("/similarity/compare")
    assert ui_resp.status_code == 200
    assert "Multi-Vector Comparison" in ui_resp.text

    compare_resp = client.post(
        "/api/embeddings/compare",
        json={
            "query": "quantum state",
            "models": ["embeddinggemma", "nomic-embed-text"],
            "limit": 5,
        },
    )
    assert compare_resp.status_code == 200
    comp_data = compare_resp.json()
    assert "comparisons" in comp_data


# -----------------------------------------------------------------------------
# Issue #64: Article Chat & Conversations Dashboard Tests
# -----------------------------------------------------------------------------

def test_conversations_api_and_dashboard(client: TestClient, auth_cookie):
    """Verifies thread creation, message retrieval, and the /conversations dashboard."""
    # 1. UI route
    ui_resp = client.get("/conversations", cookies=auth_cookie)
    assert ui_resp.status_code == 200
    assert "Ollama Chat Conversations" in ui_resp.text

    # 2. By source URL
    by_source_resp = client.get("/api/conversations/by-source?url=https://example.com/sprint6-test-article")
    assert by_source_resp.status_code == 200
    source_data = by_source_resp.json()
    assert source_data["conversation"] is not None
    assert len(source_data["messages"]) >= 2

    # 3. Chat completion via mocked Ollama client
    mock_ollama_resp = MagicMock()
    mock_ollama_resp.message = MagicMock()
    mock_ollama_resp.message.content = "Entanglement allows correlated measurements across space."

    with patch("kb_web.routers.conversations._get_ollama_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_ollama_resp
        mock_client_factory.return_value = mock_client

        chat_resp = client.post(
            "/api/conversations/chat",
            json={
                "source_id": "https://example.com/sprint6-test-article",
                "source_type": "article",
                "message": "Explain entanglement briefly.",
            },
        )
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()
        assert chat_data["reply"] == "Entanglement allows correlated measurements across space."


# -----------------------------------------------------------------------------
# Issue #65: Notes, Monaco Editor, and Obsidian Vaults Tests
# -----------------------------------------------------------------------------

def test_notes_endpoints_and_editor(client: TestClient, auth_cookie):
    """Verifies note creation, listing, tree structure, and Monaco editor."""
    # 1. Create a note via paste ingestion
    paste_resp = client.post(
        "/api/notes/paste",
        json={
            "title": "Dijkstra Shortest Path",
            "content": "def dijkstra(graph, start):\n    pass",
            "syntax": "python",
            "vault_name": "PersonalVault",
            "folder_path": "graphs",
        },
        cookies=auth_cookie,
    )
    assert paste_resp.status_code == 200
    paste_data = paste_resp.json()
    assert paste_data["status"] in ("created", "success")
    note_id = paste_data["id"]

    # 2. List notes and get tree
    list_resp = client.get("/api/notes")
    assert list_resp.status_code == 200
    notes = list_resp.json()["notes"]
    assert any(n["title"] == "Dijkstra Shortest Path" for n in notes)

    tree_resp = client.get("/api/notes/tree")
    assert tree_resp.status_code == 200
    tree_data = tree_resp.json()
    assert "vaults" in tree_data

    # 3. UI Notes List and Editor
    notes_ui_resp = client.get("/notes", cookies=auth_cookie)
    assert notes_ui_resp.status_code == 200
    assert "Notes & Obsidian Vaults" in notes_ui_resp.text

    editor_ui_resp = client.get(f"/notes/editor?id={note_id}", cookies=auth_cookie)
    assert editor_ui_resp.status_code == 200
    assert "monaco-editor" in editor_ui_resp.text

    # 4. Clean up test note
    client.delete(f"/api/notes/{note_id}", cookies=auth_cookie)


# -----------------------------------------------------------------------------
# Issue #66: Admin Portal Tabbed Layout Tests
# -----------------------------------------------------------------------------

def test_admin_portal_modernized_tabs(client: TestClient, auth_cookie):
    """Verifies that /admin renders all 5 space-efficient tabs and preserved forms."""
    resp = client.get("/admin", cookies=auth_cookie)
    assert resp.status_code == 200
    assert "tab-general" in resp.text
    assert "tab-prompts" in resp.text
    assert "tab-backups" in resp.text
    assert "tab-media" in resp.text
    assert "tab-diagnostics" in resp.text
    assert "switchAdminTab" in resp.text


# -----------------------------------------------------------------------------
# Issue #67: Custom Reports & ERP Data Grid Tests
# -----------------------------------------------------------------------------

def test_reports_tables_and_query(client: TestClient, auth_cookie):
    """Verifies table introspection, dynamic query, heavy column placeholders, and exports."""
    # 1. Tables metadata
    meta_resp = client.get("/api/reports/tables")
    assert meta_resp.status_code == 200
    tables = meta_resp.json()["tables"]
    assert "fetched_pages" in tables
    assert "youtube_videos" in tables
    assert "notes" in tables

    # 2. Dynamic Query with heavy placeholder check
    query_resp = client.post(
        "/api/reports/query",
        json={
            "base_table": "fetched_pages",
            "columns": ["fetched_pages.url", "fetched_pages.title", "fetched_pages.html_content"],
            "filters": [{"column": "fetched_pages.title", "operator": "contains", "value": "Quantum"}],
            "fetch_heavy": False,
        },
    )
    assert query_resp.status_code == 200
    q_data = query_resp.json()
    assert q_data["total_count"] >= 1
    # Check that html_content is replaced by lightweight placeholder!
    row = q_data["rows"][0]
    html_val = row.get("fetched_pages.html_content", "")
    assert "[HTML:" in html_val or "[Empty" in html_val

    # 3. Saved Views CRUD
    import time
    unique_view_name = f"Test Quantum Pages View {int(time.time() * 1000)}"
    save_resp = client.post(
        "/api/reports/views",
        json={
            "name": unique_view_name,
            "description": "View of quantum pages",
            "base_table": "fetched_pages",
            "config_json": {
                "columns": ["fetched_pages.url", "fetched_pages.title"],
                "filters": [],
            },
        },
    )
    assert save_resp.status_code == 200
    view_id = save_resp.json()["id"]

    views_list_resp = client.get("/api/reports/views")
    assert views_list_resp.status_code == 200
    assert any(v["id"] == view_id for v in views_list_resp.json())

    # 4. Exports: CSV, JSON, XLSX
    csv_resp = client.post(
        "/api/reports/export?format=csv",
        json={"base_table": "fetched_pages", "columns": ["fetched_pages.url", "fetched_pages.title"]},
    )
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "fetched_pages.url" in csv_resp.text

    json_resp = client.post(
        "/api/reports/export?format=json",
        json={"base_table": "fetched_pages", "columns": ["fetched_pages.url", "fetched_pages.title"]},
    )
    assert json_resp.status_code == 200
    assert "application/json" in json_resp.headers["content-type"]

    xlsx_resp = client.post(
        "/api/reports/export?format=xlsx",
        json={"base_table": "fetched_pages", "columns": ["fetched_pages.url", "fetched_pages.title"]},
    )
    assert xlsx_resp.status_code == 200
    assert "openxmlformats-officedocument" in xlsx_resp.headers["content-type"]

    # 5. UI Route
    reports_ui_resp = client.get("/reports", cookies=auth_cookie)
    assert reports_ui_resp.status_code == 200
    assert "Custom Reports & ERP Data Grid" in reports_ui_resp.text

    # 6. Clean up saved view
    client.delete(f"/api/reports/views/{view_id}")
