# Walkthrough: Authentication Hardening, Remote Restart, Workspace Versioning & Tev1 Gating

## Overview
This sprint addresses server reboot authentication recovery, CLI 401 Unauthorized errors, adds a remote restart command, introduces full workspace version snapshots with freeze-to-article publishing, and equips the coding agent with native `ollama>=0.6.3` `systemone` `tev1` decision gating and granular file tools.

---

## Changes Implemented

### 1. Authentication Resilience & Server Reboot Recovery
- **Persistent Disk Settings Cache**: Added `_read_cached_setting` and `_write_cached_setting` in [`src/kb_web/config.py`](file:///c:/src/kb-web/src/kb_web/config.py) (`~/.kb/configs/db_settings_cache.json`). If power loss or reboot causes PostgreSQL to take time during WAL recovery, the server reads the cached administrator password hash rather than falling back to factory defaults (`admin123`).
- **Database Engine Reconnect Options**: In [`src/kb_web/base.py`](file:///c:/src/kb-web/src/kb_web/base.py) `get_engine()`, configured `pool_recycle=300`, `pool_pre_ping=True`, and `connect_timeout=5`. Initial connection during startup is gracefully deferred if the DB is momentarily unresponsive.
- **Public Health Endpoint**: Added `/api/health` returning `{"status": "ok", "app": "kb-web"}` in [`src/kb_web/server.py`](file:///c:/src/kb-web/src/kb_web/server.py), whitelisted in `PUBLIC_EXACT_PATHS`.

### 2. CLI Authentication Hardening & Remote Restart
- **Resolves CLI 401 Unauthorized**: Updated `is_request_authenticated` and `verify_api_key` in [`src/kb_web/base.py`](file:///c:/src/kb-web/src/kb_web/base.py) to check incoming `X-API-Key` headers against registered client keys in database table `CliApiKey` (`cli_api_keys`).
- **Remote Server Restart Endpoint**: Added `POST /api/cli/system/restart` in [`src/kb_web/routers/cli_api.py`](file:///c:/src/kb-web/src/kb_web/routers/cli_api.py). Returns confirmation and schedules an orderly exit in a background thread, enabling systemd (`Restart=always`) or Docker to restart the service.
- **CLI Restart Command**: Added `kb-web-cli restart` in [`kb-web-cli/src/kb_web_cli/main.py`](file:///c:/src/kb-web/kb-web-cli/src/kb_web_cli/main.py) with automated polling against `/api/health` to confirm when the server is back online.

### 3. Workspace Versioning & Freeze-to-Article
- **`WorkspaceSnapshot` ORM Model**: Defined in [`src/kb_web/models_orm.py`](file:///c:/src/kb-web/src/kb_web/models_orm.py) with `workspace_id`, `version_tag`, `description`, `files_snapshot` (JSON text), `is_frozen`, and `created_at`.
- **Snapshot REST Endpoints**: Implemented in [`src/kb_web/routers/workspaces.py`](file:///c:/src/kb-web/src/kb_web/routers/workspaces.py):
  - `POST /api/workspaces/{id}/snapshots`: saves current file tree as an immutable tagged snapshot.
  - `GET /api/workspaces/{id}/snapshots`: lists all snapshots for a workspace.
  - `GET /api/workspaces/{id}/snapshots/{snapshot_id}`: retrieves snapshot details and file contents.
  - `POST /api/workspaces/{id}/snapshots/{snapshot_id}/restore`: restores workspace files to the exact snapshot state.
  - `POST /api/workspaces/{id}/snapshots/{snapshot_id}/freeze-article`: compiles the snapshot file manifest and code files into a permanent Knowledge Base article in `FetchedPage` (`workspace://{ws_id}/snapshot/{version_tag}`).
- **IDE UI Enhancements**: Added a Snapshots tab in the Activity Bar, a Snapshots sidebar panel with Tag/Restore/Publish buttons, and JavaScript controllers in [`src/kb_web/templates/workspace_ide.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/workspace_ide.j2.html).

### 4. Coding Agent Tools & Native `ollama.systemone` Tev1 Decision Integration
- **`ollama>=0.6.3` Upgrade**: Updated `pyproject.toml` and installed `ollama>=0.6.3` supporting native `ollama.systemone(...)` without external SDKs.
- **`LoggedOllamaClient.systemone`**: Added call duration tracking and logging to database table `ollama_logs` in [`src/kb_web/base.py`](file:///c:/src/kb-web/src/kb_web/base.py).
- **Agent Tool Primitives**: Implemented in [`src/kb_web/agent_tools.py`](file:///c:/src/kb-web/src/kb_web/agent_tools.py):
  - `tool_create_file(session, workspace_id, file_path, content, annotation)`: creates or replaces files with annotations.
  - `tool_read_file(session, workspace_id, file_path, start_line, end_line)`: reads slice windows of files without blowing context.
  - `tool_edit_file(session, workspace_id, file_path, target_content, replacement_content)`: performs precise snippet replacement.
- **Tev1 Decision Gating**: Implemented in [`src/kb_web/workspace_agent.py`](file:///c:/src/kb-web/src/kb_web/workspace_agent.py). Queries `tev1` via `client.systemone` to classify intent (`choice`: `chat`, `read_file`, `create_file`, `edit_file`), identify the target file, and evaluate whether reading is needed (`noul`).
- **CLI Terminal Harness**: Added `kb-web-cli workspace agent <workspace_id>` interactive pairing REPL in [`kb-web-cli/src/kb_web_cli/main.py`](file:///c:/src/kb-web/kb-web-cli/src/kb_web_cli/main.py).

---

## Verification & Testing Results

1. **Unit & Integration Tests**:
   - Created [`tests/test_cli_auth_and_workspaces.py`](file:///c:/src/kb-web/tests/test_cli_auth_and_workspaces.py) testing `/api/health`, CLI API key auth, `/system/restart`, disk cache resilience, tool primitives, snapshot restore/freeze, and `tev1` mock gating.
   - Full pytest run: **106 passed** (0 failures).
2. **Template Verification**:
   - `verify_ui_templates.py`: **21 HTML templates verified**, 0 warnings.
3. **Build Pipeline**:
   - `build.py`: Successfully completed `uv sync`, `pytest` (106 passed), package builds, and CLI wheel builds.
4. **VCS UAT Artifacts**:
   - Generated report in `uat/reports/` and execution log in `uat/logs/`.
