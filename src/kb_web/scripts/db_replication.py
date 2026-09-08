"""
PostgreSQL Replication Management for kb-web.

Provides setup and status diagnostics for logical streaming replication
(publication on kb_live and subscription on kb_test) and replication slots.
"""

from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, text

from kb_web.config import Config


def setup_publisher(
    live_db_url: Optional[str] = None,
    publication_name: str = "kb_live_pub",
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Configures the live database as a logical replication publisher."""
    cfg = config or Config()
    url = live_db_url or cfg.get_database_url_for_target("live")

    if not url or ("postgres" not in url and "postgresql" not in url):
        return {
            "success": False,
            "error": "Publisher target must be a PostgreSQL database connection.",
        }

    engine = create_engine(url)
    result = {"success": True, "wal_level": "unknown", "publication": publication_name}

    with engine.connect() as conn:
        # Check wal_level
        try:
            wal = conn.execute(text("SHOW wal_level;")).scalar()
            result["wal_level"] = wal
            if wal != "logical":
                print(
                    f"[WARN] wal_level is '{wal}'. PostgreSQL logical replication requires 'wal_level = logical'. "
                    "Update postgresql.conf and restart the PostgreSQL server if needed."
                )
        except Exception as e:
            result["wal_error"] = str(e)

        # Create publication
        with conn.begin():
            try:
                conn.execute(
                    text(f"CREATE PUBLICATION {publication_name} FOR ALL TABLES;")
                )
                result["message"] = f"Created publication '{publication_name}' for all tables."
                print(f"[SUCCESS] {result['message']}")
            except Exception as e:
                err_str = str(e)
                if "already exists" in err_str:
                    result["message"] = f"Publication '{publication_name}' already exists."
                    print(f"[INFO] {result['message']}")
                else:
                    result["success"] = False
                    result["error"] = err_str
                    print(f"[ERROR] Failed to create publication: {e}")

    return result


def setup_subscriber(
    test_db_url: Optional[str] = None,
    live_db_url: Optional[str] = None,
    subscription_name: str = "kb_test_sub",
    publication_name: str = "kb_live_pub",
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Configures the test database to subscribe to streaming replication from live."""
    cfg = config or Config()
    sub_url = test_db_url or cfg.get_database_url_for_target("test")
    pub_url = live_db_url or cfg.get_database_url_for_target("live")

    if not sub_url or not pub_url:
        return {
            "success": False,
            "error": "Both subscriber (test) and publisher (live) URLs must be configured.",
        }

    # Format connection string for PostgreSQL CREATE SUBSCRIPTION
    # e.g. postgresql://user:pass@host:port/dbname -> host=... port=... dbname=... user=... password=...
    from urllib.parse import urlparse

    parsed = urlparse(pub_url)
    conn_params = []
    if parsed.hostname:
        conn_params.append(f"host={parsed.hostname}")
    if parsed.port:
        conn_params.append(f"port={parsed.port}")
    if parsed.path and len(parsed.path) > 1:
        conn_params.append(f"dbname={parsed.path[1:]}")
    if parsed.username:
        conn_params.append(f"user={parsed.username}")
    if parsed.password:
        conn_params.append(f"password={parsed.password}")

    conn_str = " ".join(conn_params)

    engine = create_engine(sub_url, isolation_level="AUTOCOMMIT")
    result = {"success": True, "subscription": subscription_name}

    with engine.connect() as conn:
        try:
            # Check if subscription exists
            existing = conn.execute(
                text(f"SELECT 1 FROM pg_subscription WHERE subname = '{subscription_name}';")
            ).first()

            if existing:
                conn.execute(
                    text(f"ALTER SUBSCRIPTION {subscription_name} REFRESH PUBLICATION;")
                )
                result["message"] = f"Refreshed existing subscription '{subscription_name}'."
                print(f"[SUCCESS] {result['message']}")
            else:
                sql = (
                    f"CREATE SUBSCRIPTION {subscription_name} "
                    f"CONNECTION '{conn_str}' "
                    f"PUBLICATION {publication_name};"
                )
                conn.execute(text(sql))
                result["message"] = (
                    f"Created subscription '{subscription_name}' subscribed to '{publication_name}'."
                )
                print(f"[SUCCESS] {result['message']}")
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            print(f"[ERROR] Failed to configure subscription: {e}")

    return result


def get_replication_status(
    target_url: Optional[str] = None, config: Optional[Config] = None
) -> Dict[str, Any]:
    """Inspects PostgreSQL replication configuration and active slots/subscriptions."""
    cfg = config or Config()
    url = target_url or cfg.database_url

    if not url or ("postgres" not in url and "postgresql" not in url):
        return {"error": "Target database is not PostgreSQL."}

    engine = create_engine(url)
    status: Dict[str, Any] = {
        "wal_level": "unknown",
        "publications": [],
        "subscriptions": [],
        "replication_slots": [],
        "stat_replication": [],
    }

    with engine.connect() as conn:
        try:
            status["wal_level"] = conn.execute(text("SHOW wal_level;")).scalar()
        except Exception:
            pass

        try:
            pubs = conn.execute(
                text("SELECT pubname, puballtables, pubinsert, pubupdate, pubdelete FROM pg_publication;")
            ).fetchall()
            status["publications"] = [dict(r._mapping) for r in pubs]
        except Exception:
            pass

        try:
            subs = conn.execute(
                text("SELECT subname, subenabled, subconninfo, subpublications FROM pg_subscription;")
            ).fetchall()
            status["subscriptions"] = [dict(r._mapping) for r in subs]
        except Exception:
            pass

        try:
            slots = conn.execute(
                text("SELECT slot_name, plugin, slot_type, active, temporary FROM pg_replication_slots;")
            ).fetchall()
            status["replication_slots"] = [dict(r._mapping) for r in slots]
        except Exception:
            pass

        try:
            stat_rep = conn.execute(
                text("SELECT pid, usename, application_name, client_addr, state, sync_state FROM pg_stat_replication;")
            ).fetchall()
            status["stat_replication"] = [dict(r._mapping) for r in stat_rep]
        except Exception:
            pass

    return status
