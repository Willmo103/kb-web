# User Feedback - SQLite to PostgreSQL Data Migration & DB Management CLI

## User Request (Initial)
"The Database switchover to postgresql was successful finally, but the use of the JSON data import has been removed from the codebase so the new production database has no data. we need a script to migrate the data from the production sqlite db to the postgesql db. *I want this script added to the CLI* so that it can be ran outside of the webserver instance, and have access to the the DB URL.

I removed the json configuration, relying only on environment variables for the configured values. I have a test database URL set in my env file that is valid and pointing to the local networked server databases which have been created. the app is running and I have a test server running the app, connected to the test database:

env
```
# Application Database URLs
# DATABASE_URL=postgresql://postgres:...@192.168.0.25:5432/kb_live
# For Local Dev:
KB_DEV_DATABASE_URL=postgresql://postgres:...@192.168.0.25:5432/kb_dev
DATABASE_URL=postgresql://postgres:...@192.168.0.25:5432/kb_dev
# For Test:
KB_TEST_DATABASE_URL=postgresql://postgres:...@192.168.0.25:5432/kb_test
# DATABASE_URL=postgresql://postgres:...@192.168.0.25:5432/kb_test
# DATABASE_URL=postgresql://postgres:password@localhost:5433/kb_test
```

you need to examine the json export proces and/or write a script that will take a sqlite db path and let the user select an option fom the 3 databases; kb_dev - development, test - a replicated copy of live, and live. 

In the kb-web cli (not the upload CLI) I want to add management to the databases; managing streaming or snapshot replication, taking and syncing snapshots of live, applying migrations to  live test and dev. 

In a migration, since we are strictly a postgres/sqlalchemy/alembic database stack not, we need to commit scripts that set up a publicaton in kb_live to publish streaming data, and a replication snapshot task on a schedule of live (some of these can be scripts).

in the API we need to examine the admin/ws/import route again:
```
[2026-09-08T06:14:09.443611] INFO in server: Completed request: GET http://kb.willmo.dev/admin/ws/import - Status: 404 - Duration: 0.008s
[2026-09-08T06:14:09.435915] INFO in server: Incoming request: GET http://kb.willmo.dev/admin/ws/import from 192.168.0.33
```
```
admin:470 WebSocket error: 
Event {isTrusted: true, type: 'error', target: WebSocket, currentTarget: WebSocket, eventPhase: 2, …}
```
It seems to be an error with the ws connection, but the downloading is fine. 
we can have the server look for backups locally in the (*newly created*) Config.backups_dir (`~/.kb/kb-web_backups`) *I created this myself, not yet committed*. 

we will create a local backup every time a backup is requested and then the user may download it, so it stays on the server with an option to restore or delete it. since I have access to the server I can just copy the backup json file over to the folder."

## User Feedback (Follow-up Turn)
"How will the local server-side youtube video download indexing? they should all still be where the code expects them to be, so they displayed. there needs to be a backup process that zips all videos and creates a backup locally (max: 2 backups) and allows it to be downloaded, (or restored/deleted)."

## Context & Objectives
1. **SQLite to PostgreSQL Data Migration**:
   - Provide a CLI migration command `kb-web db migrate-sqlite` to migrate all records from SQLite to PostgreSQL (`kb_dev`, `kb_test`, `kb_live`).
   - Fix `SafeVector` binding for string vector deserialization.
   - Advance PostgreSQL primary key sequences (`setval`) after migration.

2. **Database Management & Replication in CLI**:
   - Add a `kb-web db` command suite supporting migration deployment, snapshotting, snapshot sync between live and test, and streaming replication configuration.
   - Provide migration/scripts for PostgreSQL publication setup (`kb_live_pub`) and replication snapshot tasks.

3. **Admin Backup Management & Route Fix**:
   - Diagnose and address reverse-proxy WebSocket upgrade issues on `/admin/ws/import`.
   - Store local server backups in `Config.backups_dir` (`~/.kb/kb-web_backups`).
   - Allow listing, downloading, restoring, and deleting local backups from Admin UI and API.
   - Provide standard HTTP file upload fallback for backup restoration.

4. **YouTube Video Indexing & Backup ZIP Process**:
   - Ensure videos remain located in `~/.kb/media/videos` where `server.py` (`/media`) and `pages.py` expect them.
   - Implement `index_local_videos()` to scan `~/.kb/media/videos`, match video IDs against `youtube_videos`, and update `local_path` so offline video playback is indexed and consistent.
   - Implement video ZIP backup process: zips `~/.kb/media/videos` into `Config.backups_dir / kb_videos_backup_*.zip`, enforcing a strict **maximum of 2 video backups** (auto-pruning older archives).
   - Support downloading, restoring (unzipping and auto-reindexing), and deleting video backup ZIPs via both Admin UI and CLI (`kb-web db backup-videos`, `kb-web db restore-videos`, `kb-web db reindex-videos`).

## User Feedback (Turn 3)
"@[c:\src\kb-web\tests\test_db_cli.py:L219-L285] I need to disable this test in my github ci process when it runs. Everything is working and I have fully migrated the production data and we are now running on postgresql."

- **Resolution**:
  - Decorated `test_admin_backups_and_diagnostic_routes` in `tests/test_db_cli.py` with `@pytest.mark.skipif(os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("CI") == "true", reason="Skipped in GitHub CI environment")`.
  - Fixed dependencies in `pyproject.toml` (removed redundant `dotenv`, added `python-dateutil>=2.9.0`) so `pytest` and `uv` execute cleanly without missing module errors.
  - Verified local run executes and passes all 7 tests.
  - Verified simulated CI run (`GITHUB_ACTIONS=true`) cleanly skips `test_admin_backups_and_diagnostic_routes`.

