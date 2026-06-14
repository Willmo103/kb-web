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

    # Initialize youtube_videos table for youtube metadata
    if "youtube_videos" not in db.table_names():
        try:
            db["youtube_videos"].create(
                {
                    "url": str,
                    "video_id": str,
                    "creator": str,
                    "channel_id": str,
                    "duration": int,
                    "view_count": int,
                    "thumbnail_url": str,
                    "updated_at": str,
                },
                pk="url",
                foreign_keys=[("url", "fetched_pages", "url")],
            )
            print("Initialized database table: youtube_videos")
        except Exception as e:
            print(f"Error creating youtube_videos table: {e}")

    # Retrospective migration for youtube_videos table
    if "youtube_videos" in db.table_names() and "fetched_pages" in db.table_names():
        try:
            if db["youtube_videos"].count == 0:
                from datetime import datetime
                from .models import extract_youtube_video_id
                
                rows_to_migrate = []
                for row in db["fetched_pages"].rows:
                    url = row["url"]
                    video_id = extract_youtube_video_id(url)
                    if video_id:
                        rows_to_migrate.append({
                            "url": url,
                            "video_id": video_id,
                            "creator": "Unknown Creator",
                            "updated_at": datetime.now().isoformat(),
                        })
                if rows_to_migrate:
                    db["youtube_videos"].insert_all(rows_to_migrate, pk="url")
                    print(f"Retrospective migration complete: created {len(rows_to_migrate)} entries in youtube_videos table.")
        except Exception as e:
            print(f"Warning: Retrospective migration failed: {e}")

    # Initialize collections table
    if "collections" not in db.table_names():
        try:
            db["collections"].create(
                {
                    "id": int,
                    "title": str,
                    "created_at": str,
                },
                pk="id",
            )
            print("Initialized database table: collections")
        except Exception as e:
            print(f"Error creating collections table: {e}")

    # Add collection_id to fetched_pages if missing
    if "fetched_pages" in db.table_names():
        columns = db["fetched_pages"].columns_dict
        if "collection_id" not in columns:
            try:
                db["fetched_pages"].add_column("collection_id", int)
                print("Schema Migration: Added 'collection_id' column to fetched_pages table.")
            except Exception as e:
                print(f"Error migrating database (adding collection_id column): {e}")

    # Initialize cron_jobs table
    if "cron_jobs" not in db.table_names():
        try:
            db["cron_jobs"].create(
                {
                    "id": int,
                    "title": str,
                    "url": str,
                    "interval_minutes": int,
                    "prompt_template": str,
                    "output_type": str,
                    "db_store": int, # 0 or 1
                    "file_store": int, # 0 or 1
                    "notify_on": str, # "success", "failure", "both", "none"
                    "is_active": int, # 0 or 1
                    "last_run_at": str,
                    "created_at": str,
                    "updated_at": str,
                },
                pk="id",
            )
            print("Initialized database table: cron_jobs")
        except Exception as e:
            print(f"Error creating cron_jobs table: {e}")

    # Initialize cron_job_runs table
    if "cron_job_runs" not in db.table_names():
        try:
            db["cron_job_runs"].create(
                {
                    "id": int,
                    "cron_job_id": int,
                    "status": str,
                    "fetched_at": str,
                    "prompt_output": str,
                    "error_message": str,
                    "files_created": str,
                    "duration": float,
                },
                pk="id",
                foreign_keys=[("cron_job_id", "cron_jobs", "id")],
            )
            print("Initialized database table: cron_job_runs")
        except Exception as e:
            print(f"Error creating cron_job_runs table: {e}")

    # Drop legacy active_sessions table if it exists to clean up database schema
    if "active_sessions" in db.table_names():
        try:
            db["active_sessions"].drop()
            print("Dropped legacy database table: active_sessions")
        except Exception as e:
            print(f"Warning: Failed to drop active_sessions table: {e}")

