"""
SQLite to PostgreSQL Data Migration Tool for kb-web.

Migrates existing records from a SQLite database file (e.g. .data/kb.db or ~/.kb/kb.db)
into a target PostgreSQL database (kb_dev, kb_test, kb_live) in dependency order,
with vector deserialization, batching, and primary key sequence advancement.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

from kb_web.config import Config
from kb_web.models_orm import (
    Base,
    FetchedPage,
    PageVersion,
    YouTubeVideo,
    Collection,
    CollectionItem,
    CollectionNote,
    CollectionAction,
    ChunkEmbedding,
    ArticleEmbedding,
    VideoEmbedding,
    TitleEmbedding,
    OllamaLog,
    SettingOllama,
    SettingExternal,
    AgentPrompt,
    CliApiKey,
    RegisteredClient,
    SystemLog,
    Link,
    SiteWiki,
    vault_master,
    repo_master,
    valid_repo_files,
)
from kb_web.video_manager import index_local_videos

MIGRATION_MODELS = [
    # 1. Independent parent tables
    Collection,
    FetchedPage,
    PageVersion,
    ArticleEmbedding,
    TitleEmbedding,
    YouTubeVideo,
    VideoEmbedding,
    # 2. Collection children tables
    CollectionItem,
    CollectionNote,
    CollectionAction,
    # 3. Embeddings & Content
    ChunkEmbedding,
    SiteWiki,
    Link,
    # 4. Settings & Prompts
    SettingOllama,
    SettingExternal,
    AgentPrompt,
    CliApiKey,
    RegisteredClient,
    # 5. Logs
    SystemLog,
    OllamaLog,
]


def resolve_sqlite_path(custom_path: Optional[str] = None) -> Path:
    """Locates the source SQLite database file."""
    if custom_path:
        p = Path(custom_path).resolve()
        if p.exists():
            return p
        raise FileNotFoundError(f"SQLite database file not found at: {custom_path}")

    # Standard check locations
    candidates = [
        Path.cwd() / ".data" / "kb.db",
        Path.home() / ".kb" / "kb.db",
        Path.cwd() / "kb.db",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "Could not find a SQLite database in .data/kb.db or ~/.kb/kb.db. "
        "Please provide --sqlite-path explicitly."
    )


def resolve_target_url(target: str, config: Optional[Config] = None) -> str:
    """Resolves target database URL from target name (dev, test, live, default) or raw URL string."""
    cfg = config or Config()
    url = cfg.get_database_url_for_target(target)
    if not url or url.lower() in ("default", "current", ""):
        url = cfg.database_url or f"sqlite:///{cfg.db_path}"

    if not url:
        raise ValueError(
            f"Could not resolve a database URL for target '{target}'. "
            f"Ensure KB_DEV_DATABASE_URL, KB_TEST_DATABASE_URL, or DATABASE_URL are set."
        )

    # Normalize driver prefix for SQLAlchemy
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    return url


def clean_record(row_dict: Dict[str, Any], model_cls) -> Dict[str, Any]:
    """Cleans up types for compatibility between SQLite and PostgreSQL."""
    cleaned = {}
    col_names = {c.name: c for c in model_cls.__table__.columns}

    for k, v in row_dict.items():
        if k not in col_names:
            continue

        if isinstance(v, str):
            # PostgreSQL does not permit NUL (0x00) characters in string literals
            v = v.replace("\x00", "")

        if isinstance(v, str) and v.startswith("hex:"):
            try:
                cleaned[k] = bytes.fromhex(v[4:])
            except ValueError:
                cleaned[k] = v
        elif isinstance(v, str) and (k.endswith("embedding") or k.endswith("vector")):
            if v.startswith("[") and v.endswith("]"):
                try:
                    cleaned[k] = json.loads(v)
                except Exception:
                    cleaned[k] = v
            else:
                cleaned[k] = v
        else:
            cleaned[k] = v

    return cleaned


def migrate_sqlite_to_postgres(
    sqlite_path: Optional[str] = None,
    target: str = "test",
    batch_size: int = 500,
    truncate: bool = False,
    reindex_videos: bool = True,
    config: Optional[Config] = None,
) -> Dict[str, int]:
    """Executes full migration of data from SQLite database to PostgreSQL database."""
    cfg = config or Config()
    src_path = resolve_sqlite_path(sqlite_path)
    target_url = resolve_target_url(target, cfg)

    # Display clean target information (hide password)
    safe_target = target_url.split("@")[-1] if "@" in target_url else target
    print(f"\n[INFO] Starting Migration:")
    print(f"  Source: SQLite at {src_path} ({src_path.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  Target: PostgreSQL at {safe_target}")
    print(f"  Batch Size: {batch_size} | Truncate: {truncate}\n")

    # Connect to SQLite
    src_engine = create_engine(f"sqlite:///{src_path}")
    SrcSession = sessionmaker(bind=src_engine)
    src_session = SrcSession()

    # Connect to PostgreSQL
    target_engine = create_engine(target_url)

    # Ensure pgvector extension and tables exist in PostgreSQL
    with target_engine.connect() as conn:
        with conn.begin():
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            except Exception as e:
                print(f"[WARN] pgvector extension note: {e}")

    # Ensure schema tables exist
    Base.metadata.create_all(target_engine)

    TargetSession = sessionmaker(bind=target_engine)
    target_session = TargetSession()

    src_inspector = inspect(src_engine)
    available_src_tables = set(src_inspector.get_table_names())

    migration_stats: Dict[str, int] = {}

    try:
        for model in MIGRATION_MODELS:
            table_name = model.__tablename__
            if table_name not in available_src_tables:
                continue

            print(f"[MIGRATING] Table '{table_name}'...", end="", flush=True)

            if truncate:
                try:
                    target_session.execute(text(f"TRUNCATE TABLE {table_name} CASCADE;"))
                    target_session.commit()
                except Exception:
                    target_session.rollback()
                    try:
                        target_session.query(model).delete()
                        target_session.commit()
                    except Exception:
                        target_session.rollback()

            total_src_count = src_session.query(model).count()
            if total_src_count == 0:
                print(f" 0 records (skipped)")
                migration_stats[table_name] = 0
                continue

            # Query primary key columns
            pk_cols = [c.name for c in model.__table__.primary_key.columns]

            offset = 0
            migrated_for_table = 0

            while offset < total_src_count:
                chunk = src_session.query(model).offset(offset).limit(batch_size).all()
                if not chunk:
                    break

                for item in chunk:
                    row_dict = {
                        c.name: getattr(item, c.name) for c in model.__table__.columns
                    }
                    cleaned = clean_record(row_dict, model)

                    if model in (ArticleEmbedding, TitleEmbedding, YouTubeVideo, VideoEmbedding):
                        url_val = cleaned.get("url")
                        if url_val:
                            parent = target_session.query(FetchedPage).filter_by(url=url_val).first()
                            if not parent:
                                from datetime import datetime

                                target_session.add(
                                    FetchedPage(
                                        url=url_val,
                                        title=f"Archived Item ({url_val})",
                                        fetched_at=datetime.now().isoformat(),
                                    )
                                )
                                target_session.commit()

                    if pk_cols:
                        pk_vals = {pk: cleaned[pk] for pk in pk_cols if pk in cleaned}
                        existing = None
                        if len(pk_vals) == len(pk_cols):
                            existing = (
                                target_session.query(model).filter_by(**pk_vals).first()
                            )

                        if existing:
                            for k, v in cleaned.items():
                                setattr(existing, k, v)
                        else:
                            target_session.add(model(**cleaned))
                    else:
                        target_session.add(model(**cleaned))

                    migrated_for_table += 1

                target_session.commit()
                offset += batch_size

            # Reset PostgreSQL sequences for tables with integer autoincrement primary keys
            if pk_cols and len(pk_cols) == 1:
                pk_col = pk_cols[0]
                col_obj = model.__table__.columns[pk_col]
                if hasattr(col_obj.type, "python_type") and col_obj.type.python_type == int:
                    try:
                        seq_sql = text(
                            f"SELECT setval(pg_get_serial_sequence('{table_name}', '{pk_col}'), "
                            f"COALESCE((SELECT MAX({pk_col}) FROM {table_name}), 1));"
                        )
                        target_session.execute(seq_sql)
                        target_session.commit()
                    except Exception:
                        target_session.rollback()

            print(f" OK ({migrated_for_table} records)")
            migration_stats[table_name] = migrated_for_table

        # Handle unmapped auxiliary tables if present (vault_master, repo_master, valid_repo_files)
        aux_tables = [
            ("vault_master", vault_master),
            ("repo_master", repo_master),
            ("valid_repo_files", valid_repo_files),
        ]
        for tbl_name, tbl_obj in aux_tables:
            if tbl_name in available_src_tables:
                print(f"[MIGRATING] Auxiliary table '{tbl_name}'...", end="", flush=True)
                with src_engine.connect() as s_conn:
                    rows = s_conn.execute(tbl_obj.select()).fetchall()
                    if rows:
                        with target_engine.begin() as t_conn:
                            if truncate:
                                t_conn.execute(text(f"TRUNCATE TABLE {tbl_name} CASCADE;"))
                            for r in rows:
                                t_conn.execute(tbl_obj.insert().values(dict(r._mapping)))
                        print(f" OK ({len(rows)} records)")
                        migration_stats[tbl_name] = len(rows)
                    else:
                        print(" 0 records")

    finally:
        src_session.close()
        target_session.close()

    if reindex_videos:
        print("\n[INFO] Indexing local YouTube videos against target database...")
        try:
            res = index_local_videos(config=cfg, target_db_url=target_url)
            print(f"[SUCCESS] Video indexing completed: {res['indexed_count']} updated.")
        except Exception as e:
            print(f"[WARN] Video indexing skipped: {e}")

    total_records = sum(migration_stats.values())
    print(f"\n[SUCCESS] Migration completed successfully!")
    print(f"Total records migrated: {total_records} across {len(migration_stats)} tables.\n")

    return migration_stats


if __name__ == "__main__":
    target_arg = sys.argv[1] if len(sys.argv) > 1 else "test"
    migrate_sqlite_to_postgres(target=target_arg)
