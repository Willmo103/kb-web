"""add_ollama_cache_and_uploads

Revision ID: f92d84291a25
Revises: e81c74291a24
Create Date: 2026-09-13 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = "f92d84291a25"
down_revision: Union[str, Sequence[str], None] = "e81c74291a24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # 1. Create ollama_chat_cache table
    if "ollama_chat_cache" not in tables:
        op.create_table(
            "ollama_chat_cache",
            sa.Column("prompt_hash", sa.String(length=64), nullable=False),
            sa.Column("model_used", sa.String(), nullable=False),
            sa.Column("settings_applied", sa.Text(), nullable=True),
            sa.Column("raw_prompt", sa.Text(), nullable=False),
            sa.Column("raw_response_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("hit_count", sa.Integer(), server_default="1", nullable=True),
            sa.Column("last_accessed_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("prompt_hash"),
        )
        try:
            op.create_index("idx_ollama_chat_cache_model", "ollama_chat_cache", ["model_used"])
        except Exception as e:
            print(f"[WARN] Failed creating idx_ollama_chat_cache_model: {e}")

    # 2. Create uploaded_documents table
    if "uploaded_documents" not in tables:
        op.create_table(
            "uploaded_documents",
            sa.Column("file_hash", sa.String(length=64), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=True),
            sa.Column("file_path", sa.Text(), nullable=False),
            sa.Column("docling_json_path", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), server_default="uploaded", nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("uploaded_at", sa.String(), nullable=False),
            sa.Column("source_id", sa.String(length=36), sa.ForeignKey("sources.id"), nullable=True),
            sa.PrimaryKeyConstraint("file_hash"),
        )
        try:
            op.create_index("idx_uploaded_documents_status", "uploaded_documents", ["status"])
            op.create_index("idx_uploaded_documents_source_id", "uploaded_documents", ["source_id"])
        except Exception as e:
            print(f"[WARN] Failed creating indexes on uploaded_documents: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    tables = insp.get_table_names()

    if "uploaded_documents" in tables:
        op.drop_table("uploaded_documents")

    if "ollama_chat_cache" in tables:
        op.drop_table("ollama_chat_cache")
