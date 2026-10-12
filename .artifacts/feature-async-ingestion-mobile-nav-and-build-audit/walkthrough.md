# Walkthrough: Async Ingestion Pipeline, Mobile Navigation, and Build Script Audit

## Overview
This sprint addresses critical pain points in `kb-web`:
1. **Production Deployment**: Merged previous HTML sanitization enhancements (`feature/html-boilerplate-stripper-and-cleaner`) to `production` via PR #84.
2. **Build Script Audit**: Streamlined `build.py` by removing Docker-compose loops, package building (`uv build`), and remote file copying.
3. **Pre-Boilerplate Hyperlink Extraction**: Added `extract_links_from_raw_html()` to harvest all links from raw, untouched HTML before navigation and footer boilerplate elements are decomposed.
4. **Resilient Background Ingestion Pipeline & Zero Data Loss**: Eliminated the blocking synchronous streaming loading page on `/import/url`, introduced immediate background execution with zero data loss guarantee (saving raw HTML and markdown immediately before any AI steps), and isolated downstream stages (Wiki synthesis, tag extraction, vector embeddings, video downloads).
5. **Real-Time Notification Feed & Global Toast System**: Added `IngestionNotification` tracking, REST endpoints (`/api/notifications`), header bell badge with dropdown menu, and auto-dismissing toast notifications.
6. **Responsive Mobile Navigation**: Resolved mobile viewport horizontal stretching by replacing the desktop button bar with a responsive navigation header, mobile hamburger toggle (`☰`), and collapsible mobile drawer menu.
7. **Extended LLM Timeout**: Configured prompt timeout to 1200.0s (20 minutes) across Ollama clients to prevent premature timeouts on long transcripts.

---

## Changes Implemented

### 1. Build Script Audit (`build.py`)
- Removed `bootstrap_database()` which executed `docker-compose up` and socket loops.
- Removed `copy_artifacts()` which attempted to copy packages to remote network shares.
- Removed packaging build calls (`uv build`).
- Kept lean, fast verification steps: `uv sync` and `uv run pytest -k "not test_extension"`.

### 2. Hyperlink Extraction Before Boilerplate Sanitization (`src/kb_web/html_cleaner.py`)
- Added `extract_links_from_raw_html(raw_html, base_url)`:
  - Parses raw HTML with BeautifulSoup before `<nav>`, `<header>`, `<footer>`, and `<aside>` tags are removed.
  - Extracts and resolves relative URLs into absolute URLs.
  - Deduplicates while preserving discovery order.
- Updated `fetch_url()` in `src/kb_web/utils.py` and `handle_html_import()` in `src/kb_web/routers/api.py` to extract links before calling `html_to_clean_markdown()`.

### 3. Background Ingestion Pipeline (`src/kb_web/pipeline.py`)
- Created `run_ingest_pipeline_background()`:
  - **Stage 1 (Fetch & Save)**: Immediately fetches content and saves `FetchedPage` to the database with hashes and timestamps. Guarantees zero data loss if downstream AI models fail.
  - **Stage 2 (AI Wiki Digest)**: Isolated execution with 1200.0s timeout. Skips if content hash matches existing record.
  - **Stage 3 (AI Tag Extraction)**: Isolated tag categorization.
  - **Stage 4 (Vector Embeddings)**: Chunking and Qdrant/Gemma vector embedding indexing.
  - **Stage 5 (Video Downloads)**: Optional yt-dlp download if requested.
- Updated `/import/url` in `src/kb_web/routers/admin.py` to dispatch `BackgroundTasks` and immediately redirect to `/view/page?url=...` with progress feedback.

### 4. Real-Time Notifications Feed & Toast Alerts
- **Database Model**: `IngestionNotification` in `src/kb_web/models_orm.py` with indexed fields for `task_id`, `url`, `stage`, `status`, `read`, and `created_at`.
- **API Endpoints (`src/kb_web/routers/api.py`)**:
  - `GET /api/notifications`: Returns recent notifications and unread count.
  - `POST /api/notifications/read`: Marks all unread notifications as read.
  - `POST /api/notifications/clear`: Purges stored notifications.
- **Frontend UI (`src/kb_web/templates/base.j2.html`)**:
  - Bell icon `🔔` with unread count pill badge in navbar.
  - Floating dropdown list displaying status icons (✅, ℹ️, ⚠️, ❌), stage names, timestamps, and "View Page →" links.
  - Floating toast container (`#toastContainer`) showing animated popups for new notifications.
  - Polling script fetching updates every 5 seconds.

### 5. Responsive Mobile Navigation (`base.j2.html` & `view_page.j2.html`)
- Replaced rigid horizontal nav links with:
  - Desktop links hidden on mobile (`hidden xl:flex`).
  - Mobile hamburger button `☰` (`xl:hidden`).
  - Full-featured mobile drawer menu `#mobileNavMenu` (`hidden xl:hidden`) with clean grid layout and dark mode styles.
- Added viewport containment (`overflow-x: hidden`, `break-words`, `overflow-x-auto`) to ensure zero horizontal blowout on small screens.

### 6. Extended LLM Timeout (`config.py` & `base.py`)
- Added `ollama_timeout` property to `Config` defaulting to `1200.0` seconds.
- Enforced 1200.0s timeout across `LoggedOllamaClient` and `_get_ollama_client()`.

---

## Verification Results

### Pre-Commit Tests
Ran full test suite:
```bash
uv run pytest -k "not test_extension"
```
**Results**:
- **165 passed**, 0 failed, 66 warnings in 172.53s.

### Build Verification
Ran audited build pipeline:
```bash
uv run python build.py
```
**Results**:
- Step 1 (`uv sync`): Resolved 84 packages, audited 83 packages.
- Step 2 (`uv run pytest -k not test_extension`): 165 passed in 172.53s.
- `[SUCCESS] Build verification pipeline completed successfully!`
