# Implementation Plan - Authentication Hardening, CLI Remote Restart, Workspace Versioning & Agent Tools with Tev1

## Overview
This implementation plan addresses:
1. **Authentication & Power Loss Hardening**:
   - Robust DB reconnection with connection pooling retry so power loss/reboot doesn't cause transient auth failures.
   - Local fallback caching of admin password hash so delayed DB startup doesn't revert to factory defaults.
   - Global auth middleware check for database `CliApiKey` (`cli_api_keys`) so CLI commands no longer fail with 401 Unauthorized.
   - Remote CLI restart endpoint (`POST /api/cli/system/restart`) and CLI command (`kb-web-cli restart`) with health-polling reconnection.
2. **Workspace Versioning & Freeze-to-Article**:
   - ORM model `WorkspaceSnapshot` for tagging, tracking, and restoring workspace file revisions.
   - API endpoints to create snapshots, list history, restore files, and freeze a snapshot into a published `FetchedPage` article in the knowledge base.
   - IDE UI additions in `workspace_ide.j2.html` for versioning controls and snapshot publishing.
3. **Workspace Coding Agent Tools & `tev1` Decision Model**:
   - Agent tool primitives: `create_file` (with annotation), `read_file` (line windowing), and `edit_file` (precise search/replace).
   - Upgraded `ollama>=0.6.3` with native `systemone(...)` integration on `LoggedOllamaClient`.
   - `tev1` decision agent integration for intent classification, gating, and structured reasoning.
   - Interactive terminal harness in `kb-web-cli` (`kb-web-cli workspace agent <workspace_id>`).

---

## Architecture & Implementation Slices

### Slice 1: Authentication Resilience, CLI 401 Fix & Remote Restart
- **Files**:
  - `src/kb_web/base.py`:
    - In `get_engine()`: configure `pool_pre_ping=True`, `pool_recycle=300`.
    - In `is_request_authenticated(request)`: inspect `X-API-Key` or `Authorization: Bearer <key>` against `config.api_key` AND query active `CliApiKey` in database.
  - `src/kb_web/config.py`:
    - Cache encrypted/hashed admin password in local disk cache so reboots without instant DB connection never downgrade to default `admin123`.
  - `src/kb_web/routers/cli_api.py`:
    - Add `POST /api/cli/system/restart`: authenticated via CLI API key. Runs clean restart in background thread after returning 200 OK.
  - `kb-web-cli/src/kb_web_cli/main.py`:
    - Add `restart` command with confirmation prompt and polling ping to `/api/health`.

### Slice 2: Workspace Versioning & Snapshot-to-Article
- **Files**:
  - `src/kb_web/models_orm.py`:
    - Add `WorkspaceSnapshot` table: `id`, `workspace_id`, `version_tag`, `description`, `files_snapshot` (JSON string), `is_frozen`, `created_at`.
  - `src/kb_web/routers/workspaces.py`:
    - `POST /api/workspaces/{id}/snapshots`: save current files as snapshot.
    - `GET /api/workspaces/{id}/snapshots`: list snapshots.
    - `POST /api/workspaces/{id}/snapshots/{snapshot_id}/restore`: restore snapshot files.
    - `POST /api/workspaces/{id}/snapshots/{snapshot_id}/freeze-article`: convert snapshot files to formatted Markdown wiki article and save in `FetchedPage`.
  - `src/kb_web/templates/workspace_ide.j2.html`:
    - Add Versioning & Snapshot modal / side drawer in Monaco IDE.

### Slice 3: Coding Agent Tools, Native `ollama.systemone` & `tev1` Integration
- **Files**:
  - `src/kb_web/agent_tools.py`:
    - Tool functions: `create_file`, `read_file`, `edit_file`.
  - `src/kb_web/base.py`:
    - Add `systemone(...)` forwarding to `LoggedOllamaClient`.
  - `src/kb_web/workspace_agent.py`:
    - Gating and tool dispatcher using `tev1:latest` decision engine.
  - `kb-web-cli/src/kb_web_cli/main.py`:
    - Implement `kb-web-cli workspace agent <id>` terminal harness.

---

## Verification & Testing
1. Unit tests in `tests/test_cli_auth_and_workspaces.py`.
2. Pre-commit test suite: `uv run pytest`, `uv run python build.py`.
3. Template verification: `verify_ui_templates.py`.
4. UAT artifact generation: `generate_uat_report.py`.
