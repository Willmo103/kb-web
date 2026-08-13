# Sprint 5: WebSocket Ingestion, Docling Integration, & Cache Settings

* **Sprint Goal**: Add drag-and-drop document upload, WebSocket chunked upload endpoints, docling document parser conversions, Ollama prompts cache, and configuration forms.
* **Target Issues**: Issue #36, Sub-Issue 10, Sub-Issue 11
* **Estimated Duration**: 15 Days

---

## Detailed Task List

### 1. Drag-and-Drop file uploads via WebSockets
- [ ] Add a file upload container panel to the import view (`url_import.j2.html`).
- [ ] Implement client-side JavaScript to slice large file uploads (250MB+) into chunks and stream them via WebSockets.
- [ ] Create a FastAPI WebSocket endpoint `/api/import/file/upload` that receives bytes chunks, verifies file hashes, and tracks transfer progress on the client UI.

### 2. Docling-Serve Client Integration
- [ ] Implement a `DoclingClient` utility inside `src/kb_web/utils.py`.
- [ ] Connect to `docling-serve` endpoints, exposing API configuration options in settings.
- [ ] Parse uploaded files (PDFs, Docx, CSV, Excel, etc.) to extract raw markdown and JSON structure files, store originals and outputs on server disk, and trigger chunk embedding jobs via the background worker.
- [ ] Enforce non-blacklisted file types validation on document uploads.
- [ ] Write a background task/cron daemon that purges unpossessable files older than 7 days.

### 3. Ollama Cache & Advanced Settings Dashboard
- [ ] Setup the `ollama_chat_cache` table mapping columns: `prompt_hash` (PK), `raw_prompt`, `raw_response_json`, `model_used`, and `settings_applied`.
- [ ] Intercept all Ollama Client requests to check for cache hits prior to sending remote requests.
- [ ] Build configuration interface panels in the Admin Dashboard exposing advanced kwargs (e.g. temperature, system prompt parameters) for `ollama.chat`.
- [ ] Expose an interactive Ollama request history/prompt debugger page left-joined against responses inside the Admin Dashboard.
