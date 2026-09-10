# Sprint 3: Core Database Access Refactoring & Migration Utility (Issue #45)

* **Sprint Goal**: Ports all database operations throughout the codebase to ORM session queries and create the SQLite-to-PostgreSQL migrate CLI command.
* **Parent Issue**: #30 (PostgreSQL | SQLAlchemy Support)
* **Estimated Duration**: 11 Days

---

## Detailed Task List

### 1. Database Access Refactoring (Sub-Issue #46)
- [x] Scan the entire repository (`pages.py`, `admin.py`, `links.py`, `collections.py`, `cli_api.py`, `api.py`) for direct SQLite dictionary operations:
  - e.g. `db["fetched_pages"].get(url)` or `db["fetched_pages"].upsert(serialized, pk="url")`.
- [x] Refactor database operations to query ORM models through the `db_session` middleware.
- [x] Ensure all router updates, insertions, and deletions execute transactional session operations (`session.add()`, `session.commit()`, `session.rollback()`).
- [x] Modify read-only dashboard tables views to query and paginate via SQLAlchemy pagination filters.

### 2. SQLite-to-PostgreSQL Data Ingest Utility (Sub-Issue #47)
- [x] Add the database migration sub-command handler structure to `kb-web-cli`:
  - Command: `kb-cli db migrate-to-postgres` / `kb-web db migrate-sqlite`.
- [x] Implement the migration reader and writer pipeline:
  - Read SQLite tables iteratively utilizing Python `sqlite3`.
  - Validate column names, convert SQLite datetime strings to ISO formats.
  - Perform bulk inserts using SQLAlchemy Core bulk insert operations to optimize load speed and resolve constraints conflicts.
- [x] Write integration unit tests in `tests/test_server.py` verifying that migrating a sample sqlite database dump to postgresql maps all rows and values correctly.
