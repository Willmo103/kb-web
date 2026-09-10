"""
CLI Module for the Knowledge Base Web Importer application.
"""

from typing import Optional
from pathlib import Path
import typer

app = typer.Typer(
    help="CLI management command station for the Knowledge Base Web Importer.",
    no_args_is_help=True,
)

db_app = typer.Typer(
    help="Database and video media management command suite.",
    no_args_is_help=True,
)
app.add_typer(db_app, name="db")


@app.command()
def serve(
    host: str = typer.Option(
        "0.0.0.0", help="The binding host interface address for the web server."
    ),
    port: int = typer.Option(
        8050, help="The communication port number to bind the server on."
    ),
    reload: bool = typer.Option(
        False, help="Toggle hot-reloading for development environments."
    ),
) -> None:
    """Launches the FastAPI web interface and ingestion API server under uvicorn."""
    from .gunicorn_runner import run_server

    run_server("kb_web.server:app", host=host, port=port, reload=reload)


@app.command()
def mcp(
    host: str = typer.Option(
        "0.0.0.0", help="The binding host interface address for the MCP server."
    ),
    port: int = typer.Option(
        8051, help="The communication port number to bind the MCP server on."
    ),
    transport: str = typer.Option(
        "sse", help="The transport protocol to use ('stdio' or 'sse')."
    ),
) -> None:
    """Starts the Model Context Protocol (MCP) server for agents to query articles."""
    from .mcp_server import mcp as mcp_server

    typer.echo(f"Starting Knowledge Base MCP server using {transport} transport...")
    if transport == "sse":
        mcp_server.run(transport="sse", host=host, port=port)
    else:
        mcp_server.run(transport="stdio")


# --- Database & Media CLI Subcommands ---


@db_app.command("migrate-sqlite")
def migrate_sqlite(
    sqlite_path: Optional[str] = typer.Option(
        None, "--sqlite-path", "-s", help="Path to source SQLite database file."
    ),
    target: Optional[str] = typer.Option(
        None, "--target", "-t", help="Target database: 'dev', 'test', or 'live'."
    ),
    batch_size: int = typer.Option(
        500, "--batch-size", "-b", help="Number of rows per batch."
    ),
    truncate: bool = typer.Option(
        False, "--truncate", help="Whether to clear target tables prior to inserting."
    ),
) -> None:
    """Migrates data from an existing SQLite database into a target PostgreSQL database."""
    from .scripts.db_migrate_sqlite import migrate_sqlite_to_postgres

    if not target:
        typer.echo("\nSelect target PostgreSQL database:")
        typer.echo("  [1] kb_dev  - Development database (KB_DEV_DATABASE_URL)")
        typer.echo("  [2] kb_test - Test database / Replicated copy of live (KB_TEST_DATABASE_URL)")
        typer.echo("  [3] kb_live - Production / Live database (DATABASE_URL / KB_LIVE_DATABASE_URL)")
        choice = typer.prompt("Enter choice [1/2/3]", default="2")
        mapping = {"1": "dev", "2": "test", "3": "live"}
        target = mapping.get(choice.strip(), "test")

    typer.echo(f"Migrating SQLite data to target '{target}'...")
    try:
        stats = migrate_sqlite_to_postgres(
            sqlite_path=sqlite_path,
            target=target,
            batch_size=batch_size,
            truncate=truncate,
            reindex_videos=True,
        )
        total = sum(stats.values())
        typer.secho(f"\nMigration successfully finished! {total} records copied.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"\nMigration failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@db_app.command("deploy")
def deploy_migrations(
    target: str = typer.Option(
        "default", "--target", "-t", help="Target environment: 'dev', 'test', 'live', 'all', or 'default'."
    ),
) -> None:
    """Applies Alembic and SQLAlchemy database schema migrations to target environment(s)."""
    from .scripts.deploy_migrations import deploy

    target_env = None if target == "default" else target
    typer.echo(f"Deploying database schema migrations to target: '{target}'...")
    try:
        deploy(target=target_env)
        typer.secho("\nDatabase migrations deployed successfully!", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"\nMigration deployment failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@db_app.command("snapshot")
def take_snapshot(
    target: str = typer.Option(
        "live", "--target", "-t", help="Database environment to snapshot: 'live', 'test', or 'dev'."
    ),
    out: Optional[str] = typer.Option(
        None, "--out", "-o", help="Optional custom destination path for the JSON snapshot."
    ),
) -> None:
    """Takes a multi-table point-in-time JSON snapshot of the specified database."""
    from .scripts.db_snapshot import create_database_snapshot

    typer.echo(f"Taking snapshot of '{target}' database...")
    try:
        path = create_database_snapshot(target=target, out_path=out)
        typer.secho(f"\nSnapshot saved to: {path}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"\nFailed to create snapshot: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@db_app.command("sync-snapshot")
def sync_snapshot(
    source: str = typer.Option(
        "live", "--source", help="Source database to snapshot (default: 'live')."
    ),
    target: str = typer.Option(
        "test", "--target", help="Target database to restore snapshot into (default: 'test')."
    ),
) -> None:
    """Takes a snapshot of the live database and syncs it into the test database."""
    from .scripts.db_snapshot import create_database_snapshot, restore_database_snapshot

    typer.echo(f"Syncing snapshot from '{source}' to '{target}'...")
    try:
        snap_path = create_database_snapshot(target=source)
        typer.echo(f"Restoring snapshot into '{target}'...")
        results = restore_database_snapshot(snap_path, target=target)
        total = sum(results.values())
        typer.secho(f"\nSync complete! {total} records restored into {target}.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"\nSync failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@db_app.command("replication-setup")
def replication_setup(
    mode: str = typer.Option(
        "both", "--mode", "-m", help="Setup mode: 'publisher', 'subscriber', or 'both'."
    ),
    publication: str = typer.Option(
        "kb_live_pub", "--publication", help="Publication name."
    ),
    subscription: str = typer.Option(
        "kb_test_sub", "--subscription", help="Subscription name."
    ),
) -> None:
    """Sets up PostgreSQL logical replication between live (publisher) and test (subscriber)."""
    from .scripts.db_replication import setup_publisher, setup_subscriber

    mode = mode.lower().strip()
    if mode in ("publisher", "both"):
        typer.echo(f"Configuring publisher publication '{publication}' on kb_live...")
        res_pub = setup_publisher(publication_name=publication)
        if not res_pub.get("success"):
            typer.secho(f"Publisher setup warning: {res_pub.get('error')}", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"Publisher ready: {res_pub.get('message', 'OK')}", fg=typer.colors.GREEN)

    if mode in ("subscriber", "both"):
        typer.echo(f"Configuring subscriber subscription '{subscription}' on kb_test...")
        res_sub = setup_subscriber(subscription_name=subscription, publication_name=publication)
        if not res_sub.get("success"):
            typer.secho(f"Subscriber setup warning: {res_sub.get('error')}", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"Subscriber ready: {res_sub.get('message', 'OK')}", fg=typer.colors.GREEN)


@db_app.command("replication-status")
def replication_status(
    target: Optional[str] = typer.Option(
        None, "--target", "-t", help="Target database: 'live', 'test', or 'dev' (default: active)."
    ),
) -> None:
    """Inspects PostgreSQL replication slots, publications, and active subscriptions."""
    import json
    from .config import Config
    from .scripts.db_replication import get_replication_status

    cfg = Config()
    target_url = cfg.get_database_url_for_target(target) if target else cfg.database_url
    typer.echo("Querying PostgreSQL replication status...")
    status = get_replication_status(target_url=target_url)
    typer.echo(json.dumps(status, indent=2))


@db_app.command("backup-videos")
def backup_videos(
    max_backups: int = typer.Option(
        2, "--max-backups", help="Maximum number of video backup archives to retain."
    ),
) -> None:
    """Zips local YouTube videos into ~/.kb/kb-web_backups/ enforcing max retention (default: 2)."""
    from .video_manager import create_video_backup_zip

    typer.echo("Creating YouTube video backup ZIP...")
    try:
        archive = create_video_backup_zip(max_backups=max_backups)
        if archive and archive.exists():
            size_mb = archive.stat().st_size / (1024 * 1024)
            typer.secho(f"\nVideo backup created successfully: {archive.name} ({size_mb:.2f} MB)", fg=typer.colors.GREEN)
        else:
            typer.secho("\nNo videos found to backup.", fg=typer.colors.YELLOW)
    except Exception as e:
        typer.secho(f"\nVideo backup failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@db_app.command("restore-videos")
def restore_videos(
    archive: Optional[str] = typer.Argument(
        None, help="Filename or path of video backup ZIP. If omitted, uses newest backup."
    ),
) -> None:
    """Restores videos from a ZIP archive into ~/.kb/media/videos and re-indexes them."""
    from .video_manager import restore_video_backup_zip, list_video_backups

    if not archive:
        backups = list_video_backups()
        if not backups:
            typer.secho("No video backup archives found in backups directory.", fg=typer.colors.RED)
            raise typer.Exit(code=1)
        archive = backups[0]["path"]
        typer.echo(f"Restoring newest video backup archive: {backups[0]['filename']}")

    try:
        extracted = restore_video_backup_zip(archive)
        typer.secho(f"\nRestored {extracted} videos and synchronized database index.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"\nVideo restoration failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@db_app.command("reindex-videos")
def reindex_videos(
    target: Optional[str] = typer.Option(
        None, "--target", "-t", help="Target database: 'live', 'test', or 'dev' (default: active)."
    ),
) -> None:
    """Scans ~/.kb/media/videos and updates youtube_videos.local_path in the database."""
    from .config import Config
    from .video_manager import index_local_videos

    cfg = Config()
    target_url = cfg.get_database_url_for_target(target) if target else None
    typer.echo("Scanning media/videos and re-indexing local video records...")
    res = index_local_videos(config=cfg, target_db_url=target_url)
    typer.secho(
        f"\nIndexed {res['indexed_count']} local videos ({res['total_files']} files found).",
        fg=typer.colors.GREEN,
    )


if __name__ == "__main__":
    app()
