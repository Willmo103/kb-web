"""add_sources_and_processor_xref

Revision ID: e81c74291a24
Revises: e81c74291a23
Create Date: 2026-09-13 23:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = "e81c74291a24"
down_revision: Union[str, Sequence[str], None] = "e81c74291a23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    insp = reflection.Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # 1. Create _processor_xref table if not exists
    if "_processor_xref" not in tables:
        op.create_table(
            "_processor_xref",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("service_name", sa.String(), nullable=False),
            sa.Column("callback_path", sa.String(), nullable=False),
            sa.Column("stage", sa.String(), nullable=False),
            sa.Column("next_processor_id", sa.Integer(), sa.ForeignKey("_processor_xref.id"), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default="true" if dialect == "postgresql" else "1", nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("service_name"),
        )

    # 2. Create sources table if not exists
    if "sources" not in tables:
        op.create_table(
            "sources",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("file_hash", sa.String(), nullable=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("processor_id", sa.Integer(), sa.ForeignKey("_processor_xref.id"), nullable=True),
            sa.Column("path", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), server_default="pending", nullable=True),
            sa.Column("retry_count", sa.Integer(), server_default="0", nullable=True),
            sa.Column("error_log", sa.Text(), nullable=True),
            sa.Column("timestamp", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        try:
            op.create_index("idx_sources_url", "sources", ["url"])
            op.create_index("idx_sources_file_hash", "sources", ["file_hash"])
            op.create_index("idx_sources_processor_id", "sources", ["processor_id"])
            op.create_index("idx_sources_status", "sources", ["status"])
        except Exception as e:
            print(f"[WARN] Failed creating sources indexes: {e}")

    # 3. Add source_id to fetched_pages if not present
    if "fetched_pages" in tables:
        fetched_pages_cols = [c["name"] for c in insp.get_columns("fetched_pages")]
        if "source_id" not in fetched_pages_cols:
            op.add_column("fetched_pages", sa.Column("source_id", sa.String(length=36), nullable=True))
            try:
                op.create_index("idx_fetched_pages_source_id", "fetched_pages", ["source_id"])
            except Exception as e:
                print(f"[WARN] Failed creating index idx_fetched_pages_source_id: {e}")

    # 4. Add source_id to youtube_videos if not present
    if "youtube_videos" in tables:
        yt_cols = [c["name"] for c in insp.get_columns("youtube_videos")]
        if "source_id" not in yt_cols:
            op.add_column("youtube_videos", sa.Column("source_id", sa.String(length=36), nullable=True))
            try:
                op.create_index("idx_youtube_videos_source_id", "youtube_videos", ["source_id"])
            except Exception as e:
                print(f"[WARN] Failed creating index idx_youtube_videos_source_id: {e}")

    # 5. Add source_uuid to chunk_embeddings if not present
    if "chunk_embeddings" in tables:
        chunk_cols = [c["name"] for c in insp.get_columns("chunk_embeddings")]
        if "source_uuid" not in chunk_cols:
            op.add_column("chunk_embeddings", sa.Column("source_uuid", sa.String(length=36), nullable=True))
            try:
                op.create_index("idx_chunk_embeddings_source_uuid", "chunk_embeddings", ["source_uuid"])
            except Exception as e:
                print(f"[WARN] Failed creating index idx_chunk_embeddings_source_uuid: {e}")

    # 6. Seed default processors
    from kb_web.models_orm import seed_default_processors
    try:
        seed_default_processors(conn)
    except Exception as e:
        print(f"[WARN] Failed seeding default processors during migration: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    tables = insp.get_table_names()

    if "chunk_embeddings" in tables:
        chunk_cols = [c["name"] for c in insp.get_columns("chunk_embeddings")]
        if "source_uuid" in chunk_cols:
            try:
                op.drop_index("idx_chunk_embeddings_source_uuid", table_name="chunk_embeddings")
            except Exception:
                pass
            op.drop_column("chunk_embeddings", "source_uuid")

    if "youtube_videos" in tables:
        yt_cols = [c["name"] for c in insp.get_columns("youtube_videos")]
        if "source_id" in yt_cols:
            try:
                op.drop_index("idx_youtube_videos_source_id", table_name="youtube_videos")
            except Exception:
                pass
            op.drop_column("youtube_videos", "source_id")

    if "fetched_pages" in tables:
        fp_cols = [c["name"] for c in insp.get_columns("fetched_pages")]
        if "source_id" in fp_cols:
            try:
                op.drop_index("idx_fetched_pages_source_id", table_name="fetched_pages")
            except Exception:
                pass
            op.drop_column("fetched_pages", "source_id")

    if "sources" in tables:
        op.drop_table("sources")

    if "_processor_xref" in tables:
        op.drop_table("_processor_xref")
