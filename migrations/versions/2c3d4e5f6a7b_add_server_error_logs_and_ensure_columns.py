"""add_server_error_logs_and_ensure_columns

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-10-05 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2c3d4e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "1b2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # 1. Ensure item_class column exists on taxonomy_items across all database backends
    try:
        if dialect == "postgresql":
            conn.execute(sa.text("ALTER TABLE taxonomy_items ADD COLUMN IF NOT EXISTS item_class VARCHAR(32) DEFAULT 'Notes';"))
        else:
            cols = [r[1] for r in conn.execute(sa.text("PRAGMA table_info(taxonomy_items);")).fetchall()]
            if cols and "item_class" not in cols:
                conn.execute(sa.text("ALTER TABLE taxonomy_items ADD COLUMN item_class TEXT DEFAULT 'Notes';"))
    except Exception as e:
        print(f"[WARN] Failed ensuring item_class column in migration 2c3d4e5f6a7b: {e}")

    # 2. Ensure is_frozen columns exist on content tables
    for tbl in ["fetched_pages", "notes", "youtube_videos"]:
        try:
            if dialect == "postgresql":
                conn.execute(sa.text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS is_frozen INTEGER DEFAULT 0;"))
            else:
                cols = [r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({tbl});")).fetchall()]
                if cols and "is_frozen" not in cols:
                    conn.execute(sa.text(f"ALTER TABLE {tbl} ADD COLUMN is_frozen INTEGER DEFAULT 0;"))
        except Exception as e:
            print(f"[WARN] Failed ensuring is_frozen on {tbl}: {e}")

    # 3. Create server_error_logs table and indexes
    try:
        if dialect == "postgresql":
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS server_error_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp VARCHAR,
                    error_type VARCHAR,
                    error_message TEXT,
                    stack_trace TEXT,
                    request_method VARCHAR,
                    request_url TEXT,
                    query_params TEXT,
                    client_ip VARCHAR,
                    agent_feedback TEXT,
                    status VARCHAR DEFAULT 'open'
                );
                CREATE INDEX IF NOT EXISTS idx_server_error_logs_timestamp ON server_error_logs (timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_server_error_logs_type ON server_error_logs (error_type);
                CREATE INDEX IF NOT EXISTS idx_server_error_logs_status ON server_error_logs (status);
            """))
        else:
            conn.execute(sa.text("""
                CREATE TABLE IF NOT EXISTS server_error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    stack_trace TEXT,
                    request_method TEXT,
                    request_url TEXT,
                    query_params TEXT,
                    client_ip TEXT,
                    agent_feedback TEXT,
                    status TEXT DEFAULT 'open'
                );
                CREATE INDEX IF NOT EXISTS idx_server_error_logs_timestamp ON server_error_logs (timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_server_error_logs_type ON server_error_logs (error_type);
                CREATE INDEX IF NOT EXISTS idx_server_error_logs_status ON server_error_logs (status);
            """))
    except Exception as e:
        print(f"[WARN] Failed creating server_error_logs table: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("DROP TABLE IF EXISTS server_error_logs CASCADE;"))
    except Exception as e:
        print(f"[WARN] Failed dropping server_error_logs table: {e}")
