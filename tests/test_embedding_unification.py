"""
Unit tests for embedding model unification across indexing, retrieval, and configuration.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from kb_web.server import app
from kb_web.base import db_session, config, COOKIE_NAME, generate_session_token
from kb_web.models_orm import FetchedPage, ChunkEmbedding, ArticleEmbedding, SettingOllama, SettingExternal
from kb_web.utils import (
    get_active_embedding_model,
    generate_gemma_embeddings_for_page,
    find_nearest_chunks,
    update_article_embedding,
)


@pytest.fixture
def auth_client():
    import time
    token = generate_session_token(time.time() + 3600)
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, token)
    return client


def test_get_active_embedding_model_resolution():
    with db_session() as session:
        model = get_active_embedding_model(session=session, config=config)
        assert isinstance(model, str)
        assert len(model) > 0


def test_generate_embeddings_stores_model_name():
    test_url = "https://example.com/test-embedding-unify"
    with db_session() as session:
        session.query(ChunkEmbedding).filter_by(source_id=test_url).delete()
        session.query(ArticleEmbedding).filter_by(url=test_url).delete()
        session.query(FetchedPage).filter_by(url=test_url).delete()
        page = FetchedPage(
            url=test_url,
            title="Test Embedding Unification",
            md_content="This is a test article for vector embedding model unification.",
            description="Test summary for unified embeddings",
            tags='["ai", "test"]',
        )
        session.add(page)
        session.commit()

    try:
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.1] * 768}

        with patch("kb_web.utils.ensure_model_available"):
            generate_gemma_embeddings_for_page(
                db=None,
                url=test_url,
                config=config,
                client=mock_client,
                model="nomic-embed-text",
            )

        with db_session() as session:
            chunks = session.query(ChunkEmbedding).filter_by(source_id=test_url).all()
            assert len(chunks) > 0
            for c in chunks:
                assert c.model_name == "nomic-embed-text"
    finally:
        with db_session() as session:
            session.query(ChunkEmbedding).filter_by(source_id=test_url).delete()
            session.query(ArticleEmbedding).filter_by(url=test_url).delete()
            session.query(FetchedPage).filter_by(url=test_url).delete()
            session.commit()


def test_find_nearest_chunks_strictly_filters_by_model():
    url_a = "https://example.com/test-nomic-chunk"
    url_b = "https://example.com/test-gemma-chunk"

    with db_session() as session:
        session.query(ChunkEmbedding).filter(ChunkEmbedding.source_id.in_([url_a, url_b])).delete(synchronize_session=False)
        session.add(
            ChunkEmbedding(
                source_type="articles",
                source_id=url_a,
                source_title="Nomic Doc",
                chunk_number=0,
                chunk_content="Content indexed with Nomic",
                chunk_vector=[0.1] * 768,
                model_name="nomic-embed-text",
            )
        )
        session.add(
            ChunkEmbedding(
                source_type="articles",
                source_id=url_b,
                source_title="Gemma Doc",
                chunk_number=0,
                chunk_content="Content indexed with Gemma",
                chunk_vector=[0.2] * 768,
                model_name="embeddinggemma",
            )
        )
        session.commit()

    try:
        mock_client = MagicMock()
        mock_client.embeddings.return_value = {"embedding": [0.1] * 768}

        # Query with nomic-embed-text
        results_nomic = find_nearest_chunks(
            query="Content indexed",
            model="nomic-embed-text",
            client=mock_client,
        )
        assert any(r["source_id"] == url_a for r in results_nomic)
        # Gemma doc MUST NOT be included when querying nomic model
        assert not any(r["source_id"] == url_b for r in results_nomic)
    finally:
        with db_session() as session:
            session.query(ChunkEmbedding).filter(ChunkEmbedding.source_id.in_([url_a, url_b])).delete(synchronize_session=False)
            session.commit()


def test_api_active_model_sync(auth_client):
    resp = auth_client.post("/api/embeddings/active-model", json={"model": "nomic-embed-text"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["active_model"] == "nomic-embed-text"

    # Verify GET reflects update
    get_resp = auth_client.get("/api/embeddings/active-model")
    assert get_resp.status_code == 200
    assert get_resp.json()["active_model"] == "nomic-embed-text"

    # Verify config property was synchronized
    assert config.ollama_embedding_model == "nomic-embed-text"


def test_cli_reindex_embeddings_help():
    from typer.testing import CliRunner
    from kb_web.cli import app as cli_app

    runner = CliRunner()
    result = runner.invoke(cli_app, ["reindex-embeddings", "--help"])
    assert result.exit_code == 0
    assert "Reindexes chunk embeddings" in result.output
