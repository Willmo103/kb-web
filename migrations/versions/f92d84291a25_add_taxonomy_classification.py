"""add_taxonomy_classification

Revision ID: f92d84291a25
Revises: e81c74291a23
Create Date: 2026-10-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f92d84291a25"
down_revision: Union[str, Sequence[str], None] = "e81c74291a23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # 1. Create taxonomy_categories table
    try:
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS taxonomy_categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR NOT NULL,
                slug VARCHAR UNIQUE,
                parent_id INTEGER REFERENCES taxonomy_categories(id),
                doc TEXT,
                item_count INTEGER DEFAULT 0,
                depth INTEGER DEFAULT 0,
                is_container INTEGER DEFAULT 0,
                created_at VARCHAR,
                updated_at VARCHAR
            );
        """ if dialect == "postgresql" else """
            CREATE TABLE IF NOT EXISTS taxonomy_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT UNIQUE,
                parent_id INTEGER REFERENCES taxonomy_categories(id),
                doc TEXT,
                item_count INTEGER DEFAULT 0,
                depth INTEGER DEFAULT 0,
                is_container INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
        """))
    except Exception as e:
        print(f"[WARN] Failed creating taxonomy_categories table: {e}")

    # 2. Create taxonomy_items table
    try:
        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS taxonomy_items (
                id SERIAL PRIMARY KEY,
                category_id INTEGER REFERENCES taxonomy_categories(id),
                item_type VARCHAR,
                item_id VARCHAR,
                item_title VARCHAR,
                fit_score FLOAT DEFAULT 1.0,
                assigned_at VARCHAR,
                item_class VARCHAR(32) DEFAULT 'Notes'
            );
        """ if dialect == "postgresql" else """
            CREATE TABLE IF NOT EXISTS taxonomy_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER REFERENCES taxonomy_categories(id),
                item_type TEXT,
                item_id TEXT,
                item_title TEXT,
                fit_score REAL DEFAULT 1.0,
                assigned_at TEXT,
                item_class TEXT DEFAULT 'Notes'
            );
        """))
    except Exception as e:
        print(f"[WARN] Failed creating taxonomy_items table: {e}")

    # Ensure item_class column exists if taxonomy_items was created without it
    try:
        conn.execute(sa.text("ALTER TABLE taxonomy_items ADD COLUMN IF NOT EXISTS item_class VARCHAR(32) DEFAULT 'Notes';")
                     if dialect == "postgresql" else
                     sa.text("ALTER TABLE taxonomy_items ADD COLUMN item_class TEXT DEFAULT 'Notes';"))
    except Exception:
        pass

    # 3. Create indexes
    for idx_sql in [
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_categories_slug ON taxonomy_categories (slug);",
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_items_cat_id ON taxonomy_items (category_id);",
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_items_item_id ON taxonomy_items (item_id);",
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_items_item_class ON taxonomy_items (item_class);",
    ]:
        try:
            conn.execute(sa.text(idx_sql))
        except Exception as e:
            print(f"[WARN] Failed creating index: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    # Drop tables to cleanly remove all classification records and schema
    try:
        conn.execute(sa.text("DROP TABLE IF EXISTS taxonomy_items CASCADE;"))
    except Exception as e:
        print(f"[WARN] Failed dropping taxonomy_items table: {e}")

    try:
        conn.execute(sa.text("DROP TABLE IF EXISTS taxonomy_categories CASCADE;"))
    except Exception as e:
        print(f"[WARN] Failed dropping taxonomy_categories table: {e}")

    # Purge taxonomy messages from agent_messages
    try:
        conn.execute(sa.text("DELETE FROM agent_messages WHERE channel = 'taxonomy';"))
    except Exception as e:
        print(f"[WARN] Failed cleaning taxonomy agent messages: {e}")
