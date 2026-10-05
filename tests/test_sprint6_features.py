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
import time
import unittest
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from kb_web.server import app, config as server_config
from kb_web.base import db_session
from kb_web.models_orm import FetchedPage, ChunkEmbedding, Note, ChatConversation, ChatMessage, SavedReportView


@pytest.fixture
def client() -> TestClient:
    from kb_web.base import COOKIE_NAME, generate_session_token
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


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
    # 1. UI route (redirects to /reports/rag)
    ui_resp = client.get("/conversations", cookies=auth_cookie, follow_redirects=True)
    assert ui_resp.status_code == 200
    assert "Agentic RAG Report Generator" in ui_resp.text

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


# -----------------------------------------------------------------------------
# Turn 3 UAT Regression & Issue #70 Tests
# -----------------------------------------------------------------------------

def test_notes_monaco_editor_head_block(client: TestClient, auth_cookie):
    """Verifies that Monaco Editor loader script tag is injected into the rendered HTML."""
    resp = client.get("/notes/editor", cookies=auth_cookie)
    assert resp.status_code == 200
    assert "vs/loader.min.js" in resp.text
    assert "initMonacoEditor" in resp.text


def test_article_chat_drawer_dom_controller(client: TestClient):
    """Verifies that view_page HTML has eliminated the legacy chat drawer and replaced it with RAG research button."""
    test_url = "https://example.com/sprint6-test-article"
    resp = client.get(f"/view/page?url={test_url}")
    assert resp.status_code == 200
    assert "openChatDrawer()" not in resp.text
    assert 'id="chat-drawer"' not in resp.text
    assert "RAG Research Report" in resp.text
    assert "/reports/rag?q=" in resp.text


def test_reports_group_by_query(client: TestClient):
    """Verifies that execute_report_query handles group_by parameter cleanly without 500 SQL error."""
    resp = client.post(
        "/api/reports/query",
        json={
            "base_table": "notes",
            "columns": ["notes.id", "notes.title", "notes.url", "notes.vault_name"],
            "group_by": "notes.url",
            "limit": 10,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert "total_count" in data


def test_workspaces_crud_and_ide(client: TestClient, auth_cookie):
    """Verifies persistent Replit-style workspace lifecycle: create, list, file upsert, export, duplicate, delete."""
    # 1. Create workspace
    create_resp = client.post(
        "/api/workspaces",
        json={
            "name": "Test Mini Arcade",
            "description": "A testing game workspace",
            "template": "web-game",
        },
    )
    assert create_resp.status_code == 200
    ws_data = create_resp.json()
    assert ws_data["status"] == "created"
    ws_id = ws_data["id"]

    # 2. Get workspace details (should contain seeded template files)
    detail_resp = client.get(f"/api/workspaces/{ws_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert "index.html" in detail["files"]
    assert "app.js" in detail["files"]

    # 3. Upsert a new file
    file_resp = client.post(
        f"/api/workspaces/{ws_id}/files",
        json={
            "path": "src/utils.js",
            "content": "export function add(a, b) { return a + b; }",
            "language": "javascript",
        },
    )
    assert file_resp.status_code == 200

    # 4. Export ZIP
    zip_resp = client.get(f"/api/workspaces/{ws_id}/export-zip")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"

    # 5. UI Routes
    list_ui_resp = client.get("/workspaces", cookies=auth_cookie)
    assert list_ui_resp.status_code == 200
    assert "Test Mini Arcade" in list_ui_resp.text

    ide_ui_resp = client.get(f"/workspaces/{ws_id}", cookies=auth_cookie)
    assert ide_ui_resp.status_code == 200
    assert "Test Mini Arcade" in ide_ui_resp.text
    assert "monacoEditor" in ide_ui_resp.text

    # 6. Duplicate workspace
    dup_resp = client.post(f"/api/workspaces/{ws_id}/duplicate")
    assert dup_resp.status_code == 200
    dup_id = dup_resp.json()["id"]

    # 7. Delete workspaces
    del_orig = client.delete(f"/api/workspaces/{ws_id}")
    assert del_orig.status_code == 200
    del_dup = client.delete(f"/api/workspaces/{dup_id}")
    assert del_dup.status_code == 200


def test_workspace_ollama_agent_and_models(client: TestClient, monkeypatch):
    """Verifies LoggedOllamaClient.generate, workspace models endpoint from /tags, and clean agent error handling."""
    from kb_web.base import _get_ollama_client

    ollama_c = _get_ollama_client()

    # 1. Verify LoggedOllamaClient.generate works and logs
    with unittest.mock.patch.object(ollama_c._client, "generate", return_value={"response": "test code generation"}):
        resp_gen = ollama_c.generate(model="gemma4:latest", prompt="generate hello world")
        assert resp_gen["response"] == "test code generation"

    # 2. Verify LoggedOllamaClient.__getattr__ delegates to _client
    assert hasattr(ollama_c, "_client")
    assert callable(getattr(ollama_c, "list"))

    # 3. Test GET /api/workspaces/models
    with unittest.mock.patch.object(
        ollama_c,
        "list",
        return_value={"models": [{"model": "gemma4:e4b"}, {"model": "llama3.2:latest"}]},
    ):
        with unittest.mock.patch("kb_web.routers.workspaces._get_ollama_client", return_value=ollama_c):
            models_resp = client.get("/api/workspaces/models")
            assert models_resp.status_code == 200
            m_data = models_resp.json()
            assert m_data["status"] == "success"
            assert "gemma4:e4b" in m_data["models"]
            assert "llama3.2:latest" in m_data["models"]

    # 4. Create workspace for agent chat test
    ws_resp = client.post("/api/workspaces", json={"name": "Ollama Agent Test WS", "template": "empty"})
    assert ws_resp.status_code == 200
    ws_id = ws_resp.json()["id"]

    # 5. Test agent chat with successful response
    mock_chat_resp = unittest.mock.MagicMock()
    mock_chat_resp.message.content = "Here is my advice on pythonrc.py: you should import rich."

    with unittest.mock.patch.object(ollama_c, "chat", return_value=mock_chat_resp):
        with unittest.mock.patch("kb_web.routers.workspaces._get_ollama_client", return_value=ollama_c):
            with unittest.mock.patch("kb_web.routers.workspaces.ensure_model_available"):
                chat_resp = client.post(
                    f"/api/workspaces/{ws_id}/agent/chat",
                    json={"message": "What do you think of my pythonrc.py?", "model": "gemma4:e4b"},
                )
                assert chat_resp.status_code == 200
                res_data = chat_resp.json()
                assert res_data["status"] == "success"
                assert "you should import rich" in res_data["reply"]
                # Must not contain hallucinated fake app.js diff
                assert "app.js" not in res_data["reply"]

    # 6. Test agent chat with error (no hallucinated mock diffs)
    with unittest.mock.patch.object(ollama_c, "chat", side_effect=RuntimeError("Connection refused by Ollama")):
        with unittest.mock.patch.object(ollama_c, "generate", side_effect=RuntimeError("Connection refused by Ollama")):
            with unittest.mock.patch("kb_web.routers.workspaces._get_ollama_client", return_value=ollama_c):
                with unittest.mock.patch("kb_web.routers.workspaces.ensure_model_available"):
                    chat_err_resp = client.post(
                        f"/api/workspaces/{ws_id}/agent/chat",
                        json={"message": "Suggest changes", "model": "gemma4:e4b"},
                    )
                    assert chat_err_resp.status_code == 200
                    err_data = chat_err_resp.json()
                    assert err_data["status"] == "error"
                    assert "Ollama server connection or execution failed" in err_data["reply"]
                    # Strictly no fake codeblocks for app.js
                    assert "```file:app.js" not in err_data["reply"]

    # Clean up workspace
    client.delete(f"/api/workspaces/{ws_id}")


# -----------------------------------------------------------------------------
# Issue #75: Notes Modal Freeze, Autoescape, and PWA Manifest Tests
# -----------------------------------------------------------------------------

def test_issue75_notes_modal_freeze_and_pwa_manifest(client: TestClient, auth_cookie):
    """Verifies that notes with HTML/scripts are safely autoescaped, modal scripts
    are declared early and properly, sw.js omits no-op fetch handler, and manifest
    includes share_target enctype."""
    # 1. Test PWA manifest enctype
    manifest_resp = client.get("/manifest.json")
    assert manifest_resp.status_code == 200
    manifest_data = manifest_resp.json()
    assert "share_target" in manifest_data
    assert manifest_data["share_target"].get("enctype") == "application/x-www-form-urlencoded"

    # 2. Test sw.js does not contain no-op fetch handler
    sw_resp = client.get("/sw.js")
    assert sw_resp.status_code == 200
    assert "addEventListener('fetch'" not in sw_resp.text
    assert "addEventListener(\"fetch\"" not in sw_resp.text
    assert "addEventListener('install'" in sw_resp.text
    assert "addEventListener('activate'" in sw_resp.text

    # 3. Create note containing unclosed/raw script tags and code
    paste_resp = client.post(
        "/api/notes/paste",
        json={
            "title": "Raw Script <script>alert('xss')</script> Test",
            "content": "Code with script:\n<script src=\"evil.js\">\nconst x = 1.0;\n</script>",
            "syntax": "javascript",
            "vault_name": "Obsidian <Vault>",
            "folder_path": "scripts/<test>",
        },
        cookies=auth_cookie,
    )
    assert paste_resp.status_code == 200
    note_id = paste_resp.json()["id"]

    # 4. Request /notes UI dashboard and verify escaping and modal functions
    notes_ui_resp = client.get("/notes", cookies=auth_cookie)
    assert notes_ui_resp.status_code == 200
    html = notes_ui_resp.text

    # Raw script tags in title or content must NOT be present unescaped
    assert "<script>alert('xss')</script>" not in html
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html or "&lt;script&gt;" in html
    # Modal trigger functions must be declared
    assert "window.openPasteModal" in html
    assert "window.openVaultUploadModal" in html
    assert "id=\"open-paste-modal-btn\"" in html
    assert "id=\"open-vault-modal-btn\"" in html

    # Clean up test note
    client.delete(f"/api/notes/{note_id}", cookies=auth_cookie)



