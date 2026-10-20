# Feature Walkthrough & Verification Guide

**Branch**: `feature/evals-refactor-taxonomy-notifications-agents`  
**Date**: 2026-10-19  
**Status**: Verified & Tested (19/19 new tests passing, 29/29 UI templates validated)

---

## 1. Evals Studio Overhaul & Prompt Promotion

### Capabilities Implemented
1. **Model Filtering by Type Across Studio Tabs**:
   - Tab 1 (Prompt Matrix): Chat and text generation LLMs only (`classify_model_type(name) == 'llm'`).
   - Tab 2 (Decision Calibration): SystemOne decision and gating models only (`d1`, `tev1`).
   - Tab 3 (Embedding Benchmarks): Vector embedding models only (`embeddinggemma`, `nomic-embed-text`, etc.).
2. **Per-Model Generation Parameters**:
   - Expandable "Model Generation Parameters (Per-Model Overrides)" drawer beneath model badges.
   - Hover tooltips on each parameter explaining performance and sampling trade-offs (`temperature`, `top_p`, `top_k`, `num_predict`, `num_ctx`).
   - Overrides forwarded via `model_options` in `POST /api/evals/matrix/stream` and `POST /api/evals/matrix`.
3. **Free-Form Evaluation & Empty Prompt**:
   - "+ Add Empty Prompt" button allows scratchpad testing without relying on pre-canned templates.
4. **"Set As... ▾" Direct Prompt Promotion**:
   - Promotion dropdown menu on tested prompt cards.
   - Target destinations:
     * Wiki Curation System Prompt (`wiki_prompt`)
     * YouTube Media Summary Prompt (`youtube_wiki_prompt`)
     * Tag Curation Taxonomy Prompt (`tags_prompt`)
     * Agentic RAG System Instructions (`rag_system_prompt`)
     * Custom Agent Persona / Instructions (`custom_agent:<agent_id>`)
   - Backend endpoint: `POST /api/evals/prompts/promote`.

---

## 2. Notes Deletion & Taxonomy Folder Pruning

### Capabilities Implemented
- Whenever notes are deleted via `DELETE /api/notes/{id}` or batch-deleted via `DELETE /api/notes/batch`, `_prune_empty_taxonomy_categories()` executes recursively bottom-up.
- Empty child folders and empty ancestor parent categories are cleanly removed from the database, preventing orphaned empty taxonomy folders from lingering in the UI.

---

## 3. Perpetual Notifications & History Portal

### Capabilities Implemented
- Ingestion notifications remain in perpetuity until explicitly cleared by the user.
- **Dedicated Portal**: Navigating to `/notifications` loads `notifications_history.j2.html`.
- **Features**:
  - Filter by stage (`fetch`, `wiki`, `tags`, `vector`, `video`, `agent`, `error`).
  - Filter by status (`success`, `warning`, `failed`, `info`).
  - Filter by read/unread state.
  - Keyword search across notification titles, task IDs, and error message content.
  - Interactive pagination controls.
  - Single notification deletion (`DELETE /api/notifications/{id}`) and mark-as-read (`PATCH /api/notifications/{id}/read`).
  - Batch deletion (`DELETE /api/notifications`).
- Dropdown menu in `base.j2.html` updated with a direct "View All History →" button.

---

## 4. Autonomous Topic-Expert Custom Agent System ("Mini OpenClaw")

### Capabilities Implemented
1. **Distinct Page Entities**:
   - **`TopicWikiPage`**:
     * Logical path slugs (e.g. `overview`, `architecture/storage`, `election`).
     * Hierarchical sidebar navigation tree of all published pages for the agent.
     * Markdown formatting with citation links referencing library items.
     * Route: `/wiki/{agent_id}/{path:path}`.
   - **`AgentPage`**:
     * Dynamic canvas addressed by unique hash token.
     * Render modes:
       - `themed`: Embedded inside the site layout with dark mode, interactive form inputs, and approval cards.
       - `raw`: Pure unstyled HTML output without inherited base template or site chrome.
     * Route: `/pages/agent/{hash_id}`.
2. **Controlled Steered Grounding**:
   - Grounding discovery strictly queries already-imported library items (`FetchedPage`) in the database.
   - Relevant items are recorded into `agent_observations` working memory.
3. **Strict Human-In-The-Loop (HITL) Local Python Execution**:
   - Agents propose execution via `propose_python_execution()`.
   - Proposing code creates an `AgentPythonApproval` record and an approval `AgentPage`, dispatching an alert notification.
   - Execution in the local `.venv` environment **only occurs after explicit user approval** (`POST /api/pages/agent/{hash_id}/submit` with `{"decision": "approve"}`).
   - Rejection records feedback and aborts execution safely.
4. **Deliberation Loop**:
   - Autonomous background turn (`deliberate_agent()`) that processes working memory observations, sets tasks for itself (`agent_self_tasks`), and compiles/updates topic wiki pages.

---

## 5. Test Suite Verification Summary

| Test File | Total Tests | Status |
|-----------|-------------|--------|
| `tests/test_notes_taxonomy_prune.py` | 3 | ✅ All Passing |
| `tests/test_notifications_history.py` | 5 | ✅ All Passing |
| `tests/test_evals_freeform_and_per_model.py` | 4 | ✅ All Passing |
| `tests/test_custom_agent_pages.py` | 7 | ✅ All Passing |
| `tests/test_notes_cascade_and_workspace_ux.py` | 7 | ✅ All Passing |
| **Combined Feature Test Suite** | **26** | **✅ 100% Passing** |
| `verify_ui_templates.py` | 29 Templates | ✅ 0 Warnings |
