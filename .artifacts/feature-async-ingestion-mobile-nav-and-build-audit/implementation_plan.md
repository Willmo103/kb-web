# Implementation Plan: Build Audit, Responsive Mobile Nav, and Resilient Async Ingestion Pipeline

**Branch**: `feature/async-ingestion-mobile-nav-and-build-audit`  
**Date**: 2026-10-12  

---

## 1. Overview & Objectives

This implementation plan addresses three critical areas identified by the user:

1. **Build Script Audit (`build.py`)**:
   - Eliminate unnecessary and slow steps: remove docker-compose database bootstrapping (`bootstrap_database`), package wheel/sdist builds (`uv build`, `python -m build`), and remote artifact copying (`copy_artifacts` to `ARTIFACTS_ROOT`).
   - Transform `build.py` into a lean, fast, reliable verification pipeline executing `uv sync` and `uv run pytest`.

2. **Mobile Navigation & Screen Containment Fix (`base.j2.html`, `view_page.j2.html`)**:
   - Prevent horizontal screen blowout on mobile phones caused by 11 nav buttons and action links in the header.
   - Implement a responsive navigation bar with a mobile hamburger toggle drawer.
   - Add viewport containment (`overflow-x: hidden`, `break-words`, `break-all`) on base layout and article viewer.

3. **Background Ingestion & Robust Async Pipeline (Eliminating the Loading Page)**:
   - **Eliminate the synchronous streaming loading page** (`/import/url` StreamingResponse); replace with immediate redirect and background task dispatch.
   - **Immediate Persistence (Never Lose Data)**: Save fetched content / YouTube transcript immediately to `FetchedPage` before running any LLM, guaranteeing zero data loss.
   - **Isolated, Re-runnable Stages**: Wrap wiki generation, tag extraction, vector embeddings, and video downloading in independent, re-runnable try/except stages.
   - **LLM Timeout**: Set Ollama client timeout to `1200.0` seconds (20 minutes) so prompts never timeout prematurely.
   - **User Notifications System**: Introduce `IngestionNotification` ORM model, `/api/notifications` REST endpoints, and an interactive real-time notification bell dropdown in the top navbar with toasts.

---

## 2. Proposed Changes & Technical Architecture

### Component 1: `build.py` Audit
- **Files**: `build.py`
- **Actions**:
  - Remove `bootstrap_database()` function and its socket/docker-compose retry loops.
  - Remove `copy_artifacts()` function and `ARTIFACTS_ROOT` checks.
  - Remove packaging steps `uv build` for root project and CLI submodule.
  - Simplify `clean_previous_builds()` to clean local `dist/` if present.
  - Keep core verification: environment sync (`uv sync`) and unit tests (`uv run pytest -k "not test_extension"`).

### Component 2: Responsive Mobile Navbar & Viewport Containment
- **Files**:
  - `src/kb_web/templates/base.j2.html`
  - `src/kb_web/templates/view_page.j2.html`
- **Actions**:
  - In `base.j2.html`:
    - Add responsive navbar:
      - Mobile header: Brand logo, notification bell, theme toggle, and hamburger button (`☰`).
      - Mobile collapsible drawer: Clean vertical stack for all navigation links (`Home`, `Sites`, `Videos`, `Collections`, `RAG`, `Notes`, `Taxonomy`, `Board`, `Studio`, `Reports`, `Links`) and action buttons (`+ Ingest URL`, `Admin Dashboard`, `Logout`).
      - Desktop (`lg:flex`): Existing sleek horizontal bar with unread notification bell.
    - Add `overflow-x: hidden` and max-width safety constraints to `html`, `body`, and container wrappers.
  - In `view_page.j2.html`:
    - Ensure article titles, URLs, and code blocks contain `break-words` and `break-all` to prevent stretching.

### Component 3: LLM Timeout Upgrade
- **Files**:
  - `src/kb_web/config.py`
  - `src/kb_web/base.py`
  - `src/kb_web/utils.py`
- **Actions**:
  - In `config.py`: Add `ollama_timeout: float = 1200.0` (configurable via `KB_OLLAMA_TIMEOUT`).
  - In `base.py`: Update `LoggedOllamaClient(timeout: float = 1200.0)` and `_get_ollama_client(timeout: float = 1200.0)`.
  - In `utils.py`: Increase `httpx.get` timeout in `fetch_url` to 60 seconds (with retry/fallback) for large pages.

### Component 4: Background Async Ingestion Pipeline & Immediate Persistence
- **Files**:
  - `src/kb_web/pipeline.py` (New dedicated module or `tasks.py`):
    - `run_ingest_pipeline_background(url, collection_id=None, new_collection_title=None, download_video=False)`:
      1. **Stage 1: Fetch & Instant Save**:
         - Fetch HTML / YouTube transcript.
         - **Extract all hyperlinks (`links`) from the raw, untouched HTML first** before any `<nav>`, `<header>`, `<footer>`, `<aside>`, or boilerplate tags are decomposed.
         - Normalize title and generate clean markdown using `html_to_clean_markdown`.
         - Immediately persist or update `FetchedPage` in the database.
         - If YouTube video, persist `YouTubeVideo` record.
         - Create notification: `status="success", stage="fetch", message="Fetched content: <title>"`.
      2. **Stage 2: Wiki Synthesis (Isolated)**:
         - Generate wiki digest with 1200s timeout.
         - Update `FetchedPage.description`.
         - Create notification: `status="success", stage="wiki", message="Wiki summary generated: <title>"`.
         - On exception: Keep raw markdown intact, log error, create notification: `status="failed", stage="wiki", message="Wiki generation failed: <error>"`.
      3. **Stage 3: Tag Extraction (Isolated)**:
         - Generate tags with Ollama.
         - Update `FetchedPage.tags`.
         - Create notification: `status="success", stage="tags", message="Tags extracted: <title>"`.
      4. **Stage 4: Vector Embeddings (Isolated)**:
         - Update `article_embeddings` and `chunk_embeddings`.
         - Create notification: `status="success", stage="vector", message="Indexed embeddings: <title>"`.
      5. **Stage 5: Offline Video Download (Isolated)**:
         - If requested, download video to disk and update `youtube_videos.local_path`.
         - Create notification: `status="success", stage="video", message="Downloaded offline video: <title>"`.
  - `src/kb_web/routers/admin.py`:
    - Remove the `StreamingResponse` loading page in `/import/url`.
    - Dispatch `run_ingest_pipeline_background` via `BackgroundTasks`.
    - Redirect immediately to `/view/page?url=<url>&msg=Import+started+in+background` (or `/import?msg=...`), with a clear flash notice.

### Component 5: User Notifications Backend & UI Feed
- **Files**:
  - `src/kb_web/models_orm.py`:
    - Add `IngestionNotification` ORM model:
      - `id`, `task_id`, `url`, `title`, `stage`, `status`, `message`, `created_at`, `read`.
  - `src/kb_web/routers/api.py`:
    - `GET /api/notifications`: Returns last 20 notifications + unread count.
    - `POST /api/notifications/read`: Marks notifications as read.
    - `POST /api/notifications/clear`: Clears notifications.
  - `src/kb_web/templates/base.j2.html`:
    - Add notification bell `🔔` with badge counter in header.
    - Add notification flyout drawer displaying real-time events, status icons, article links, timestamps, and "Clear" action.
    - Client-side polling (every 5 seconds) to refresh notification badge and trigger toast alerts.

---

## 3. Verification & Testing Strategy

1. **Unit Testing (`pytest`)**:
   - `tests/test_async_ingestion_and_notifications.py`:
     - Test `run_ingest_pipeline_background` immediate persistence: verifies `FetchedPage` exists even if subsequent LLM stages fail.
     - Test isolated stage recovery: verifies wiki generation failure does not abort or delete the saved article.
     - Test `IngestionNotification` model and `/api/notifications` REST endpoints.
     - Test `_get_ollama_client` timeout parameter (1200s).
   - Run full regression test suite: `uv run pytest -k "not test_extension"`.

2. **Build Script Verification**:
   - Run `uv run python build.py`.
   - Verify script completes fast without hanging on docker-compose, package packaging, or remote copying.

3. **Responsive UI Verification**:
   - Verify `base.j2.html` mobile navigation renders cleanly on viewport widths 360px–414px without horizontal overflow.
   - Verify article view (`view_page.j2.html`) does not blow out the screen.
