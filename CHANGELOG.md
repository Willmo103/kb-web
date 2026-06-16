# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.24] - 2026-06-16
### Added
- Implemented many-to-many collections schema with custom drag-and-drop ordering, visibility settings, and multi-select page assignment.
- Integrated character-level overlap text chunking (1500 limit, 150 overlap) with Google Gemma embeddings prefixing (`search_document: ` / `search_query: `) via Ollama.
- Implemented Qdrant client REST synchronization endpoints with Cosine distance and a 768-dimensional default vector space, including offline fallback JSON queuing.
- Added admin General Collection populator streaming route.
- Added line tail limits selection and text downloads to admin logs panel.
- Refactored URL import route to support synchronous HTML progress streaming.
- Updated database backups/restores JSON formats to support all database tables.

### Fixed
- Fixed process-level DB initialization locks and Gotify notification AttributeError bug.
- Aligned similarity graph legend badges to render correctly as inline-block elements.
- Cleaned up page listings by removing play buttons and making video/article cards fully clickable links.

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
