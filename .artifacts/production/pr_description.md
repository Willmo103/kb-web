## Release v0.2.0: PostgreSQL & SQLAlchemy ORM Migration, pgvector Searches, Database CLI Suite, & Admin Backups

This release PR integrates all changes from the `production` branch into `master`, completing the full multi-phase PostgreSQL migration and database management tools.

### Sprints & Issues Resolved:
- **Parent Issue #30**: PostgreSQL | SQLAlchemy Support (Closed)
- **Sprint 2 (#41)**: SQLAlchemy ORM & pgvector Searches (Closed)
  - Resolves #42 (Sub-Issue 3: pgvector Extension Integration & Embeddings Refactor)
  - Resolves #43 (Sub-Issue 4: SQLAlchemy ORM Schema mapping)
  - Resolves #44 (Sub-Issue 5: Database Session & Driver Abstraction)
- **Sprint 3 (#45)**: Core Database Access Refactoring & Migration Utility (Closed)
  - Resolves #46 (Sub-Issue 6: Database Access Refactoring)
  - Resolves #47 (Sub-Issue 7: SQLite-to-PostgreSQL Data Ingest Utility)
- **Previous Resolved Issues in PR scope**:
  - Resolves #31: Protected links interface and redirect authentication tracking
  - Resolves #33: Target URL deduplication verification
  - Resolves #34: Video downloading and source detection option
  - Resolves #37, #38, #39, #40: Sprint 1 DevContainer & Alembic baseline migrations

### Summary of Changes:
1. **PostgreSQL & SQLAlchemy Dialect Support**:
   - Declarative models in `models_orm.py` covering all 20 tables.
   - `SafeVector` custom TypeDecorator for cross-dialect compatibility (`pgvector` on Postgres, JSON text on SQLite).
   - Connection pooling and `db_session` middleware in `base.py`.
   - Router database access fully refactored to ORM.
2. **Database CLI Station (`kb-web db`)**:
   - `migrate-sqlite`: Foreign-key ordered migration, NUL byte stripping, orphan synthesis, and sequence advancement.
   - `deploy`, `snapshot`, `sync-snapshot`, `replication-setup`, `replication-status`.
   - `backup-videos`, `restore-videos`, `reindex-videos` (with max-2 backup ZIP retention).
3. **Admin Dashboard Backups UI**:
   - Server-side backup storage in `Config.backups_dir`.
   - Diagnostic fallback for WebSocket reverse-proxy issues.
4. **Verification & Testing**:
   - 54 unit tests passing (100% pass rate).
   - Pre-commit build pipeline and wheel compilation verified cleanly.
   - VCS UAT reports generated in `uat/reports/`.
