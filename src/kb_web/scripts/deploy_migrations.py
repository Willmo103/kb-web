import sys
from pathlib import Path
from typing import Optional
from alembic.config import Config as AlembicConfig
from alembic import command
from kb_web.base import get_engine, db_session
from kb_web.models_orm import Base
from datetime import datetime


def seed_database():
    from kb_web.models_orm import Collection, SettingOllama, SettingExternal, AgentPrompt
    from kb_web.config import (
        DEFAULT_RAG_SYSTEM_PROMPT,
        DEFAULT_TAXONOMY_SYSTEM_PROMPT,
        DEFAULT_WIKI_PROMPT,
        DEFAULT_YOUTUBE_WIKI_PROMPT,
    )

    with db_session() as session:
        # Check if General Collection exists
        general = session.query(Collection).filter_by(title="General Collection").first()
        if not general:
            # Check if id=1 is available
            existing_one = session.query(Collection).filter_by(id=1).first()
            if not existing_one:
                general = Collection(
                    id=1,
                    title="General Collection",
                    visibility="private",
                    rag_system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
                    taxonomy_system_prompt=DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                    general_system_context="{}",
                    created_at=datetime.now().isoformat(),
                )
            else:
                general = Collection(
                    title="General Collection",
                    visibility="private",
                    rag_system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
                    taxonomy_system_prompt=DEFAULT_TAXONOMY_SYSTEM_PROMPT,
                    general_system_context="{}",
                    created_at=datetime.now().isoformat(),
                )
            session.add(general)

        # Seed default Ollama settings
        ollama_settings = {
            "ollama_host": "http://localhost:11434",
            "ollama_model": "gemma4:latest",
            "ollama_embedding_model": "nomic-embed-text",
            "ollama_think": "0",
            "max_input_length": "20000",
        }
        for k, v in ollama_settings.items():
            setting = session.query(SettingOllama).filter_by(key=k).first()
            if not setting:
                session.add(SettingOllama(key=k, value=v))

        # Seed default external settings
        ext_settings = {
            "admin_password": "admin123",
            "api_key": "kb-secret-key",
            "similarity_threshold": "0.8",
        }
        for k, v in ext_settings.items():
            setting = session.query(SettingExternal).filter_by(key=k).first()
            if not setting:
                session.add(SettingExternal(key=k, value=v))

        # Seed default prompt templates
        prompts = [
            ("wiki_prompt", DEFAULT_WIKI_PROMPT),
            ("youtube_wiki_prompt", DEFAULT_YOUTUBE_WIKI_PROMPT),
        ]
        for ptype, ptext in prompts:
            prompt = session.query(AgentPrompt).filter_by(prompt_type=ptype, is_head=1).first()
            if not prompt:
                session.add(
                    AgentPrompt(
                        prompt_type=ptype,
                        prompt_text=ptext,
                        is_head=1,
                        version=1,
                        created_at=datetime.now().isoformat(),
                    )
                )


def fix_sqlite_collection_actions(engine):
    from sqlalchemy import inspect, text
    import sqlalchemy as sa
    inspector = inspect(engine)
    if "collection_actions" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("collection_actions")]
        if "id" not in columns:
            print("[INFO] Migrating SQLite collection_actions table to include autoincrement ID column...")
            with engine.begin() as conn:
                views = [row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='view'")).fetchall()]
                for v in views:
                    try:
                        conn.execute(text(f"DROP VIEW IF EXISTS {v};"))
                    except Exception as e:
                        pass
                conn.execute(text("ALTER TABLE collection_actions RENAME TO collection_actions_old;"))
                conn.execute(text("""
                    CREATE TABLE collection_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        collection_id INTEGER,
                        action_type TEXT,
                        source_type TEXT,
                        source_id TEXT,
                        note TEXT,
                        created_at TEXT
                    );
                """))
                conn.execute(text("""
                    INSERT INTO collection_actions (collection_id, action_type, source_type, source_id, note, created_at)
                    SELECT collection_id, action_type, source_type, source_id, note, created_at
                    FROM collection_actions_old;
                """))
                conn.execute(text("DROP TABLE collection_actions_old;"))
            print("[SUCCESS] Migrated collection_actions table.")


def deploy_single(engine, alembic_cfg, target_label: str = "current"):
    from sqlalchemy import inspect, text

    print(f"\n[INFO] Initializing schema for target: {target_label}...")

    # Apply SQLite collection_actions workaround if needed
    if engine.dialect.name == "sqlite":
        fix_sqlite_collection_actions(engine)
    elif engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            with conn.begin():
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                except Exception as e:
                    pass

    # 1. Create all tables if they don't exist
    Base.metadata.create_all(engine)
    from kb_web.models_orm import ensure_views_and_indexes
    ensure_views_and_indexes(engine)

    # If PostgreSQL, ensure vector columns are flexible
    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            with conn.begin():
                for tbl, col in [
                    ("article_embeddings", "embedding"),
                    ("title_embeddings", "embedding"),
                    ("chunk_embeddings", "chunk_vector"),
                    ("video_embeddings", "embedding"),
                ]:
                    try:
                        conn.execute(
                            text(f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE vector;")
                        )
                    except Exception:
                        pass

    # 2. Seed database defaults
    seed_database()

    # 3. Check Alembic status
    inspector = inspect(engine)
    if "alembic_version" in inspector.get_table_names():
        with engine.connect() as conn:
            res = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            if res:
                print(f"[INFO] Existing database revision detected: {res[0]}. Running upgrade to head...")
                with engine.begin() as connection:
                    alembic_cfg.attributes["connection"] = connection
                    command.upgrade(alembic_cfg, "head")
                print(f"[SUCCESS] Alembic database migrations applied successfully for {target_label}!")
                return

    # If no revision is recorded, stamp head
    print(f"[INFO] Fresh database detected for {target_label}. Stamping schema revision to head...")
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.stamp(alembic_cfg, "head")
    print(f"[SUCCESS] Database schema initialized and stamped successfully for {target_label}!")


def deploy(target: Optional[str] = None):
    from kb_web.config import Config
    from sqlalchemy import create_engine
    cfg = Config()

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not ini_path.exists():
        ini_path = Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini"
    if not ini_path.exists():
        ini_path = Path.cwd() / "alembic.ini"

    alembic_cfg = AlembicConfig(str(ini_path))

    if target and target.lower().strip() == "all":
        targets = ["dev", "test", "live"]
        for t in targets:
            url = cfg.get_database_url_for_target(t)
            if url:
                if url.startswith("postgres://"):
                    url = url.replace("postgres://", "postgresql+psycopg2://", 1)
                elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
                    url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
                alembic_cfg.set_main_option("sqlalchemy.url", url)
                eng = create_engine(url)
                deploy_single(eng, alembic_cfg, target_label=t)
        return

    if target:
        url = cfg.get_database_url_for_target(target)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        engine = create_engine(url)
        deploy_single(engine, alembic_cfg, target_label=target)
    else:
        engine = get_engine()
        deploy_single(engine, alembic_cfg, target_label="default")


if __name__ == "__main__":
    target_env = sys.argv[1] if len(sys.argv) > 1 else None
    deploy(target=target_env)
