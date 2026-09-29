# Walkthrough - Resolution of /links 500 Error, Live Server DB Logging, and /admin & /view/site Latency

Resolves [Issue #59](https://github.com/Willmo103/kb-web/issues/59) associated with Draft PR [#57](https://github.com/Willmo103/kb-web/pull/57).

## Summary of Changes

### 1. `/links` 500 Internal Server Error Fixed
- **Root Cause**: In [links.py](file:///c:/src/kb-web/src/kb_web/routers/links.py), SQLAlchemy 2.0 ORM instances were being passed outside the `with db_session()` block. When Jinja evaluated `{{ link.id }}` after the session closed, SQLAlchemy threw `DetachedInstanceError: Instance <Link> is not bound to a Session; attribute refresh operation cannot proceed`. Additionally, [links.j2.html](file:///c:/src/kb-web/src/kb_web/templates/links.j2.html) had unshielded slices `link.created_at[:10]` and `link.last_clicked_at[:10]` which failed with `TypeError: 'NoneType' object is not subscriptable` when timestamps were null.
- **Fix**:
  - In `view_links()`, decoupled ORM rows into plain Python dictionaries inside `db_session()`.
  - In `links.j2.html`, added safe fallback guards `link.created_at[:10] if link.created_at else 'Unknown'` and safe last-clicked checks.

### 2. Live Server DB Logging Restored & Alembic Noise Filtered
- **Root Cause**: Under Gunicorn and Uvicorn worker process initialization, logger handlers on the root logger were reset. Because `setup_logging()` previously only ran at module import time, `DatabaseLogHandler` was detached when running under the production server or systemd. Furthermore, Alembic emitted 30+ plugin setup logs during migrations that were saved to `system_logs`.
- **Fix**:
  - In [base.py](file:///c:/src/kb-web/src/kb_web/base.py), filtered out log records from `alembic` (`record.name.startswith("alembic")` or `record.module == "plugins"`) in `DatabaseLogHandler.emit()`.
  - In [server.py](file:///c:/src/kb-web/src/kb_web/server.py), attached `DatabaseLogHandler` directly to `kb_web`, `uvicorn`, `uvicorn.error`, and `uvicorn.access` loggers.
  - Re-invoked `setup_logging()` inside FastAPI's `lifespan` handler so that handlers remain firmly attached after any worker fork or Uvicorn config resets.

### 3. `/admin` Dashboard Latency Reduced from 7.92s to <5ms
- **Root Cause**: [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py) executed `all_pages = session.query(FetchedPage).all()`, pulling hundreds of megabytes of `html_content`, `md_content`, and `text_content` into memory just to count unprocessed pages.
- **Fix**:
  - Replaced the full table scan with a SQL aggregate count:
    ```python
    count = (
        session.query(func.count(FetchedPage.url))
        .filter(
            or_(
                FetchedPage.description.is_(None),
                FetchedPage.description == "",
                FetchedPage.description.like("%AI Processing skipped%"),
            )
        )
        .scalar()
        or 0
    )
    ```

### 4. `/view/site` Latency Optimized & Character-Split Tags Fixed
- **Root Cause**: [sites.py](file:///c:/src/kb-web/src/kb_web/routers/sites.py) loaded all pages with all heavy columns, passed raw JSON tag strings to [view_site.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_site.j2.html) (which iterated character-by-character creating single-letter pills like `[ " a i ...`), and omitted `safe_url`.
- **Fix**:
  - Query only `(FetchedPage.url)` to construct the sites directory counts in milliseconds.
  - Query only lightweight columns `(url, title, tags, description, fetched_at)` for matching site pages.
  - Implemented `_parse_tags` to deserialize JSON strings into `list[str]`.
  - Populated `safe_url = quote_plus(row.url)` on each page dictionary.

---

## Verification Results

### Automated Tests
- **Targeted Tests**:
  - `test_links_safe_rendering_and_null_dates`: Passed (verified 200 OK with null dates).
  - `test_admin_dashboard_performance_and_render`: Passed (verified fast load and 200 OK).
  - `test_view_site_tag_deserialization_and_safe_url`: Passed (verified whole tag badge strings and `safe_url` routing).
  - `test_database_logger_filtering_and_capture`: Passed (verified Alembic suppression and live server log capture).
- **Full Pytest Suite**:
  - `69 passed, 48 warnings in 31.29s`
- **UI Template Verification**:
  - `verify_ui_templates.py`: All 14 templates verified with 0 warnings.
- **Full Build Pipeline**:
  - `python build.py`: Succeeded cleanly, building both core and CLI wheels and copying to local repo artifacts.
- **VCS UAT Artifacts**:
  - Generated `uat/logs/test_log_site_admin_links_logging_20260913_180158.log`
  - Generated `uat/reports/uat_report_site_admin_links_logging_20260913_180158.md`
