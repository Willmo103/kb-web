# Tasks Checklist

- [x] Implement `SQLiteLogHandler` in `src/kb_web/base.py`
- [x] Replace `RotatingFileHandler` with `SQLiteLogHandler` in `src/kb_web/server.py`
- [x] Add HTTP request logging middleware to `src/kb_web/server.py`
- [x] Update `/admin/logs` and `/admin/logs/download` routes in `src/kb_web/routers/admin.py` to fetch from DB
- [x] Modify `src/kb_web/templates/url_import.j2.html` to add collection dropdown and remove bookmarklet
- [x] Update `/import` GET/POST endpoints in `src/kb_web/routers/admin.py` to support collection assignment/creation
- [x] Normalize subdomains and add comprehensive logging in `run_recursive_crawl` in `src/kb_web/routers/pages.py`
- [x] Run test suite and add regression tests for DB logging, crawler subdomain checks, and collections imports
- [x] Run build pipeline to verify packaging success
