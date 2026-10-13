# Implementation Plan: Mobile Views Polish, Dedicated Articles Page, and Autonomous Background Server Worker

**Branch**: `feature/mobile-views-articles-page-and-background-tasks`  
**Target Release**: `v9.1.0` / Next Feature Increment  
**Status**: In Review & Ready for Approval  

---

## 1. Problem Statement & Objectives

1. **Mobile Views & Admin Layout Polish**:
   - **Header Brand Title on Mobile**: On mobile viewports (< 640px), the brand title `Knowledge Base` is hidden by `hidden sm:inline`, leaving only the stack of books emoji (`📚`). We need the title to remain cleanly visible on mobile screens.
   - **Admin Portal Desktop Margins**: The lower sections under the Backups & Database tab (`tab-backups` in `admin.j2.html`)—specifically *Server Database Snapshots* and *Administrative Batch Operations & Content Purge*—suffer from cramped vertical spacing and lack bottom margins. We need clear visual separation and generous margins (`space-y-8`, bottom margins).
   - **Admin Portal Mobile Tab Navigation**: The tab bar currently uses `overflow-x-auto`, which forces a horizontal scrollbar on mobile screens. The user requests static buttons for mobile view rather than horizontal scrolling.
   - **Home Page Left Nav on Mobile**: In `pages_list.j2.html`, the left sidebar navigation (`<aside>`) is displayed on mobile before the main content, cluttering the mobile view. Since the global header navbar now includes a collapsible hamburger drawer menu, the left sidebar should be hidden on mobile/tablet screens (`hidden lg:block`).

2. **Dedicated Articles Page (`/articles`)**:
   - Currently, `/` and `/?view=articles` are conflated. There is no dedicated `/articles` route or top navbar link for Articles.
   - Create a dedicated `/articles` route that serves an articles-only list, and ensure the `📄 Articles` link is accessible from all pages across the desktop navbar (`base.j2.html`), mobile hamburger drawer, and sidebar.

3. **Autonomous Background Server Worker Engine**:
   - Web imports can now be saved immediately before AI wiki extraction or tagging finishes.
   - Build a reliable periodic background worker running every $X$ minutes that scans for records lacking wikis or tags and processes them one at a time, failing gracefully on LLM downtime or parse errors without crashing the server.
   - Design an extensible task hook architecture for future autonomous capabilities (e.g., generating index QA questions, testing RAG results, crawling links autonomously).
   - Provide and compare architecture options (Native in-process worker vs. Sidecar daemon vs. n8n workflow vs. Supabase pg_cron).

---

## 2. Background Task Architecture Options Analysis

| Architecture Option | How It Works | Strengths | Trade-offs & Limitations |
| :--- | :--- | :--- | :--- |
| **Option A: Native In-Process Async Worker (Recommended)** | An asynchronous background loop initialized during FastAPI application lifespan (`server.py`) using `asyncio.create_task` and non-blocking threadpools. Configured via env (`KB_WORKER_ENABLED=true`, `KB_WORKER_INTERVAL_MINUTES=5`). | • Zero extra infrastructure or services needed.<br>• Native access to SQLAlchemy ORM, Ollama, Qdrant, and in-app notifications.<br>• Works offline and in local development out of the box.<br>• Exposes REST endpoints (`/api/worker/cycle`, `/api/worker/status`) so other tools can also trigger it. | • Tied to the web server process lifecycle.<br>• Long blocking operations must strictly run in threadpools to avoid blocking the event loop. |
| **Option B: Standalone Sidecar Daemon (`kb-web-worker`)** | A standalone CLI daemon (`kb-web-cli worker --interval 300`) run as an independent systemd service (`kb-web-worker.service`), similar to `kb-web-mcp.service`. | • Complete OS-level process isolation from the web server.<br>• Heavy LLM inferences never compete for web server event loop or memory.<br>• Can be restarted independently. | • Requires configuring and monitoring an additional systemd service.<br>• More overhead for lightweight or single-server deployments. |
| **Option C: n8n Workflow Automation Layer** | An external self-hosted n8n instance triggers scheduled cron workflows (`*/5 * * * *`), calls `kb-web` REST API endpoints (`/api/worker/cycle`), or runs Ollama nodes directly. | • Visual workflow builder with drag-and-drop orchestration.<br>• Rich alerting connectors (Slack, Discord, Telegram, Gotify, Email).<br>• Great if the user already runs n8n for other workflows. | • Requires maintaining a separate n8n Docker container / server.<br>• Adds network latency and API authentication overhead.<br>• If n8n crashes, background curation stops. |
| **Option D: Supabase / PostgreSQL `pg_cron` + Webhooks** | If utilizing Supabase / PostgreSQL, `pg_cron` triggers a periodic HTTP call via `pg_net` to `POST /api/worker/cycle` every 5 minutes. | • Native to the PostgreSQL database engine.<br>• Resilient and decoupled from web application restarts.<br>• Great fit for users standardizing on Supabase. | • Requires PostgreSQL extensions (`pg_cron`, `pg_net`) which may not be present in standard local PostgreSQL or SQLite.<br>• Database triggers cannot run Ollama LLMs directly, so it still needs to invoke an HTTP worker endpoint. |

### Proposed Architecture Strategy: The Hybrid Engine
We propose implementing **Option A as the built-in default engine** inside `kb-web` with:
1. Native background scheduler running automatically in the web service.
2. REST API endpoints (`POST /api/worker/cycle`, `GET /api/worker/status`, `POST /api/worker/toggle`) so that if the user wants to trigger it externally via **n8n (Option C)** or **Supabase `pg_cron` (Option D)**, they can do so seamlessly!
3. Admin dashboard panel in `admin.j2.html` allowing the admin to view worker status, trigger an immediate cycle, or change intervals.

---

## 3. Detailed Implementation Steps

### Phase 1: Mobile Views & Navigation Polish
1. **Header Brand Title on Mobile (`src/kb_web/templates/base.j2.html`)**:
   - Change line 416 from `hidden sm:inline` to responsive text:
     ```html
     <span class="font-bold text-gray-900 text-xs sm:text-sm tracking-tight truncate max-w-[150px] xs:max-w-none">Knowledge Base</span>
     ```
   - Ensure the logo icon and title remain cleanly aligned across all screen sizes.

2. **Add "📄 Articles" to Global Navigation (`base.j2.html`)**:
   - Add `<a href="/articles" class="text-indigo-600 hover:text-indigo-800 nav-link flex items-center transition"><span class="mr-1">📄</span> Articles</a>` in the desktop nav (`nav.hidden.xl:flex`).
   - Add the corresponding tile in the mobile hamburger drawer (`#mobileNavMenu`).

3. **Admin Portal Layout Margins & Mobile Static Buttons (`src/kb_web/templates/admin.j2.html`)**:
   - **Mobile Tabs**: Replace `#adminTabsNav` class `flex space-x-2 mt-4 overflow-x-auto pb-1` with:
     ```html
     <nav class="grid grid-cols-2 sm:grid-cols-3 md:flex md:flex-wrap gap-2 mt-4" aria-label="Admin Tabs" id="adminTabsNav">
     ```
     This turns the tabs into a clean grid of static buttons on mobile screens with no awkward horizontal scrolling.
   - **Desktop Margins in `tab-backups`**:
     - Change the tab container to `space-y-8`.
     - Add generous `mb-8` and `mt-8` spacing between *Server Database Snapshots* and *Administrative Batch Operations & Content Purge*.
     - Ensure the bottom section has ample padding and container margin so cards do not hug the bottom of the viewport.

4. **Home Page Mobile Left Sidebar (`src/kb_web/templates/pages_list.j2.html`)**:
   - Change line 12 from `<aside class="w-full lg:w-60 flex-shrink-0">` to:
     ```html
     <aside class="hidden lg:block w-60 flex-shrink-0">
     ```
   - On mobile, the left sidebar is completely hidden; users utilize the global hamburger drawer menu.

---

### Phase 2: Dedicated Articles Page (`/articles`)
1. **Route Implementation (`src/kb_web/routers/pages.py`)**:
   - Add `@router.get("/articles", response_class=HTMLResponse)` rendering dedicated articles.
   - Ensure search (`q`), tag filtering (`tag`), and pagination work smoothly with `view="articles"`.
   - Update `pages_list.j2.html` header when on `/articles` to display:
     - Title: `📄 Articles Archive`
     - Subtitle: `Chronological directory of captured web articles and technical wiki documentation.`
   - Ensure Home (`/`) retains its portal view.

---

### Phase 3: Autonomous Background Server Worker Engine
1. **Create `src/kb_web/worker.py` (`AutonomousWorker`)**:
   - **Singleton Engine**: `AutonomousWorker` class managing periodic cycles and execution state.
   - **Configurability**:
     - `KB_AUTONOMOUS_WORKER_ENABLED` (default: `True`)
     - `KB_AUTONOMOUS_WORKER_INTERVAL_MINUTES` (default: `5`)
     - `KB_AUTONOMOUS_WORKER_BATCH_SIZE` (default: `1`)
   - **Tasks Executed Per Cycle (One-at-a-time, Graceful Failure)**:
     - **Task 1: Wiki Generation for Unprocessed Pages**:
       - Finds the earliest page where `description` is `None`, empty, or `"AI Processing skipped"`.
       - Calls `extract_wiki_content` via threadpool.
       - If Ollama fails, catches exception, logs warning, records failure notification, and continues without crashing.
       - On success, updates `description`, generates embeddings if missing, and records success notification.
     - **Task 2: Tag Extraction for Untagged Pages**:
       - Finds the earliest page where `tags` is `None`, empty, or `'[]'`.
       - Calls `extract_tags_content` via threadpool.
       - On success, persists tags and records notification.
     - **Task 3: Extensible Hooks (Future Foundations)**:
       - Pluggable hook functions for `generate_synthetic_qa_questions()`, `evaluate_rag_accuracy()`, and `crawl_discovered_links()`.
   - **Concurrency Safety**: Protected with `asyncio.Lock` and status tracking (`idle`, `running`, `last_run`, `items_processed_total`).

2. **Lifespan Hook (`src/kb_web/server.py`)**:
   - Start the worker loop in `lifespan(app)` using `asyncio.create_task`.
   - On shutdown, cleanly cancel the background task and await shutdown.

3. **REST Endpoints (`src/kb_web/routers/worker.py` or `admin.py`)**:
   - `GET /api/worker/status`: Returns current status, is_running, last_run, next_run, items_processed.
   - `POST /api/worker/cycle`: Triggers an immediate maintenance cycle (authenticated).
   - `POST /api/worker/toggle`: Enables/disables the automatic loop (authenticated).

4. **Admin UI Management Panel (`src/kb_web/templates/admin.j2.html`)**:
   - Add an **Autonomous Server Worker** card under *Prompts & Pipeline* showing:
     - Active status badge (🟢 Active / ⏸️ Paused).
     - Next run countdown / Last run timestamp.
     - "Run Cycle Now" button for instant on-demand execution.
     - Recent worker activity logs / processed items count.

---

## 4. Verification & Testing Plan

1. **Automated Unit & Integration Tests**:
   - Test `/articles` endpoint: Verify 200 OK, HTML response, pagination, and search filtering.
   - Test `AutonomousWorker`:
     - Test processing a mock page missing wiki content.
     - Test graceful failure when Ollama throws a connection error.
     - Test tag generation for an untagged page.
     - Test `/api/worker/status` and `/api/worker/cycle`.
2. **UI & Template Verification**:
   - Run `uv run python build.py` to ensure all Jinja2 templates compile cleanly and no syntax errors exist.
   - Inspect mobile viewport (< 640px) to verify brand title is displayed, left sidebar on `/` is hidden, and admin tabs are rendered as static button cards.
   - Inspect desktop view (1920x1080) to verify lower sections on the Admin page have proper margins.
3. **End-to-End Build**:
   - Run `uv run pytest -k "not test_extension"` to confirm full test suite passes.
