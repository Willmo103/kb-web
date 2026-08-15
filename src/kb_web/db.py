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
    """A no-op compatibility helper for legacy sqlite-utils database setup."""
    pass


def get_general_collection_id(db=None) -> int:
    """Finds the General Collection ID from the database using SQLAlchemy ORM, seeding it if missing."""
    from .models_orm import Collection
    from .base import db_session
    from datetime import datetime

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
