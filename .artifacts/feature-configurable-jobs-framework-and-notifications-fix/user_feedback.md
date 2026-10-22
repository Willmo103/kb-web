# User Feedback & Directives: Iteration v0.5.9

**Date:** 2026-10-12  
**Branch:** `feature/configurable-jobs-framework-and-notifications-fix`  
**Iteration:** v0.5.9  

---

## 1. Directives & New Mandatory Rules

### New Mandatory Agent Rule: Strict Configuration Transparency & Admin Exposure
> [!IMPORTANT]
> **RULE: STRICT ADHERENCE**
> *"When a configuration value is needed it is added to the admin portal and docs for the agent and the user."*
> No arbitrary constants, batch limits, search top-k cutoffs, crawl depths, polling intervals, or thresholds may remain hidden or hardcoded in backend code or frontend scripts. All operational parameters MUST be registered in `config.py`, persisted in the database (`SettingOllama`/`SettingExternal`), exposed in the Admin Portal (`/admin`), and documented in `README.md` and `GEMINI.md`.

### Release & Tiered Lifecycle Policy
- **User Directive:** "Dont merge all the way to master **unless I tell you to**.."
- **Resolution:** Work strictly on `feature/configurable-jobs-framework-and-notifications-fix`. Do NOT merge to `production` or `master` without explicit user permission.

---

## 2. Issues, Audit Findings & Solutions

### Item 1: Notes ZIP Import & Arbitrary 100 Limit Audit
- **User Question:** "are we limiting the import of a notes zip file to 100 notes? Why if so? please remove or expose ALL ARBITRARY CONFIGURATION VALUES to the ADMIN PORTAL this is going to require an audit of the codebase and an indexing of all of the configurations like number of notes taxonomy looks at, or number of notes importer, and anything on the UI also."
- **Audit Findings:**
  - `upload_obsidian_vault` (`src/kb_web/routers/notes.py`) unpacks all markdown notes without an arbitrary file limit.
  - HOWEVER, `ClassifyNotesRequest` in `src/kb_web/routers/taxonomy.py` had a hardcoded default `limit: int = 100`, capping batch classification to 100 notes at a time!
  - Other audited hardcoded values:
    - RAG retrieval `top_k`: hardcoded to 10 in `rest_api.py`, `rag_reports.py`, and `utils.py`.
    - Similarity threshold: default 0.8 in `config.py`, but missing an input field in the Admin UI.
    - Web Crawler max links: default 25 hardcoded in crawler routes.
    - Repo importer default depth: hardcoded to 1.
    - Notifications polling frequency: hardcoded to 5000ms in `base.j2.html`.
    - Library cards per page: hardcoded to 20 in `pages.py`.
- **Resolution:** Expose all of these configuration values to `config.py`, persist them to `SettingOllama`/`SettingExternal`, and build a comprehensive **Advanced Engine & Thresholds** section in the Admin Portal.

### Item 2: Notification Display Failure
- **User Issue:** "The notification API seems to be being hit in the server logs but I am not seeing any notifications in the webpage. When I click the notification button the display is empty."
- **Root Cause:** `/api/notifications` returns an envelope object `{"status": "success", "unread_count": N, "notifications": [...]}`. In `base.j2.html`, JavaScript called `notifs.filter(...)` directly on the envelope object, throwing a silent `TypeError` that aborted rendering.
- **Resolution:** Parse `data.notifications`, populate `page_id` in backend records, and format notification rows with dark mode styles.

### Item 3: Modular Server Jobs & Agents Framework
- **User Issue:** "I dont really have the configuration ability over setting up server jobs and agents that I wanted to in the admin portal when I requested the feature. I want to have seperate jobs for tags and wikis not just one agent that hits the first thing with neither and does one or the other. also I want to be able to configure the timespan between runs of the job. basically I want the framework for defining and running jobs with some ollama model (decision, llm or embedding model)."
- **Resolution:** Refactor `worker.py` into a modular server jobs framework with separate jobs for Wiki Generation (`wiki_curation`), Tag Curation (`tag_curation`), and Embedding Refresh (`embedding_refresh`). Allow independent configuration of run intervals (minutes), enabled/paused state, and assigned Ollama model. Provide interactive job cards with individual "⚡ Run Now" triggers in the Admin Portal.

### Item 4: Git Repository Web Importer
- **User Issue:** "how the hell am i supposted to pull a repo and import that into the webpage from the UI? that was something else that came up in testing."
- **Resolution:** Add a 3rd tab **"📦 Pull & Import Git Repo"** to `/import` (`url_import.j2.html`), backed by `repo_importer.py` and `POST /api/import/repo`, supporting shallow cloning, directory tree rendering, file pattern matching/excluding, and collection assignment.

### Item 5: Admin Model Input Redundancy & Dark Mode Gaps
- **User Issue:** "in the admin panel there is an extra text entry field for ollama that is left over from when we started polling the server directly." and "The ui on the admin portal tab Prompts and Generation the model details section does not toggle to dark mode."
- **Resolution:** Consolidate redundant inputs into a unified model selector with live Ollama polling; add full dark mode styling (`dark:from-gray-900 dark:to-gray-850 dark:border-gray-800 dark:text-gray-100`) to the Quick Diagnostics card and all elements in `tab-prompts`.

### Item 6: Workspace Tool Live Reactivity
- **User Issue:** "The workdspace file tool use does not populate the files in the workspace in a live reactive sort of way. I have to leave the workspace and reenter to see the filechanges that the models makes."
- **Resolution:** Implement live VFS/filetree sync (`refreshWorkspaceFilesFromServer()`) in `workspace_ide.j2.html`, automatically triggered whenever the coding agent executes file tools.

### Item 7: Syntax Highlighting for PowerShell & Batch
- **User Issue:** "file types are still not being hilighted .ps (see attached screenshots)"
- **Resolution:** Map `.ps1`, `.ps`, `.psm1`, `.psd1` $\rightarrow$ `"powershell"` and `.cmd`, `.bat` $\rightarrow$ `"bat"` across `_infer_language` in `workspaces.py` and `VFS.inferLanguage` in `workspace_ide.j2.html`, activating Monaco Editor's built-in syntax tokenizers.
