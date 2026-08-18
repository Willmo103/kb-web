"""
Database initialization and utilities for the Knowledge Base Web Importer application.
"""

from typing import Optional
from .config import (
    Config,
    DEFAULT_RAG_SYSTEM_PROMPT,
    DEFAULT_TAXONOMY_SYSTEM_PROMPT,
)


def get_db(config: Config):
    """Connects to the database and returns a Database instance from sqlite-utils.

    This is kept for backward compatibility with base CLI configurations.
    """
    db = config.get_db()
    try:
        db.enable_wal()
    except Exception:
        pass
    return db


def init_db(db, config: Optional[Config] = None) -> None:
    """Seeds the database with default general collection and default agent prompts if missing."""
    from .base import db_session
    from .models_orm import AgentPrompt
    from .config import DEFAULT_WIKI_PROMPT, DEFAULT_YOUTUBE_WIKI_PROMPT
    from datetime import datetime

    # 1. Seed general collection
    try:
        get_general_collection_id()
    except Exception as e:
        print(f"Error seeding General Collection in init_db: {e}")

    # 2. Seed agent prompts
    try:
        with db_session() as session:
            # Seed wiki_prompt
            wp = session.query(AgentPrompt).filter_by(prompt_type="wiki_prompt").first()
            if not wp:
                session.add(
                    AgentPrompt(
                        prompt_type="wiki_prompt",
                        prompt_text=DEFAULT_WIKI_PROMPT,
                        is_head=1,
                        version=1,
                        created_at=datetime.now().isoformat(),
                    )
                )
            
            # Seed youtube_wiki_prompt
            ywp = session.query(AgentPrompt).filter_by(prompt_type="youtube_wiki_prompt").first()
            if not ywp:
                session.add(
                    AgentPrompt(
                        prompt_type="youtube_wiki_prompt",
                        prompt_text=DEFAULT_YOUTUBE_WIKI_PROMPT,
                        is_head=1,
                        version=1,
                        created_at=datetime.now().isoformat(),
                    )
                )
    except Exception as e:
        print(f"Error seeding default prompts in init_db: {e}")


def get_general_collection_id(db=None) -> int:
    """Finds the General Collection ID from the database using SQLAlchemy ORM, seeding it if missing."""
    from .models_orm import Collection
    from .base import db_session
    from datetime import datetime
    from sqlalchemy import text

    with db_session() as session:
        general = session.query(Collection).filter_by(title="General Collection").first()
        if general:
            return general.id

        # Seed it if missing
        try:
            # Try to insert id=1 first
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
                session.add(general)
                session.flush()
                if session.bind and "postgresql" in str(session.bind.url):
                    session.execute(text("SELECT setval('collections_id_seq', (SELECT MAX(id) FROM collections))"))
                session.commit()
                return 1
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
                session.flush()
                session.commit()
                return general.id
        except Exception as e:
            print(f"Error seeding General Collection in ORM helper: {e}")
            return 1
