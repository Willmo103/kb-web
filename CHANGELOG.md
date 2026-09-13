# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-09-12
### Added
- **UI Performance & Latency Overhaul with Database View (Resolves #56)**:
  - Created pre-aggregated PostgreSQL database view `vw_page_cards` joining `fetched_pages`, `youtube_videos`, and `collections` with `string_agg(c.title, ', ')`, completely eliminating N+1 collection queries on index feeds.
  - Added targeted database performance indexes on `fetched_pages.fetched_at DESC`, `collection_items.source_id`, and `youtube_videos.creator` in Alembic migration `c72b89d412e1_add_page_card_view_and_indexes.py` and `ensure_views_and_indexes()`.
  - Added dedicated, high-performance REST API router `src/kb_web/routers/rest_api.py` serving lightweight JSON payloads for web frontends and external client agents:
    - `GET /api/articles`: Paginated article cards with search (`q`), tag filtering (`tag`), sort order, and metadata.
    - `GET /api/articles/detail`: Full article details with markdown and raw HTML (on-demand only).
    - `GET /api/videos`: Paginated YouTube video profiles with creator aggregation and duration/view counts.
    - `GET /api/videos/transcript`: Timestamped subtitle transcript extraction and segment parsing (`[MM:SS]` formatting).
    - `GET /api/sites`: Virtual domain directory grouped by hostname and article counts.
    - `GET /api/tags`: Tag cloud index with frequency counts.
  - Added responsive UI pagination and dynamic reactive search controls to `src/kb_web/templates/pages_list.j2.html`:
    - Responsive pagination bar with Previous/Next buttons, active page pills, item counters, and limit selector.
    - Client-side reactive JavaScript controller with 300ms search input debouncing, animated skeleton loading placeholders (`animate-pulse`), and seamless URL address bar state synchronization (`history.pushState`).
    - Added comprehensive unit test suite in `tests/test_rest_api.py` covering pagination bounds, query filtering, transcript segment extraction, and HTML shell responses.

### Changed
- **Phasing out SQLite in favor of PostgreSQL as Primary Storage Engine**:
  - Initiated deprecation of SQLite as primary production storage engine; optimized database queries, views, and indexes specifically for PostgreSQL.
  - Excluded heavy `html_content` and `md_content` fields from default article hydration queries to minimize network transfer overhead.
  - Optimized virtual site domain extraction in `view_all_pages` to project only `(url, title)` instead of full table scans.

### Fixed
- Fixed `AttributeError` / `OperationalError` during database snapshot export by ignoring database views in `db_snapshot.py`.
- Excluded view models from `Base.metadata.create_all()` to prevent accidental table creation before view instantiation.
- Resolved `NameError: name 'func' is not defined` in `src/kb_web/routers/pages.py`.
- Replaced deprecated `regex` parameter with `pattern` in FastAPI Query annotations across `rest_api.py`.

## [0.2.0] - 2026-09-09
### Added
- **Complete PostgreSQL & SQLAlchemy Migration (Resolves #30)**:
  - Migrated core database operations, models, configurations, and logs to SQLAlchemy ORM, providing complete dialect-agnostic support for SQLite and PostgreSQL (resolving #43, #46).
  - Implemented custom SQLAlchemy TypeDecorator `SafeVector` that dynamically maps to `pgvector.sqlalchemy.Vector` on PostgreSQL and a JSON-encoded Text fallback on SQLite (resolving #42).
  - Added custom comparator support for `SafeVector` (defining `.cosine_distance()`, `.l2_distance()`, and `.max_inner_product()`) that automatically delegates to pgvector comparators under PostgreSQL (resolving #42).
  - Implemented thread-safe connection pooling, dialect configuration in `Config`, and transaction-managed `db_session` middleware (resolving #44).
  - Added automatic PostgreSQL sequence synchronization (`setval`) inside database initialization and seeding routines.
  - Closed Sprint 2 (#41) and Sprint 3 (#45) milestones.
- **Unified Database CLI Suite (`kb-web db`, Resolves #47)**:
  - `migrate-sqlite`: Migrate SQLite database to PostgreSQL environments (`dev`, `test`, `live`) in foreign-key dependency order, sanitizing NUL characters, auto-generating parent stubs for orphaned records, and syncing sequences.
  - `deploy`: Deploy migrations across targets (`dev`, `test`, `live`, `all`) and ensure PostgreSQL pgvector column compatibility.
  - `snapshot`: Create point-in-time multi-table JSON snapshots of database tables saved locally in `Config.backups_dir`.
  - `sync-snapshot`: Synchronize snapshots from live database directly into test database.
  - `replication-setup`: Automated publisher (`kb_live_pub`) and subscriber (`kb_test_sub`) setup for PostgreSQL logical replication.
  - `replication-status`: Real-time inspection of PostgreSQL replication slots, publications, and active subscriptions.
  - `backup-videos`: Automated ZIP archive backup of all local YouTube videos with strict retention of maximum 2 archives.
  - `restore-videos`: Restores YouTube video files from backup ZIP into `media/videos` with automatic database indexing.
  - `reindex-videos`: Scans `media/videos` directory, extracts YouTube video IDs, and links them to `youtube_videos.local_path`.
- Added Alembic migration `b52a19d8c638_setup_pg_publication.py` setting up `CREATE PUBLICATION IF NOT EXISTS kb_live_pub FOR ALL TABLES;` on PostgreSQL.
- Added video management subsystem (`video_manager.py`) with recursive media scanning, video ID regex parsers, automated 2-backup max ZIP retention, and index repair.
- Added server-side local backup storage in `Config.backups_dir` (`~/.kb/kb-web_backups`) with full Admin Dashboard UI controls for creating, downloading, restoring, and deleting database JSON and video ZIP archives.
- Added diagnostic fallback for `/admin/ws/import` on HTTP GET requests when reverse proxies drop WebSocket Upgrade headers, alongside direct HTTP multipart file upload.

### Fixed
- Resolved `ValueError: expected list or ndarray` in `SafeVector` by deserializing JSON vector strings before binding to `pgvector.sqlalchemy.Vector`.
- Removed hardcoded dimension restriction from `SafeVector` in `models_orm.py`, allowing 768-dimension `nomic-embed-text` vectors without length mismatch errors.
- Fixed `AttributeError: 'Config' object has no attribute 'get_db'` by implementing `Config.get_db()` and fixing settings read/write helpers.
- Resolved `ValueError: A string literal cannot contain NUL (0x00) characters` during PostgreSQL imports by stripping NUL bytes in `clean_record` and `websocket_import`.
- Resolved `ForeignKeyViolation` on migration from SQLite by synthesizing placeholder parent records in `fetched_pages` for orphaned embeddings and video rows.
- Fixed `export_database` and snapshot creation when running in SQLite or default target mode.
- Updated automated unit test suite (`pytest`) to run against parameterized sqlite/postgresql dialects, resolving foreign keys, binary serialization, and dimensions assertions.

## [0.1.32] - 2026-08-13
### Added
- Implemented duplicate URL import verification across UI, CLI, and REST endpoint pipelines, archiving changed pages to `page_versions` and bypassing LLM processing on identical content (resolving Issue #33).
- Added parallel background video downloading option to the URL import page, complete with dynamic JavaScript detection of YouTube URLs (resolving Issue #34).

### Fixed
- Resolved `sqlite3.OperationalError: database is locked` errors during test suite execution by fully consuming streaming responses in test client requests and closing database connections immediately after use.
- Avoided `sqlite_utils.db.NotFoundError` crashes on duplicate checks for new URLs by using `rows_where` queries instead of `get`.

## [0.1.31] - 2026-08-12
### Security
- Added `Depends(verify_auth)` to the `GET /links` and `GET /links/go` endpoints, securing the saved links views and tracking from unauthorized users (resolving Issue #31).

### Fixed
- Globally mocked `kb_core.notifier.Gotify` in the test suite setup fixture (`tests/test_server.py`) to prevent real alerts and notifications from being fired during automated tests.

### Documented
- Added documentation under the Running Automated Tests section of `README.md` and init rules of `GEMINI.md` to guide developers on disabling Gotify notifications when running test suites.

## [0.1.30] - 2026-08-10
### Added
- Implemented `kb-cli logs` command in CLI tool allowing remote inspection of server system logs with `--limit` parameter persistence.
- Added `GET /api/cli/logs` endpoint in CLI API router returning database system logs (ordered by most recent first).
- Added clipboard copy button (`📋 Copy`) next to redacted CLI API keys in Admin Dashboard with HTTPS and HTTP fallback support.

### Changed
- Converted layout containers across all web templates (`admin`, `collection_editor`, `collections`, `logs`, `pages_list`, `similarity_graph`, `sites_list`, `view_collection`, `view_page`, `view_site`, `base`) from static max-widths (`max-w-4xl`, `max-w-5xl`, `max-w-6xl`, `max-w-7xl`) to reactive full-width `max-w-[95%] w-full` layout containers.
- Increased default Ollama client connection timeout from 90s to 300s in `src/kb_web/base.py` and CLI HTTP client timeouts to 300s in `kb-web-cli/src/kb_web_cli/main.py` to prevent timeout errors during Ollama cold-starts and heavy model reasoning calls.

## [0.1.29] - 2026-08-07
### Added
- Implemented regular webpage links saving and cataloging dashboard (`/links`).
- Added click usage and redirection tracking (`/links/go?id=...`) to increment click count and record last clicked timestamp.
- Implemented Chromium standard HTML bookmarks file importer to upload and bulk populate saved links directory.
- Restored the missing `generate_gemma_embeddings_for_page` implementation block.

### Fixed
- Fixed Ollama reasoning `think` parameter compatibility crashes with older Ollama servers by only passing the argument conditionally when enabled.
- Propagated exceptions in `extract_wiki_content` and `extract_tags_content` so that ingestion failures show actual errors instead of silently creating broken `"Ingestion Backup"` pages.
- Broken circular dependency import inside `cli_api.py` by importing the Jinja2 environment from `..base`.

## [0.1.28] - 2026-08-05
### Added
- Implemented standalone CLI package `kb-web-cli` as a nested git submodule containing `kb-cli` console command executable wrapper.
- Added server-side CLI API router endpoints (`/api/cli`) exposing client registration, synchronous ingestion, tag/collection updates, and context-aware RAG agent query tasks.
- Integrated dashboard CLI Integration configuration card panel, displaying generated API keys, registered computer terminal clients, and administrative revoke action forms.
- Added comprehensive unit test suite `test_cli_client_server_integration` verifying full REST/CLI flow.

## [0.1.27] - 2026-08-04
### Added
- Implemented descriptive YouTube video filenames formatting as `[Creator] - Title [VideoId].mp4` upon local offline downloads.
- Added a directory-scan matching fallback to dynamically check `media/videos/` for any filenames matching `*{video_id}*`, preventing breakage from stale database paths.
- Added comprehensive mock unit test `test_descriptive_video_download_and_resolution` to assert filename pattern and dynamic resolution.

### Fixed
- Fixed directory glob lookup character-range patterns parsing bug for filenames containing square brackets `[` `]` by utilizing direct filesystem iterators.

## [0.1.26] - 2026-08-04
### Added
- Migrated all configuration settings (Ollama, Gotify, Qdrant details) to the database with dynamic, thread-safe sync.
- Implemented system prompt versioning and curation in the database (via table `agent_prompts`), displaying full history dropdowns and providing "Use This Version" rollback buttons in the Admin Dashboard.
- Added a quick "Assign Item" collections sidebar form on the Collections dashboard.
- Appended robust unit tests verifying video offline badge states, DB config migrations, prompt rollback operations, and log limits persistence.

### Fixed
- Fixed YouTube videos missing the collections badge, collection form dropdowns, and "Change Collections" action details by correctly passing collection template variables.
- Fixed collections created via `/import` screen being created as private by default, updating them to public to match standard collections dashboards.
- Fixed collections created via `/import` screen setting incorrect `source_type` ("articles") for video URLs, dynamically resolving it to "videos".
- Fixed offline video player detection logic to check both the DB-recorded path and the default location in the media directory for offline files.
- Fixed server log display to sort in reverse chronological order (most recent first) across log rendering and downloads.
- Implemented persistent line limit preferences on server logs using request cookies, defaulting limit options to 100.

## [0.1.25] - 2026-08-01
### Fixed
- Fixed YouTube transcript wiki generation hangs by disabling reasoning latency (`think=False`) for intermediate chunk summaries.
- Fixed FastAPI event loop blocking hangs by wrapping synchronous ingestion steps (`fetch_url`, `extract_wiki_content`, etc.) in a threadpool utilizing `run_in_threadpool`.
- Fixed background tasks thread-safety by opening a new connection handle via `_get_db()` within worker functions instead of sharing the request's database connection.
- Optimized tag extraction and collection suggestions by setting `think=False` to prevent unnecessary reasoning delays.
### Removed
- Excised the entire cron job scheduler and management subsystem:
  - Deleted `cron_scheduler.py` and `src/kb_web/routers/cron.py`.
  - Deleted UI templates `cron_jobs.j2.html` and `view_cron_job.j2.html`.
  - Removed table initializations for `cron_jobs` and `cron_job_runs` in `src/kb_web/db.py` and added a startup routine to drop these tables if they exist.
  - Excised all references in `server.py` and `graph.py`.

## [0.1.24] - 2026-07-25
### Added
- Condensed all history, architecture, and agent instructions into package-level `GEMINI.md`.
- Implemented sub-divided development rules in `.agent/rules/` (`development_rules.md`, `documentation_rules.md`, `python_coding_rules.md`, `git_rules.md`, `uat_and_ui_testing_rules.md`, `ui_component_uat_rules.md`, `vcs_testing_artifact_rules.md`, `custom_html_feedback_rules.md`).
- Implemented automated UAT testing & feedback skills in `.agent/skills/`:
  - `collect-uat-feedback-and-create-issues`: Interactive HTML feedback form template (`uat_feedback_form.html`) and issue parser script (`parse_uat_issues.py`) to convert user JSON submissions into actionable agent tasks.
  - `generate-uat-testing-artifact`: Script (`generate_uat_report.py`) and template (`uat_report_template.md`) to generate VCS-tracked test logs and reports in `uat/`.
  - `ui-component-uat-check`: Automated Jinja2 template & theme verifier script (`verify_ui_templates.py`).
  - Added skills for `pre-commit-checks`, `document-code-issue-and-fix`, `kb-web-browser-extension`, and `kb-web-service-management`.

## [0.1.23] - 2026-06-14
### Changed
- Fixed invisible collections action buttons.
- Allowed accepting multiple AI suggestion groupings consecutively without page reload using AJAX updates.
- Added think=False argument to all remaining Ollama chat sessions to disable reasoning latency.

## [0.1.22] - 2026-06-14
### Added
- Refactored and modularized `server.py` into FastAPI APIRouters under `src/kb_web/routers/` (auth, pages, sites, admin, api, collections, cron, graph) and helper libraries (`utils.py`, `gotify.py`, `cron_scheduler.py`).
- Implemented custom user Collections manager with CRUD operations, inline collection classification, and AI-suggested group recommendations using Ollama.
- Fixed HTML attribute escaping inside the AI collection suggestions acceptance forms, resolving formatting and unclosed quote bugs during submission.
- Passed format="json" option to Ollama client.chat and added regex-based fallback to guarantee robust parsing of AI collection suggestions responses.
- Created interval-based scheduled Cron Jobs configuration dashboard with execution run history logging, generated outputs download, and success/failure notification triggers.
- Integrated Obsidian-style interactive visualizer using Vis.js representing embedding similarity relationships between pages, sites, creators, and tags.
- Embedded a server log viewer panel directly in the admin dashboard tailing the `kb-web.log` stream.
- Setup Gotify tracebacks logging to push uncaught exceptions and context variables directly to administrators.

## [0.1.21] - 2026-06-13
### Added
- Implemented layout fix for YouTube iframe container on Tailwind CSS v2 via explicit aspect-ratio style.
- Implemented text chunking helper `chunk_text` and segmented ingestion/synthesis pipeline to handle long documents/transcripts safely (preventing Ollama context overload crashes).
- Integrated `max_input_length` config property (default 20,000 chars) with environment/json loading/saving, and added form control in admin panel.
- Eliminated standalone Tags page and replaced navbar "Tags" link with "Videos" (linking to `/?view=videos`).
- Simplified Video creator filtering by removing sidebar count listings and showing a clear filter header on creator selections.
- Implemented tag query param filter on main route to render a unified matching articles and videos grid.
- Converted all tag displays and creator metadata labels to active clickable links.

## [0.1.20] - 2026-06-13
### Added
- Created a separate `youtube_videos` database table referencing `fetched_pages` to decouple and represent YouTube uploader metadata.
- Implemented dedicated YouTube videos section (`/?view=videos`) filterable by uploader/creator.
- Added responsive embedded YouTube iframe display directly on the viewing page of video articles.
- Added specialized `youtube_wiki_prompt` system configuration for synthesizing structured chronological video breakdowns with timestamped quotes.
- Implemented markdown list preprocessor to fix single asterisk formatting issues and insert preceding spacing.
- Added `kb-web-mcp.service` configuration file and exposed sse host/port binding parameters in CLI `mcp` start commands.
- Added video details/attributes block rendering (creator, duration, views, channel ID) on the video viewing page.
- Added a "Regenerate Video Attrs" action button and `/admin/regenerate/youtube-metadata` POST endpoint to re-fetch/update video metadata from YouTube.
- Added duration overlays and formatted view counts to the video listing card grid.
- Fixed video validation parsing skipping by declaring optional YouTube-specific fields on the HTMLPage Pydantic model.

## [0.1.19] - 2026-06-07
### Changed
- Simplified site profiles (`/view/site`) to only display the listing of scraped pages under that domain, removing legacy Ollama site-wide wiki generation and cached table references.
- Re-styled page viewer buttons layout to a vertical flex-column formatted directly to the right of the title block.
- Removed tag badges from similar articles in the left sidebar panel.
- Updated unit tests to align with simplified sites logic.

## [0.1.18] - 2026-06-06
### Added
- Created virtual sites index view (`/sites`) and individual site profile views (`/view/site`).
- Added database caching via `site_wikis` table for consolidated site-wide wikis synthesized by Ollama.
- Integrated same-domain scraped links grid on `/view/page` route with confirmation modal ingestion pipelines.
- Rendered original scraped markdown content as styled HTML inside collapsible details element.
- Positioned semantically similar articles panel inside a sticky left sidebar.
- Added `test_virtual_sites` unit test covering new routes, grouping logic, and wiki compilation.

## [0.1.15] - 2026-06-05
### Changed
- Refactored authentication to use stateless, cryptographically signed session cookies (HMAC-SHA256), resolving Gunicorn write contention and database locks.
- Removed legacy `active_sessions` database table and replaced write-on-read token evictions with lock-free CPU checks.
- Implemented thread-local database cache (`threading.local`) and synchronized schema initialization (`init_db`) inside a thread lock.
### Added
- Integration tests `test_get_requests_are_write_free` and `test_concurrent_reads_no_lock` to assert zero write queries on GET requests and thread safety under concurrent requests.

## [0.1.14] - 2026-06-05
### Fixed
- Enabled WAL (Write-Ahead Logging) mode on database connection to allow concurrent reads and writes from multiple Gunicorn processes.
- Set connection timeout to 30 seconds to prevent `database is locked` OperationalErrors during concurrent logins or writes.

## [0.1.13] - 2026-06-05
### Changed
- Replaced in-memory `ACTIVE_SESSIONS` cache with a persistent `active_sessions` table in SQLite database. This fixes session drops across Gunicorn worker processes and server service restarts.
- Modified logout handler to clear active session entries from the persistent SQLite database.

## [0.1.12] - 2026-06-05
### Fixed
- Fixed YouTube video transcript extraction on newer versions of `youtube-transcript-api` that use instance-based APIs.
- Silenced `yt-dlp` warning output regarding missing `ffmpeg` and JavaScript runtimes on target server environments.
- Cleaned up unused imports in testing module.

## [0.1.10] - 2026-06-04
### Added
- Model Context Protocol (MCP) server stdio API integration.
- YouTube transcript and metadata fetching using `youtube-transcript-api` and `yt-dlp`.
- Tags catalog and filtered article index views.
- Description and tag vector embeddings cache using Ollama's embeddings API, plus similar articles lookup.
- Desktop browser bookmarklet support for 1-click sharing.
### Changed
- Refactored verify_auth and login to support next query parameter redirects.
- Changed URL import form input validation to support parsing URLs from copy-pasted blocks.

## [0.1.9] - 2026-06-03
### Added
- FastAPI server with multi-platform Gunicorn/Uvicorn runner.
### Changed
- Added clean steps to `build.py` to purge previous dist artifacts.

## [0.1.8] - 2026-06-01
### Added
- Gunicorn support for production deployments with a CLI integration.

## [0.1.7] - 2026-06-01
### Added
- Admin dashboard with server configuration, pipeline management, and database import/export tools.

## [0.1.6] - 2026-05-31
### Fixed
- Resolved systemd service configuration paths and setup requirements.

## [0.1.5] - 2026-05-31
### Changed
- Updated `ExecStart` path to point to virtual environment binary in `kb-web.service`.

## [0.1.4] - 2026-05-31
### Added
- Service installation and management scripts for production deployment.

## [0.1.0] - 2026-05-30
### Added
- Initial project release with bookmarks database, FastAPI curation ingestion API, and browser extensions integration.
