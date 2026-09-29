# User Feedback & Sprint Requirements

**Branch**: `feature/sprint-6-rag-chat-notes-reports`  
**Base**: `production`  
**Sprint Tracking Issue**: #68  
**Date**: 2026-09-18  

---

## 1. Context & Branching Constraints

* **Sprint 4-5 Merge Status**: The merge of `sprint-4-5` has **NOT** been completed yet. This new feature sprint is developed independently on its own branch directly off `production`.
* **Branch Created**: `feature/sprint-6-rag-chat-notes-reports` checked out from `production` at commit `8694c65`.
* **VCS / Artifact Directory**: `/.artifacts/feature/sprint-6-rag-chat-notes-reports/`.

---

## 2. User-Specified Feature Requests

### A. Main Page Semantic / RAG Chunk Search (Issue #62)
* Expose interactive RAG search across all article and video embeddings directly from the main web portal (`/` or `/pages`).
* Allow users to enter freeform text queries and retrieve the exact document/transcript chunks that match closest.
* Display chunks with similarity scores, parent document metadata, and direct jump links to the corresponding chunk in the parent article or video.

### B. Multi-Model Embedding Reindexing, Comparison, & Vector Source Toggle (Issue #63)
* Ability to reindex (re-embed) all knowledge base items using separate embedding models (e.g., `embeddinggemma`, `nomic-embed-text`, `bge-m3`).
* Side-by-side comparison tool to evaluate chunk retrieval and nearest-neighbor results across models.
* Setting/toggle to switch which model's vectors are actively used as the source for displaying nearest neighbors, recommendations, and search results.

### C. Article-Level Ollama Chat & Dedicated Conversations View (Issue #64)
* Expose in-context Ollama chat at the individual article level (`/view/page`, `/view/article`).
* Conversations must persist per article so chat history is retained and restored whenever returning to an article.
* Global conversations view (`/conversations`) displaying all active and past conversations, linking each thread to its associated article(s), timestamps, and message previews.

### D. Notes & Code Ingestion, Browser Monaco Editor, & Obsidian Vault Mirroring (Issue #65)
* Paste raw markdown or code snippets directly into the application and have them treated as uploaded items ("Notes" subclass of the Item schema).
* Automatically generate AI wiki entries and curated tags for notes via Ollama.
* Integrate the VS Code browser editor (Monaco Editor) for rich, in-browser code and markdown editing.
* Support uploading an entire Obsidian vault/folder with relative directory structure mirrored and editable in the browser.

### E. Admin Portal UI/UX Modernization (Issue #66)
* The existing `/admin` portal is a vertically sprawling, clunky layout requiring endless scrolling with substantial wasted space.
* Overhaul the layout into a sleek, compact, space-efficient dashboard utilizing tabbed/pill navigation (System Status, AI & Prompts, Backups & Recovery, YouTube & Media, Diagnostics & Logs).
* Eliminate oversized textareas, apply clean dark/light themes, and ensure responsiveness.

### F. Dynamic Custom Reports & ERP-Style Data Grid Builder (Issue #67)
* Interactive data grid view of database tables (articles, videos, notes, sites, tags, collections).
* Dynamic table joins linking related entities.
* Ability to add/remove columns, sort by fields, group by values, and apply complex multi-attribute filters.
* Save customized views as reusable reports for one-click re-use.
* Export report data on demand to Excel (`.xlsx`), CSV, or JSON.
* Schedule recurring export jobs running in the background.

---

## 3. GitHub Issues Reference Summary

| Issue | Type | Title | Status |
| :--- | :--- | :--- | :--- |
| **#62** | Feature | Feature: Main Page RAG Chunk Search Across Articles & Videos | OPEN |
| **#63** | Feature | Feature: Multi-Model Embedding Reindexing, Model Comparison, & Vector Source Toggle | OPEN |
| **#64** | Feature | Feature: Article-Level Ollama Chat & Dedicated Conversations View | OPEN |
| **#65** | Feature | Feature: Notes & Code Ingestion, Browser Monaco Editor, & Obsidian Vault Mirroring | OPEN |
| **#66** | UI/UX | UX/UI: Admin Portal Modernization & Space-Efficient Tabbed Layout | OPEN |
| **#67** | Feature | Feature: Custom Report & Data Grid Builder with Dynamic Joins, Filters, & Scheduled Exports | OPEN |
| **#68** | Sprint | Sprint 6: RAG Search, Multi-Model Embeddings, Article Chat, Notes/Obsidian, Admin Redesign, & Custom Reports | OPEN |

---

## 4. Turn 2 Plan Review & Design Directives (2026-09-18)

* **Plan Approved**: User reviewed and approved `implementation_plan.md`.
* **Data Grid Optimization Directive**:
  > *"We can represent the fields like HTML, Markdown and vectors as placeholders and not load them"*
* **Architectural Action**:
  - In the dynamic ERP data grid query engine (`/api/reports/query`), heavy textual content columns (`html_content`, `md_content`, `transcript_segments`) and embedding vector columns (`chunk_vector`, `embedding`) will NOT be loaded over the wire during standard grid rendering.
  - Instead, they are projected as metadata placeholders (e.g. `[HTML: 14.2 KB]`, `[Markdown: 3.1 KB]`, `[Vector: 768-dim]`).
  - Full payloads are only fetched on explicit user drilldown or when specifically selected during file export (`.xlsx`/`.csv`/`.json`).

---

## 5. Turn 3 UAT Results & Feedback (2026-09-25)

### Bug 1: Monaco Editor `require is not defined`
* **Symptom**: When navigating to `/notes/editor?id=...`, the Monaco editor fails to initialize and the console displays: `Uncaught ReferenceError: require is not defined at editor?id=57:159:1`.
* **Root Cause**: `note_editor.j2.html` placed the Monaco AMD loader `<script src=".../vs/loader.min.js">` inside `{% block head_extra %}`, but `base.j2.html` defines the block as `{% block extra_head %}`. The script tag was omitted from the rendered HTML.
* **Fix Action**: Change `{% block head_extra %}` to `{% block extra_head %}` in `note_editor.j2.html` (and support `head_extra` in `base.j2.html` for backward compatibility).

### Bug 2: "Chat About Article" Button Does Nothing
* **Symptom**: Clicking "Chat About Article" on `/view/page` yields no action, error, or modal.
* **Root Cause**: In `view_page.j2.html`, JavaScript variables `chatDrawer`, `chatBackdrop`, etc. were bound at top-level execution before the chat drawer modal elements (`id="chat-drawer"`, etc.) appeared in the HTML. As a result, `chatDrawer` was `null` and `openChatDrawer()` returned early.
* **Fix Action**: Resolve DOM elements dynamically inside `openChatDrawer()` / `DOMContentLoaded`, and position the modal markup cleanly before or alongside the controller.

### Bug 3: Report Generator Error on Group By
* **Symptom**: Selecting a `GROUP BY` column in `/reports` produces an error: `Failed to execute report query: Unexpected token '<', "<!DOCTYPE "... is not valid JSON`.
* **Root Cause**: In `src/kb_web/routers/reports.py`, the query generator emitted `GROUP BY {gtbl}.{gcol}` while `SELECT` requested non-grouped columns (`notes.id`, `notes.title`, etc.) without aggregate functions, triggering a PostgreSQL `psycopg2.errors.GroupingError` and unhandled 500 HTML response.
* **Fix Action**:
  1. In `reports.py`, wrap query execution in structured error handling so any database exception returns clean JSON `{ "detail": str(e) }` rather than an unhandled 500 HTML page.
  2. Implement robust ERP data grid grouping: cluster rows by group key (`ORDER BY {gtbl}.{gcol} ASC, ...`) and render collapsible group header rows with item counts in `reports.j2.html`.

### Feature 4: Persistent Replit-Lite Coding Workspaces & Ephemeral Generation Agent
* **User Request**: Incorporate `workspace.html` into `kb-web` with persistent workspace storage ("store my workspaces in perpetuity untill I delete them" like Replit), Pyodide Python WASM runtime, live sandboxed web preview with console interceptor, and ephemeral Ollama coding agent with diff review/apply.
* **Implementation Plan**:
  1. Add ORM models `Workspace` and `WorkspaceFile` in `src/kb_web/models_orm.py`.
  2. Add dedicated router `src/kb_web/routers/workspaces.py` with full REST API (`/api/workspaces`, `/api/workspaces/{id}`, `/api/workspaces/{id}/files`, `/api/workspaces/{id}/export-zip`, `/api/workspaces/{id}/generate`).
  3. Add `/workspaces` dashboard template (`workspaces_list.j2.html`) for creating, browsing, duplicating, and deleting persistent workspaces.
  4. Add full IDE studio template (`workspace_ide.j2.html`) based on `workspace.html` with Monaco Editor, Pyodide WASM, Sandboxed Web Preview, Ollama Agent, and persistent auto-saving to `kb-web`.
  5. Add top nav bar link `💻 Studio` in `base.j2.html`.

