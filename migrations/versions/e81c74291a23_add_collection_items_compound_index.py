"""add_collection_items_compound_index

Revision ID: e81c74291a23
Revises: c72b89d412e1
Create Date: 2026-09-13 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e81c74291a23"
down_revision: Union[str, Sequence[str], None] = "c72b89d412e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        try:
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_collection_items_col_source ON collection_items (collection_id, source_id);"))
        except Exception as e:
            print(f"[WARN] Failed creating compound index on collection_items: {e}")
    else:
        try:
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_collection_items_col_source ON collection_items (collection_id, source_id);"))
        except Exception as e:
            print(f"[WARN] Failed creating SQLite index: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_collection_items_col_source;"))
    except Exception as e:
        print(f"[WARN] Failed dropping compound index on collection_items: {e}")
