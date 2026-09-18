# Sprint 6 Tracker: RAG Search, Multi-Model Embeddings, Article Chat, Notes/Obsidian, Admin Redesign, & Custom Reports

**Sprint Issue**: #68  
**Branch**: `feature/sprint-6-rag-chat-notes-reports`  
**Base**: `production`  

This document tracks implementation status, verification gates, and issue resolution for Sprint 6.

---

## Sprint Checklist

- [ ] **#62 - Main Page RAG Chunk Search Across Articles & Videos**
  - [ ] Database chunk vector retrieval function (`find_nearest_chunks`) supporting `pgvector` and Qdrant.
  - [ ] REST API endpoint `POST /api/search/rag` returning top-k matching chunks with similarity scores and document metadata.
  - [ ] Main page UI component (`pages_list.j2.html`) with interactive RAG search mode toggle, search bar, and chunk results grid.
  - [ ] Direct anchor jump links navigating to specific matched chunks within article and video detail views.

- [ ] **#63 - Multi-Model Embedding Reindexing, Model Comparison, & Vector Source Toggle**
  - [ ] Multi-model embedding schema update (support model identifier tag/column in `ChunkEmbedding`, `ArticleEmbedding`, `VideoEmbedding`, or model-specific Qdrant collections).
  - [ ] Reindexing CLI command and admin trigger (`kb-web reindex --model <model_name>` / `POST /api/embeddings/reindex`).
  - [ ] Model comparison explorer view (`/similarity/compare`) showing side-by-side search matches, cosine scores, and ranking differences.
  - [ ] Admin setting and runtime toggle for active vector source model.

- [ ] **#64 - Article-Level Ollama Chat & Dedicated Conversations View**
  - [ ] Schema additions for persistent chat: `chat_conversations` and `chat_messages` tables with article/video references.
  - [ ] In-context slide-out chat widget on `/view/page` injecting article text, title, and wiki as system context.
  - [ ] REST endpoints for conversation lifecycle: `GET /api/conversations/article/{url}`, `POST /api/conversations/message`, `GET /api/conversations`.
  - [ ] Dedicated `/conversations` dashboard page listing all active threads, linked items, message count, and preview snippets.

- [ ] **#65 - Notes & Code Ingestion, Browser Monaco Editor, & Obsidian Vault Mirroring**
  - [ ] Item schema subclass: `NoteItem` / database source representation for pasted markdown, code snippets, and vault notes.
  - [ ] Automated wiki generation, auto-titling, and tag curation pipeline for notes.
  - [ ] Monaco Editor integration for web-based code and markdown editing with live preview.
  - [ ] Obsidian vault folder/ZIP upload handler with directory tree preservation, file tree sidebar, and link resolution.

- [ ] **#66 - Admin Portal Modernization & Space-Efficient Tabbed Layout**
  - [ ] Restructure `/admin` into modern tabbed/pill navigation:
    - *Tab 1*: Overview & System Status
    - *Tab 2*: AI & Prompts
    - *Tab 3*: Database & Backups
    - *Tab 4*: Media & YouTube
    - *Tab 5*: Diagnostics & Logs
  - [ ] Compact form controls, reduced padding/margins, and removal of dead whitespace.
  - [ ] Retain all existing functionality (backup downloads, direct HTTP/WebSocket upload, prompt version history modals, log viewer).

- [ ] **#67 - Custom Report & Data Grid Builder with Dynamic Joins, Filters, & Scheduled Exports**
  - [ ] Schema additions: `saved_reports` and `scheduled_export_jobs` tables.
  - [ ] Interactive ERP-style data grid explorer (`/reports`): dynamic column selector, joins across articles/videos/notes/collections/tags, multi-column sorting, grouping, and filtering.
  - [ ] On-demand export service generating `.xlsx`, `.csv`, and `.json` outputs.
  - [ ] Background job scheduler integration for recurring automated report exports.
