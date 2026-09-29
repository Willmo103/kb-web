# Implementation Plan - Fix /links 500 Error, Restore Server Logging, & Optimize /admin and /view/site

Address 4 critical post-migration issues identified during UAT on the testing server:
1. **`/links` 500 Internal Server Error**: Resolve `DetachedInstanceError` and `NoneType` subscripting exceptions.
2. **Missing Live Server Logging**: Ensure request logs and uncaught error tracebacks are persisted to `system_logs` under Gunicorn/Uvicorn worker lifecycle, and suppress noisy Alembic plugin setup logs.
3. **`/admin` Dashboard Latency**: Eliminate full table scan with heavy text columns (`html_content`, `md_content`, `text_content`) by replacing it with a SQL aggregate count (reducing latency from ~7.92s to <5ms).
4. **`/view/site` Latency & Corrupted Tags**: Eliminate full table scans in `sites.py`, parse JSON tags properly to prevent character-by-character pill rendering, and populate `safe_url` for site page links.

## User Review Required

> [!IMPORTANT]
> - All changes maintain PostgreSQL compatibility and phase out SQLite dependencies as required.
> - Work is being carried out on branch `feature/site-admin-links-logging` branched from `production`, associated with Issue [#59](https://github.com/Willmo103/kb-web/issues/59) and Draft PR [#57](https://github.com/Willmo103/kb-web/pull/57).
> - No database schema migrations are needed for this change; this addresses query patterns, logging handler lifecycle, and template rendering safety.

## Proposed Changes

---

### Component: Logging & Server Worker Lifecycle

#### [MODIFY] [base.py](file:///c:/src/kb-web/src/kb_web/base.py)
- In `DatabaseLogHandler.emit()`:
  - Add filters to ignore log records from `alembic` (`record.name.startswith("alembic")` and `record.module == "plugins"`) in addition to `sqlalchemy`, preventing 30+ plugin registration messages from flooding the `system_logs` table.
  - Keep the silent fallback on database errors to prevent logging from crashing request threads.

#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- In `setup_logging()`:
  - Attach `DatabaseLogHandler` directly to `logging.getLogger("kb_web")`, `logging.getLogger("uvicorn.error")`, and root `logging.getLogger()`.
- In `lifespan(app)`:
  - Re-invoke `setup_logging()` inside `lifespan` on startup. When Gunicorn or Uvicorn workers fork and initialize, their logging configuration clears or overrides root logger handlers. Re-running `setup_logging()` inside `lifespan` ensures `DatabaseLogHandler` remains attached throughout the worker process lifetime.

---

### Component: Links Router & Template Safety

#### [MODIFY] [links.py](file:///c:/src/kb-web/src/kb_web/routers/links.py)
- In `view_links()`:
  - Render the template or convert ORM instances to dictionaries while the `db_session()` context is active. This prevents SQLAlchemy 2.0 `DetachedInstanceError` when Jinja evaluates model attributes on expired/closed session objects.
  - Ensure dictionary items contain safe fallback defaults for `click_count`, `created_at`, and `last_clicked_at`.

#### [MODIFY] [links.j2.html](file:///c:/src/kb-web/src/kb_web/templates/links.j2.html)
- Lines 94 & 97:
  - Replace `{{ link.created_at[:10] }}` with `{{ link.created_at[:10] if link.created_at else 'Unknown' }}`.
  - Replace `{{ link.last_clicked_at[:10] }}` with `{{ link.last_clicked_at[:10] if link.last_clicked_at else 'Never' }}`.

---

### Component: Admin Dashboard Performance

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- In `get_admin_dashboard()` (lines 437-443):
  - Replace `all_pages = session.query(FetchedPage).all()` and Python list comprehension with a SQL aggregate count:
    ```python
    from sqlalchemy import func, or_
    count = session.query(func.count(FetchedPage.url)).filter(
        or_(
            FetchedPage.description.is_(None),
            FetchedPage.description == "",
            FetchedPage.description.like("%AI Processing skipped%")
        )
    ).scalar() or 0
    ```
  - This eliminates loading hundreds of megabytes of HTML/MD content into memory, dropping `/admin` page load time from ~7.92s to ~0.002s.

---

### Component: Virtual Sites Profile Optimization & Tag Parsing

#### [MODIFY] [sites.py](file:///c:/src/kb-web/src/kb_web/routers/sites.py)
- In `view_site_profile()`:
  - Replace `session.query(FetchedPage).all()` with lightweight queries:
    1. For `pages`: Query only `(FetchedPage.url, FetchedPage.title, FetchedPage.tags, FetchedPage.description, FetchedPage.fetched_at)` matching the domain.
    2. For `other_sites`: Query only `session.query(FetchedPage.url).all()` to count pages per domain without loading any content columns.
  - Parse `p.tags`: If `tags` is a JSON string (e.g. `'["ai", "tech"]'`), deserialize it with `json.loads()` into a list of strings so Jinja iterates tag badges instead of individual characters.
  - Include `safe_url = quote_plus(row.url)` so link buttons work properly.

---

## Verification Plan

### Automated Tests
- Run unit test suite:
  ```powershell
  uv run pytest tests/test_server.py
  uv run pytest
  ```
- Add dedicated test cases in `tests/test_server.py` or new test file:
  - `GET /links` with authenticated session returns 200 OK even when `created_at` or `last_clicked_at` is None.
  - `GET /admin` returns 200 OK and executes efficiently.
  - `GET /view/site?site=youtu.be` returns 200 OK, correctly deserializes tag list, and populates `safe_url`.
  - Database logger verification: logs are written to `SystemLog` table and Alembic logs are filtered out.
- Run UI verification and pre-commit checks:
  ```powershell
  uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py
  uv run python build.py
  ```

### Manual Verification
- Verify that navigating to `/links` renders clean cards with no 500 error.
- Verify that navigating to `/view/site?site=youtu.be` renders tag pills as full words (e.g. `ai safety`, `generative ai`) rather than single characters (`[`, `"`, `a`, `i`).
- Verify that `/admin` and `/view/site` load in under 100ms.
- Verify that `/admin/logs` displays live HTTP request logs and error traces without Alembic plugin noise.
