# Walkthrough - PostgreSQL Migration CLI, Replication, Video Retention & Admin Backups

We implemented the complete SQLite to PostgreSQL migration subsystem, PostgreSQL logical replication automation, multi-table point-in-time snapshot and sync tools, YouTube video media management with strict max-2 backup ZIP retention, and enhanced the Admin Dashboard with server-side backup management and WebSocket diagnostic fallbacks.

---

## Changes Made

### 1. SQLite to PostgreSQL Migration CLI & Script
- **[`src/kb_web/scripts/db_migrate_sqlite.py`](file:///c:/src/kb-web/src/kb_web/scripts/db_migrate_sqlite.py)**:
  - Migrates records in strict foreign-key dependency order across 20 tables: `collections` -> `fetched_pages` -> `page_versions` -> `article_embeddings` -> `title_embeddings` -> `youtube_videos` -> `video_embeddings` -> `collection_items` -> `collection_notes` -> `collection_actions` -> `chunk_embeddings` -> `site_wikis` -> `links` -> `settings_ollama` -> `settings_external` -> `agent_prompts` -> `cli_api_keys` -> `registered_clients` -> `system_logs` -> `ollama_logs`.
  - Strips PostgreSQL-incompatible NUL (`\x00`) characters from scraped webpage content.
  - Generates placeholder `FetchedPage` parent records for orphaned embeddings or YouTube video rows to maintain referential integrity without data loss.
  - Advances PostgreSQL primary key sequences (`setval`) after insertion.
  - **Live Verification**: Successfully migrated **6,504 records** from `.data/kb.db` into `kb_test` on `192.168.0.25:5432/kb_test`.

### 2. PostgreSQL Logical Replication & Alembic Publication
- **[`migrations/versions/b52a19d8c638_setup_pg_publication.py`](file:///c:/src/kb-web/migrations/versions/b52a19d8c638_setup_pg_publication.py)**:
  - Alembic migration creating `CREATE PUBLICATION IF NOT EXISTS kb_live_pub FOR ALL TABLES;` on PostgreSQL.
- **[`src/kb_web/scripts/db_replication.py`](file:///c:/src/kb-web/src/kb_web/scripts/db_replication.py)**:
  - `setup_publisher`: Creates publication `kb_live_pub` on live database.
  - `setup_subscriber`: Creates subscription `kb_test_sub` connecting `kb_test` to `kb_live`.
  - `get_replication_status`: Queries `pg_publication`, `pg_subscription`, and `pg_replication_slots`.

### 3. Database Snapshots & Live-to-Test Sync
- **[`src/kb_web/scripts/db_snapshot.py`](file:///c:/src/kb-web/src/kb_web/scripts/db_snapshot.py)**:
  - `create_database_snapshot`: Exports full multi-table JSON snapshots to `Config.backups_dir` (`~/.kb/kb-web_backups`).
  - `restore_database_snapshot`: Restores records from snapshot JSON files into target databases.
  - `sync_live_to_test`: Takes live snapshot and restores directly into test database.

### 4. YouTube Video Media Indexing & Max-2 Backup Retention
- **[`src/kb_web/video_manager.py`](file:///c:/src/kb-web/src/kb_web/video_manager.py)**:
  - `index_local_videos`: Scans `media/videos`, parses 11-character YouTube video IDs using regex, and updates `youtube_videos.local_path`.
  - `create_video_backup_zip`: Creates timestamped ZIP archives of all video media in `~/.kb/kb-web_backups/` and strictly enforces the **maximum 2 backups retention policy**, automatically pruning the oldest archives.
  - `restore_video_backup_zip`: Extracts video archives securely into `media/videos` and triggers automatic re-indexing.
  - `list_video_backups` and `delete_video_backup_zip`: Lists and manages video archives.

### 5. Unified CLI Station (`kb-web db`)
- **[`src/kb_web/cli.py`](file:///c:/src/kb-web/src/kb_web/cli.py)**:
  - Registered `db` subcommand group:
    - `kb-web db migrate-sqlite`: Migrate SQLite data to `dev`, `test`, or `live`.
    - `kb-web db deploy`: Deploy migrations to targets (`dev`, `test`, `live`, `all`).
    - `kb-web db snapshot`: Create point-in-time database snapshot.
    - `kb-web db sync-snapshot`: Sync live snapshot to test database.
    - `kb-web db replication-setup`: Setup logical replication pub/sub.
    - `kb-web db replication-status`: Inspect PostgreSQL replication slots and subscriptions.
    - `kb-web db backup-videos`: Create video backup ZIP (max 2 retention).
    - `kb-web db restore-videos`: Restore video backup ZIP.
    - `kb-web db reindex-videos`: Re-index local media files with database records.

### 6. Admin Dashboard UI & API Endpoints
- **[`src/kb_web/routers/admin.py`](file:///c:/src/kb-web/src/kb_web/routers/admin.py)**:
  - Local database backups: `/admin/backups/create`, `/admin/backups/download/{filename}`, `/admin/backups/restore`, `/admin/backups/delete/{filename}`, `/admin/backups/upload`.
  - Local video backups: `/admin/backups/videos/create`, `/admin/backups/videos/download/{filename}`, `/admin/backups/videos/restore`, `/admin/backups/videos/delete/{filename}`, `/admin/backups/videos/reindex`.
  - WebSocket diagnostic fallback: `GET /admin/ws/import` returning HTML explaining reverse proxy header drops and guiding to HTTP upload/local backups.
- **[`src/kb_web/templates/admin.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)**:
  - Added "Local Server Database Backups" and "YouTube Video Media Backups & Indexing" UI management cards.

### 7. Core Bug Fixes & Schema Adaptations
- **[`src/kb_web/models_orm.py`](file:///c:/src/kb-web/src/kb_web/models_orm.py)**:
  - Updated `SafeVector.process_bind_param` to deserialize stringified vectors (`json.loads`) before binding to `pgvector.sqlalchemy.Vector`.
  - Made `SafeVector(dim=None)` dimension optional, supporting 768-dimension `nomic-embed-text` vectors without length mismatch errors.
  - Added safe `dialect is None` handling in `SafeVector.process_bind_param` and `process_result_value`.
- **[`src/kb_web/config.py`](file:///c:/src/kb-web/src/kb_web/config.py)**:
  - Added `Config.get_db()` and `get_database_url_for_target(target)`.
  - Fixed `_read_db_setting` and `_write_db_setting` to use `get_db(self)`.

---

## Verification Results

### 1. Dedicated Integration & Unit Tests (`tests/test_db_cli.py`)
- Created 7 new automated tests covering:
  - `test_safe_vector_type`: Validated string, list, and dialect handling.
  - `test_video_manager_indexing`: Verified file discovery, ID extraction, and database record updating.
  - `test_video_backup_max_two_retention`: Verified strict maximum 2 archives retention with automatic pruning.
  - `test_video_backup_restore_and_delete`: Verified ZIP restoration and deletion.
  - `test_db_cli_help`: Verified all 9 `kb-web db` subcommands are registered.
  - `test_db_cli_reindex_and_backup_execution`: Verified CLI execution.
  - `test_admin_backups_and_diagnostic_routes`: Verified all backup API routes and WS HTTP fallback.
- **Result**: `7 passed in 32.28s`.

### 2. Full Pytest Suite
- Ran the entire test suite across all 54 tests:
  ```bash
  uv run pytest
  ====================== 54 passed, 48 warnings in 53.58s =======================
  ```

### 3. Pre-Commit Build Pipeline
- Executed `uv run python build.py`:
  - Synchronized virtual environment (`uv sync`).
  - Ran 54 unit tests (100% passed).
  - Built source distribution and wheel packages (`dist/kb_web-0.1.29-py3-none-any.whl`).
  - Built CLI submodule packages (`dist/kb_web_cli-0.1.0-py3-none-any.whl`).
  - Copied build artifacts to distribution repository.
  - `[SUCCESS] Build pipeline completed successfully!`.

### 4. Real SQLite to PostgreSQL Migration
- Migrated 6,504 records from `.data/kb.db` into `kb_test` database:
  - `collections`: 2
  - `fetched_pages`: 2,333
  - `page_versions`: 2,282
  - `article_embeddings`: 45
  - `title_embeddings`: 144
  - `youtube_videos`: 1,402
  - `video_embeddings`: 0
  - `collection_items`: 0
  - `collection_notes`: 0
  - `collection_actions`: 0
  - `chunk_embeddings`: 0
  - `site_wikis`: 3
  - `links`: 283
  - `settings_ollama`: 0
  - `settings_external`: 0
  - `agent_prompts`: 0
  - `cli_api_keys`: 1
  - `registered_clients`: 0
  - `system_logs`: 9
  - `ollama_logs`: 0
  - **Total**: 6,504 records migrated with zero data loss and sequences advanced.
