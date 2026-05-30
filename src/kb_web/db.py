import sqlite_utils
from .config import Config


def get_db(config: Config) -> sqlite_utils.Database:
    """Connects to the database and returns a Database instance from sqlite-utils.

    Args:
        config (Config): Loaded configuration instance.

    Returns:
        sqlite_utils.Database: Database object targeting ~/.kb/kb.db.
    """
    db = config.get_db()
    init_db(db)
    return db


def init_db(db: sqlite_utils.Database) -> None:
    """Checks for the presence of the `fetched_pages` table and initializes

    its schema if it is missing.

    Args:
        db (sqlite_utils.Database): Database object to check and initialize.
    """
    if "fetched_pages" not in db.table_names():
        # Create table with correct schema types and declare url as primary key
        db["fetched_pages"].create(
            {
                "url": str,
                "html_content": str,
                "md_content": str,
                "links": str,  # JSON-encoded array of URLs
                "html_content_hash": str,
                "md_content_hash": str,
                "fetched_at": str,
                "description": str,  # Ingestion summary or wiki content
                "keywords": str,  # JSON-encoded array of strings
            },
            pk="url",
        )
        print("Initialized database table: fetched_pages")
