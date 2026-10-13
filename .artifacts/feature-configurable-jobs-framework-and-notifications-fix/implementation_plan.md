# Implementation Plan: Configurable Server Jobs Framework, Notifications Fix, Repo Importer UI, Configuration Transparency Audit, Admin Dark Mode, Workspace Tool Reactivity & Syntax Highlighting

**Sprint / Iteration:** v0.5.9  
**Feature Branch:** `feature/configurable-jobs-framework-and-notifications-fix`  
**Target Merge Base:** `development` (Strict Policy: **Do NOT merge to `production` or `master` unless explicitly requested**)  

---

## 1. Problem Statement & Mandatory Rules

### New Mandatory Rule: Strict Configuration Transparency & Admin Exposure
> [!IMPORTANT]
> **RULE: STRICT ADHERENCE**
> *"When a configuration value is needed it is added to the admin portal and docs for the agent and the user."*
> No arbitrary constants, batch limits, search top-k cutoffs, crawl depths, polling intervals, or thresholds may remain hidden or hardcoded in backend code or frontend scripts. All operational parameters MUST be registered in `config.py`, persisted in the database (`SettingOllama`/`SettingExternal`), exposed in the Admin Portal (`/admin`), and documented for both the user and agents.

### Audit of Arbitrary Configuration Values
1. **Notes Import & Taxonomy Batch Limits**:
   - `upload_obsidian_vault` (`routers/notes.py`): Unpacks all notes without arbitrary limits, but `ClassifyNotesRequest` (`routers/taxonomy.py`) hardcoded a default `limit: int = 100`, capping batch classification to 100 notes.
   - Fix: Expose `taxonomy_batch_limit` (default 100, configurable up to 5000 or unbounded) in `config.py` and Admin Portal.
2. **RAG & Search Limits**:
   - `rag_search_top_k` was hardcoded to 10 across `rest_api.py`, `rag_reports.py`, and `utils.py`.
   - `similarity_threshold` had a default in `config.py` (0.8) but had no input field in the Admin UI.
   - Fix: Expose `rag_search_top_k` and `similarity_threshold` in Admin Portal.
3. **Web Crawler & Repo Importer Limits**:
   - Crawler max links (default 25) and Repo Importer default depth (default 1).
   - Fix: Expose `crawler_default_max_pages` and `repo_import_default_depth` in Admin Portal.
4. **UI Polling & Pagination**:
   - Notifications polling interval was hardcoded to 5000ms in `base.j2.html`.
   - Cards per page was hardcoded to 20 in `pages.py`.
   - Fix: Expose `notifications_poll_interval_seconds` and `page_cards_per_page` in Admin Portal.

---

## 2. Proposed Architecture & Component Designs

### Component A: Notifications UI & API Envelope Fix
- **Backend (`src/kb_web/routers/api.py`)**: Attach resolved `page_id` by matching notification `url` to `FetchedPage.id`.
- **Frontend (`src/kb_web/templates/base.j2.html`)**: Extract `data.notifications` from the response envelope; apply dark mode styles to dropdown rows and toasts.

### Component B: Modular Server Jobs & Agents Framework
- **Core Architecture (`src/kb_web/worker.py`)**:
  - Modular server jobs engine replacing the single monolithic worker:
    1. **`wiki_curation`**: Autonomous AI Wiki Generation.
    2. **`tag_curation`**: Autonomous Tag Taxonomy Curation.
    3. **`embedding_refresh`**: Autonomous Embedding Vector Generation.
    4. **Extensible Stubs**: Synthetic QA, RAG Evaluation, and Link Crawler.
  - Independent timespans (configurable interval in minutes per job).
  - Independent Ollama model selection (LLM, decision/gating, or embedding model).
  - Persistent settings stored in `SettingOllama` (`job_config_{job_id}`).
  - Independent run timers, metrics tracking, and on-demand "⚡ Run Now" buttons in the Admin dashboard.

### Component C: Git Repository Web Importer UI & Backend
- **Backend (`src/kb_web/repo_importer.py` & `src/kb_web/routers/rest_api.py`)**: Port repo importer from PR 82, supporting shallow cloning, directory tree rendering, file pattern matching/excluding, and collection assignment.
- **Frontend (`src/kb_web/templates/url_import.j2.html`)**: Add a 3rd tab **"📦 Pull & Import Git Repo"** with live progress display.

### Component D: Configuration Transparency Engine & Admin UI Overhaul
- **Configuration Engine (`src/kb_web/config.py` & `routers/admin.py`)**:
  - Add properties for audited parameters: `taxonomy_batch_limit`, `rag_search_top_k`, `similarity_threshold`, `page_cards_per_page`, `notifications_poll_interval_seconds`, `crawler_default_max_pages`, `repo_import_default_depth`, `ollama_timeout`.
  - Store and reload values via `SettingOllama`/`SettingExternal` and disk cache.
- **Admin Portal UI (`src/kb_web/templates/admin.j2.html`)**:
  - Add an **Engine Thresholds & Batch Limits** configuration card.
  - Replace redundant dual Ollama text input with a unified model selector.
  - Fix dark mode classes on Quick Diagnostics mini-card and all elements in `tab-prompts`.

### Component E: Workspace Tool Live Reactivity & Syntax Highlighting
- **Live Tool Reactivity (`workspace_ide.j2.html`)**: Implement `refreshWorkspaceFilesFromServer()` triggered automatically after agent chat turns with tool calls, keeping `VFS`, file tree, and open editor tabs updated live.
- **Syntax Highlighting for PowerShell & Batch**:
  - Map `.ps1`, `.ps`, `.psm1`, `.psd1` $\rightarrow$ `"powershell"` in `workspaces.py` and `workspace_ide.j2.html`.
  - Map `.cmd`, `.bat` $\rightarrow$ `"bat"` in `workspaces.py` and `workspace_ide.j2.html`.
  - Map icons in `getFileIconName()`.

---

## 3. Verification & Testing Strategy

1. **Automated Unit & API Suite (`tests/test_jobs_framework_and_notifications.py`)**:
   - Test notification envelope parsing and `page_id` population.
   - Test independent execution of wiki, tag, and embedding jobs.
   - Test config persistence for new audited engine limits (`taxonomy_batch_limit`, `rag_search_top_k`, etc.).
   - Test Git repo importer endpoint.
   - Test language inference for `.ps1` and `.cmd`.
2. **UI & Template Validation**: Run `python uat/verify_ui_templates.py` (0 warnings).
3. **Pre-Commit Checks**: Run `uv run pytest` and `uv run python build.py`.
4. **VCS UAT Report & Interactive Feedback Form**: Generate test reports in `uat/reports/` and provide interactive HTML feedback form.

---

## 4. Release Guardrails

- Work strictly on `feature/configurable-jobs-framework-and-notifications-fix`.
- Open draft PR into `development`.
- **DO NOT merge to `production` or `master` unless explicitly requested by the user.**
