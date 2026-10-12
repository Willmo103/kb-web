"""
Tests for unified Supabase RAG view (vw_rag_items) and devtul repo importer.
"""

from datetime import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from kb_web.base import db_session, generate_session_token, COOKIE_NAME
from kb_web.models_orm import (
    FetchedPage,
    Note,
    YouTubeVideo,
    ChunkEmbedding,
    ArticleEmbedding,
    Workspace,
    WorkspaceFile,
    ensure_views_and_indexes,
)
from kb_web.repo_importer import (
    build_ascii_tree,
    build_repo_markdown_repr,
    normalize_repo_url,
    get_markdown_syntax,
    should_ignore_path,
)
from kb_web.server import app


@pytest.fixture
def auth_client():
    token = generate_session_token(datetime.now().timestamp() + 3600)
    return TestClient(app, cookies={COOKIE_NAME: token})


def test_normalize_repo_url():
    canon1, title1 = normalize_repo_url("https://github.com/willmo103/devtul.git")
    assert canon1 == "repo://github.com/willmo103/devtul"
    assert title1 == "willmo103/devtul"

    canon2, title2 = normalize_repo_url("git@gitlab.com:org/project.git")
    assert canon2 == "repo://gitlab.com/org/project"
    assert title2 == "org/project"


def test_ascii_tree_builder():
    files = [
        "README.md",
        "src/main.py",
        "src/utils/helpers.py",
        "docs/guide.md"
    ]
    tree = build_ascii_tree(files, parent_name="my_repo")
    assert "my_repo/" in tree
    assert "README.md" in tree
    assert "src/" in tree
    assert "helpers.py" in tree
    assert "guide.md" in tree


def test_repo_markdown_synthesis(tmp_path):
    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Sample Project\n\nWelcome to sample project.", encoding="utf-8")
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def run():\n    print('Hello World')\n", encoding="utf-8")
    git_dir = repo_dir / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("dummy", encoding="utf-8")

    md, metrics = build_repo_markdown_repr(repo_dir, repo_url="https://github.com/sample/project")

    assert "SAMPLE_REPO" in md
    assert "## Structure" in md
    assert "## Files" in md
    assert "### `README.md`" in md
    assert "### `src/main.py`" in md
    assert "```python" in md
    assert "print('Hello World')" in md
    assert metrics["files_included"] == 2
    assert "python" in metrics["languages"]


def test_vw_rag_items_view_and_multi_source_unification():
    """Verifies that vw_rag_items aggregates notes, pages, videos, and workspaces with standard Supabase schema."""
    with db_session() as session:
        engine = session.bind
        ensure_views_and_indexes(engine)

        now_str = datetime.now().isoformat()
        # 1. Page & Chunk
        page_url = f"https://example.com/test-rag-page-{datetime.now().timestamp()}"
        session.query(FetchedPage).filter_by(url=page_url).delete()
        page = FetchedPage(
            url=page_url,
            title="Test RAG Page",
            description="Page description for RAG",
            tags="ai, rag",
            md_content="# Content of Page",
            fetched_at=now_str,
            is_frozen=0,
        )
        session.add(page)
        session.flush()

        chunk_page = ChunkEmbedding(
            source_type="articles",
            source_id=page_url,
            source_title="Test RAG Page",
            chunk_number=0,
            chunk_content="This is chunk 0 of test page",
            model_name="embeddinggemma",
            created_at=now_str,
        )
        session.add(chunk_page)

        # 2. Note & Chunk
        note_url = f"note://personal-vault/test-note-{datetime.now().timestamp()}"
        note = Note(
            title="Test RAG Note",
            content="# Note Body",
            vault_name="personal-vault",
            folder_path="research",
            url=note_url,
            is_frozen=0,
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(note)
        session.flush()

        chunk_note = ChunkEmbedding(
            source_type="notes",
            source_id=note_url,
            source_title="Test RAG Note",
            chunk_number=0,
            chunk_content="This is chunk 0 of test note",
            model_name="embeddinggemma",
            created_at=now_str,
        )
        session.add(chunk_note)

        # 3. Workspace & File
        ws = Workspace(
            name=f"test-rag-ws-{int(datetime.now().timestamp())}",
            template="web-game",
            created_at=now_str,
            updated_at=now_str,
        )
        session.add(ws)
        session.flush()

        ws_file = WorkspaceFile(
            workspace_id=ws.id,
            file_path="app.py",
            content="print('workspace script')",
            language="python",
        )
        session.add(ws_file)
        session.commit()

        # Query vw_rag_items view
        rows = session.execute(text("SELECT id, source_type, title, content_chunk, url, metadata FROM vw_rag_items")).fetchall()
        assert len(rows) >= 3

        source_types = [r[1] for r in rows]
        assert "web_page" in source_types
        assert "note" in source_types
        assert "workspace" in source_types

        # Find note row
        note_row = next(r for r in rows if r[1] == "note" and r[4] == note_url)
        assert note_row[2] == "Test RAG Note"
        assert "chunk 0 of test note" in note_row[3]
        meta = note_row[5]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta["vault_name"] == "personal-vault"
        assert meta["folder_path"] == "research"


def test_api_import_repo_endpoint(auth_client: TestClient):
    """Tests POST /api/import/repo endpoint with mocked repository importer."""
    fake_page = FetchedPage(
        url="repo://github.com/mock/repo",
        title="mock/repo",
        description="Git repository representation: https://github.com/mock/repo (5 files)",
        tags="repo, git, python",
        md_content="# MOCK REPO",
        fetched_at=datetime.now().isoformat(),
        is_frozen=0,
    )

    with patch("kb_web.repo_importer.import_git_repo", return_value=fake_page):
        resp = auth_client.post(
            "/api/import/repo",
            json={
                "repo_url": "https://github.com/mock/repo.git",
                "depth": 1,
                "match": ["*.py"],
                "exclude": ["tests/*"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["url"] == "repo://github.com/mock/repo"
        assert data["title"] == "mock/repo"
        assert "/view/page?url=" in data["view_url"]


def test_api_rag_items_endpoint(auth_client: TestClient):
    """Tests GET /api/rag/items endpoint query and filtering."""
    resp = auth_client.get("/api/rag/items?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    if data["items"]:
        item = data["items"][0]
        assert "id" in item
        assert "source_type" in item
        assert "title" in item
        assert "content_chunk" in item
        assert "url" in item
        assert "metadata" in item
