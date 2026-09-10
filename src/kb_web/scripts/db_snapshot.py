"""
Database Snapshot and Live-to-Test Sync Tool for kb-web.

Supports taking point-in-time multi-table JSON snapshots of databases,
saving them into Config.backups_dir, and syncing live snapshots into the test database.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from kb_web.config import Config
from kb_web.models_orm import Base
from kb_web.scripts.db_migrate_sqlite import clean_record, resolve_target_url, MIGRATION_MODELS


def create_database_snapshot(
    target: str = "live",
    config: Optional[Config] = None,
    out_path: Optional[Path | str] = None,
) -> Path:
    """Exports a full multi-table snapshot of the target database to a JSON file."""
    cfg = config or Config()
    target_url = resolve_target_url(target, cfg)
    connect_args = {}
    if target_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    engine = create_engine(target_url, connect_args=connect_args)
    Session = sessionmaker(bind=engine)
    session = Session()

    backups_dir = cfg.backups_dir
    backups_dir.mkdir(parents=True, exist_ok=True)

    if out_path:
        dest_file = Path(out_path).resolve()
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_file = backups_dir / f"kb_snapshot_{target}_{ts}.json"

    export_data: Dict[str, Any] = {}
    try:
        models = list(MIGRATION_MODELS)
        if hasattr(Base, "registry"):
            for mapper in Base.registry.mappers:
                if mapper.class_ not in models:
                    models.append(mapper.class_)

        for model in models:
            tbl_name = model.__tablename__
            rows = session.query(model).all()
            clean_rows = []
            for row in rows:
                r_dict = {}
                for col in row.__table__.columns:
                    val = getattr(row, col.name)
                    if isinstance(val, bytes):
                        r_dict[col.name] = f"hex:{val.hex()}"
                    else:
                        r_dict[col.name] = val
                clean_rows.append(r_dict)
            export_data[tbl_name] = clean_rows

        with open(dest_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2)

        print(f"[SUCCESS] Created database snapshot at: {dest_file}")
        return dest_file
    finally:
        session.close()


def restore_database_snapshot(
    snapshot_path: Path | str,
    target: str = "test",
    config: Optional[Config] = None,
) -> Dict[str, int]:
    """Restores database records from a JSON snapshot file into the target database."""
    cfg = config or Config()
    path = Path(snapshot_path).resolve()
    if not path.exists():
        # Check in backups_dir
        path = cfg.backups_dir / snapshot_path
        if not path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {snapshot_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Invalid snapshot file format: expected JSON object with table keys.")

    target_url = resolve_target_url(target, cfg)
    connect_args = {}
    if target_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    engine = create_engine(target_url, connect_args=connect_args)
    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    restored_counts: Dict[str, int] = {}

    try:
        models = list(MIGRATION_MODELS)
        if hasattr(Base, "registry"):
            for mapper in Base.registry.mappers:
                if mapper.class_ not in models:
                    models.append(mapper.class_)

        for model in models:
            tbl_name = model.__tablename__
            if tbl_name not in data or not data[tbl_name]:
                continue

            raw_rows = data[tbl_name]
            pk_cols = [c.name for c in model.__table__.primary_key.columns]
            tbl_restored = 0

            for r in raw_rows:
                cleaned = clean_record(r, model)
                if pk_cols:
                    pk_vals = {pk: cleaned[pk] for pk in pk_cols if pk in cleaned}
                    existing = None
                    if len(pk_vals) == len(pk_cols):
                        existing = session.query(model).filter_by(**pk_vals).first()
                    if existing:
                        for k, v in cleaned.items():
                            setattr(existing, k, v)
                    else:
                        session.add(model(**cleaned))
                else:
                    session.add(model(**cleaned))
                tbl_restored += 1

            session.commit()

            # Advance sequence if applicable (PostgreSQL only)
            if "postgresql" in target_url and pk_cols and len(pk_cols) == 1:
                pk_col = pk_cols[0]
                col_obj = model.__table__.columns[pk_col]
                if hasattr(col_obj.type, "python_type") and col_obj.type.python_type == int:
                    try:
                        seq_sql = text(
                            f"SELECT setval(pg_get_serial_sequence('{tbl_name}', '{pk_col}'), "
                            f"COALESCE((SELECT MAX({pk_col}) FROM {tbl_name}), 1));"
                        )
                        session.execute(seq_sql)
                        session.commit()
                    except Exception:
                        session.rollback()

            restored_counts[tbl_name] = tbl_restored

        print(f"[SUCCESS] Restored {sum(restored_counts.values())} records from {path.name} into {target}.")
        return restored_counts
    finally:
        session.close()


def sync_live_to_test(config: Optional[Config] = None) -> Dict[str, int]:
    """Takes a snapshot of the live database and syncs it into the test database."""
    cfg = config or Config()
    print("[INFO] Initiating live database snapshot...")
    snapshot_path = create_database_snapshot(target="live", config=cfg)

    print("[INFO] Restoring live snapshot into test database...")
    result = restore_database_snapshot(snapshot_path, target="test", config=cfg)
    return result
