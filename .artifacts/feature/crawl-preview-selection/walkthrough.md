# Walkthrough: Webpage Crawl Discovery, Interactive Selection, and AI Pre-Checking

**Issue**: [#60](https://github.com/Willmo103/kb-web/issues/60)  
**PR**: [#57](https://github.com/Willmo103/kb-web/pull/57) (`production` -> `master`)  
**Branch**: `feature/crawl-preview-selection`  

---

## 1. Executive Summary

We implemented an interactive, two-stage webpage crawling and ingestion pipeline:
1. **Candidate Discovery Stage**: Explores a seed webpage, extracts clean internal hyperlinks, strips tracking params and anchor hashes, checks database ingestion status, and presents an interactive selection table with instant search filtering.
2. **AI Pre-Selection**: Employs an Ollama LLM with structured JSON output (`format="json"`) to automatically curate high-value technical articles and documentation while strictly filtering out foreign language variants (`/zh/`, `/es/`, `/ja/`, etc.), sitemaps, RSS feeds, legal/privacy boilerplate, and authentication routes. Supports custom user driving instructions.
3. **Background Scraping Queue**: Selected candidate URLs are enqueued into a non-blocking background queue with target collection grouping and completion notifications via Gotify and UI toasts.
4. **Server Logging Safeguard**: Resolved an underlying Alembic `fileConfig` issue that previously muted application and Uvicorn loggers across worker process lifecycles.

---

## 2. Key Changes & File Architecture

### Core Crawler Module
- **[src/kb_web/crawler.py](file:///c:/src/kb-web/src/kb_web/crawler.py)**:
  - `normalize_url(base_url, link)`: Resolves relative paths, strips anchor fragments (`#...`), cleans marketing tracking parameters (`utm_*`, `ref`), and rejects invalid protocols (`mailto:`, `javascript:`, `tel:`).
  - `extract_candidate_links(seed_url, same_domain=True, max_links=150)`: Fetches HTML using `httpx`, extracts page title and `<a>` tags, eliminates duplicates, and queries `FetchedPage` to flag `already_ingested: bool`.
  - `ai_curate_candidate_links(seed_url, page_title, links, custom_instructions=None, client=None)`: Leverages structured JSON generation (`{"selected_urls": [...], "explanation": "..."}`) with a strict curation prompt, language regex exclusions (`FOREIGN_LANG_REGEX`), and markdown cleanup fallback.
  - `run_batch_crawl_ingestion(urls, collection_id=None, collection_title=None)`: Background worker task that sequentially ingests selected pages with error handling, collection association, and Gotify alerts.

### REST Endpoints
- **[src/kb_web/routers/admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)**:
  - `POST /api/crawl/discover`: Extracts and returns candidate links from a seed URL with page metadata.
  - `POST /api/crawl/ai-filter`: Executes AI curation with custom instructions and returns filtered URLs and reasoning.
  - `POST /api/crawl/enqueue`: Submits chosen URLs into background ingestion tasks.

### Frontend UI & Templates
- **[src/kb_web/templates/url_import.j2.html](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html)**:
  - Added modern tabbed interface: "📄 Single Page Ingest" and "🕷️ Crawl & Discover URLs".
  - Interactive discovery controls: seed URL input, same-domain toggle, max links selector, custom AI instructions input.
  - Candidate table: live search filter, Select All / None / New Only controls, already-ingested status badges, and dynamic selection counter pill.
  - "🤖 AI Pre-Select" button with loading spinners and an AI curation reasoning banner.
  - Target collection selector with inline new collection modal.
  - Toast notifications confirming background enqueueing.
- **[src/kb_web/templates/view_page.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)**:
  - Added shortcut to launch deep interactive discovery directly from existing page profiles (`/import?mode=crawl&seed=...`).

### Alembic & Server Logging Fix
- **[migrations/env.py](file:///c:/src/kb-web/migrations/env.py)**:
  - Updated `fileConfig(config.config_file_name, disable_existing_loggers=False)` to prevent Alembic startup migrations from muting runtime Python loggers.
- **[src/kb_web/server.py](file:///c:/src/kb-web/src/kb_web/server.py)**:
  - Added `lg.disabled = False` in `setup_logging()` to guarantee server and application loggers remain active.

---

## 3. Verification & Testing

### Automated Test Suite
- **[tests/test_crawler.py](file:///c:/src/kb-web/tests/test_crawler.py)**:
  - `test_normalize_url`: Tests relative paths, fragment stripping, tracking parameter removal, and invalid scheme rejection.
  - `test_extract_candidate_links`: Tests anchor parsing, same-domain filtering, and `already_ingested` detection.
  - `test_ai_curate_candidate_links`: Tests structured JSON prompt handling, language variant filtering, and custom user driving instructions.
  - `test_api_crawl_endpoints`: Tests `/api/crawl/discover`, `/api/crawl/ai-filter`, and `/api/crawl/enqueue` with authenticated TestClient.
- **Full Suite**: 73 passing unit tests across the entire repository (`uv run pytest`).
- **UI Template Check**: 0 warnings across all 14 Jinja2 templates via `verify_ui_templates.py`.
- **Package Build**: Clean source distribution and wheel compilation via `build.py`.
- **VCS UAT Artifacts**: Generated report `uat/reports/uat_report_crawl_preview_selection_20260913_195001.md` and log `uat/logs/test_log_crawl_preview_selection_20260913_195001.log`.
