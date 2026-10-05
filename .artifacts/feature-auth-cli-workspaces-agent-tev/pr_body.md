## Summary

This pull request resolves authentication issues after server power loss, fixes CLI 401 Unauthorized errors, adds a remote restart command, introduces full workspace version snapshots with freeze-to-article publishing, equips the coding agent with native `ollama>=0.6.3` `systemone` `tev1` decision gating and granular file tools, replaces the legacy single-article chat drawer with an Autonomous Agentic RAG Multi-Sub-Agent Report Generator, updates the workspace IDE welcome card, and introduces a site-wide high-contrast muted neon dark mode theme with a cute Moon/Sun circle toggle.

### Key Changes
1. **Authentication Resilience & Server Reboot Recovery**:
   - Added persistent disk settings cache (`~/.kb/configs/db_settings_cache.json`) to prevent WAL recovery delays from dropping custom admin passcodes.
   - Configured resilient reconnect parameters on engine startup (`pool_recycle=300`, `pool_pre_ping=True`, `connect_timeout=5`).
   - Added public `/api/health` endpoint.
2. **CLI Authentication Hardening & Remote Restart**:
   - Fixed `is_request_authenticated` and `verify_api_key` to authenticate registered database `CliApiKey` tokens.
   - Added `POST /api/cli/system/restart` endpoint with test-runner guard.
   - Added `kb-web-cli restart` with automatic `/api/health` polling.
3. **Workspace Versioning & Freeze-to-Article**:
   - Created `WorkspaceSnapshot` ORM and API endpoints for creating snapshots, listing, restoring, and freezing snapshots directly as Knowledge Base articles (`workspace://{id}/snapshot/{tag}`).
   - Integrated Snapshots tab and controls directly in the IDE UI.
4. **Coding Agent Tools & Native Tev1 Integration**:
   - Upgraded to `ollama>=0.6.3` supporting native `ollama.Client.systemone(...)` directly through the project's existing `ollama` dependency (no external SDK required).
   - Added `LoggedOllamaClient.systemone` with duration tracking and database logging.
   - Implemented agent tool primitives (`tool_create_file`, `tool_read_file`, `tool_edit_file`).
   - Integrated `tev1` fast structured decision gating (intent, target_file, needs_reading).
   - Added interactive CLI terminal harness: `kb-web-cli workspace agent <workspace_id>`.
5. **Elimination of Single-Article Chat & Navigation Update**:
   - Eliminated single-article chat drawer from `view_page.j2.html` and replaced it with a direct "📊 RAG Research Report" button.
   - Redirected legacy `/conversations` routes to `/reports/rag`.
   - Updated main navigation bar and pages index with `🔬 RAG Reports`.
6. **Autonomous Agentic RAG Multi-Sub-Agent Report Generator & Tev1 Decision Scoring**:
   - Built multi-sub-agent engine in `src/kb_web/rag_agent.py`:
     - **Tag-Searching Sub-Agent**: matches taxonomy and article/note tags.
     - **Query-RAG Sub-Agent**: embeds queries and searches vector chunk embeddings (`pgvector` cosine distance / SQLite vector fallback).
     - **Pure Text Search Sub-Agent**: lexical search across titles, markdown content, and note bodies.
     - **Deduplication & Provenance Aggregator**: deduplicates candidates and boosts multi-source evidence.
     - **Tev1 Decision Scoring Sub-Agent**: evaluates candidates against query and research purpose using native `ollama.systemone` with model `tev1` (up to 64 questions per turn across 6 technical dimensions).
     - **Synthesis & Report Compiler Agent**: synthesizes top-scored candidates into a structured publication-grade Markdown research report.
   - Added RAG report UI in `src/kb_web/templates/rag_report.j2.html` with query input, presets, live pipeline visualizer, `tev1` decision matrix table, rendered report markdown viewer with Copy/Download/Save to Notes buttons, and recent reports drawer.
   - Implemented REST endpoints in `src/kb_web/routers/rag_reports.py`: `GET /reports/rag`, `POST /api/reports/rag/generate`, `GET /api/reports/rag`, `GET /api/reports/rag/{id}`, `POST /api/reports/rag/{id}/save-to-notes`, and `DELETE /api/reports/rag/{id}`.
   - Added CLI command in `kb-web-cli`: `kb-web-cli rag report "<query>"` with `--purpose`, `--output`, `--model`, and `--save-notes` flags.
7. **Workspace Agent Welcome Card Update (UAT Fix)**:
   - Updated the workspace IDE agent welcome card in `workspace_ide.j2.html` with `tev1 Gated` badge, active tool definitions (`create_file`, `read_file`, `edit_file`), and CLI command reference.
8. **Site-Wide Muted Neon Dark Mode & Moon/Sun Circle Toggle**:
   - Created a comprehensive high-contrast muted neon retro dark theme in `src/kb_web/templates/base.j2.html` with obsidian slate base (`#090e17`), card containers (`#111827`), high-contrast sharp typography (`#f8fafc`), and muted neon accents (electric cyan `#38bdf8`, neon violet `#c084fc`, emerald `#34d399`, amber `#fbbf24`, rose `#f87171`).
   - Added an interactive circular Moon/Sun toggle button (`theme-circle-toggle`) with smooth 360-degree rotation animation and stateful SVG icon swapping across both authenticated and guest navigation headers.
   - Implemented synchronous anti-flicker script in `<head>` honoring `localStorage` and `prefers-color-scheme` media query for 0ms white flash.

### Verification & Testing
- **Unit Tests**: 113 passed (uv run pytest).
- **UI Component Check**: 22 Jinja2 templates verified (0 warnings).
- **Build Pipeline**: Cleanly compiled wheels and distributions (build.py).
- **Artifacts**: VCS reports generated in `uat/reports/` and `uat/logs/`.
