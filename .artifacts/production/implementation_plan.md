# Implementation Plan - SQLite to PostgreSQL Data Migration, DB Management CLI & Video Backup System

This plan introduces a complete database migration, synchronization, and management toolchain for `kb-web` following the switch from SQLite to PostgreSQL. It also implements YouTube video indexing maintenance and an automated ZIP backup system for local videos (retaining at most 2 backups) with full Admin UI and CLI controls.

## User Review Required

> [!IMPORTANT]
> **Video Storage Location & Indexing**:
> Downloaded YouTube videos will remain stored in `~/.kb/media/videos` (mounted at `/media/videos` by `server.py`). A new indexing routine will scan `~/.kb/media/videos`, parse video IDs from filenames, and synchronize `youtube_videos.local_path` in PostgreSQL to ensure seamless local video playback across migrations and server moves.

> [!IMPORTANT]
> **Video Backup Retention (Max 2 Backups)**:
> When creating a video backup ZIP, all videos in `~/.kb/media/videos` are archived into `~/.kb/kb-web_backups/kb_videos_backup_<timestamp>.zip`. The system automatically checks existing video archives and prunes the oldest archives to retain strictly at most 2 video backups. Restoring a video ZIP unzips it into `~/.kb/media/videos` and automatically re-indexes the database records.

> [!NOTE]
> **Database Targets Resolution**:
> The CLI supports three target environments via environment variables:
> - `dev`: `KB_DEV_DATABASE_URL` (defaults to `DATABASE_URL` if pointing to `kb_dev`)
> - `test`: `KB_TEST_DATABASE_URL` (replicated copy of live)
> - `live`: `DATABASE_URL` or `KB_LIVE_DATABASE_URL` (or assembled from `POSTGRES_*` settings with `kb_live`)

---

## Proposed Changes

### 1. YouTube Video Indexing & ZIP Backup System

#### [NEW] [video_manager.py](file:///c:/src/kb-web/src/kb_web/video_manager.py)
- `index_local_videos(config=None) -> dict`:
  - Scans `~/.kb/media/videos` for media files (`.mp4`, `.webm`, `.mkv`).
  - Extracts `video_id` from filename patterns (`[creator] - title [video_id].mp4`, `title [video_id].mp4`, `{video_id}.mp4`).
  - Connects to the database and updates `youtube_videos.local_path` with the canonical file path.
  - Returns count of indexed videos and missing matches.
- `create_video_backup_zip(config=None) -> Path`:
  - Zips all files in `~/.kb/media/videos` into `~/.kb/kb-web_backups/kb_videos_backup_%Y%m%d_%H%M%S.zip`.
  - Scans `~/.kb/kb-web_backups` for existing `kb_videos_backup_*.zip` files, sorts by timestamp, and removes older archives beyond the 2 most recent to enforce the **max 2 backups limit**.
  - Returns path to the new archive.
- `restore_video_backup_zip(zip_path: Path, config=None) -> int`:
  - Extracts ZIP contents into `~/.kb/media/videos`.
  - Calls `index_local_videos()` to re-index all restored files in the active database.
  - Returns count of extracted files.
- `list_video_backups(config=None) -> list[dict]`:
  - Returns metadata for local video backup ZIPs (filename, size, created timestamp).

---

### 2. Vector Type Binding & Config Database Settings

#### [MODIFY] [models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py)
- Update `SafeVector.process_bind_param` so that if `dialect.name == "postgresql"` and `value` is a string (e.g., JSON string `'[0.1, ...]'` from SQLite or JSON backups), it safely deserializes to a Python list using `json.loads(value)` before passing to `pgvector.sqlalchemy.Vector`. This prevents `ValueError: expected list or ndarray`.

#### [MODIFY] [config.py](file:///c:/src/kb-web/src/kb_web/config.py)
- Ensure `Config.backups_dir` is initialized (`data_root / "kb-web_backups"`) and auto-creates the directory when accessed.
- Fix `_read_db_setting` and `_write_db_setting` so SQLite fallback calls `from .db import get_db; db = get_db(self)` instead of the non-existent `self.get_db()`.
- Add helper methods to resolve database URLs for each environment (`dev`, `test`, `live`).

---

### 3. SQLite to PostgreSQL Data Migration Tool

#### [NEW] [db_migrate_sqlite.py](file:///c:/src/kb-web/src/kb_web/scripts/db_migrate_sqlite.py)
- Standalone migration module that can be invoked directly or via CLI.
- Connects to SQLite (e.g. `.data/kb.db` or user-specified path) and target PostgreSQL database (`dev`, `test`, or `live`).
- Migrates tables in foreign-key dependency order:
  1. `collections`
  2. `fetched_pages`
  3. `page_versions`
  4. `article_embeddings`
  5. `title_embeddings`
  6. `youtube_videos`
  7. `video_embeddings`
  8. `collection_items`
  9. `collection_notes`
  10. `collection_actions`
  11. `chunk_embeddings`
  12. `site_wikis`
  13. `links`
  14. `settings_ollama`
  15. `settings_external`
  16. `agent_prompts`
  17. `cli_api_keys`
  18. `registered_clients`
  19. `system_logs`
  20. `ollama_logs`
  21. `vault_master`, `repo_master`, `valid_repo_files` (if present)
- Performs chunked reading and batch insertion with transaction management.
- Resets PostgreSQL autoincrement primary key sequences (`setval`) after migration for tables with sequence IDs (`collections`, `collection_items`, `page_versions`, `chunk_embeddings`, `links`, etc.).
- Automatically triggers `index_local_videos()` if local video files exist.

---

### 4. Database Management & Video Subcommands in CLI

#### [MODIFY] [cli.py](file:///c:/src/kb-web/src/kb_web/cli.py)
- Add `db` Typer subcommand group:
  - `kb-web db migrate-sqlite`: Migrate data from SQLite to PostgreSQL with `--sqlite-path`, `--target` (`dev`/`test`/`live`), and `--batch-size`.
  - `kb-web db deploy`: Run schema migrations and initial seeding against `--target` (`dev`, `test`, `live`, or `all`).
  - `kb-web db snapshot`: Create a JSON/SQL snapshot of the selected target database and store it in `Config.backups_dir`.
  - `kb-web db sync-snapshot`: Take a snapshot of `kb_live` and restore it into `kb_test` so test is a replicated copy of live.
  - `kb-web db replication setup-publisher`: Connect to `kb_live` and configure publication `kb_live_pub` for logical streaming replication.
  - `kb-web db replication setup-subscriber`: Connect to `kb_test` and configure subscription from `kb_live`.
  - `kb-web db replication status`: Check status of PostgreSQL publications, subscriptions, and replication slots.
  - `kb-web db backup-videos`: Creates a ZIP archive of all local videos with max 2 retention.
  - `kb-web db restore-videos`: Restores a video ZIP archive and re-indexes the database.
  - `kb-web db reindex-videos`: Scans `media/videos` and updates `local_path` in `youtube_videos`.

---

### 5. Replication & Snapshot Automation Scripts and Alembic Migration

#### [NEW] [b52a19d8c638_setup_pg_publication.py](file:///c:/src/kb-web/migrations/versions/b52a19d8c638_setup_pg_publication.py)
- Alembic migration script that checks if the dialect is PostgreSQL, and if so, safely executes:
  `CREATE PUBLICATION IF NOT EXISTS kb_live_pub FOR ALL TABLES;`
  (with downgrade `DROP PUBLICATION IF EXISTS kb_live_pub;`).

#### [NEW] [db_replication.py](file:///c:/src/kb-web/src/kb_web/scripts/db_replication.py)
- Utility script for publication and subscription setup, health checks, and replication slot status.

#### [NEW] [db_snapshot.py](file:///c:/src/kb-web/src/kb_web/scripts/db_snapshot.py)
- Utility script for taking point-in-time snapshots of `kb_live`, pruning old backups, and syncing `kb_live` snapshots into `kb_test`.

---

### 6. Local Server Backup Management & Admin UI Enhancements

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- **Local Database Backup Persistence**:
  - Whenever `/admin/export` or a backup request is triggered, generate and persist the full database JSON export into `Config.backups_dir / f"kb_backup_{timestamp}.json"`, then stream/return the file for download.
- **Local Database Backup Endpoints**:
  - `POST /admin/backups/create`: Creates and saves local database backup JSON.
  - `GET /admin/backups/download/{filename}`: Downloads an existing database backup JSON.
  - `POST /admin/backups/restore`: Restores database from a local JSON backup.
  - `POST /admin/backups/delete`: Deletes a database backup JSON.
  - `POST /admin/backups/upload`: Direct HTTP multipart upload of backup file with optional immediate restore.
- **Local Video Backup Endpoints**:
  - `POST /admin/backups/videos/create`: Creates video backup ZIP (enforces max 2 retention).
  - `GET /admin/backups/videos/download/{filename}`: Downloads video backup ZIP.
  - `POST /admin/backups/videos/restore`: Restores from video backup ZIP and re-indexes videos.
  - `POST /admin/backups/videos/delete`: Deletes a video backup ZIP.
  - `POST /admin/backups/videos/reindex`: Re-indexes local videos.
- **WebSocket / Import Route Fix**:
  - Add `@router.get("/admin/ws/import")` returning an informative error/diagnostic response if a reverse proxy forwarded the request as plain HTTP GET.

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Add "Local Server Backups" and "Video Media Backups" sections to the Database Management tab:
  - Table displaying available database backups (JSON) and video archives (ZIP, max 2).
  - Actions per item: **Restore**, **Download**, **Delete** (with confirmation dialogs).
  - Buttons to **Create DB Backup**, **Backup Videos (ZIP)**, **Re-index Local Videos**.
  - Direct HTTP Upload Form for database backups.

---

## Verification Plan

### Automated Tests
- Run `uv run pytest` to ensure all existing and new tests pass.
- Add tests in `tests/test_db_cli.py`:
  - Test SQLite -> PostgreSQL migration logic.
  - Test `SafeVector` with JSON string representations.
  - Test local backup generation, listing, download, restore, and deletion routes.
  - Test video backup ZIP creation, max 2 retention pruning, extraction, and video indexing.
  - Test `kb-web db` CLI command entrypoints.
- Run `uv run python build.py` to ensure package build and verification passes.

### Manual Verification
- Test `kb-web db migrate-sqlite --target test` using `.data/kb.db` against `kb_test`.
- Verify row counts in `kb_test` match `.data/kb.db` across all tables.
- Test `kb-web db backup-videos` multiple times to verify max 2 retention rule.
- Test `kb-web db reindex-videos` and verify video resolution in `pages.py`.
- Test `kb-web db snapshot` and `kb-web db sync-snapshot`.
- Verify local database backup and video backup operations in the Admin UI.
