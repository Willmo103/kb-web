"""add_unified_rag_view

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-10-09 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3d4e5f6a7b8c"
down_revision: Union[str, Sequence[str], None] = "2c3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        try:
            conn.execute(sa.text("DROP VIEW IF EXISTS vw_rag_items;"))
            conn.execute(sa.text("""
                CREATE OR REPLACE VIEW vw_rag_items AS
                -- 1. Chunk Embeddings linked with FetchedPages
                SELECT
                    'chunk:page:' || ce.id::text AS id,
                    CASE 
                        WHEN y.video_id IS NOT NULL THEN 'youtube_video'
                        WHEN f.url LIKE 'repo://%' THEN 'repo'
                        WHEN f.url LIKE 'file://%' THEN 'document'
                        ELSE 'web_page'
                    END AS source_type,
                    COALESCE(f.title, ce.source_title, 'Untitled Page') AS title,
                    ce.chunk_content AS content_chunk,
                    f.url AS url,
                    ce.chunk_vector AS embedding,
                    json_build_object(
                        'chunk_number', ce.chunk_number,
                        'model_name', ce.model_name,
                        'tags', f.tags,
                        'collection_id', f.collection_id,
                        'is_frozen', COALESCE(f.is_frozen, 0),
                        'fetched_at', f.fetched_at,
                        'description', f.description,
                        'creator', y.creator,
                        'duration', y.duration
                    )::jsonb AS metadata
                FROM chunk_embeddings ce
                JOIN fetched_pages f ON ce.source_id = f.url
                LEFT JOIN youtube_videos y ON f.url = y.url

                UNION ALL

                -- 2. Chunk Embeddings linked with Notes
                SELECT
                    'chunk:note:' || ce.id::text AS id,
                    'note' AS source_type,
                    n.title AS title,
                    ce.chunk_content AS content_chunk,
                    n.url AS url,
                    ce.chunk_vector AS embedding,
                    json_build_object(
                        'chunk_number', ce.chunk_number,
                        'model_name', ce.model_name,
                        'note_id', n.id,
                        'vault_name', n.vault_name,
                        'folder_path', n.folder_path,
                        'is_frozen', COALESCE(n.is_frozen, 0),
                        'created_at', n.created_at,
                        'updated_at', n.updated_at
                    )::jsonb AS metadata
                FROM chunk_embeddings ce
                JOIN notes n ON ce.source_id = n.url

                UNION ALL

                -- 3. Document-Level Article Embeddings for FetchedPages
                SELECT
                    'article:page:' || f.url AS id,
                    CASE 
                        WHEN y.video_id IS NOT NULL THEN 'youtube_video'
                        WHEN f.url LIKE 'repo://%' THEN 'repo'
                        WHEN f.url LIKE 'file://%' THEN 'document'
                        ELSE 'web_page'
                    END AS source_type,
                    COALESCE(f.title, 'Untitled Page') AS title,
                    COALESCE(f.md_content, f.description, '') AS content_chunk,
                    f.url AS url,
                    ae.embedding AS embedding,
                    json_build_object(
                        'is_document_level', true,
                        'tags', f.tags,
                        'collection_id', f.collection_id,
                        'is_frozen', COALESCE(f.is_frozen, 0),
                        'fetched_at', f.fetched_at,
                        'description', f.description,
                        'creator', y.creator
                    )::jsonb AS metadata
                FROM article_embeddings ae
                JOIN fetched_pages f ON ae.url = f.url
                LEFT JOIN youtube_videos y ON f.url = y.url

                UNION ALL

                -- 4. Workspaces & Workspace Code Files
                SELECT
                    'workspace:file:' || wf.id::text AS id,
                    'workspace' AS source_type,
                    w.name || ' - ' || wf.file_path AS title,
                    wf.content AS content_chunk,
                    'workspace://' || w.id::text || '/' || wf.file_path AS url,
                    NULL::vector AS embedding,
                    json_build_object(
                        'workspace_id', w.id,
                        'workspace_name', w.name,
                        'template', w.template,
                        'file_path', wf.file_path,
                        'language', wf.language,
                        'created_at', w.created_at,
                        'updated_at', w.updated_at
                    )::jsonb AS metadata
                FROM workspace_files wf
                JOIN workspaces w ON wf.workspace_id = w.id;
            """))
        except Exception as e:
            print(f"[WARN] Failed creating PostgreSQL vw_rag_items view: {e}")
    else:
        try:
            conn.execute(sa.text("DROP VIEW IF EXISTS vw_rag_items;"))
            conn.execute(sa.text("""
                CREATE VIEW vw_rag_items AS
                -- 1. Chunk Embeddings linked with FetchedPages
                SELECT
                    'chunk:page:' || CAST(ce.id AS TEXT) AS id,
                    CASE 
                        WHEN y.video_id IS NOT NULL THEN 'youtube_video'
                        WHEN f.url LIKE 'repo://%' THEN 'repo'
                        WHEN f.url LIKE 'file://%' THEN 'document'
                        ELSE 'web_page'
                    END AS source_type,
                    COALESCE(f.title, ce.source_title, 'Untitled Page') AS title,
                    ce.chunk_content AS content_chunk,
                    f.url AS url,
                    ce.chunk_vector AS embedding,
                    json_object(
                        'chunk_number', ce.chunk_number,
                        'model_name', ce.model_name,
                        'tags', f.tags,
                        'collection_id', f.collection_id,
                        'is_frozen', COALESCE(f.is_frozen, 0),
                        'fetched_at', f.fetched_at,
                        'description', f.description,
                        'creator', y.creator,
                        'duration', y.duration
                    ) AS metadata
                FROM chunk_embeddings ce
                JOIN fetched_pages f ON ce.source_id = f.url
                LEFT JOIN youtube_videos y ON f.url = y.url

                UNION ALL

                -- 2. Chunk Embeddings linked with Notes
                SELECT
                    'chunk:note:' || CAST(ce.id AS TEXT) AS id,
                    'note' AS source_type,
                    n.title AS title,
                    ce.chunk_content AS content_chunk,
                    n.url AS url,
                    ce.chunk_vector AS embedding,
                    json_object(
                        'chunk_number', ce.chunk_number,
                        'model_name', ce.model_name,
                        'note_id', n.id,
                        'vault_name', n.vault_name,
                        'folder_path', n.folder_path,
                        'is_frozen', COALESCE(n.is_frozen, 0),
                        'created_at', n.created_at,
                        'updated_at', n.updated_at
                    ) AS metadata
                FROM chunk_embeddings ce
                JOIN notes n ON ce.source_id = n.url

                UNION ALL

                -- 3. Document-Level Article Embeddings for FetchedPages
                SELECT
                    'article:page:' || f.url AS id,
                    CASE 
                        WHEN y.video_id IS NOT NULL THEN 'youtube_video'
                        WHEN f.url LIKE 'repo://%' THEN 'repo'
                        WHEN f.url LIKE 'file://%' THEN 'document'
                        ELSE 'web_page'
                    END AS source_type,
                    COALESCE(f.title, 'Untitled Page') AS title,
                    COALESCE(f.md_content, f.description, '') AS content_chunk,
                    f.url AS url,
                    ae.embedding AS embedding,
                    json_object(
                        'is_document_level', 1,
                        'tags', f.tags,
                        'collection_id', f.collection_id,
                        'is_frozen', COALESCE(f.is_frozen, 0),
                        'fetched_at', f.fetched_at,
                        'description', f.description,
                        'creator', y.creator
                    ) AS metadata
                FROM article_embeddings ae
                JOIN fetched_pages f ON ae.url = f.url
                LEFT JOIN youtube_videos y ON f.url = y.url

                UNION ALL

                -- 4. Workspaces & Workspace Code Files
                SELECT
                    'workspace:file:' || CAST(wf.id AS TEXT) AS id,
                    'workspace' AS source_type,
                    w.name || ' - ' || wf.file_path AS title,
                    wf.content AS content_chunk,
                    'workspace://' || CAST(w.id AS TEXT) || '/' || wf.file_path AS url,
                    NULL AS embedding,
                    json_object(
                        'workspace_id', w.id,
                        'workspace_name', w.name,
                        'template', w.template,
                        'file_path', wf.file_path,
                        'language', wf.language,
                        'created_at', w.created_at,
                        'updated_at', w.updated_at
                    ) AS metadata
                FROM workspace_files wf
                JOIN workspaces w ON wf.workspace_id = w.id;

            """))
        except Exception as e:
            print(f"[WARN] Failed creating SQLite vw_rag_items view: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("DROP VIEW IF EXISTS vw_rag_items;"))
    except Exception as e:
        print(f"[WARN] Failed dropping vw_rag_items view: {e}")
