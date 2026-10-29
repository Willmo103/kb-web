## Release v0.5.12 (Staging Production -> Master)

This pull request merges the verified `production` baseline (`v0.5.12`) into `master` following the repository tiered release lifecycle.

### Overview of Included Enhancements & Fixes (v0.5.12)

#### 1. Raw READ-ONLY SQL Query Reports Gated by Decision Model (`routers/reports.py`, `templates/reports.j2.html`)
- Implemented dual-layer safety gating for raw SQL execution in Custom Reports (`/reports`):
  - **Deterministic AST & Regex Pre-Screening**: Blocks destructive operations (`DROP`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `ATTACH`, `DETACH`, `VACUUM`, and `INSERT/UPDATE/DELETE` on persistent tables) while excusing the creation and deletion of session-scoped temporary tables (`CREATE TEMP TABLE ...`, `CREATE TEMPORARY TABLE ...`, `DROP TABLE IF EXISTS #...`, `DROP TABLE temp_...`).
  - **Native Ollama SystemOne Decision Gating**: Queries `client.systemone` evaluating `statement_dialect`, dialect compliance (`d_01_compliance`), and non-destructive compliance (`nd_01_compliance >= 0.5`) across PostgreSQL and SQLite targets, falling back gracefully to strict static validation when Ollama is offline.
- Added REST endpoints `POST /api/reports/raw-sql` and `POST /api/reports/raw-sql/export` (streaming CSV and JSON exports).
- Added Raw SQL Query UI tab in `reports.j2.html` featuring monospace query editor, quick query snippets, decision gate audit score badges, data grid result rendering, and instant CSV/JSON exports.
- Added 10 unit tests in `tests/test_raw_sql_reports_and_restart.py`.

#### 2. Clickable Selection Cards on Import Crawl and Collection Operations (`templates/url_import.j2.html`, `templates/view_collection.j2.html`)
- Made list card rows fully clickable across the webpage link discovery workspace (`url_import.j2.html`) and collection manager (`view_collection.j2.html`).
- Guarded click propagation to ignore clicks on external anchor links (`<a>`), action buttons, or direct checkbox clicks.

#### 3. Admin Server Restart Action with Optional Git Pull & UV Sync (`routers/admin.py`, `templates/admin.j2.html`, GitHub Issue #120)
- Added `POST /admin/server/restart` endpoint with admin session authentication.
- Supports optional `pull_git: bool` parameter that pulls latest commits from the active git branch without switching branches and synchronizes dependencies with `uv sync` prior to restarting.
- Added "Restart Server" action button and confirmation modal in `templates/admin.j2.html` with live countdown and reconnection polling.

---

### Verification & Testing
- Full build pipeline verification (`uv run python build.py`): **288/288 passed**.
- Template syntax & structural completeness (`verify_ui_templates.py`): **29/29 verified with 0 warnings**.
- VCS testing artifacts: `uat/reports/uat_report_raw_sql_clickable_cards_server_restart_20261028_004802.md`.

