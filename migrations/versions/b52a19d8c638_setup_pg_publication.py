"""setup_pg_publication

Revision ID: b52a19d8c638
Revises: a19d8c63896e
Create Date: 2026-09-08 02:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b52a19d8c638"
down_revision: Union[str, Sequence[str], None] = "a19d8c63896e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        # Check if publication already exists before creating
        res = conn.execute(
            sa.text("SELECT 1 FROM pg_publication WHERE pubname = 'kb_live_pub';")
        ).first()
        if not res:
            try:
                conn.execute(sa.text("CREATE PUBLICATION kb_live_pub FOR ALL TABLES;"))
                print("[INFO] Created PostgreSQL logical publication 'kb_live_pub'.")
            except Exception as e:
                print(f"[WARN] Could not create publication 'kb_live_pub' (requires superuser or REPLICATION privilege): {e}")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        try:
            conn.execute(sa.text("DROP PUBLICATION IF EXISTS kb_live_pub;"))
        except Exception as e:
            print(f"[WARN] Failed to drop publication: {e}")
