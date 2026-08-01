# Implementation Plan: Crawler Domain Normalization, Database Logging, Request Middleware, and URL Import Collections

This plan details the changes to resolve crawler execution issues, expand request logging, move all logs to a database table, and allow selecting or creating collections during URL imports.

---

## Proposed Changes

### Database Logging

#### [MODIFY] [base.py](file:///c:/src/kb-web/src/kb_web/base.py)
- Implement `SQLiteLogHandler` (subclassing `logging.Handler`) to insert logging records into the `system_logs` table of the SQLite database.
- Define safe direct inserts using `sqlite3` to prevent recursive logger calls.

#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- Replace standard RotatingFileHandler with `SQLiteLogHandler` in `setup_logging()`.
- Add an HTTP middleware to FastAPI (`log_request_middleware`) to automatically log the method, URL, client IP, response status, and duration for every request at the `INFO` level.

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Update `/admin/logs` and `/admin/logs/download` to query and format log output from the `system_logs` table instead of reading from `kb-web.log`.
- Add extensive `logger.info` tracking inside `handle_url_import` and other admin actions.

---

### Ingestion Collections Selector

#### [MODIFY] [url_import.j2.html](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html)
- Add a Collection dropdown selector (`collection_id`) populated with all existing user collections.
- Add an option to "+ Create New Collection..." which dynamically displays a text input field (`new_collection_title`) to name the new collection.
- Remove the entire bottom panel containing the "Quick Share Bookmarklet" bookmark section and its associated DOM load script.

#### [MODIFY] [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Update GET `/import` and `/import/shared-url` to query and pass existing `collections` list to `url_import.j2.html`.
- Update POST `/import/url` form parameters to receive optional `collection_id` and `new_collection_title` values.
- In `stream_ingestion`, process collection creation if a new collection is requested, associate the page data with `collection_id`, and insert a link record in `collection_items` to cleanly group the page under the chosen collection.

---

### Crawler Domain Normalization & Logging

#### [MODIFY] [pages.py](file:///c:/src/kb-web/src/kb_web/routers/pages.py)
- Fix subdomain domain mismatch by normalizing and stripping `www.` subdomains from netlocs before comparison inside `run_recursive_crawl`.
- Update `run_recursive_crawl` to log all crawl events (starting, skipping already ingested, page processing, successfully ingested, links parsed, and crawler completion) using standard `logger.info` and `logger.error` so they write directly to the database logging table.

---

## Verification Plan

### Automated Tests
- Run `C:\Users\Will\.local\bin\uv.exe run pytest` to ensure no routes are broken.
- Add new unit tests in `tests/test_server.py`:
  - `test_sqlite_logging_handler()`: verify log messages write directly to `system_logs` and query correctly.
  - `test_crawler_domain_normalization()`: mock and verify that `run_recursive_crawl` correctly crawls links across `www.` subdomains.
  - `test_import_with_collection()`: verify that importing a URL with collection parameters creates the collection (if needed) and links the page correctly.

### Manual Verification
- Go to `/import`, select an existing collection or choose "+ Create New Collection...", submit a URL, and verify it ingests and appears in the target collection.
- Trigger a recursive crawl, visit `/admin/logs`, and verify that crawl events are logged step-by-step.
- Verify that standard logging files are no longer generated and that logs display correctly in the log viewer panel.
