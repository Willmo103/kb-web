# Walkthrough: Authentication Hardening, Remote Restart, Workspace Versioning, Tev1 Decision Gating & Agentic RAG Reports

## Overview
This sprint iteration addresses server reboot authentication recovery, CLI 401 Unauthorized errors, adds a remote restart command, introduces full workspace version snapshots with freeze-to-article publishing, equips the coding agent with native `ollama>=0.6.3` `systemone` `tev1` decision gating and granular file tools, replaces the legacy single-article chat drawer with an Autonomous Agentic RAG Report Generator, and updates the workspace IDE welcome card.

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

### 5. Elimination of Single-Article Chat & Navigation Update
- **Article Chat Retirement**: Removed the single-article chat drawer, `#chat-drawer-backdrop`, and chat controller JavaScript from [`src/kb_web/templates/view_page.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html). Replaced with an active "📊 RAG Research Report" button linking directly to `/reports/rag?q=...`.
- **Navigation Updates**:
  - Replaced `💬 Chat` link with `🔬 RAG` in [`src/kb_web/templates/base.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html).
  - Replaced `💬 Chat Threads` link with `🔬 RAG Reports` in [`src/kb_web/templates/pages_list.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/pages_list.j2.html).
  - Configured HTTP 302 redirect from `/conversations` to `/reports/rag` in [`src/kb_web/routers/conversations.py`](file:///c:/src/kb-web/src/kb_web/routers/conversations.py).

### 6. Autonomous Agentic RAG Report Generator & Tev1 Decision Scoring
- **Multi-Sub-Agent Engine ([`src/kb_web/rag_agent.py`](file:///c:/src/kb-web/src/kb_web/rag_agent.py))**:
  - `tag_search_subagent`: crawls taxonomy and article/note tags for query matches.
  - `vector_rag_subagent`: computes query embedding and runs similarity search against `ChunkEmbedding` (supports PostgreSQL `pgvector` `<->` cosine distance and SQLite vector fallback).
  - `text_search_subagent`: performs full-text lexical search across titles, markdown content, and note bodies.
  - `aggregate_candidates`: merges, deduplicates, and provenance-boosts candidates found across multiple sub-agents.
  - `tev1_scoring_subagent`: evaluates candidate articles against user query and research purpose using native `ollama.systemone` with model `tev1`. Batches up to 48 questions (8 candidates x 6 technical criteria: relevance, code actionability, technical depth, architectural authority, factual density, synthesis readiness) in a single turn.
  - `compile_rag_report`: compiles vetted primary evidence into a publication-grade Markdown research report with executive summary, answers, code, comparison table, and cited links.
- **RAG Report Web Portal ([`src/kb_web/templates/rag_report.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/rag_report.j2.html))**:
  - Live query input with quick presets and optional purpose parameter.
  - Real-time pipeline visualizer (sub-agent status, candidate metrics, `tev1` score badge).
  - `tev1` decision scoring table displaying criteria questions, pass/fail status, and percentage confidence.
  - Rendered Markdown report viewer with Copy to Clipboard, Download `.md`, and Save to Notes integration.
  - Recent research reports sidebar drawer.
- **REST API ([`src/kb_web/routers/rag_reports.py`](file:///c:/src/kb-web/src/kb_web/routers/rag_reports.py))**:
  - `GET /reports/rag`: serves the RAG report UI.
  - `POST /api/reports/rag/generate`: initiates the multi-sub-agent pipeline, runs `tev1` gating, and generates the report.
  - `GET /api/reports/rag`: lists previous reports.
  - `GET /api/reports/rag/{id}`: retrieves a single report.
  - `POST /api/reports/rag/{id}/save-to-notes`: exports the synthesized report directly to Knowledge Base Notes.
  - `DELETE /api/reports/rag/{id}`: deletes a report.
- **CLI Command ([`kb-web-cli/src/kb_web_cli/main.py`](file:///c:/src/kb-web/kb-web-cli/src/kb_web_cli/main.py))**:
  - `kb-web-cli rag report "<query>"` with `--purpose`, `--output`, `--model`, and `--save-notes` flags.

### 7. UAT Tester Welcome Card Fix
- Updated the AI Agent welcome card in [`src/kb_web/templates/workspace_ide.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/workspace_ide.j2.html) with:
  - `tev1 Gated` badge.
  - Active tool cards: `create_file` (with commentary annotations), `read_file` (window slice inspection), `edit_file` (precise search-and-replace).
  - Direct CLI launch reference: `kb-web-cli workspace agent <ws_id>`.

### 8. Site-Wide Muted Neon Dark Mode & Moon/Sun Circle Toggle
- **High-Contrast Muted Neon Palette**: Implemented in [`src/kb_web/templates/base.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html) using deep obsidian/slate backgrounds (`#090e17` / `#111827`), technological slate borders (`#1e293b`), high-contrast crisp text (`#f8fafc` / `#cbd5e1`), and muted neon accents (electric cyan `#38bdf8`, neon violet `#c084fc`, emerald `#34d399`, amber `#fbbf24`, rose `#f87171`).
- **Moon/Sun Circle Toggle Button**: Added circular button (`theme-circle-toggle`) with smooth 360-degree rotation animation, swapping amber sun (☀️) and cyan glowing moon (🌙) icons across both authenticated and guest navigation headers.
### 9. Configurable RAG Pipeline & Production UI Terminology Audit
- **Full RAG Pipeline Configuration**:
  - In [`src/kb_web/rag_agent.py`](file:///c:/src/kb-web/src/kb_web/rag_agent.py), added configurable limits (tag, vector, text, pool size, top sources), thresholds (min vector similarity, min decision score), search toggles, and dynamic decision gating questions manager.
  - Implemented database persistence via `SettingExternal(key="rag_pipeline_config")` (`get_rag_pipeline_config`, `save_rag_pipeline_config`).
  - Added REST endpoints in [`src/kb_web/routers/rag_reports.py`](file:///c:/src/kb-web/src/kb_web/routers/rag_reports.py): `GET /api/reports/rag/config`, `POST /api/reports/rag/config`, `POST /api/reports/rag/config/reset`.
  - Added an expandable/collapsible **Pipeline Configuration** panel in [`src/kb_web/templates/rag_report.j2.html`](file:///c:/src/kb-web/src/kb_web/templates/rag_report.j2.html) allowing users to tweak parameters, toggle searches, add/edit/delete gating questions, and click "Save Configuration" directly on the RAG screen.
- **Production UI Naming & Terminology Standard**:
  - Audited site-wide templates to eliminate internal developer shorthand, verbatim conversational terms, and library feature branding across buttons and links.
  - Replaced "ERP Grid" with "Reporting".
  - Replaced "tev1 Decision Gated" with "Decision Gated".
  - Replaced "Engine Wiki Storage File" with "Article Profile".
  - Replaced "Ollama Coding Agent" with "Coding Assistant".
  - Codified permanent rule in [`GEMINI.md`](file:///c:/src/kb-web/GEMINI.md): Rule 6 (Production UI Naming & Terminology Standard).

---

## Verification & Testing Results

1. **Automated Test Suite**:
   - [`tests/test_cli_auth_and_workspaces.py`](file:///c:/src/kb-web/tests/test_cli_auth_and_workspaces.py): 7 tests passing.
   - [`tests/test_rag_agent_and_reports.py`](file:///c:/src/kb-web/tests/test_rag_agent_and_reports.py): **10 tests passing** (tag/vector/text sub-agents, decision scoring matrix, fallback compilation, REST API workflow, redirect of /conversations, CLI commands, dark mode theme/toggle, RAG pipeline configuration API and persistence, custom pipeline execution, and clean labels audit).
   - Full pytest run: **116 passed** (0 failures).
2. **Template Verification**:
   - `.agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py`: **22 HTML templates verified**, 0 warnings.
3. **Build Pipeline**:
   - `build.py`: Successfully completed `uv sync`, `pytest` (116 passed), `uv build` for `kb-web-0.2.0`, and `uv build` for `kb-web-cli-0.1.0`.
4. **VCS UAT Artifacts**:
   - Generated report in `uat/reports/uat_report_Configurable RAG Pipeline & Clean UI Labels_20261003_032139.md` and execution log in `uat/logs/test_log_Configurable RAG Pipeline & Clean UI Labels_20261003_032139.log`.


