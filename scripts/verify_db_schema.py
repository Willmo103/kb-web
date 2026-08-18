"""
Verification script to test SQLAlchemy ORM models against the production SQLite database copy.
"""

import sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from kb_web.models_orm import (
    Base, FetchedPage, PageVersion, YouTubeVideo, Collection, CollectionItem,
    CollectionNote, CollectionAction, ChunkEmbedding, ArticleEmbedding,
    VideoEmbedding, TitleEmbedding, OllamaLog, SettingOllama, SettingExternal,
    AgentPrompt, CliApiKey, RegisteredClient, SystemLog, Link, SiteWiki
)

MODELS = [
    FetchedPage, PageVersion, YouTubeVideo, Collection, CollectionItem,
    CollectionNote, CollectionAction, ChunkEmbedding, ArticleEmbedding,
    VideoEmbedding, TitleEmbedding, OllamaLog, SettingOllama, SettingExternal,
    AgentPrompt, CliApiKey, RegisteredClient, SystemLog, Link, SiteWiki
]

def fix_sqlite_collection_actions(engine):
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

def main():
    db_path = ".data/kb.db"
    print(f"Connecting to database copy: {db_path}")
    
    engine = create_engine(f"sqlite:///{db_path}")
    
    # Run the SQLite schema fix first
    fix_sqlite_collection_actions(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    success = True
    
    for model in MODELS:
        table_name = model.__tablename__
        print(f"Verifying table '{table_name}' mapped to {model.__name__}...", end="")
        try:
            # Query the first record or just select 1 to verify table & columns mapping
            count = session.query(model).count()
            print(f" OK (Count: {count})")
        except Exception as e:
            print(f" FAILED\n[ERROR] Table verification failed for '{table_name}': {e}")
            success = False
            
    session.close()
    
    if success:
        print("\n[SUCCESS] All SQLAlchemy ORM models mapped successfully to .data/kb.db schema!")
        sys.exit(0)
    else:
        print("\n[ERROR] Schema verification failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
