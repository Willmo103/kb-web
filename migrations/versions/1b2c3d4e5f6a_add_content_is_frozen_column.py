"""add_content_is_frozen_column

Revision ID: 1b2c3d4e5f6a
Revises: 0a9b8c7d6e5f
Create Date: 2026-10-05 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b2c3d4e5f6a"
down_revision: Union[str, Sequence[str], None] = "0a9b8c7d6e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # Add is_frozen column to fetched_pages, notes, and youtube_videos
    for table_name in ["fetched_pages", "notes", "youtube_videos"]:
        try:
            if dialect == "postgresql":
                conn.execute(sa.text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS is_frozen INTEGER DEFAULT 0;"))
                conn.execute(sa.text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_is_frozen ON {table_name} (is_frozen);"))
            else:
                cols = [row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table_name});")).fetchall()]
                if "is_frozen" not in cols:
                    conn.execute(sa.text(f"ALTER TABLE {table_name} ADD COLUMN is_frozen INTEGER DEFAULT 0;"))
                conn.execute(sa.text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_is_frozen ON {table_name} (is_frozen);"))
        except Exception as e:
            print(f"[WARN] Failed adding is_frozen column to {table_name}: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    for table_name in ["fetched_pages", "notes", "youtube_videos"]:
        try:
            if dialect == "postgresql":
                conn.execute(sa.text(f"DROP INDEX IF EXISTS idx_{table_name}_is_frozen;"))
                conn.execute(sa.text(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS is_frozen;"))
            else:
                conn.execute(sa.text(f"DROP INDEX IF EXISTS idx_{table_name}_is_frozen;"))
        except Exception as e:
            print(f"[WARN] Failed downgrading is_frozen column on {table_name}: {e}")
