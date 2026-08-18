from pathlib import Path
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


def deploy():
    project_dir = Path(__file__).resolve().parent.parent
    ini_path = project_dir / "alembic.ini"
    alembic_cfg = AlembicConfig(str(ini_path))

    # Initialize SQLAlchemy connection engine
    engine = get_engine()

    # Apply SQLite collection_actions workaround if needed
    if engine.dialect.name == "sqlite":
        fix_sqlite_collection_actions(engine)

    # 1. Create all tables if they don't exist (dialect-agnostic)
    print("[INFO] Initializing database schema via SQLAlchemy ORM...")
    Base.metadata.create_all(engine)

    # 2. Seed database defaults
    print("[INFO] Seeding default database templates and collections...")
    seed_database()

    # 3. Check Alembic status
    from sqlalchemy import inspect
    inspector = inspect(engine)

    # Check if alembic_version table exists and has rows
    if "alembic_version" in inspector.get_table_names():
        with engine.connect() as conn:
            from sqlalchemy import text
            res = conn.execute(text("SELECT version_num FROM alembic_version")).first()
            if res:
                print(f"[INFO] Existing database revision detected: {res[0]}. Running upgrade...")
                command.upgrade(alembic_cfg, "head")
                print("[SUCCESS] Alembic database migrations applied successfully!")
                return

    # If no revision is recorded, stamp the database version as head
    print("[INFO] Fresh database detected. Stamping schema revision to head...")
    command.stamp(alembic_cfg, "head")
    print("[SUCCESS] Database schema initialized and stamped successfully!")


if __name__ == "__main__":
    deploy()
