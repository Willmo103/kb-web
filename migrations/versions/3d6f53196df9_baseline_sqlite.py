"""baseline_sqlite

Revision ID: 3d6f53196df9
Revises: 
Create Date: 2026-08-13 00:32:25.552472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d6f53196df9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import os
    
    current_dir = os.path.dirname(__file__)
    sql_file = os.path.abspath(os.path.join(current_dir, "..", "baseline_sqlite.sql"))
    
    if not os.path.exists(sql_file):
        raise FileNotFoundError(f"Baseline SQL script not found at {sql_file}")
        
    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()
        
    statements = sql_content.split(";")
    conn = op.get_bind()
    for stmt in statements:
        stmt_clean = stmt.strip()
        if stmt_clean:
            conn.execute(sa.text(stmt_clean))


def downgrade() -> None:
    conn = op.get_bind()
    
    # Drop views first
    views = ["root_items", "valid_vault_files", "valid_repo_files", "repo_master", "vault_master"]
    for view in views:
        conn.execute(sa.text(f"DROP VIEW IF EXISTS {view};"))
        
    # Drop tables
    tables = [
        "links", "registered_clients", "cli_api_keys", "settings_external", "settings_ollama",
        "system_logs", "title_embeddings", "ollama_logs", "collection_notes", "collection_actions",
        "video_embeddings", "chunk_embeddings", "collection_items", "collections", "youtube_videos",
        "site_wikis", "article_embeddings", "page_versions", "fetched_pages", "rss_sources", "ollama_models",
        "documentation_links", "server_links", "rtsp_streams", "browser_pages", "browsing_history",
        "browser_bookmarks", "roots", "root_files", "root_images"
    ]
    for table in tables:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {table};"))
