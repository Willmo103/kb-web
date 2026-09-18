# Implementation Plan - Sprint 6: Knowledge Platform Expansion

Implement advanced semantic search, multi-model vector comparisons, in-context article chat, note/Obsidian ingestion, modern admin UI overhaul, and custom ERP-style report builder.

Sprint 6 is developed on a dedicated branch branched directly from `production`:
**Branch**: `feature/sprint-6-rag-chat-notes-reports`  
**Base**: `production`  
**Parent Sprint Issue**: #68  

---

## User Review Required

> [!IMPORTANT]
> **Branch & Sprint Isolation**: Per your instructions, this work is branched cleanly from `production` and is completely decoupled from the unmerged `sprint-4-5` branch.
> 
> **Created GitHub Issues**:
> - **#62**: Feature: Main Page RAG Chunk Search Across Articles & Videos
> - **#63**: Feature: Multi-Model Embedding Reindexing, Model Comparison, & Vector Source Toggle
> - **#64**: Feature: Article-Level Ollama Chat & Dedicated Conversations View
> - **#65**: Feature: Notes & Code Ingestion, Browser Monaco Editor, & Obsidian Vault Mirroring
> - **#66**: UX/UI: Admin Portal Modernization & Space-Efficient Tabbed Layout
> - **#67**: Feature: Custom Report & Data Grid Builder with Dynamic Joins, Filters, & Scheduled Exports
> - **#68**: Sprint 6 Master Tracking Issue

> [!NOTE]
> **Component Libraries & Dependencies**:
> - **Monaco Editor**: Will be embedded in the browser via CDN/AMD loader (lightweight, standard VS Code editor core) for note editing and markdown preview.
> - **Excel Exports**: Backend export using `openpyxl` / `xlsxwriter` for `.xlsx` generation.
> - **Data Grid**: High-performance vanilla JS data grid with sorting, filtering, and grouping, adhering to our Vanilla CSS / modern web app design standards. Heavy fields (`html_content`, `md_content`, `chunk_vector`, embeddings) are rendered as lightweight placeholders (e.g. `[HTML: 14KB]`, `[Vector: 768-dim]`) rather than loaded over the wire during standard grid rendering.

---

## Open Questions

> [!TIP]
> 1. **Obsidian Vault Media Handling**: When an Obsidian vault contains internal attachments (e.g. `.png` or `.pdf` inside an `attachments/` folder), should these be stored locally in `./media/notes/` and automatically resolved in the preview? (Recommended: Yes, mirror full vault assets).
> 2. **Multi-Model Embedding Defaults**: For multi-model comparison, are `embeddinggemma` and `nomic-embed-text` the primary models you'd like pre-populated as options?

---

## Proposed Changes by Component

---

### Component 1: Database Models & Migrations (`src/kb_web/models_orm.py`, `src/kb_web/models.py`)

#### [MODIFY] [models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py)
- **Multi-Model Embeddings**: Update `ChunkEmbedding`, `ArticleEmbedding`, `VideoEmbedding` to support an optional `model_name` column (defaulting to current active model, e.g. `embeddinggemma`), enabling multiple vector sets per item.
- **Chat History Schema**:
  - `ChatConversation`: `id`, `title`, `source_type` (article/video/general), `source_id` (url), `created_at`, `updated_at`.
  - `ChatMessage`: `id`, `conversation_id`, `role` (user/assistant/system), `content`, `timestamp`, `model`.
- **Notes & Uploaded Items Schema**:
  - `Note`: `id`, `title`, `content_md`, `syntax` (markdown/python/javascript/etc.), `folder_path`, `vault_name`, `created_at`, `updated_at`, `tags`, `wiki_summary`.
- **Saved Reports & Schedules**:
  - `SavedReportView`: `id`, `name`, `base_table`, `selected_columns`, `joins_config`, `sort_config`, `filter_config`, `group_config`, `created_at`, `updated_at`.
  - `ScheduledReportJob`: `id`, `report_view_id`, `cron_expression`, `export_format` (csv/xlsx/json), `destination`, `last_run_at`, `next_run_at`, `enabled`.

#### [MODIFY] [models.py](file:///c:/src/kb-web/src/kb_web/models.py)
- Add Pydantic schemas for `RAGSearchRequest`, `RAGSearchResult`, `ChatMessageRequest`, `NoteCreateRequest`, `ReportViewConfig`, `ExportJobRequest`.

---

### Component 2: Main Page Semantic / RAG Chunk Search (Issue #62)

#### [MODIFY] [rest_api.py](file:///c:/src/kb-web/src/kb_web/routers/rest_api.py)
- Add endpoint `POST /api/search/rag`:
  - Receives `query`, `top_k` (default 10), optional `model`, and optional `source_type` filter (`article` vs `video`).
  - Calls embedding model to embed the query.
  - Queries `chunk_embeddings` using cosine distance via `pgvector` / Qdrant.
  - Returns ranked list with chunk text, score, parent item URL, title, and chunk index.

#### [MODIFY] [pages_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/pages_list.j2.html)
- Add a "RAG Chunk Search" toggle button next to the standard title/content search bar.
- When active, search queries hit `/api/search/rag` and render interactive chunk result cards displaying matched excerpt snippets, similarity badges, and direct anchor links to the exact section in the article or video.

---

### Component 3: Multi-Model Embeddings & Model Comparison (Issue #63)

#### [NEW] [embeddings.py](file:///c:/src/kb-web/src/kb_web/routers/embeddings.py)
- Endpoint `POST /api/embeddings/reindex`: triggers asynchronous reindexing of items using a target embedding model.
- Endpoint `GET /api/embeddings/models`: lists available embedding models and their current indexing coverage.
- Endpoint `POST /api/embeddings/active-model`: toggles the active embedding model used for similarity and RAG across the app.
- Endpoint `POST /api/embeddings/compare`: accepts a search string or document ID and returns side-by-side vector results from 2+ models with rank comparison and cosine metrics.

#### [NEW] [embedding_comparison.j2.html](file:///c:/src/kb-web/src/kb_web/templates/embedding_comparison.j2.html)
- Visual side-by-side comparison dashboard to test models against identical queries and view nearest neighbor overlaps.

---

### Component 4: Article-Level Ollama Chat & Conversations View (Issue #64)

#### [NEW] [conversations.py](file:///c:/src/kb-web/src/kb_web/routers/conversations.py)
- `GET /api/conversations/article?url=...`: retrieves existing conversation history for an article.
- `POST /api/conversations/chat`: streams or generates assistant response with context injection (article summary, full markdown or top matching chunks).
- `GET /api/conversations`: paginated list of all conversations across all articles.
- `DELETE /api/conversations/{id}`: delete conversation thread.

#### [MODIFY] [view_page.j2.html](file:///c:/src/kb-web/src/kb_web/templates/view_page.j2.html)
- Add an in-page collapsible slide-out Chat Drawer / Assistant sidebar.
- Persist active thread in the database and auto-load previous conversation history when the user opens the page.

#### [NEW] [conversations_list.j2.html](file:///c:/src/kb-web/src/kb_web/templates/conversations_list.j2.html)
- Dedicated `/conversations` page listing all chat sessions, showing linked article titles, preview bubbles, message counts, and resumption links.

---

### Component 5: Notes Ingestion, Monaco Editor, & Obsidian Vault Upload (Issue #65)

#### [NEW] [notes.py](file:///c:/src/kb-web/src/kb_web/routers/notes.py)
- `POST /api/notes/paste`: accepts raw markdown or code snippet; creates `Note` item; triggers Ollama background worker to auto-generate wiki summary and tags.
- `POST /api/notes/upload-vault`: accepts ZIP or multi-file upload of an Obsidian directory; unpacks and mirrors folder hierarchy.
- `GET /api/notes/tree`: returns directory structure of mirrored notes.
- `PUT /api/notes/{id}`: saves edited code/markdown content from Monaco Editor.

#### [NEW] [note_editor.j2.html](file:///c:/src/kb-web/src/kb_web/templates/note_editor.j2.html)
- Full-featured browser editor powered by Monaco Editor (VS Code browser component).
- Side-by-side live markdown preview, folder tree navigator for Obsidian vaults, syntax highlighting, and autosave.

---

### Component 6: Admin Portal Modernization (Issue #66)

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html)
- Replace endless single-column scrolling layout with space-efficient Tabbed / Pill navigation:
  1. **System & Security**: Admin password change, Qdrant host/API key, system status.
  2. **AI & Prompts**: Wiki extraction prompts, YouTube prompts, model selector, prompt version history modals.
  3. **Database & Backups**: Knowledge base export, HTTP backup upload, WebSocket chunked import, local backup list.
  4. **Media & YouTube**: YouTube video re-indexing, media backup ZIP creation, storage stats.
  5. **Diagnostics & Logs**: Real-time server log viewer, Gotify settings, background task status.
- Use dense, modern glassmorphic card grids, compact button groups, and responsive forms.

---

### Component 7: Dynamic Custom Reports & ERP-Style Data Grid Builder (Issue #67)

#### [NEW] [reports.py](file:///c:/src/kb-web/src/kb_web/routers/reports.py)
- `GET /api/reports/tables`: metadata schema describing available tables, fields, and foreign-key join relationships.
- `POST /api/reports/query`: dynamic query engine executing user-configured projections, joins, filters, sorting, and grouping with pagination.
- `POST /api/reports/views`: save and update named report views.
- `GET /api/reports/export`: generates `.xlsx`, `.csv`, or `.json` stream for a report view.
- `POST /api/reports/schedule`: configures scheduled export jobs.

#### [NEW] [reports.j2.html](file:///c:/src/kb-web/src/kb_web/templates/reports.j2.html)
- ERP-style interactive data grid with:
  - Table and joined entity selector.
  - Column picker (drag, toggle, reorder).
  - Multi-column filter builder (contains, equals, greater than, date ranges).
  - Group-by and aggregation controls.
  - Export dropdown (Download Excel, CSV, JSON) and "Save View" modal.

---

## Verification Plan

### Automated Tests
- `uv run pytest tests/` to ensure all existing database, API, and crawler tests pass.
- New unit tests in `tests/test_rag_search.py` verifying chunk search endpoint.
- New unit tests in `tests/test_conversations.py` verifying chat session creation and message history persistence.
- New unit tests in `tests/test_reports.py` verifying dynamic query builder and export formatting.
- Linter checks: `uv run ruff check .`

### UI & UAT Verification
- Automated template check: `uv run python verify_ui_templates.py`
- Browser validation of the modernized `/admin` tabbed layout.
- Browser validation of Monaco Editor and live preview.
- Browser validation of main page RAG search chunk cards.
- Generate testing report via `generate-uat-testing-artifact`.
