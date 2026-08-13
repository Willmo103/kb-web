# Sprint 1: Dev Environment & Baseline Migrations (Issue #37)

* **Sprint Goal**: Establish local PostgreSQL container environments, compile baseline schema documentation, and build automated Alembic migrations deployment scripts.
* **Parent Issue**: #30 (PostgreSQL | SQLAlchemy Support)
* **Estimated Duration**: 11 Days

---

## Detailed Task List

### 1. DevContainer & PostgreSQL Setup (Sub-Issue #38)
- [x] Add `.devcontainer/docker-compose.yml` to declare a `db` database container service:
  - Base Image: `pgvector/pgvector:pg16`
  - Ports: map `5432:5432`
  - Volumes: store db data in a named docker volume `pg_data`
  - Healthcheck: implement `pg_isready` check with proper polling intervals
- [x] Define workspace config in `.devcontainer/devcontainer.json` mapping environment variables and launching the postgres docker-compose stack.
- [x] Create a check script `scripts/check_db_ready.py` that attempts connection to the PostgreSQL port and exits 0 only when fully online.
- [x] Refactor the pre-test pipeline in `build.py` to check for active test db configurations and initialize transient postgres instances before running unit tests.

### 2. Database Schema Documentation & SQLite baseline (Sub-Issue #39)
- [x] Create `docs/database_schema.md` detailing:
  - Description and layout of all 20+ active tables (`fetched_pages`, `article_embeddings`, `links`, etc.).
  - Primary keys, foreign key relations, constraints, indexes, and calculated views.
- [x] Export the existing SQLite schema structure to `migrations/baseline_sqlite.sql`.

### 3. Alembic initialization & Deployment scripting (Sub-Issue #40)
- [x] Install Alembic dependencies: `pip install alembic psycopg2-binary`.
- [x] Initialize alembic in root folder: `alembic init migrations`.
- [x] Configure `migrations/env.py` to:
  - Import the SQL connection string dynamically from configuration files.
  - Establish compatibility for both SQLite connection engines and PostgreSQL connection drivers.
- [x] Write the first baseline migration script under `migrations/versions/` representing the base database layout.
- [x] Write `scripts/deploy_migrations.py` utilizing the Alembic programmatic API (`alembic.config.Config`, `alembic.command.upgrade`) to run pending migrations on server startup.
