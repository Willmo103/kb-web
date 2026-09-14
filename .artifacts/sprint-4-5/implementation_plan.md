# Implementation Plan: Sprint 5 - WebSocket Ingestion, Docling Integration, & Cache Settings

Sprint 5 addresses:
- **Parent Issue #51**: Sprint 5: WebSocket Ingestion, Docling Integration, & Cache Settings
- **Issue #36**: Add `docling-serve` Support and File Imports
- **Sub-Issue 10 (#52)**: WebSocket File Ingestion & Drag-and-Drop Ingestion UI
- **Sub-Issue 11 (#53)**: Standalone Ollama Chat Caching, Prompts Logs, & Settings Management

---

## User Review Required

> [!IMPORTANT]
> **Key Architecture Decisions for Sprint 5:**
> 1. **WebSocket File Ingestion (`/api/import/file/upload`)**:
>    - Large document files (PDF, DOCX, PPTX, XLSX, etc.) are sliced client-side into 1MB chunks and streamed via WebSocket.
>    - Provides real-time byte-level transfer progress percentage, SHA-256 checksum verification, and error notifications.
> 2. **Docling Storage Vectors & Deduplication (Issue #36)**:
>    - Primary storage vectors:
>      - `media/uploads/originals/{file_hash}.{ext}` (raw uploaded file)
>      - `media/uploads/docling_json/{file_hash}.json` (structured Docling AST/JSON)
>      - `FetchedPage` entry with markdown content and `file://` URI so existing vector embedding, Qdrant export, and semantic search seamlessly index uploaded documents.
>    - File content SHA-256 serves as primary key/index for deduplication.
>    - Files failing conversion or flagged as unprocessable will be retained for at most 7 days before automated cleanup.
> 3. **`DoclingClient` & `docling-serve` Integration**:
>    - Configurable `DOCLING_SERVE_URL` (default `http://localhost:5001`).
>    - If `docling-serve` is unreachable, `DoclingClient` gracefully falls back to local Python `docling` library or clean text extraction without crashing.
> 4. **`OllamaChatCache` Table & Prompt Caching (Sub-Issue #53)**:
>    - New table `ollama_chat_cache` (`prompt_hash` PK, `model_used`, `settings_applied`, `raw_prompt`, `raw_response_json`, `created_at`, `hit_count`, `last_accessed_at`).
>    - Transparently caches all LLM extraction calls (`extract_wiki_content`, `extract_tags_content`, `ai_curate_candidate_links`), eliminating duplicate Ollama queries and drastically lowering latency on repeated scrapes and crawls.
> 5. **Admin Dashboard Settings**:
>    - Advanced Ollama parameters: `temperature`, `top_p`, `num_ctx`, `think`.
>    - Docling settings: `docling_serve_url`, `enable_ocr`, `max_file_size_mb`.
>    - Interactive prompt cache inspection table with search and cache flush triggers.

---

## Proposed Changes

### 1. Database Schema & ORM (`src/kb_web/models_orm.py`, `migrations/`)

#### [MODIFY] [models_orm.py](file:///c:/src/kb-web/src/kb_web/models_orm.py)
- Define `OllamaChatCache`:
  ```python
  class OllamaChatCache(Base):
      __tablename__ = "ollama_chat_cache"

      prompt_hash = Column(String(64), primary_key=True)
      model_used = Column(String, nullable=False, index=True)
      settings_applied = Column(Text, nullable=True)
      raw_prompt = Column(Text, nullable=False)
      raw_response_json = Column(Text, nullable=False)
      created_at = Column(String, nullable=False)
      hit_count = Column(Integer, default=1)
      last_accessed_at = Column(String, nullable=False)
  ```
- Define `UploadedDocument`:
  ```python
  class UploadedDocument(Base):
      __tablename__ = "uploaded_documents"

      file_hash = Column(String(64), primary_key=True)
      filename = Column(String, nullable=False)
      file_size = Column(Integer, nullable=False)
      mime_type = Column(String, nullable=True)
      file_path = Column(Text, nullable=False)
      docling_json_path = Column(Text, nullable=True)
      status = Column(String, default="uploaded", index=True)  # uploaded, parsed, failed, purged
      error_message = Column(Text, nullable=True)
      uploaded_at = Column(String, nullable=False)
      source_id = Column(String(36), ForeignKey("sources.id"), nullable=True, index=True)
  ```

#### [NEW] [migrations/versions/f92d84291a25_add_ollama_cache_and_uploads.py](file:///c:/src/kb-web/migrations/versions/f92d84291a25_add_ollama_cache_and_uploads.py)
- Create `ollama_chat_cache` and `uploaded_documents` tables with performance indexes.

---

### 2. Configuration & Docling Client (`src/kb_web/config.py`, `src/kb_web/utils.py`)

#### [MODIFY] [config.py](file:///c:/src/kb-web/src/kb_web/config.py)
- Add properties with DB persistence (`settings_external` / `settings_ollama`):
  - `docling_serve_url: str` (default `"http://localhost:5001"`)
  - `docling_ocr_enabled: bool` (default `False`)
  - `ollama_temperature: float` (default `0.2`)
  - `ollama_top_p: float` (default `0.9`)
  - `uploads_dir: Path` (`~/.kb/uploads` or configured project media directory)

#### [MODIFY] [utils.py](file:///c:/src/kb-web/src/kb_web/utils.py)
- Add `DoclingClient` class:
  - Methods: `is_alive()`, `convert_file(file_path: Path) -> dict` returning markdown, docling JSON, and document metadata.
  - Graceful fallback: attempts HTTP request to `docling-serve` first; if unavailable, attempts Python `docling` package; falls back to text reader for plain text/md/csv.
- Add `cached_ollama_chat(client, model, messages, options=None, think=None)`:
  - Hashes input arguments with SHA-256.
  - Checks `OllamaChatCache`; returns cached response on hit; writes to cache on miss.
- Integrate `cached_ollama_chat` into `extract_wiki_content`, `extract_tags_content`, and `ai_curate_candidate_links`.
- Add `purge_expired_uploads(uploads_dir: Path, max_age_days: int = 7) -> int` to remove unprocessable uploads older than 7 days.

---

### 3. WebSocket Upload & API Router (`src/kb_web/routers/uploads.py`, `src/kb_web/server.py`)

#### [NEW] [src/kb_web/routers/uploads.py](file:///c:/src/kb-web/src/kb_web/routers/uploads.py)
- WebSocket endpoint `@router.websocket("/api/import/file/upload")`:
  - Receives JSON handshake with metadata: `filename`, `file_size`, `collection_id`.
  - Validates non-blacklisted file extensions (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.csv`, `.epub`, etc.).
  - Receives binary or base64 chunks, writes to disk under `media/uploads/originals/`, tracks bytes received, and calculates SHA-256.
  - Sends WebSocket progress updates: `{"status": "uploading", "progress": 45, "received": 450000, "total": 1000000}`.
  - Upon completion:
    - Verifies file integrity.
    - Runs `DoclingClient.convert_file()`.
    - Creates `UploadedDocument` record.
    - Enqueues into `sources` table via `enqueue_source(file_path, source_type="docling", collection_id=...)` to advance pipeline (tagger $\rightarrow$ embeddings).
    - Sends WebSocket completion event: `{"status": "completed", "file_hash": hash, "source_id": id, "url": view_url}`.
  - Error handling: catches conversion exceptions, marks status as `failed`, and retains for 7-day purge window.

#### [MODIFY] [server.py](file:///c:/src/kb-web/src/kb_web/server.py)
- Register `uploads.router` in FastAPI application.

---

### 4. UI: Drag-and-Drop Uploader & Admin Settings (`src/kb_web/templates/`)

#### [MODIFY] [url_import.j2.html](file:///c:/src/kb-web/src/kb_web/templates/url_import.j2.html)
- Add Tab 3: "📁 Document Upload (Docling)".
- Implement drag-and-drop zone with animated border and file icon.
- File selector with supported file types badge list.
- Reactive client-side JavaScript streaming files in 1MB chunks to `ws://.../api/import/file/upload`.
- Visual progress bar, transfer speed / bytes counter, and completion toast linking to the created wiki entry.

#### [MODIFY] [admin.j2.html](file:///c:/src/kb-web/src/kb_web/templates/admin.j2.html) & [admin.py](file:///c:/src/kb-web/src/kb_web/routers/admin.py)
- Add Docling Settings card:
  - Docling-Serve URL input with "Test Docling Connection" trigger.
  - OCR toggle.
- Add Ollama Advanced Settings card:
  - Temperature, Top-P, Reasoning Think Mode toggles.
- Add Ollama Cache & History section:
  - Table of recent cached prompts with hit counters, timestamps, and "Clear Cache" action.
  - Endpoint `POST /admin/ollama/cache/clear`.

---

## Verification Plan

### Automated Tests
1. **New Test Suite `tests/test_sprint_5_docling_ollama.py`**:
   - `test_ollama_cache_hit_and_miss`: Tests that identical prompts hit cache without sending Ollama network calls.
   - `test_docling_client_mock_convert`: Tests `DoclingClient` parsing markdown and JSON output.
   - `test_websocket_chunked_file_upload`: Tests `/api/import/file/upload` streaming chunks, computing SHA-256, and saving original file.
   - `test_file_type_validation_and_blacklist`: Tests rejection of invalid/executable file types.
   - `test_purge_expired_uploads`: Tests 7-day retention purge of unprocessable files.
   - `test_admin_docling_and_cache_settings`: Tests settings persistence and cache clearance.
2. **Full Repository Checks**:
   - `uv run pytest`: 100% pass across all tests.
   - `uv run python build.py`: Clean build packaging.
   - `verify_ui_templates.py`: 0 template warnings.
   - `generate_uat_report.py`: Generate VCS UAT testing report for Sprint 5.

### Manual Verification
- Test drag-and-drop file upload on `/import` tab 3 with a PDF/markdown file.
- Inspect upload progress bar and verify wiki card appears on `/` and `/collections`.
- Check `/admin` to verify Docling settings and prompt cache table.
