# Implementation Plan - Sprint 1: Dev Environment & Baseline Migrations

This plan outlines the implementation steps to configure local PostgreSQL + pgvector environment, baseline documentation, and Alembic database migration automation for Sprint 1.

## User Review Required

Please review the proposed DevContainer configuration and migration strategy before approving.

## Open Questions

- **Transient DB Testing in CI/CD**: For local test execution (`pytest`), should `build.py` assume the PostgreSQL database container is already running via docker-compose, or should it run docker-compose commands to boot it up if it is not detected?
  - *Recommendation*: `build.py` should attempt to contact PostgreSQL, and if unavailable, execute a subprocess call to `docker compose up -d db` and wait for it to be ready.

---

## Proposed Changes

### Configuration & Dev Environment

#### [NEW] [docker-compose.yml](file:///c:/src/kb-web/.devcontainer/docker-compose.yml)
Define the docker services for devContainer:
- Database service `db` utilizing the `pgvector/pgvector:pg16` image.
- Expose port `5432` locally.
- Persist data to container volume `pg_data`.
- Configure healthcheck using `pg_isready`.

#### [MODIFY] [devcontainer.json](file:///c:/src/kb-web/.devcontainer/devcontainer.json)
Configure the development workspace to boot the docker-compose stack and link the workspace to the database service container.

#### [NEW] [check_db_ready.py](file:///c:/src/kb-web/scripts/check_db_ready.py)
A lightweight healthcheck utility script that attempts to establish a socket connection on the PostgreSQL port, exiting 0 once online.

#### [MODIFY] [build.py](file:///c:/src/kb-web/build.py)
Integrate database connectivity check. If PostgreSQL settings are present in the environment but database is offline, attempt to spin it up using `docker compose up -d db` and block until check script succeeds.

---

### Database Documentation & Baseline

#### [NEW] [database_schema.md](file:///c:/src/kb-web/docs/database_schema.md)
Compile reference manual documenting all 20+ active tables, column keys, constraints, and views matching the SQLite database model.

#### [NEW] [baseline_sqlite.sql](file:///c:/src/kb-web/migrations/baseline_sqlite.sql)
A database schema baseline script containing the exact CREATE statements representing the starting database schema state.

---

### Alembic Migration Setup

#### [NEW] [alembic.ini](file:///c:/src/kb-web/alembic.ini)
Initialize Alembic configuration parameters.

#### [NEW] [env.py](file:///c:/src/kb-web/migrations/env.py)
Configure Alembic runner script to:
- Bind connection engines dynamically matching SQLite/PostgreSQL configuration settings.
- Map the metadata objects.

#### [NEW] [baseline migration version](file:///c:/src/kb-web/migrations/versions/)
Generate the first migration script establishing baseline tables.

#### [NEW] [deploy_migrations.py](file:///c:/src/kb-web/scripts/deploy_migrations.py)
Programmatically call `alembic upgrade head` on application startup to ensure tables are always provisioned.

---

## Verification Plan

### Automated Tests
- Run `uv run pytest` to ensure regression test suite passes cleanly against the database.
- Execute migrations check to verify database upgrades compile without errors.

### Manual Verification
- Rebuild DevContainer, confirm PostgreSQL container starts cleanly and `pgvector` extension is active.
- Verify migrations deployment script executes on backend startup.
