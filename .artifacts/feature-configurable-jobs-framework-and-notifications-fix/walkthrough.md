# Walkthrough: Configurable Jobs Framework, Notification UI Fix, Git Repo Importer & Rule 7 Transparency

## 1. Summary of Delivered Features & Fixes

All requested features, fixes, and architectural adjustments have been successfully implemented, verified with pre-commit automated checks, and committed to branch `feature/configurable-jobs-framework-and-notifications-fix` (targeting `development`):

1. **Strict Release Constraint**:
   - Work is confined strictly to `feature/configurable-jobs-framework-and-notifications-fix` branching off `development`. No merges to `production` or `master` were executed.

2. **Notification API & Dropdown Fix**:
   - Fixed the response parsing mismatch in [base.j2.html](file:///c:/src/kb-web/src/kb_web/templates/base.j2.html) where `/api/notifications` returns `{ unread_count, notifications }` envelope.
   - Fixed [api.py](file:///c:/src/kb-web/src/kb_web/routers/api.py) to resolve page URLs and `page_id` without hitting non-existent database columns.
   - Updated dropdown and floating toast links to route directly to `/view/page?url=...` for instant viewing of ingested web articles. Added complete dark mode styling to the notification menu.

3. **Modular Server Jobs & Dedicated Agents Framework**:
   - Decoupled the monolithic worker in [worker.py](file:///c:/src/kb-web/src/kb_web/worker.py) into independent, isolated jobs (`ServerJob` registry managed by `AutonomousWorker`).
   - Individual scheduling timespans: Each job has its own configurable `interval_minutes`, toggle state, and isolated execution lock.
   - Dedicated Ollama Model Assignment: Each job can be assigned its own LLM, embedding, or decision model with database persistence.
   - Built-in job roster: `wiki_curation` (AI wiki synthesis), `tag_curation` (topic taxonomy tags), `embedding_refresh` (Qdrant & SafeVector indexing), and extensible foundation stubs for `synthetic_qa`, `rag_eval`, and `link_crawler`.
   - Exposed REST APIs in [routers/worker.py](file:///c:/src/kb-web/src/kb_web/routers/worker.py): `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/run`, `POST /api/jobs/{id}/config`, `/admin/jobs/{id}/run`, `/admin/jobs/{id}/config`.
   - Comprehensive UI in [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html): Responsive job cards with live telemetry counters, inline interval & model inputs, and interactive "Run Now" triggers.

4. **Git Repository Web Importer**:
   - Ported Git clone and analysis engine (`rpr` devtul) into [repo_importer.py](file:///c:/src/kb-web/src/kb_web/repo_importer.py).
   - Added REST endpoint `POST /api/import/repo` in [routers/rest_api.py](file:///c:/src/kb-web/src/kb_web/routers/rest_api.py) accepting repository URL, branch, depth limits, and target collection.
   - Added 3rd tab **"📦 Pull & Import Git Repo"** to [url_import.j2.html](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html) with interactive parameters for branch selection, collection assignment, file size caps, and tree depth.

5. **Rule 7 Compliance & Operational Thresholds**:
   - Added Rule 7 to [GEMINI.md](file:///c:/src/kb-web/GEMINI.md) and Rule 6 to [.agents/rules/development_rules.md](file:///c:/src/kb-web/.agents/rules/development_rules.md) strictly prohibiting arbitrary hidden hardcoded limits.
   - Lifted hardcoded note taxonomy cap (100 notes in `taxonomy.py`) and surfaced dynamic setting `taxonomy_batch_limit` (default: 500, configurable up to 5000).
   - Exposed operational engine thresholds in [config.py](file:///c:/src/kb-web/src/kb_web/config.py) backed by database settings: `rag_search_top_k`, `similarity_threshold`, `ollama_timeout`, `notifications_poll_interval_seconds`, `page_cards_per_page`, `crawler_default_max_pages`, and `repo_import_default_depth`.
   - Added **"Engine Thresholds & Operational Limits"** configuration card to the General tab in [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html) and handled in [routers/admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py).

6. **Admin Model Selector & Dark Mode Polishing**:
   - Eliminated leftover duplicate text input and select boxes in [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html), replacing them with unified text input backed by native `<datalist id="admin_model_options">` displaying active VRAM models.
   - Fixed dark mode styling across Quick Diagnostics mini-card and prompt generation sections.

7. **Workspace IDE Live Reactivity & Multi-Language Syntax Highlighting**:
   - Added `GET /api/workspaces/{workspace_id}/files` in [routers/workspaces.py](file:///c:/src/kb-web/src/kb_web/routers/workspaces.py) returning complete workspace virtual files.
   - Added `refreshWorkspaceFilesFromServer()` and background polling in [workspace_ide.j2.html](file:///c:/src/kb-web/src/kb_web/templates/workspace_ide.j2.html) to reflect agent file creation/modification live without leaving the workspace.
   - Added language inference and syntax highlighting in [workspaces.py](file:///c:/src/kb-web/src/kb_web/routers/workspaces.py) and [workspace_ide.j2.html](file:///c:/src/kb-web/src/kb_web/templates/workspace_ide.j2.html) for PowerShell (`.ps1`, `.ps`, `.psm1`, `.psd1`) and Windows Batch (`.cmd`, `.bat`).

---

## 2. Test Verification Summary

- **UI Component Verification**:
  ```powershell
  uv run python .agents/skills/ui-component-uat-check/scripts/verify_ui_templates.py
  ```
  *Result*: 25 HTML templates verified with 0 warnings.

- **Feature Tests**:
  ```powershell
  uv run pytest tests/test_jobs_framework_and_notifications.py -v
  ```
  *Result*: 7 passed in 2.65s.

- **Full Pytest Suite**:
  ```powershell
  uv run pytest
  ```
  *Result*: 179 passed, 0 failed in 175.62s.

- **Build Pipeline Verification**:
  ```powershell
  uv run python build.py
  ```
  *Result*: Clean environment sync, 179 tests passed, pipeline completed successfully.

- **VCS UAT Artifacts Generated**:
  - `uat/logs/test_log_configurable_jobs_framework_and_notifications_20261012_233006.log`
  - `uat/reports/uat_report_configurable_jobs_framework_and_notifications_20261012_233006.md`
  - Interactive UAT Feedback Form: `.artifacts/feature-configurable-jobs-framework-and-notifications-fix/uat_form.html`
