import json
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Table, Boolean
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


class ProcessorXref(Base):
    __tablename__ = "_processor_xref"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_name = Column(String, nullable=False, unique=True)
    callback_path = Column(String, nullable=False)
    stage = Column(String, nullable=False)  # "pre", "process", "post"
    next_processor_id = Column(Integer, ForeignKey("_processor_xref.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    description = Column(Text, nullable=True)


class Source(Base):
    __tablename__ = "sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    url = Column(Text, nullable=True, index=True)
    file_hash = Column(String, nullable=True, index=True)
    type = Column(String, nullable=False)  # "html", "youtube", "file", "docling"
    processor_id = Column(Integer, ForeignKey("_processor_xref.id"), nullable=True, index=True)
    path = Column(Text, nullable=True)
    status = Column(String, default="pending", index=True)  # "pending", "processing", "completed", "failed"
    retry_count = Column(Integer, default=0)
    error_log = Column(Text, nullable=True)
    timestamp = Column(String, default=lambda: datetime.now().isoformat())
    metadata_json = Column(Text, nullable=True)


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
    source_id = Column(String(36), ForeignKey("sources.id"), nullable=True, index=True)


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
    source_id = Column(String(36), ForeignKey("sources.id"), nullable=True, index=True)


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
    created_at = Column(String)
    source_uuid = Column(String(36), ForeignKey("sources.id"), nullable=True, index=True)


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

    seed_default_processors(engine)


DEFAULT_PROCESSORS = [
    {
        "id": 1,
        "service_name": "fetcher",
        "callback_path": "kb_web.queue_processor:process_fetch",
        "stage": "pre",
        "next_processor_id": 2,
        "is_active": True,
        "description": "Scrapes and cleans raw web HTML into markdown.",
    },
    {
        "id": 2,
        "service_name": "wiki_summary",
        "callback_path": "kb_web.queue_processor:process_summary",
        "stage": "process",
        "next_processor_id": 3,
        "is_active": True,
        "description": "Generates structured wiki markdown summary and key points via LLM.",
    },
    {
        "id": 3,
        "service_name": "tagger",
        "callback_path": "kb_web.queue_processor:process_tags",
        "stage": "process",
        "next_processor_id": 4,
        "is_active": True,
        "description": "Extracts semantic tags and classification labels via LLM.",
    },
    {
        "id": 4,
        "service_name": "embeddings",
        "callback_path": "kb_web.queue_processor:process_embeddings",
        "stage": "post",
        "next_processor_id": None,
        "is_active": True,
        "description": "Generates vector embeddings and chunks for vector search index.",
    },
    {
        "id": 5,
        "service_name": "youtube_metadata",
        "callback_path": "kb_web.queue_processor:process_youtube_metadata",
        "stage": "pre",
        "next_processor_id": 6,
        "is_active": True,
        "description": "Extracts YouTube video metadata and transcripts via yt-dlp.",
    },
    {
        "id": 6,
        "service_name": "youtube_wiki",
        "callback_path": "kb_web.queue_processor:process_youtube_wiki",
        "stage": "process",
        "next_processor_id": 4,
        "is_active": True,
        "description": "Generates structured wiki summary from video transcript.",
    },
    {
        "id": 7,
        "service_name": "docling_parser",
        "callback_path": "kb_web.queue_processor:process_docling_file",
        "stage": "process",
        "next_processor_id": 3,
        "is_active": True,
        "description": "Parses document files (PDF/DOCX/etc.) via Docling into markdown.",
    },
]


def seed_default_processors(engine_or_session):
    """Seeds the _processor_xref table with default pipeline processors if empty or missing."""
    from sqlalchemy.orm import Session
    from sqlalchemy import select

    if isinstance(engine_or_session, Session):
        session = engine_or_session
        should_close = False
    else:
        session = Session(bind=engine_or_session)
        should_close = True

    try:
        # First pass: ensure all rows exist without foreign key references to uninserted rows
        for proc_data in DEFAULT_PROCESSORS:
            existing = session.execute(
                select(ProcessorXref).where(ProcessorXref.service_name == proc_data["service_name"])
            ).scalars().first()
            if not existing:
                proc = ProcessorXref(
                    id=proc_data["id"],
                    service_name=proc_data["service_name"],
                    callback_path=proc_data["callback_path"],
                    stage=proc_data["stage"],
                    next_processor_id=None,
                    is_active=proc_data["is_active"],
                    description=proc_data["description"],
                )
                session.add(proc)
        session.commit()

        # Second pass: wire up next_processor_id
        for proc_data in DEFAULT_PROCESSORS:
            if proc_data.get("next_processor_id"):
                existing = session.execute(
                    select(ProcessorXref).where(ProcessorXref.service_name == proc_data["service_name"])
                ).scalars().first()
                if existing and existing.next_processor_id != proc_data["next_processor_id"]:
                    existing.next_processor_id = proc_data["next_processor_id"]
        session.commit()

        # In PostgreSQL, advance the autoincrement sequence past the max explicit ID
        bind = session.get_bind()
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            from sqlalchemy import text
            try:
                session.execute(text("SELECT setval(pg_get_serial_sequence('_processor_xref', 'id'), COALESCE((SELECT MAX(id) FROM _processor_xref), 1));"))
                session.commit()
            except Exception:
                pass
    except Exception as e:
        session.rollback()
        # Non-fatal if table doesn't exist yet prior to migration
        print(f"Warning seeding default processors: {e}")
    finally:
        if should_close:
            session.close()


