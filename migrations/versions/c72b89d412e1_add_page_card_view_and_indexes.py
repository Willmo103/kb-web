"""add_page_card_view_and_indexes

Revision ID: c72b89d412e1
Revises: b52a19d8c638
Create Date: 2026-09-12 18:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c72b89d412e1"
down_revision: Union[str, Sequence[str], None] = "b52a19d8c638"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        # Indexes for query performance and sorting
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_fetched_pages_fetched_at ON fetched_pages (fetched_at DESC);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_collection_items_source_id ON collection_items (source_id);"))
        conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_youtube_videos_creator ON youtube_videos (creator);"))

        # PostgreSQL optimized view using string_agg to eliminate N+1 collection queries
        conn.execute(sa.text("""
            CREATE OR REPLACE VIEW vw_page_cards AS
            SELECT 
                f.url,
                f.title,
                f.description,
                f.tags,
                f.fetched_at,
                f.collection_id,
                f.exclude_from_general,
                y.creator,
                y.video_id,
                y.duration,
                y.view_count,
                y.thumbnail_url,
                string_agg(c.title, ', ') AS collection_title,
                MIN(c.id) AS collection_first_id
            FROM fetched_pages f
            LEFT JOIN youtube_videos y ON f.url = y.url
            LEFT JOIN collection_items ci ON f.url = ci.source_id AND ci.collection_id != 1
            LEFT JOIN collections c ON ci.collection_id = c.id
            GROUP BY f.url, f.title, f.description, f.tags, f.fetched_at, f.collection_id, f.exclude_from_general,
                     y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url;
        """))
        print("[INFO] Created PostgreSQL indexes and view 'vw_page_cards'.")
    else:
        # SQLite fallback
        try:
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_fetched_pages_fetched_at ON fetched_pages (fetched_at DESC);"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_collection_items_source_id ON collection_items (source_id);"))
            conn.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_youtube_videos_creator ON youtube_videos (creator);"))
        except Exception as e:
            print(f"[WARN] Failed creating SQLite indexes: {e}")

        try:
            conn.execute(sa.text("DROP VIEW IF EXISTS vw_page_cards;"))
            conn.execute(sa.text("""
                CREATE VIEW vw_page_cards AS
                SELECT 
                    f.url,
                    f.title,
                    f.description,
                    f.tags,
                    f.fetched_at,
                    f.collection_id,
                    f.exclude_from_general,
                    y.creator,
                    y.video_id,
                    y.duration,
                    y.view_count,
                    y.thumbnail_url,
                    group_concat(c.title, ', ') AS collection_title,
                    MIN(c.id) AS collection_first_id
                FROM fetched_pages f
                LEFT JOIN youtube_videos y ON f.url = y.url
                LEFT JOIN collection_items ci ON f.url = ci.source_id AND ci.collection_id != 1
                LEFT JOIN collections c ON ci.collection_id = c.id
                GROUP BY f.url, f.title, f.description, f.tags, f.fetched_at, f.collection_id, f.exclude_from_general,
                         y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url;
            """))
            print("[INFO] Created SQLite fallback view 'vw_page_cards'.")
        except Exception as e:
            print(f"[WARN] Failed creating SQLite view: {e}")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP VIEW IF EXISTS vw_page_cards;"))
    try:
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_fetched_pages_fetched_at;"))
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_collection_items_source_id;"))
        conn.execute(sa.text("DROP INDEX IF EXISTS idx_youtube_videos_creator;"))
    except Exception as e:
        print(f"[WARN] Failed dropping indexes in downgrade: {e}")
