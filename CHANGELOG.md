# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
