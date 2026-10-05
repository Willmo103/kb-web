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
    # Taxonomy purge neutralized to prevent wiping user taxonomy collections across environments.
    pass


def downgrade() -> None:
    pass
