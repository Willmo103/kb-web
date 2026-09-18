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

