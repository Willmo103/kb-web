"""one_time_taxonomy_purge

Revision ID: 0a9b8c7d6e5f
Revises: f92d84291a25
Create Date: 2026-10-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0a9b8c7d6e5f"
down_revision: Union[str, Sequence[str], None] = "f92d84291a25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # One-time rollback/purge to remove test classification records from production
    try:
        conn.execute(sa.text("DELETE FROM taxonomy_items;"))
        conn.execute(sa.text("DELETE FROM taxonomy_categories;"))
        conn.execute(sa.text("DELETE FROM agent_messages WHERE channel = 'taxonomy';"))
    except Exception as e:
        print(f"[WARN] Failed executing one-time taxonomy purge: {e}")


def downgrade() -> None:
    pass
