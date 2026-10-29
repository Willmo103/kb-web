# Implementation Plan: Raw SQL Reports with Decision Gating, Clickable Selection Cards, and Server Restart UI

## Overview
This plan implements the three user issues and feature requests outlined in `issues.md`:
1. **Raw SQL Query Reports Gated by Decision Model** (`feature-request\allow-raw-sql-query-reports-gated-by-decision-model`):
   - Allow execution of raw SQL queries against PostgreSQL/SQLite in the Custom Reports & ERP Grid view (`/reports`).
   - Excuse session-scoped temporary table creation and deletion (`CREATE TEMPORARY TABLE`, `DROP TABLE IF EXISTS ...`, `CREATE TEMP TABLE`).
   - Enforce dual-layer safety: AST / regex non-destructive statement analysis + native Ollama `systemone` / `d1` / `tev1` decision model gating (`nd_01_compliance` and `d_01_compliance`).
   - Execute in read-only transaction where supported (`SET TRANSACTION READ ONLY`).
   - Provide Raw SQL Query UI in `reports.j2.html` with Monaco / syntax editor, Decision Gate check indicator, result preview grid, CSV/JSON export, and error diagnostics.
2. **Clickable Selection Cards on Import Crawl & Collection Ops** (`feature-request\make-list-cards-clickable-to-select-or-deselect-on-import-crawl-and-collection-ops`):
   - Update list card rows in `/import` (crawl / discovered links list) and collection bulk operations (`url_import.j2.html`, `collections.j2.html`, etc.) so clicking anywhere on the item/row container selects/deselects the item checkbox.
   - Guard against click hijacking: do not toggle when the user clicks directly on interactive child elements (e.g. `<a>` anchor links, action buttons, or the checkbox itself).
3. **Admin Server Restart Functionality** (GitHub Issue #120):
   - Add a `Restart Server` action in `/admin`.
   - Include an optional checkbox: "Pull latest git changes from current branch" (runs `git pull && uv sync` before restarting systemd service).
   - Backend endpoint `POST /admin/server/restart` in `src/kb_web/routers/admin.py` with admin session authentication, executing safely in a background process or detached thread (`sudo systemctl restart kb-web.service || sudo systemctl restart kb-web-test.service`), with graceful fallback on non-systemd/Windows dev environments.
   - Modal and UI confirmation dialog in `admin.j2.html`.

---

## Detailed Step-by-Step Changes

### Step 1: Clickable Selection Cards
- **Target Files**:
  - `src/kb_web/templates/url_import.j2.html`:
    - Add click handler to discovered link cards (`.crawl-link-item`, `.discovered-link-card`, or rows containing `name="selected_urls"` / `class="crawl-link-cb"`).
    - If user clicks the card row, toggle the checkbox and dispatch `change` event so badge counts and bulk action bars update.
    - Prevent double toggle when clicking the checkbox directly, and ignore clicks on `<a>` tags or action buttons.
  - `src/kb_web/templates/collections.j2.html` / `src/kb_web/templates/collection_editor.j2.html`:
    - Ensure item rows with bulk selection checkboxes have row click toggling as well.

### Step 2: Admin Server Restart (Issue #120)
- **Target Files**:
  - `src/kb_web/routers/admin.py`:
    - Implement `POST /admin/server/restart`:
      - Gated by admin session authentication (`_check_admin(request)`).
      - Accept JSON payload `{"pull_git": bool}`.
      - If `pull_git` is true, run `git pull` and `uv sync`.
      - Trigger service restart: in Linux/systemd environments, dispatch background command `sudo systemctl restart kb-web.service` (or `kb-web-test.service` if running in test environment).
      - If running on Windows or without systemctl, log and return graceful simulation response indicating command received.
  - `src/kb_web/templates/admin.j2.html`:
    - Add "Restart Server" button in the admin system diagnostics/actions section.
    - Provide a modal with "Pull latest git changes from current branch" checkbox, confirm button, and progress/reloading spinner.

### Step 3: Raw SQL Query Reports Gated by Decision Model
- **Target Files**:
  - `src/kb_web/routers/reports.py`:
    - Implement `evaluate_sql_safety(sql: str, dialect: str = "PostgreSQL") -> tuple[bool, str, dict]`:
      - Parse statements and check for prohibited destructive operations: `DROP DATABASE`, `DROP SCHEMA`, `TRUNCATE`, `ALTER`, `GRANT`, `REVOKE`, `DELETE FROM`, `UPDATE ... SET` (unless operating on temporary tables).
      - Permit `CREATE TEMPORARY TABLE`, `CREATE TEMP TABLE`, `DROP TABLE IF EXISTS #...`, `DROP TEMPORARY TABLE`, and `SELECT ... INTO TEMPORARY TABLE`.
      - Invoke `client.systemone` (or `tev1`/`d1` decision model) to evaluate `nd_01_compliance` (non-destructive) and `d_01_compliance` (valid dialect).
      - Graceful fallback: if Ollama client or decision model is unavailable, rely on strict SQL AST/regex validation.
    - Implement `POST /api/reports/raw-sql`:
      - Accept `{"query": str, "limit": int}`.
      - Evaluate safety with `evaluate_sql_safety`. If rejected, return 400 with detailed explanation and gate criteria results.
      - Execute query using `read_only_transaction` or read-only connection cursor.
      - Limit max rows to protect server memory.
      - Return column names, row records, execution time, and decision gating audit metadata.
  - `src/kb_web/templates/reports.j2.html`:
    - Add "Raw SQL Query" tab / panel alongside visual query builder.
    - Include query text editor with sample queries and temp table demonstration.
    - Include "Decision Gate: Non-Destructive SQL Check" badge.
    - Display results in the dynamic data grid with CSV/JSON export.

### Step 4: Verification, Testing & Artifacts
- **Unit Tests**:
  - Create `tests/test_raw_sql_reports_and_restart.py`:
    - Test raw SQL execution for safe queries (`SELECT`, `CREATE TEMP TABLE`, `SELECT FROM temp`).
    - Test rejection of destructive queries (`DROP TABLE`, `DELETE FROM`, `TRUNCATE`).
    - Test `/admin/server/restart` endpoint auth and parameter handling.
- **UI Checks & UAT**:
  - Run `verify_ui_templates.py`.
  - Run `uv run pytest`.
  - Run `uv run python build.py`.
  - Run `generate_uat_report.py`.

### Step 5: Self-Documentation & Release
- Update `CHANGELOG.md` under `[0.5.12]`.
- Update `issues.md` marking the issues resolved.
- Commit to `feature/sql-reports-clickable-cards-server-restart`.
- Merge into `development`.
