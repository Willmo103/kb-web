# User Feedback - Production Hotfix

## User Request
"We need to add the scripts folder (to run the migrations) into the project sorce. The production server broke when I merged the last pr."

## Context
When `kb-web` was built and packaged as a python package (using `uv_build` backend), directories at the root directory level like `scripts/` were excluded. When run in production, invoking the `kb-web serve` entrypoint attempted to load database migrations on startup by importing `from scripts.deploy_migrations import deploy`. Because `scripts` was not in Python's package path (nor packaged in site-packages), this resulted in a `ModuleNotFoundError: No module named 'scripts'` exception, breaking database initialization and schema migration, which subsequently crashed the production server.
