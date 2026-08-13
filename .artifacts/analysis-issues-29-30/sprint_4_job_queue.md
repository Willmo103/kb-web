# Sprint 4: Unified Ingestion Sources Schema & Queue Processor (Issue #48)

* **Sprint Goal**: Refactor the linear ingestion flow into a state-driven queue processor driven by a unified `sources` schema and `_processor_xref` service callback registry.
* **Parent Issue**: #29 (Import Process Needs to Be Broken Down)
* **Estimated Duration**: 11 Days

---

## Detailed Task List

### 1. Processing Sources & Registry Schema (Sub-Issue #49)
- [ ] Declare ORM mapping models for `sources` and `_processor_xref` tables:
  - `sources` fields: `id` (UUID PK), `url` (text nullable), `file_hash` (text nullable), `type` (enum source_type), `processor_id` (int nullable FK), `path` (text nullable), `timestamp` (DateTime).
  - `_processor_xref` fields: `id` (int PK), `service_name` (text), `callback_path` (text), `stage` (enum: pre, process, post).
- [ ] Relate child entities (`fetched_pages`, `youtube_videos`, `chunk_embeddings`) to `sources.id` via foreign key constraints.
- [ ] Write seed scripts to pre-populate default ingestion services (fetcher, summary, tags, embeddings, downloads) inside the `_processor_xref` registry during startup.

### 2. State-Driven Job Queue Processor Daemon (Sub-Issue #50)
- [ ] Implement a queue worker class `IngestionWorker` in `src/kb_web/queue_processor.py`.
- [ ] Configure a background thread executor inside the FastAPI startup lifecycle that polls the `sources` table for items with active `processor_id`.
- [ ] Implement dynamic execution routing: load and invoke the python module/callback registered to the active `processor_id` dynamically.
- [ ] Drive the processing pipeline by updating `processor_id` to point to the next registered processor ID upon success.
- [ ] Implement retry management: track attempts and write exception stack traces into `error_log` fields on failure.
- [ ] Hook up Gotify notification triggers to alert users on job failure/critical exceptions.
