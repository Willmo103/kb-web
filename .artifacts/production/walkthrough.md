# Walkthrough - Production Migrations Hotfix

We resolved the production server crash caused by packaging exclusions of the migration scripts.

## Changes Made

### 1. Created packaged sub-module `src/kb_web/scripts/`
- Recreated python scripts inside the application package source `src/kb_web/scripts/` (complete with `__init__.py`) to guarantee they are correctly bundled in the Python wheel/installation distribution:
  - [`src/kb_web/scripts/__init__.py`](file:///c:/src/kb-web/src/kb_web/scripts/__init__.py)
  - [`src/kb_web/scripts/check_db_ready.py`](file:///c:/src/kb-web/src/kb_web/scripts/check_db_ready.py)
  - [`src/kb_web/scripts/deploy_migrations.py`](file:///c:/src/kb-web/src/kb_web/scripts/deploy_migrations.py)
  - [`src/kb_web/scripts/verify_db_schema.py`](file:///c:/src/kb-web/src/kb_web/scripts/verify_db_schema.py)

### 2. Configured dynamic path resolution for `alembic.ini`
- Modified [`src/kb_web/scripts/deploy_migrations.py`](file:///c:/src/kb-web/src/kb_web/scripts/deploy_migrations.py) to dynamically lookup the `alembic.ini` path. It falls back across:
  1. Root workspace parent path when running packaged/sourced.
  2. Legacy scripts directory parent path when running standalone.
  3. The current working directory (Cwd) fallback in production.

### 3. Integrated migrations loader in server lifespan
- Updated [`src/kb_web/server.py`](file:///c:/src/kb-web/src/kb_web/server.py) startup event to import `deploy` from the packaged path: `from kb_web.scripts.deploy_migrations import deploy`.

### 4. Re-targeted root scripts as wrappers
- Converted root python scripts to simple wrappers forwarding execution to the package code. This keeps command-line developer scripts (`./scripts/deploy_migrations.py`, etc.) functional:
  - [`scripts/check_db_ready.py`](file:///c:/src/kb-web/scripts/check_db_ready.py)
  - [`scripts/deploy_migrations.py`](file:///c:/src/kb-web/scripts/deploy_migrations.py)
  - [`scripts/verify_db_schema.py`](file:///c:/src/kb-web/scripts/verify_db_schema.py)

## Verification Results

### Automated Tests
- Ran the entire test suite `uv run pytest` parameterizing both sqlite/postgresql databases to ensure migrations run successfully. All **47 tests passed** with zero failures:
  ```bash
  ====================== 47 passed, 40 warnings in 25.78s =======================
  ```
- Executed `verify_ui_templates.py` structural checks with **zero warnings**.
- Compiled VCS-trackable UAT test logs and reports:
  - [`uat/logs/test_log_db_migration_sqlalchemy_20260826_202921.log`](file:///c:/src/kb-web/uat/logs/test_log_db_migration_sqlalchemy_20260826_202921.log)
  - [`uat/reports/uat_report_db_migration_sqlalchemy_20260826_202921.md`](file:///c:/src/kb-web/uat/reports/uat_report_db_migration_sqlalchemy_20260826_202921.md)
