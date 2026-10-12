"""Unit and integration tests for Notes Cascading Delete, Workspace AI UX & Gist,

Loaded Ollama Models Introspection, and Taxonomy Graph Collision Retries.
"""

from datetime import datetime
import json
import time
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient

from kb_web.server import app, config as server_config
from kb_web.base import db_session, COOKIE_NAME, generate_session_token
from kb_web.models_orm import (
    Note,
    FetchedPage,
    ChunkEmbedding,
    ArticleEmbedding,
    TaxonomyCategory,
    TaxonomyItem,
    ChatConversation,
    ChatMessage,
    Link,
    Workspace,
    WorkspaceFile,
    Collection,
    CollectionItem,
)
from kb_web.routers.notes import _cascade_delete_notes
from kb_web.taxonomy_state_machine import (
    _ensure_unique_slug,
    _format_metadata_summary,
    _synthesize_new_category,
    classify_single_item,
)


@pytest.fixture
def client() -> TestClient:
    token = generate_session_token(time.time() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {server_config.api_key}"}


def test_cascade_delete_notes_full_graph(client: TestClient):
    """Verifies that deleting a note cascades across all 10 dependent tables and decrements category item counts."""
    now_str = datetime.now().isoformat()
    with db_session() as session:
        # Create a category
        cat = TaxonomyCategory(
            name="Cascade Testing Category",
            slug=_ensure_unique_slug(session, "cascade-testing-category"),
            item_count=1,
            doc="Test category for cascade delete.",
        )
        session.add(cat)
        session.commit()
        session.refresh(cat)
        cat_id = cat.id

        uniq_id = int(time.time() * 1000)
        # Create Note
        note = Note(
            title="Cascade Delete Target Note",
            content="# Target Content\nSome sensitive notes to delete.",
            vault_name="WorkVault",
            folder_path="scratch",
            url=f"note://workvault/scratch/cascade-target-{uniq_id}",
            is_frozen=0,
            tags=json.dumps(["cascade", "test"]),
            links=json.dumps(["https://example.com/test-cascade-link"]),
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id
        note_url = note.url

        # Mirrored FetchedPage
        page = FetchedPage(
            url=note_url,
            title=f"📝 {note.title}",
            html_content="",
            md_content=note.content,
            fetched_at=now_str,
            is_frozen=0,
        )
        session.add(page)
        session.commit()

        # Dependent items:
        # 1. Taxonomy Item
        t_item = TaxonomyItem(
            category_id=cat_id,
            item_type="note",
            item_id=f"note_{note_id}",
            item_title=note.title,
            fit_score=0.98,
            assigned_at=now_str,
            item_class="Notes",
        )
        session.add(t_item)

        # 2. Chunk Embedding
        chunk = ChunkEmbedding(
            source_type="note",
            source_id=note_url,
            chunk_number=0,
            chunk_content="Some sensitive notes to delete.",
            created_at=now_str,
        )
        session.add(chunk)

        # 3. Article Embedding
        art_emb = ArticleEmbedding(
            url=note_url,
            updated_at=now_str,
        )
        session.add(art_emb)

        # 4. Link
        lnk = Link(
            url=note_url,
            title="Cascade Target Link",
        )
        session.add(lnk)

        # 5. Chat Conversation & Message
        conv = ChatConversation(
            source_id=note_url,
            source_type="note",
            title=f"Chat on {note.title}",
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)
        conv_id = conv.id

        msg = ChatMessage(
            conversation_id=conv_id,
            role="user",
            content="Can you summarize this note?",
            timestamp=now_str,
        )
        session.add(msg)

        # 6. Collection Item
        col = Collection(title="Test Cascade Collection", visibility="private", created_at=now_str)
        session.add(col)
        session.commit()
        session.refresh(col)
        col_id = col.id

        col_item = CollectionItem(
            collection_id=col_id,
            source_type="note",
            source_id=note_url,
            added_at=now_str,
        )
        session.add(col_item)
        session.commit()

    # Perform DELETE via API endpoint
    resp = client.delete(f"/api/notes/{note_id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["deleted_id"] == note_id

    # Verify database state
    with db_session() as session:
        # Note deleted
        assert session.query(Note).filter_by(id=note_id).first() is None
        # Mirrored FetchedPage deleted
        assert session.query(FetchedPage).filter_by(url=note_url).first() is None
        # Taxonomy item deleted
        assert session.query(TaxonomyItem).filter_by(item_id=f"note_{note_id}").first() is None
        # Category item_count decremented
        c = session.query(TaxonomyCategory).filter_by(id=cat_id).first()
        assert c is not None
        assert c.item_count == 0
        # Embeddings deleted
        assert session.query(ChunkEmbedding).filter_by(source_id=note_url).first() is None
        assert session.query(ArticleEmbedding).filter_by(url=note_url).first() is None
        # Links deleted
        assert session.query(Link).filter_by(url=note_url).first() is None
        # Conversations and messages deleted
        assert session.query(ChatConversation).filter_by(source_id=note_url).first() is None
        assert session.query(ChatMessage).filter_by(conversation_id=conv_id).first() is None
        # Collection item deleted
        assert session.query(CollectionItem).filter_by(collection_id=col_id, source_id=note_url).first() is None


def test_cascade_delete_frozen_note_blocked(client: TestClient):
    """Verifies that frozen notes cannot be deleted and return HTTP 403."""
    with db_session() as session:
        note = Note(
            title="Frozen Immutability Note",
            content="Frozen forever",
            vault_name="FrozenVault",
            url=f"note://frozen/{int(time.time()*1000)}",
            is_frozen=1,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        frozen_id = note.id

    resp = client.delete(f"/api/notes/{frozen_id}")
    assert resp.status_code == 403
    assert "frozen" in resp.json()["detail"].lower()

    # Ensure still exists
    with db_session() as session:
        assert session.query(Note).filter_by(id=frozen_id).first() is not None


def test_workspace_prompt_generation_and_custom_template(client: TestClient):
    """Tests creating a workspace using an AI prompt and flexible custom template."""
    prompt_payload = {
        "name": "Rust Micro-Engine",
        "prompt": "Build an algorithmic trading parser in Rust with Cargo.toml and main.rs",
        "template": "rust-lang",
    }

    mock_llm_response = {
        "message": {
            "content": json.dumps({
                "name": "AlgoTrader Rust",
                "template": "rust-lang",
                "files": [
                    {"path": "Cargo.toml", "content": "[package]\nname = \"algotrader\"\nversion = \"0.1.0\"\n"},
                    {"path": "src/main.rs", "content": "fn main() {\n    println!(\"Trading Engine Active\");\n}\n"},
                    {"path": "README.md", "content": "# AlgoTrader Rust\n\nHigh-frequency trading engine in Rust.\n"},
                ]
            })
        }
    }

    with patch("kb_web.routers.workspaces._get_ollama_client") as mock_cli:
        mock_instance = MagicMock()
        mock_instance.chat.return_value = mock_llm_response
        mock_cli.return_value = mock_instance

        resp = client.post("/api/workspaces", json=prompt_payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["template"] == "rust-lang"
        ws_id = data["id"]

    with db_session() as session:
        ws = session.query(Workspace).filter_by(id=ws_id).first()
        assert ws is not None
        assert ws.template == "rust-lang"
        files = session.query(WorkspaceFile).filter_by(workspace_id=ws_id).all()
        paths = {f.file_path for f in files}
        assert "Cargo.toml" in paths
        assert "src/main.rs" in paths
        assert "README.md" in paths


def test_loaded_models_introspection(client: TestClient):
    """Tests /api/workspaces/models and /api/models properly querying Ollama /api/ps for loaded VRAM models."""
    mock_tags = MagicMock()
    m1 = MagicMock()
    m1.model = "qwen2.5-coder:7b"
    m2 = MagicMock()
    m2.model = "llama3.2:3b"
    mock_tags.models = [m1, m2]

    mock_ps = {
        "models": [
            {"model": "qwen2.5-coder:7b", "size_vram": 4500000000},
        ]
    }

    mock_hclient = MagicMock()
    mock_ps_resp = MagicMock()
    mock_ps_resp.status_code = 200
    mock_ps_resp.json.return_value = mock_ps
    mock_hclient.get.return_value = mock_ps_resp
    mock_hclient.__enter__.return_value = mock_hclient

    with patch("kb_web.routers.workspaces._get_ollama_client") as mock_cli, \
         patch("kb_web.routers.workspaces.httpx.Client", return_value=mock_hclient):
        mock_inst = MagicMock()
        mock_inst.list.return_value = mock_tags
        mock_cli.return_value = mock_inst

        resp = client.get("/api/workspaces/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "loaded_models" in data
        assert "qwen2.5-coder:7b" in data["loaded_models"]
        assert "llama3.2:3b" not in data["loaded_models"]

        # Also verify global /api/models endpoint
        resp2 = client.get("/api/models")
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert "loaded_models" in data2
        assert "qwen2.5-coder:7b" in data2["loaded_models"]


def test_targeted_classify_notes_endpoint(client: TestClient):
    """Tests POST /api/taxonomy/classify-notes endpoint scheduling unclassified notes."""
    with db_session() as session:
        n1 = Note(title="Unclassified Note 1", content="Machine learning models", vault_name="AI_Vault", url=f"note://ai/1_{int(time.time()*1000)}")
        n2 = Note(title="Unclassified Note 2", content="Cooking pasta sauces", vault_name="Personal", url=f"note://personal/2_{int(time.time()*1000)}")
        session.add_all([n1, n2])
        session.commit()

    with patch("kb_web.routers.taxonomy.classify_single_item") as mock_classify:
        mock_classify.return_value = {"status": "assigned", "category_name": "Test Domain"}

        resp = client.post("/api/taxonomy/classify-notes", json={"vault": "AI_Vault", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
        assert data["target_count"] >= 1


def test_taxonomy_slug_collision_retry_and_uniqueness():
    """Tests taxonomy slug collision detection, agent retry loop, and fallback uniqueness."""
    with db_session() as session:
        # Create an existing category
        u_token = int(time.time() * 1000)
        base_name = f"Cloud Infrastructure {u_token}"
        from kb_web.taxonomy_state_machine import _generate_category_slug
        base_slug = _generate_category_slug(base_name)

        cat = TaxonomyCategory(
            name=base_name,
            slug=base_slug,
            item_count=1,
            doc="Existing category",
        )
        session.add(cat)
        session.commit()

        # Test _ensure_unique_slug
        unique_slug = _ensure_unique_slug(session, base_slug)
        assert unique_slug == f"{base_slug}-2"

        # Test _format_metadata_summary
        meta = {
            "vault": "WorkVault",
            "folder": "devops/aws",
            "syntax": "yaml",
            "version_count": 3,
        }
        summary = _format_metadata_summary(meta)
        assert "- Vault: WorkVault" in summary
        assert "- Folder: devops/aws" in summary
        assert "- Syntax: yaml" in summary
        assert "- Version History: 3 revisions recorded" in summary

        retry_name = f"Serverless Microservices {u_token}"
        expected_slug = _generate_category_slug(retry_name)

        # Test _synthesize_new_category with retry loop
        mock_client = MagicMock()
        # First call produces colliding name/slug, retry produces new distinct title
        mock_client.chat.side_effect = [
            {"message": {"content": json.dumps({"category_name": base_name, "category_doc": "Colliding doc"})}},
            {"message": {"content": json.dumps({"category_name": retry_name, "category_doc": "Distinct doc"})}},
        ]

        mock_config = MagicMock()
        mock_config.ollama_model = "gemma2"

        synth_cat = _synthesize_new_category(
            session=session,
            item_title="Lambda Trigger Config",
            item_excerpt="Serverless AWS lambda handler",
            item_tags=["aws", "lambda"],
            existing_categories=[cat],
            client=mock_client,
            config=mock_config,
            item_class="Documentation",
            item_metadata=meta,
        )
        assert synth_cat.slug == expected_slug
        assert synth_cat.name == retry_name


def test_taxonomy_provenance_enrichment_in_classify_single_item():
    """Verifies classify_single_item packages rich provenance metadata before invoking classify_item."""
    with db_session() as session:
        note = Note(
            title="Kubernetes Helm Architecture",
            content="Deploying charts with ingress",
            vault_name="Operations",
            folder_path="k8s/helm",
            url=f"note://ops/helm_{int(time.time()*1000)}",
            tags=json.dumps(["k8s", "helm"]),
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        note_id = note.id

    with patch("kb_web.taxonomy_state_machine.classify_item") as mock_classify_item:
        mock_classify_item.return_value = {"status": "assigned"}

        res = classify_single_item("note", note_id)
        assert res["status"] == "assigned"
        mock_classify_item.assert_called_once()
        _, kwargs = mock_classify_item.call_args
        meta = kwargs.get("item_metadata")
        assert meta is not None
        assert meta["vault"] == "Operations"
        assert meta["folder"] == "k8s/helm"
