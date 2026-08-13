# Sprint 1 Task List

- `[x]` Sub-Issue 0: DevContainer PostgreSQL & pgvector Setup (Issue #38)
  - `[x]` Create `.devcontainer/docker-compose.yml` defining the PostgreSQL stack
  - `[x]` Create `.devcontainer/devcontainer.json` defining workspace configuration
  - `[x]` Create `scripts/check_db_ready.py` health check script
  - `[x]` Update `build.py` to launch the database container and run socket checks
- `[ ]` Sub-Issue 1: Database Schema Docs & SQLite baseline (Issue #39)
  - `[ ]` Create `docs/database_schema.md` outlining the SQLite layout
  - `[ ]` Create `migrations/baseline_sqlite.sql` baseline schema snapshot
- `[ ]` Sub-Issue 2: Alembic Baseline Migration & Deploy Scripts (Issue #40)
  - `[ ]` Initialize Alembic framework
  - `[ ]` Configure `migrations/env.py` database settings
  - `[ ]` Write Alembic baseline migration version
  - `[ ]` Write `scripts/deploy_migrations.py` programmatic deploy script
  - `[ ]` Integrate deployment upgrade routines into the server startup lifecycle
