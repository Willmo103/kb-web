"""
Database initialization and utilities for the Knowledge Base Web Importer application.
"""

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

    its schema if it is missing. Runs schema migrations to append title and
    tags columns if they are not already present in the table.

    Args:
        db (sqlite_utils.Database): Database object to check and initialize.
    """
    try:
        db.enable_wal()
    except Exception as e:
        print(f"Warning: Failed to enable WAL mode: {e}")

    if "fetched_pages" not in db.table_names():
        # Create table with correct schema types and declare url as primary key
        db["fetched_pages"].create(
            {
                "url": str,
                "title": str,  # Page title (assigned during wiki generation)
                "html_content": str,
                "md_content": str,
                "links": str,  # JSON-encoded array of URLs
                "html_content_hash": str,
                "md_content_hash": str,
                "fetched_at": str,
                "description": str,  # Ingestion summary or wiki content
                "keywords": str,  # JSON-encoded array of strings
                "tags": str,  # JSON-encoded array of tags/labels
            },
            pk="url",
        )
        print("Initialized database table: fetched_pages")
    else:
        # Schema migration helper for existing databases
        columns = db["fetched_pages"].columns_dict
        if "title" not in columns:
            try:
                db["fetched_pages"].add_column("title", str)
                print("Schema Migration: Added 'title' column to fetched_pages table.")
            except Exception as e:
                print(f"Error migrating database (adding title column): {e}")

        if "tags" not in columns:
            try:
                db["fetched_pages"].add_column("tags", str)
                print("Schema Migration: Added 'tags' column to fetched_pages table.")
            except Exception as e:
                print(f"Error migrating database (adding tags column): {e}")

    # Initialize page_versions table for archiving historical snapshots
    if "page_versions" not in db.table_names():
        try:
            db["page_versions"].create(
                {
                    "id": int,
                    "url": str,
                    "title": str,
                    "html_content": str,
                    "md_content": str,
                    "links": str,
                    "html_content_hash": str,
                    "md_content_hash": str,
                    "fetched_at": str,
                    "description": str,
                    "keywords": str,
                    "tags": str,
                },
                pk="id",
            )
            print("Initialized database table: page_versions")
        except Exception as e:
            print(f"Error creating page_versions table: {e}")

    # Initialize article_embeddings table for similarity comparisons
    if "article_embeddings" not in db.table_names():
        try:
            db["article_embeddings"].create(
                {
                    "url": str,
                    "embedding": str,  # JSON-encoded list[float]
                    "updated_at": str,
                },
                pk="url",
                foreign_keys=[("url", "fetched_pages", "url")],
            )
            print("Initialized database table: article_embeddings")
        except Exception as e:
            print(f"Error creating article_embeddings table: {e}")

    # Initialize site_wikis table for caching virtual site profiles' wiki descriptions
    if "site_wikis" not in db.table_names():
        try:
            db["site_wikis"].create(
                {
                    "site": str,
                    "wiki_content": str,
                    "updated_at": str,
                },
                pk="site",
            )
            print("Initialized database table: site_wikis")
        except Exception as e:
            print(f"Error creating site_wikis table: {e}")

    # Drop legacy active_sessions table if it exists to clean up database schema
    if "active_sessions" in db.table_names():
        try:
            db["active_sessions"].drop()
            print("Dropped legacy database table: active_sessions")
        except Exception as e:
            print(f"Warning: Failed to drop active_sessions table: {e}")
