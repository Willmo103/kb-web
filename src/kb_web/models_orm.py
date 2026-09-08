import json
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Table
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
    fetched_at = Column(String)
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
    creator = Column(String)
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
    source_id = Column(String)  # URL
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
