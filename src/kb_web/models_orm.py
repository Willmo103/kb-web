import json
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator

Base = declarative_base()


class SafeVector(TypeDecorator):
    """Custom SQLAlchemy TypeDecorator for vector columns.

    Compiles to pgvector.sqlalchemy.Vector on PostgreSQL, and json-encoded
    sqlite TEXT fallback on SQLite.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dim=None):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect and getattr(dialect, "name", None) == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(self.dim) if self.dim else Vector())
            except ImportError:
                pass
        return dialect.type_descriptor(Text) if dialect else Text

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect and getattr(dialect, "name", None) == "postgresql":
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return value
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect and getattr(dialect, "name", None) == "postgresql":
            # pgvector returns it as array/list of float
            return list(value) if not isinstance(value, list) else value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, str):
                    parsed = json.loads(parsed)
                return parsed
            except Exception:
                pass
        return value

    class comparator_factory(TypeDecorator.Comparator):
        def cosine_distance(self, other):
            from pgvector.sqlalchemy import Vector
            return Vector.comparator_factory(self.expr).cosine_distance(other)

        def l2_distance(self, other):
            from pgvector.sqlalchemy import Vector
            return Vector.comparator_factory(self.expr).l2_distance(other)

        def max_inner_product(self, other):
            from pgvector.sqlalchemy import Vector
            return Vector.comparator_factory(self.expr).max_inner_product(other)


class FetchedPage(Base):
    __tablename__ = "fetched_pages"

    url = Column(String, primary_key=True)
    title = Column(String)
    html_content = Column(Text)
    md_content = Column(Text)
    links = Column(Text)  # JSON-encoded array of URLs
    html_content_hash = Column(String)
    md_content_hash = Column(String)
    fetched_at = Column(String, index=True)
    description = Column(Text)
    keywords = Column(Text)  # JSON-encoded array of strings
    tags = Column(Text)  # JSON-encoded array of tags/labels
    collection_id = Column(Integer)
    exclude_from_general = Column(Integer, default=0)


class PageVersion(Base):
    __tablename__ = "page_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String)
    title = Column(String)
    html_content = Column(Text)
    md_content = Column(Text)
    links = Column(Text)
    html_content_hash = Column(String)
    md_content_hash = Column(String)
    fetched_at = Column(String)
    description = Column(Text)
    keywords = Column(Text)
    tags = Column(Text)


class ArticleEmbedding(Base):
    __tablename__ = "article_embeddings"

    url = Column(String, ForeignKey("fetched_pages.url"), primary_key=True)
    embedding = Column(SafeVector())
    updated_at = Column(String)


class TitleEmbedding(Base):
    __tablename__ = "title_embeddings"

    url = Column(String, ForeignKey("fetched_pages.url"), primary_key=True)
    embedding = Column(SafeVector())
    updated_at = Column(String)


class SiteWiki(Base):
    __tablename__ = "site_wikis"

    site = Column(String, primary_key=True)
    wiki_content = Column(Text)
    updated_at = Column(String)


class YouTubeVideo(Base):
    __tablename__ = "youtube_videos"

    url = Column(String, ForeignKey("fetched_pages.url"), primary_key=True)
    video_id = Column(String)
    creator = Column(String, index=True)
    channel_id = Column(String)
    duration = Column(Integer)
    view_count = Column(Integer)
    thumbnail_url = Column(String)
    local_path = Column(String)
    updated_at = Column(String)


class Collection(Base):
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String)
    visibility = Column(String)  # "public" or "private"
    rag_system_prompt = Column(Text)
    taxonomy_system_prompt = Column(Text)
    general_system_context = Column(Text)  # JSON string
    created_at = Column(String)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, ForeignKey("collections.id"))
    source_type = Column(String)  # "articles" or "videos"
    source_id = Column(String, index=True)  # URL
    item_note = Column(Text)
    taxonomy_path = Column(String)
    item_order = Column(Integer)
    added_at = Column(String)


class CollectionNote(Base):
    __tablename__ = "collection_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, ForeignKey("collections.id"))
    title = Column(String)
    content = Column(Text)
    taxonomy_path = Column(String)
    created_at = Column(String)
    updated_at = Column(String)


class CollectionAction(Base):
    __tablename__ = "collection_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, ForeignKey("collections.id"))
    action_type = Column(String)
    source_type = Column(String)
    source_id = Column(String)
    note = Column(Text)
    created_at = Column(String)


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String)
    source_id = Column(String)
    source_title = Column(String)
    chunk_number = Column(Integer)
    chunk_content = Column(Text)
    chunk_vector = Column(SafeVector())
    model_name = Column(String, default="embeddinggemma")
    created_at = Column(String)



class VideoEmbedding(Base):
    __tablename__ = "video_embeddings"

    url = Column(String, ForeignKey("fetched_pages.url"), primary_key=True)
    embedding = Column(SafeVector())
    updated_at = Column(String)


class OllamaLog(Base):
    __tablename__ = "ollama_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String)
    model = Column(String)
    prompt_type = Column(String)
    messages = Column(Text)
    options = Column(Text)
    response = Column(Text)
    duration = Column(Float)
    status = Column(String)


class SettingOllama(Base):
    __tablename__ = "settings_ollama"

    key = Column(String, primary_key=True)
    value = Column(String)


class SettingExternal(Base):
    __tablename__ = "settings_external"

    key = Column(String, primary_key=True)
    value = Column(String)


class AgentPrompt(Base):
    __tablename__ = "agent_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_type = Column(String)
    prompt_text = Column(Text)
    is_head = Column(Integer)
    created_at = Column(String)
    version = Column(Integer)


class CliApiKey(Base):
    __tablename__ = "cli_api_keys"

    key = Column(String, primary_key=True)
    name = Column(String)
    created_at = Column(String)


class RegisteredClient(Base):
    __tablename__ = "registered_clients"

    computer_name = Column(String, primary_key=True)
    api_key = Column(String)
    registered_at = Column(String)
    status = Column(String)


class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String)
    title = Column(String)
    description = Column(Text)
    click_count = Column(Integer, default=0)
    created_at = Column(String)
    last_clicked_at = Column(String)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String)
    level = Column(String)
    module = Column(String)
    message = Column(Text)
    traceback = Column(Text)


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, unique=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    syntax = Column(String, default="markdown")
    folder_path = Column(String, default="")
    vault_name = Column(String, default="Personal")
    tags = Column(Text)  # JSON-encoded array
    wiki_summary = Column(Text)
    created_at = Column(String)
    updated_at = Column(String)


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String)
    source_type = Column(String, default="article")  # "article", "video", "note", "general"
    source_id = Column(String, index=True)
    created_at = Column(String)
    updated_at = Column(String)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True)
    role = Column(String)  # "user", "assistant", "system"
    content = Column(Text)
    timestamp = Column(String)
    model = Column(String)


class SavedReportView(Base):
    __tablename__ = "saved_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)
    description = Column(Text)
    base_table = Column(String)
    selected_columns = Column(Text)  # JSON array
    joins_config = Column(Text)  # JSON array
    sort_config = Column(Text)  # JSON object
    filter_config = Column(Text)  # JSON array
    group_config = Column(Text)  # JSON array
    created_at = Column(String)
    updated_at = Column(String)


class ScheduledReportJob(Base):
    __tablename__ = "scheduled_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("saved_reports.id", ondelete="CASCADE"))
    cron_expression = Column(String)
    export_format = Column(String, default="xlsx")
    destination = Column(String, default="local")
    last_run_at = Column(String)
    next_run_at = Column(String)
    enabled = Column(Integer, default=1)
    created_at = Column(String)


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    template = Column(String, default="web-game")  # "web-game", "python-demo", "blank"
    created_at = Column(String)
    updated_at = Column(String)

    files = relationship("WorkspaceFile", back_populates="workspace", cascade="all, delete-orphan", lazy="joined")


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String, nullable=False)
    content = Column(Text, default="")
    language = Column(String, default="plaintext")
    updated_at = Column(String)

    workspace = relationship("Workspace", back_populates="files")


metadata = Base.metadata


vault_master = Table(
    "vault_master",
    metadata,
    Column("vault_name", String),
    Column("vp_uuid", String),
    Column("vfc_uuid", String),
    Column("vf_uuid", String),
    Column("relative_path", String),
    Column("created", String),
    Column("modified", String),
    Column("file_name", String),
    Column("extension", String),
    Column("size", Integer),
    Column("content_hash", String),
    Column("content", Text),
    Column("version", Integer),
    Column("description", Text),
)

repo_master = Table(
    "repo_master",
    metadata,
    Column("repo_name", String),
    Column("rp_uuid", String),
    Column("rfc_uuid", String),
    Column("rf_uuid", String),
    Column("relative_path", String),
    Column("created", String),
    Column("modified", String),
    Column("file_name", String),
    Column("extension", String),
    Column("size", Integer),
    Column("content_hash", String),
    Column("content", Text),
    Column("version", Integer),
    Column("description", Text),
)

valid_repo_files = Table(
    "valid_repo_files",
    metadata,
    Column("file_path", String),
    Column("repo_path", String),
)


class PageCardView(Base):
    """Declarative model mapped to the vw_page_cards pre-processed view.

    Excludes heavy html_content and md_content fields, and pre-aggregates
    collections to prevent N+1 queries.
    """
    __tablename__ = "vw_page_cards"
    __table_args__ = {"info": dict(is_view=True)}

    url = Column(String, primary_key=True)
    title = Column(String)
    description = Column(Text)
    tags = Column(Text)
    fetched_at = Column(String)
    collection_id = Column(Integer)
    exclude_from_general = Column(Integer, default=0)
    creator = Column(String)
    video_id = Column(String)
    duration = Column(Integer)
    view_count = Column(Integer)
    thumbnail_url = Column(String)
    collection_title = Column(String)
    collection_first_id = Column(Integer)


# Remove PageCardView from Base.metadata tables to avoid CREATE TABLE vw_page_cards during Base.metadata.create_all
if PageCardView.__table__ in Base.metadata.tables.values():
    Base.metadata.remove(PageCardView.__table__)


def ensure_views_and_indexes(engine):
    """Ensures that the vw_page_cards view and performance indexes exist on the target database."""
    from sqlalchemy import text
    dialect = getattr(engine.dialect, "name", "sqlite")
    with engine.connect() as conn:
        with conn.begin():
            try:
                Base.metadata.create_all(bind=conn)
            except Exception:
                pass

            try:
                if dialect == "postgresql":
                    conn.execute(text("ALTER TABLE chunk_embeddings ADD COLUMN IF NOT EXISTS model_name VARCHAR DEFAULT 'embeddinggemma';"))
                else:
                    conn.execute(text("ALTER TABLE chunk_embeddings ADD COLUMN model_name TEXT DEFAULT 'embeddinggemma';"))
            except Exception:
                pass

            if dialect == "postgresql":
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fetched_pages_fetched_at ON fetched_pages (fetched_at DESC);"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collection_items_source_id ON collection_items (source_id);"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collection_items_col_source ON collection_items (collection_id, source_id);"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_youtube_videos_creator ON youtube_videos (creator);"))
                except Exception as e:
                    print(f"Warning creating PostgreSQL indexes: {e}")

                try:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'vw_page_cards') THEN
                                EXECUTE 'DROP TABLE vw_page_cards CASCADE';
                            ELSIF EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'vw_page_cards') THEN
                                EXECUTE 'DROP VIEW vw_page_cards CASCADE';
                            END IF;
                        END $$;
                    """))

                    # Clean up any orphaned ghost stubs generated during previous SQLite migrations
                    ghost_urls = conn.execute(text("""
                        SELECT url FROM fetched_pages 
                        WHERE title LIKE 'Archived Item (%%' 
                          AND (html_content IS NULL OR html_content = '')
                          AND (md_content IS NULL OR md_content = '')
                    """)).fetchall()
                    for (g_url,) in ghost_urls:
                        conn.execute(text("DELETE FROM article_embeddings WHERE url = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM title_embeddings WHERE url = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM video_embeddings WHERE url = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM chunk_embeddings WHERE source_id = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM youtube_videos WHERE url = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM collection_items WHERE source_id = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM collection_actions WHERE source_id = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM page_versions WHERE url = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM links WHERE url = :u"), {"u": g_url})
                        conn.execute(text("DELETE FROM fetched_pages WHERE url = :u"), {"u": g_url})

                    conn.execute(text("""
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
                            string_agg(c.title, ', ') AS collection_title,
                            MIN(c.id) AS collection_first_id
                        FROM fetched_pages f
                        LEFT JOIN youtube_videos y ON f.url = y.url
                        LEFT JOIN collection_items ci ON f.url = ci.source_id AND ci.collection_id != 1
                        LEFT JOIN collections c ON ci.collection_id = c.id
                        WHERE (f.title NOT LIKE 'Archived Item (%%' OR (f.html_content IS NOT NULL AND f.html_content != '') OR (f.md_content IS NOT NULL AND f.md_content != '') OR (y.video_id IS NOT NULL))
                        GROUP BY f.url, f.title, f.description, f.tags, f.fetched_at, f.collection_id, f.exclude_from_general,
                                 y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url;
                    """))
                except Exception as e:
                    print(f"Warning creating PostgreSQL view: {e}")
            else:
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fetched_pages_fetched_at ON fetched_pages (fetched_at DESC);"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_collection_items_source_id ON collection_items (source_id);"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_youtube_videos_creator ON youtube_videos (creator);"))
                except Exception:
                    pass
                try:
                    conn.execute(text("DROP TABLE IF EXISTS vw_page_cards;"))
                    conn.execute(text("DROP VIEW IF EXISTS vw_page_cards;"))
                    conn.execute(text("""
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
                        WHERE (f.title NOT LIKE 'Archived Item (%%' OR (f.html_content IS NOT NULL AND f.html_content != '') OR (f.md_content IS NOT NULL AND f.md_content != '') OR (y.video_id IS NOT NULL))
                        GROUP BY f.url, f.title, f.description, f.tags, f.fetched_at, f.collection_id, f.exclude_from_general,
                                 y.creator, y.video_id, y.duration, y.view_count, y.thumbnail_url;
                    """))
                except Exception:
                    pass

